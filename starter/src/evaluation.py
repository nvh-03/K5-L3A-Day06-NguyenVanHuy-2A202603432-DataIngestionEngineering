"""Evidence-based retrieval metrics and per-query traces."""
from collections import defaultdict
from typing import Any

from .ingestion import normalize_text


def evaluate_query(
    question: dict[str, Any],
    hits: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence = normalize_text(question["evidence_quote"]).casefold()
    gold_source = question["gold_source_id"]
    gold_pages = question.get("gold_pages", [question["gold_page"]])
    hit_records = []
    for hit in hits:
        page_and_source_match = (
            hit.get("document_id") == gold_source and hit.get("page") in gold_pages
        )
        has_evidence = evidence in normalize_text(hit.get("text", "")).casefold()
        hit_records.append(
            {
                **hit,
                "gold_page_match": page_and_source_match,
                "evidence_match": page_and_source_match and has_evidence,
            }
        )

    return {
        "question_id": question["id"],
        "split": question["split"],
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold_source_id": gold_source,
        "gold_page": question["gold_page"],
        "filter": question.get("filter"),
        "hits": hit_records,
        "hit_at_1": bool(hit_records and hit_records[0]["evidence_match"]),
        "evidence_hit_at_3": any(hit["evidence_match"] for hit in hit_records[:3]),
    }


def summarize(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        grouped[(trace["strategy"], trace["split"])].append(trace)

    summary = []
    for (strategy, split), rows in sorted(grouped.items()):
        total = len(rows)
        hit_at_1 = sum(row["hit_at_1"] for row in rows)
        hit_at_3 = sum(row["evidence_hit_at_3"] for row in rows)
        summary.append(
            {
                "strategy": strategy,
                "split": split,
                "questions": total,
                "hit_at_1": {"hits": hit_at_1, "total": total, "rate": hit_at_1 / total},
                "evidence_hit_at_3": {
                    "hits": hit_at_3,
                    "total": total,
                    "rate": hit_at_3 / total,
                },
            }
        )
    return summary
