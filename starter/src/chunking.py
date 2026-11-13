"""Fixed-size and paragraph-aware chunking with stable IDs and page metadata."""
import hashlib
import re

from .models import Chunk, DocumentPage


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be between 0 and size - 1")
    if not page.text:
        return []

    chunks: list[Chunk] = []
    step = size - overlap
    for index, start in enumerate(range(0, len(page.text), step)):
        text = page.text[start : start + size].strip()
        if text:
            chunks.append(_make_chunk(page, "fixed", index, text))
        if start + size >= len(page.text):
            break
    return chunks


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    if max_size <= 0:
        raise ValueError("max_size must be positive")
    if not page.text:
        return []

    chunks: list[Chunk] = []
    index = 0
    for paragraph in (part.strip() for part in page.text.split("\n\n")):
        if not paragraph:
            continue
        for text in _pack_sentences(paragraph, max_size):
            chunks.append(_make_chunk(page, "paragraph", index, text))
            index += 1
    return chunks


def _pack_sentences(text: str, max_size: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    segments: list[str] = []
    current = ""

    for sentence in sentences:
        pieces = [
            sentence[start : start + max_size]
            for start in range(0, len(sentence), max_size)
        ]
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_size:
                segments.append(current)
                current = piece
            else:
                current = candidate

    if current:
        segments.append(current)
    return segments


def _make_chunk(page: DocumentPage, method: str, index: int, text: str) -> Chunk:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return Chunk(
        chunk_id=f"{page.document_id}:{page.page}:{method}:{index}:{digest}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata=dict(page.metadata),
    )
