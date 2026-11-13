"""Persistent PostgreSQL + pgvector storage and metadata-filtered cosine search."""
import math
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import Chunk


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions

    def create_schema(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS rfeh_chunks (
                        strategy TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        page INTEGER NOT NULL,
                        section TEXT,
                        chunk_text TEXT NOT NULL,
                        embedding vector({self.dimensions}) NOT NULL,
                        PRIMARY KEY (strategy, chunk_id)
                    )
                    """
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS rfeh_chunks_strategy_section_idx "
                    "ON rfeh_chunks (strategy, section)"
                )

    def server_info(self) -> dict[str, str]:
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT current_database(), current_setting('server_version'),
                           (SELECT extversion FROM pg_extension WHERE extname = 'vector')
                    """
                )
                row = cursor.fetchone()
        if row is None or row[2] is None:
            raise RuntimeError("PostgreSQL is connected but pgvector is not installed.")
        return {
            "database": row[0],
            "postgresql": row[1],
            "pgvector": row[2],
        }

    def upsert(
        self,
        strategy: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        rows = []
        for chunk, vector in zip(chunks, vectors):
            self._validate_vector(vector)
            rows.append(
                (
                    strategy,
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.source,
                    chunk.page,
                    chunk.metadata.get("section"),
                    chunk.text,
                    _vector_literal(vector),
                )
            )

        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM rfeh_chunks WHERE strategy = %s", (strategy,))
                if rows:
                    cursor.executemany(
                        """
                        INSERT INTO rfeh_chunks
                            (strategy, chunk_id, document_id, source, page, section,
                             chunk_text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                        """,
                        rows,
                    )

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_vector(query_vector)
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        where_clause = "strategy = %s"
        parameters: list[Any] = [strategy]
        if filters:
            unsupported = set(filters) - {"section"}
            if unsupported:
                raise ValueError(f"Unsupported metadata filter fields: {sorted(unsupported)}")
            section = filters.get("section")
            if not isinstance(section, str) or not section:
                raise ValueError("section filter must be a non-empty string")
            where_clause += " AND section = %s"
            parameters.append(section)

        query_literal = _vector_literal(query_vector)
        parameters.extend((query_literal, top_k))
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT chunk_id, document_id, source, page, section, chunk_text,
                           1 - (embedding <=> %s::vector) AS score
                    FROM rfeh_chunks
                    WHERE {where_clause}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_literal, *parameters),
                )
                rows = cursor.fetchall()

        return [
            {
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "source": row["source"],
                "page": row["page"],
                "text": row["chunk_text"],
                "score": float(row["score"]),
                "metadata": {"section": row["section"]},
            }
            for row in rows
        ]

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.dimensions:
            raise ValueError(
                f"Expected vector dimension {self.dimensions}, received {len(vector)}"
            )
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Vectors must contain only finite numbers")


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"
