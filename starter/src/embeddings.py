"""Local sentence-transformer embeddings shared by documents and queries."""
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with stored document vectors."""


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, revision: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.revision = revision
        self._model = SentenceTransformer(model_name, revision=revision)
        self.device = str(self._model.device)
        get_dimension = getattr(self._model, "get_embedding_dimension", None)
        if get_dimension is None:
            get_dimension = self._model.get_sentence_embedding_dimension
        dimensions = get_dimension()
        if dimensions is None or dimensions <= 0:
            raise RuntimeError(f"Embedding model returned invalid dimensions: {dimensions}")
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            batch_size=32,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 32,
        )
        return vectors.tolist()

    def embed_query(self, question: str) -> list[float]:
        vectors = self._model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors[0].tolist()
