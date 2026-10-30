"""Hybrid retrieval: keyword (BM25) and semantic (vector) rankings merged with reciprocal rank fusion.
Keywords catch exact terms like "SCA" or "€90"; vectors catch questions worded differently from the text."""
import re
import threading
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .db import Chunk, Document
from .embeddings import Embedder

STOPWORDS = set("""a an and are as at be but by can do does for from how i if in into is it its me my of on or our
should so than that the their them then there these they this to us was we what when where which who why will with
you your get got need needs have has many much any""".split())
RRF_K = 60


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9€°%]+", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS]


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    document_title: str
    heading: str
    page: int | None
    text: str
    score: float
    keyword_rank: int | None
    vector_rank: int | None


class SearchIndex:
    """Keeps the BM25 index in memory; vectors live in the database (pgvector on Postgres)."""

    def __init__(self, sessions: sessionmaker, embedder: Embedder | None):
        self._sessions = sessions
        self.embedder = embedder
        self._lock = threading.Lock()
        self._ids: list[int] = []
        self._bm25: BM25Okapi | None = None

    def rebuild(self) -> None:
        with self._sessions() as s:
            rows = s.execute(select(Chunk.id, Chunk.heading, Chunk.text).order_by(Chunk.id)).all()
        ids = [r.id for r in rows]
        corpus = [tokenize(f"{r.heading}\n{r.text}") for r in rows]
        with self._lock:
            self._ids = ids
            self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, question: str, k: int = 6) -> list[Hit]:
        keyword = self._keyword(question, k * 3)
        vector = self._vector(question, k * 3) if self.embedder else []
        fused: dict[int, float] = {}
        for ranking in (keyword, vector):
            for rank, chunk_id in enumerate(ranking):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
        best = sorted(fused, key=fused.get, reverse=True)[:k]
        if not best:
            return []
        with self._sessions() as s:
            rows = {c.id: c for c in s.scalars(select(Chunk).where(Chunk.id.in_(best)))}
            titles = dict(s.execute(select(Document.id, Document.title)).all())
        return [Hit(chunk_id=i, document_id=rows[i].document_id, document_title=titles[rows[i].document_id],
                    heading=rows[i].heading, page=rows[i].page, text=rows[i].text, score=round(fused[i], 5),
                    keyword_rank=keyword.index(i) + 1 if i in keyword else None,
                    vector_rank=vector.index(i) + 1 if i in vector else None)
                for i in best if i in rows]

    def _keyword(self, question: str, k: int) -> list[int]:
        terms = tokenize(question)
        with self._lock:
            if not self._bm25 or not terms:
                return []
            scores = self._bm25.get_scores(terms)
            order = np.argsort(scores)[::-1][:k]
            return [self._ids[i] for i in order if scores[i] > 0]

    def _vector(self, question: str, k: int) -> list[int]:
        query = self.embedder.embed([question], "query")[0]
        with self._sessions() as s:
            if s.get_bind().dialect.name == "postgresql":
                # pgvector: cosine distance, served by the HNSW index
                stmt = select(Chunk.id).where(Chunk.embedding.is_not(None)) \
                    .order_by(Chunk.embedding.op("<=>")(query)).limit(k)
                return list(s.scalars(stmt))
            return _cosine_top_k(s, query, k)


def _cosine_top_k(s: Session, query: list[float], k: int) -> list[int]:
    rows = s.execute(select(Chunk.id, Chunk.embedding).where(Chunk.embedding.is_not(None))).all()
    if not rows:
        return []
    matrix = np.array([r.embedding for r in rows], dtype=np.float32)
    q = np.array(query, dtype=np.float32)
    sims = matrix @ q / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(q) + 1e-9)
    return [rows[i].id for i in np.argsort(sims)[::-1][:k]]
