"""Turns text into vectors for semantic search. Voyage AI is the embedding provider Anthropic recommends."""
from typing import Protocol

import httpx


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        """kind is "document" for passages being stored and "query" for a question."""
        ...


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str, dim: int):
        self.name = model
        self._model = model
        self._dim = dim
        self._client = httpx.Client(base_url="https://api.voyageai.com/v1", timeout=30.0,
                                    headers={"Authorization": f"Bearer {api_key}"})

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 64):
            batch = texts[start:start + 64]
            r = self._client.post("/embeddings", json={
                "model": self._model, "input": batch, "input_type": kind, "output_dimension": self._dim})
            r.raise_for_status()
            vectors.extend(item["embedding"] for item in sorted(r.json()["data"], key=lambda d: d["index"]))
        return vectors
