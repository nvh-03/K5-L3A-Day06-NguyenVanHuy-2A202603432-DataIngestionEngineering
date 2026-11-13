"""Run the pipeline twice and compare stable outputs and database counts."""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

STARTER_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = STARTER_DIR / "results"
STRATEGIES = ("A", "B", "C")


def main() -> None:
    load_dotenv(STARTER_DIR / ".env")
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is missing; configure starter/.env first.")

    _run_pipeline()
    first = _snapshot()
    first_counts = _database_counts()

    _run_pipeline()
    second = _snapshot()
    second_counts = _database_counts()

    if first != second:
        raise AssertionError("Stable pipeline outputs changed between consecutive runs.")
    if first_counts != second_counts:
        raise AssertionError(
            f"Database chunk counts changed between runs: {first_counts} != {second_counts}."
        )
    expected_counts = {
        strategy["strategy"]: strategy["chunk_count"]
        for strategy in second["summary"]["strategies"]
    }
    if second_counts != expected_counts:
        raise AssertionError(
            f"Database counts do not match pipeline output: {second_counts} != {expected_counts}."
        )
    print("Reproducibility OK: stable traces, metrics, and database counts across two runs.")


def _run_pipeline() -> None:
    subprocess.run(
        [sys.executable, "-m", "src.run"],
        cwd=STARTER_DIR,
        check=True,
    )


def _snapshot() -> dict[str, Any]:
    traces = json.loads((RESULTS_DIR / "traces.json").read_text(encoding="utf-8"))
    summary = json.loads((RESULTS_DIR / "summary.json").read_text(encoding="utf-8"))
    stable_strategies = [
        {
            key: value
            for key, value in strategy.items()
            if key
            not in {
                "embedding_seconds",
                "store_seconds",
                "ingest_seconds",
                "retrieval_seconds",
            }
        }
        for strategy in summary["strategies"]
    ]
    return {
        "traces": [_stable_trace(trace) for trace in traces],
        "summary": {
            key: summary[key]
            for key in (
                "benchmark_id",
                "document_id",
                "source_sha256",
                "benchmark_sha256",
                "embedding_model",
                "embedding_model_revision",
                "database",
                "environment",
                "retrieval_metrics",
                "manual_audit_file",
                "manual_audit_status",
                "manual_audit_required",
            )
        }
        | {"strategies": stable_strategies},
    }


def _stable_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        **trace,
        "hits": [
            {
                **hit,
                "score": round(float(hit["score"]), 6),
            }
            for hit in trace["hits"]
        ],
    }


def _database_counts() -> dict[str, int]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT strategy, count(*), count(DISTINCT chunk_id)
                FROM rfeh_chunks
                WHERE strategy IN (%s, %s, %s)
                GROUP BY strategy
                """,
                STRATEGIES,
            )
            rows = cursor.fetchall()
    counts = {strategy: count for strategy, count, _ in rows}
    distinct_counts = {strategy: distinct for strategy, _, distinct in rows}
    if counts != distinct_counts:
        raise AssertionError(f"Duplicate chunk IDs found in the database: {counts}.")
    return counts


if __name__ == "__main__":
    main()
