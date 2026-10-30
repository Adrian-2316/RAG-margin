"""Adds and removes documents: parse, chunk, embed, store, and refresh the search index."""
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from .chunking import chunk_markdown, chunk_pages
from .db import Chunk, Document
from .parsing import Parsed, parse
from .search import SearchIndex

log = logging.getLogger(__name__)


class Library:
    def __init__(self, sessions: sessionmaker, index: SearchIndex):
        self._sessions = sessions
        self.index = index

    def add(self, filename: str, data: bytes) -> Document:
        parsed = parse(filename, data)
        return self._store(filename, parsed)

    def _store(self, filename: str, parsed: Parsed) -> Document:
        pieces = chunk_markdown(parsed.pages[0], parsed.title) if parsed.kind == "md" \
            else chunk_pages(parsed.pages, parsed.title)
        vectors = None
        if self.index.embedder and pieces:
            vectors = self.index.embedder.embed([f"{p.heading}\n{p.text}" for p in pieces], "document")
        doc = Document(title=parsed.title, filename=Path(filename).name[:255], kind=parsed.kind,
                       pages=len(parsed.pages), chars=sum(len(p) for p in parsed.pages))
        doc.chunks = [Chunk(ordinal=i, page=p.page, heading=p.heading[:500], text=p.text,
                            embedding=vectors[i] if vectors else None) for i, p in enumerate(pieces)]
        with self._sessions.begin() as s:
            s.add(doc)
        self.index.rebuild()
        log.info("Added %s: %d passages", doc.title, len(pieces))
        return doc

    def remove(self, document_id: int) -> bool:
        with self._sessions.begin() as s:
            doc = s.get(Document, document_id)
            if doc is None:
                return False
            s.delete(doc)
        self.index.rebuild()
        return True

    def documents(self) -> list[tuple[Document, int]]:
        with self._sessions() as s:
            counts = dict(s.execute(select(Chunk.document_id, func.count()).group_by(Chunk.document_id)).all())
            docs = s.scalars(select(Document).order_by(Document.title)).all()
            return [(d, counts.get(d.id, 0)) for d in docs]

    def passages(self, document_id: int) -> tuple[Document, list[Chunk]] | None:
        with self._sessions() as s:
            doc = s.get(Document, document_id)
            if doc is None:
                return None
            return doc, list(s.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal)))

    def seed(self, folder: Path) -> None:
        with self._sessions() as s:
            if s.scalar(select(func.count()).select_from(Document)):
                return
        for path in sorted(folder.glob("*.md")):
            self.add(path.name, path.read_bytes())
