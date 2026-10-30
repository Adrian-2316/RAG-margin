"""Retrieval eval: does search put the passage that holds the answer in the top k?

    uv run python -m evals.retrieval            # keyword search
    VOYAGE_API_KEY=... uv run python -m evals.retrieval   # hybrid search

Runs against a throwaway SQLite library built from seed_docs/, so it never touches your data.
"""
import os
import sys
import tempfile
from pathlib import Path

import yaml

from margin.config import Settings
from margin.db import make_engine, make_sessionmaker
from margin.embeddings import VoyageEmbedder
from margin.library import Library
from margin.search import SearchIndex

ROOT = Path(__file__).resolve().parent.parent
K = 3


def main() -> int:
    settings = Settings()
    cases = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text())
    embedder = (VoyageEmbedder(settings.voyage_api_key, settings.voyage_model, settings.embedding_dim)
                if settings.voyage_api_key else None)
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite:///{tmp}/eval.db", settings.embedding_dim)
        index = SearchIndex(make_sessionmaker(engine), embedder)
        Library(make_sessionmaker(engine), index).seed(ROOT / "seed_docs")
        index.rebuild()

        hits_at_k, reciprocal = 0, 0.0
        for case in cases:
            headings = [h.heading for h in index.search(case["q"], k=10)]
            rank = headings.index(case["expect"]) + 1 if case["expect"] in headings else None
            hits_at_k += bool(rank and rank <= K)
            reciprocal += 1 / rank if rank else 0
            mark = "ok " if rank and rank <= K else "MISS"
            print(f"{mark} rank={rank or '-':>2}  {case['q']}")
        engine.dispose()

    n = len(cases)
    print(f"\nsearch: {'hybrid (' + embedder.name + ')' if embedder else 'keywords'}")
    print(f"recall@{K}: {hits_at_k / n:.0%}   MRR: {reciprocal / n:.2f}   ({n} questions)")
    return 0 if hits_at_k / n >= float(os.environ.get("MIN_RECALL", "0.8")) else 1


if __name__ == "__main__":
    sys.exit(main())
