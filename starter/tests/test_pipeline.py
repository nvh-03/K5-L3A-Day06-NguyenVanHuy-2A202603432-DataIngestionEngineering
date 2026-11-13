import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.chunking import by_paragraph, fixed_size
from src.evaluation import evaluate_query, summarize
from src.ingestion import normalize_text
from src.models import DocumentPage
from src.run import _verify_hash


class IngestionAndChunkingTests(unittest.TestCase):
    def test_normalize_text_handles_unicode_and_line_break_hyphenation(self) -> None:
        normalized = normalize_text("ＲＦ energy-har-\nvesting\n\nsecond line")
        self.assertEqual(normalized, "RF energy-harvesting\n\nsecond line")

    def test_hash_verification_accepts_pinned_input_and_rejects_changes(self) -> None:
        content = b"pinned corpus"
        expected = hashlib.sha256(content).hexdigest()

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "corpus.pdf"
            path.write_bytes(content)
            _verify_hash(path, expected, "corpus")

            path.write_bytes(b"changed corpus")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                _verify_hash(path, expected, "corpus")

    def test_fixed_size_chunks_overlap_and_keep_page_metadata(self) -> None:
        page = DocumentPage(
            document_id="doc",
            source="paper.pdf",
            page=2,
            text="abcdefghijk",
            metadata={"section": "fundamentals"},
        )

        chunks = fixed_size(page, size=5, overlap=2)

        self.assertEqual([chunk.text for chunk in chunks], ["abcde", "defgh", "ghijk"])
        self.assertTrue(all(chunk.metadata["section"] == "fundamentals" for chunk in chunks))

    def test_paragraph_chunking_respects_limit_and_preserves_metadata(self) -> None:
        page = DocumentPage(
            document_id="doc",
            source="paper.pdf",
            page=2,
            text="First sentence. Second sentence.\n\nThird sentence.",
            metadata={"section": "fundamentals"},
        )

        chunks = by_paragraph(page, max_size=20)

        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk.text) <= 20 for chunk in chunks))
        self.assertTrue(all(chunk.metadata["section"] == "fundamentals" for chunk in chunks))
        self.assertEqual(" ".join(chunk.text for chunk in chunks), "First sentence. Second sentence. Third sentence.")


class EvaluationTests(unittest.TestCase):
    def test_source_page_and_chunk_id_survive_in_retrieval_trace(self) -> None:
        page = DocumentPage(
            document_id="doc",
            source="data/paper.pdf",
            page=8,
            text="A supporting fact.",
            metadata={"section": "fundamentals"},
        )
        chunk = by_paragraph(page, max_size=100)[0]
        question = {
            "id": "q1",
            "split": "dev",
            "question": "What?",
            "expected_answer": "A fact",
            "gold_source_id": "doc",
            "gold_page": 8,
            "evidence_quote": "A supporting fact.",
        }
        hit = {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "source": chunk.source,
            "page": chunk.page,
            "text": chunk.text,
            "score": 0.9,
            "metadata": chunk.metadata,
        }

        trace = evaluate_query(question, [hit])
        traced_hit = trace["hits"][0]

        self.assertEqual(traced_hit["chunk_id"], chunk.chunk_id)
        self.assertEqual(traced_hit["document_id"], "doc")
        self.assertEqual(traced_hit["source"], "data/paper.pdf")
        self.assertEqual(traced_hit["page"], 8)
        self.assertEqual(traced_hit["metadata"]["section"], "fundamentals")

    def test_evidence_hit_requires_gold_page_and_quote(self) -> None:
        question = {
            "id": "q1",
            "split": "dev",
            "question": "What?",
            "expected_answer": "Answer",
            "gold_source_id": "doc",
            "gold_page": 2,
            "evidence_quote": "Supported fact.",
        }
        hit = {
            "document_id": "doc",
            "page": 2,
            "text": "Context. Supported fact. More context.",
            "score": 0.9,
        }

        trace = evaluate_query(question, [hit])
        trace["strategy"] = "A"

        self.assertTrue(trace["hit_at_1"])
        self.assertTrue(trace["evidence_hit_at_3"])
        self.assertEqual(summarize([trace])[0]["evidence_hit_at_3"]["hits"], 1)

        wrong_page = evaluate_query(question, [{**hit, "page": 3}])
        self.assertFalse(wrong_page["evidence_hit_at_3"])


if __name__ == "__main__":
    unittest.main()
