"""Run the controlled A/B/C ingestion and retrieval benchmark."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import SentenceTransformerEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf, normalize_text
from .models import Chunk, DocumentPage
from .store import PgVectorStore

ROOT = Path(__file__).resolve().parents[2]
STARTER_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
STRATEGIES = (
    {"name": "A", "chunker": "fixed", "size": 500, "overlap": 50},
    {"name": "B", "chunker": "paragraph", "max_size": 500},
    {"name": "C", "chunker": "paragraph", "max_size": 500},
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the manifest, PDF, benchmark and evidence without embedding or DB",
    )
    arguments = parser.parse_args()

    load_dotenv(STARTER_DIR / ".env")
    manifest, pages, questions = _load_inputs()
    if arguments.validate_only:
        print(
            f"Benchmark OK: {len(pages)} content pages, "
            f"{len(questions)} questions "
            f"({sum(q['split'] == 'dev' for q in questions)} dev / "
            f"{sum(q['split'] == 'test' for q in questions)} test), "
            f"{sum(bool(q.get('filter')) for q in questions)} filtered."
        )
        return

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing; configure starter/.env first.")

    model_name = os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
    model_revision = os.getenv("EMBEDDING_MODEL_REVISION")
    if model_name == DEFAULT_MODEL and not model_revision:
        model_revision = DEFAULT_MODEL_REVISION
    embedder = SentenceTransformerEmbedder(model_name, revision=model_revision)
    store = PgVectorStore(database_url, embedder.dimensions)
    store.create_schema()
    database_info = store.server_info()

    all_traces: list[dict[str, Any]] = []
    strategy_runs: list[dict[str, Any]] = []
    vector_cache: dict[str, list[float]] = {}
    query_embedding_started = time.perf_counter()
    query_vectors = {
        question["id"]: embedder.embed_query(question["question"])
        for question in questions
    }
    query_embedding_seconds = time.perf_counter() - query_embedding_started

    for spec in STRATEGIES:
        chunks = _build_chunks(pages, spec)
        missing_chunks = [chunk for chunk in chunks if chunk.chunk_id not in vector_cache]
        embedding_started = time.perf_counter()
        missing_vectors = embedder.embed_documents([chunk.text for chunk in missing_chunks])
        embedding_seconds = time.perf_counter() - embedding_started
        if len(missing_chunks) != len(missing_vectors):
            raise RuntimeError("Embedding provider returned an unexpected number of vectors.")
        vector_cache.update(
            (chunk.chunk_id, vector)
            for chunk, vector in zip(missing_chunks, missing_vectors)
        )
        store_started = time.perf_counter()
        store.upsert(
            spec["name"],
            chunks,
            [vector_cache[chunk.chunk_id] for chunk in chunks],
        )
        store_seconds = time.perf_counter() - store_started

        retrieval_started = time.perf_counter()
        for question in questions:
            filters = question.get("filter") if spec["name"] == "C" else None
            hits = store.search(
                spec["name"],
                query_vectors[question["id"]],
                top_k=3,
                filters=filters,
            )
            trace = evaluate_query(question, hits)
            trace["strategy"] = spec["name"]
            trace["applied_filter"] = filters
            all_traces.append(trace)
        retrieval_seconds = time.perf_counter() - retrieval_started

        lengths = [len(chunk.text) for chunk in chunks]
        strategy_runs.append(
            {
                "strategy": spec["name"],
                "configuration": spec,
                "chunk_count": len(chunks),
                "chunk_length_chars": {
                    "min": min(lengths, default=0),
                    "mean": statistics.mean(lengths) if lengths else 0,
                    "max": max(lengths, default=0),
                },
                "new_embedding_chunks": len(missing_chunks),
                "reused_embedding_chunks": len(chunks) - len(missing_chunks),
                "embedding_seconds": round(embedding_seconds, 3),
                "store_seconds": round(store_seconds, 3),
                "ingest_seconds": round(embedding_seconds + store_seconds, 3),
                "retrieval_seconds": round(retrieval_seconds, 3),
                "embedding_model": model_name,
                "embedding_dimensions": embedder.dimensions,
                "vector_store": "PostgreSQL + pgvector",
                "similarity": "exact cosine distance",
                "cost_usd": 0,
            }
        )

    results_dir = STARTER_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_json(results_dir / "traces.json", all_traces)
    _write_json(
        results_dir / "summary.json",
        {
            "benchmark_id": "telecom-06-00045-v1",
            "document_id": manifest["document_id"],
            "source_sha256": manifest["source_sha256"],
            "benchmark_sha256": manifest["benchmark_sha256"],
            "embedding_model": model_name,
            "embedding_model_revision": embedder.revision,
            "query_embedding_seconds": round(query_embedding_seconds, 3),
            "database": database_info,
            "vector_store": "PostgreSQL + pgvector",
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "embedding_device": embedder.device,
                "packages": {
                    package: importlib.metadata.version(package)
                    for package in (
                        "huggingface-hub",
                        "numpy",
                        "psycopg",
                        "pypdf",
                        "python-dotenv",
                        "safetensors",
                        "scikit-learn",
                        "scipy",
                        "sentence-transformers",
                        "tokenizers",
                        "torch",
                        "transformers",
                    )
                },
            },
            "strategies": strategy_runs,
            "retrieval_metrics": summarize(all_traces),
            "manual_audit_file": "results/manual_audit.json",
            "manual_audit_status": "AI-assisted preliminary review; author verification required",
            "manual_audit_required": [
                "chunk_coherence",
                "metadata_correctness_and_usefulness",
                "grounding_quality",
                "data_strategy_tradeoffs",
            ],
        },
    )
    print(f"Completed A/B/C. Results saved in {results_dir}.")


def _load_inputs() -> tuple[dict[str, Any], list[DocumentPage], list[dict[str, Any]]]:
    manifest_path = ROOT / "data" / "manifest.json"
    benchmark_path = ROOT / "benchmark" / "questions.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = ROOT / manifest["source"]
    _verify_hash(source_path, manifest["source_sha256"], "corpus")
    _verify_hash(benchmark_path, manifest["benchmark_sha256"], "benchmark")
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    pages = load_pdf(source_path, manifest["document_id"], manifest["source"])
    content_ranges = manifest["content_page_ranges"]
    content_pages = [
        page
        for page in pages
        if _is_in_ranges(page.page, content_ranges) and page.text
    ]
    if len(content_pages) < 30:
        raise ValueError(
            f"Corpus has {len(content_pages)} extractable content pages; at least 30 required."
        )

    section_names = set()
    for section in manifest["sections"]:
        section_names.add(section["name"])
        for page in content_pages:
            if _is_in_ranges(page.page, section["page_ranges"]):
                if page.metadata.get("section"):
                    raise ValueError(f"Overlapping section ranges include page {page.page}.")
                page.metadata["section"] = section["name"]
    missing_sections = [page.page for page in content_pages if not page.metadata.get("section")]
    if missing_sections:
        raise ValueError(f"Manifest does not assign a section to pages: {missing_sections}")

    questions = benchmark["questions"]
    _validate_questions(
        questions,
        manifest["document_id"],
        pages,
        content_ranges,
        section_names,
    )
    return manifest, content_pages, questions


def _validate_questions(
    questions: list[dict[str, Any]],
    document_id: str,
    pages: list[DocumentPage],
    content_ranges: list[list[int]],
    section_names: set[str],
) -> None:
    if len(questions) < 20:
        raise ValueError(f"Benchmark needs at least 20 questions; found {len(questions)}.")
    question_ids = [question.get("id") for question in questions]
    if len(question_ids) != len(set(question_ids)) or any(not item for item in question_ids):
        raise ValueError("Benchmark question IDs must be present and unique.")

    dev_count = sum(question.get("split") == "dev" for question in questions)
    test_count = sum(question.get("split") == "test" for question in questions)
    if dev_count < 15 or test_count < 5:
        raise ValueError(f"Benchmark needs at least 15 dev / 5 test; found {dev_count}/{test_count}.")
    filtered_questions = [question for question in questions if question.get("filter")]
    if len(filtered_questions) < 3 or not any(
        question.get("split") == "test" for question in filtered_questions
    ):
        raise ValueError("Benchmark needs at least 3 filtered questions, including a test question.")

    pages_by_number = {page.page: page for page in pages}
    for question in questions:
        required = (
            "split",
            "question",
            "expected_answer",
            "gold_source_id",
            "gold_page",
            "evidence_quote",
        )
        missing = [field for field in required if not question.get(field)]
        if missing:
            raise ValueError(f"{question.get('id')} is missing fields: {missing}")
        if question["split"] not in {"dev", "test"}:
            raise ValueError(f"{question['id']} has unsupported split {question['split']!r}.")
        if question["gold_source_id"] != document_id:
            raise ValueError(f"{question['id']} points to an unknown gold document.")
        gold_page = question["gold_page"]
        if not _is_in_ranges(gold_page, content_ranges):
            raise ValueError(f"{question['id']} gold page {gold_page} is not a content page.")
        source_page = pages_by_number.get(gold_page)
        if source_page is None or normalize_text(question["evidence_quote"]).casefold() not in (
            normalize_text(source_page.text).casefold()
        ):
            raise ValueError(
                f"{question['id']} evidence_quote was not found on PDF page {gold_page}."
            )

        filters = question.get("filter")
        if filters:
            if set(filters) != {"section"} or filters["section"] not in section_names:
                raise ValueError(f"{question['id']} contains an invalid metadata filter.")
            if not _is_in_ranges(gold_page, _ranges_for_section(filters["section"])):
                raise ValueError(
                    f"{question['id']} filter does not include its gold page {gold_page}."
                )


def _ranges_for_section(section_name: str) -> list[list[int]]:
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    for section in manifest["sections"]:
        if section["name"] == section_name:
            return section["page_ranges"]
    return []


def _is_in_ranges(page: int, ranges: list[list[int]]) -> bool:
    return any(first <= page <= last for first, last in ranges)


def _build_chunks(pages: list[DocumentPage], spec: dict[str, Any]) -> list[Chunk]:
    chunks = []
    for page in pages:
        if spec["chunker"] == "fixed":
            page_chunks = fixed_size(page, spec["size"], spec["overlap"])
        elif spec["chunker"] == "paragraph":
            page_chunks = by_paragraph(page, spec["max_size"])
        else:
            raise ValueError(f"Unsupported chunker: {spec['chunker']}")
        chunks.extend(page_chunks)
    return chunks


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _verify_hash(path: Path, expected: str, label: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(
            f"{label} SHA-256 mismatch for {path}: expected {expected}, got {actual}."
        )


if __name__ == "__main__":
    main()
