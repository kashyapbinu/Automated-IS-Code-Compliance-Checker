"""Portable knowledge-base index: the Chroma collection exported to numpy + JSON, searched without Chroma or torch.

The BGE-large passage vectors and the vectors of every compliance-check query are computed once, locally,
and saved to kb_index/. A deployment (e.g. Streamlit Community Cloud) then only needs numpy: the
retrieval queries are fixed per check (src.agents.checks), so no embedding model runs at request time.

  kb_index/chunks.json      ids, documents, metadatas
  kb_index/embeddings.npy   float32 (n_chunks, dim), L2-normalised
  kb_index/queries.json     query strings, row-aligned with queries.npy
  kb_index/queries.npy      float32 (n_queries, dim), L2-normalised (BGE query instruction applied)

Usage:  python -m src.rag.index_store      (export from the existing Chroma collection)
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

from src import config


# --------------------------------------------------------------------------- where-filter (Chroma subset)

def matches(meta: Dict[str, object], where: Optional[dict]) -> bool:
    """Evaluate the Chroma `where` subset used in this project: equality, $in, $and, $or."""
    if not where:
        return True
    for key, cond in where.items():
        if key == "$and":
            if not all(matches(meta, c) for c in cond):
                return False
        elif key == "$or":
            if not any(matches(meta, c) for c in cond):
                return False
        elif isinstance(cond, dict):
            if "$in" in cond and meta.get(key) not in cond["$in"]:
                return False
            if "$eq" in cond and meta.get(key) != cond["$eq"]:
                return False
        elif meta.get(key) != cond:
            return False
    return True


# --------------------------------------------------------------------------- collection

class NumpyCollection:
    """Drop-in for the two Chroma collection calls the Retriever makes: query() and get()."""

    def __init__(self, ids: List[str], documents: List[str], metadatas: List[dict], embeddings: np.ndarray):
        self.ids, self.documents, self.metadatas = ids, documents, metadatas
        self.embeddings = embeddings.astype(np.float32)

    @classmethod
    def load(cls, index_dir: Path = None) -> "NumpyCollection":
        index_dir = Path(index_dir or config.KB_INDEX_DIR)
        data = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
        return cls(data["ids"], data["documents"], data["metadatas"], np.load(index_dir / "embeddings.npy"))

    def count(self) -> int:
        return len(self.ids)

    def _rows(self, where: Optional[dict]) -> np.ndarray:
        return np.array([i for i, m in enumerate(self.metadatas) if matches(m, where)], dtype=int)

    def query(self, query_embeddings, n_results: int = 4, where: Optional[dict] = None) -> dict:
        rows = self._rows(where)
        out = {"ids": [], "documents": [], "metadatas": [], "distances": []}
        for q in query_embeddings:
            if rows.size == 0:
                top, dist = [], []
            else:
                sims = self.embeddings[rows] @ np.asarray(q, dtype=np.float32)
                order = np.argsort(-sims)[:n_results]
                top, dist = rows[order].tolist(), (1.0 - sims[order]).tolist()  # cosine distance, as Chroma
            out["ids"].append([self.ids[i] for i in top])
            out["documents"].append([self.documents[i] for i in top])
            out["metadatas"].append([self.metadatas[i] for i in top])
            out["distances"].append(dist)
        return out

    def get(self, where: Optional[dict] = None, limit: Optional[int] = None) -> dict:
        rows = self._rows(where).tolist()[:limit]
        return {"ids": [self.ids[i] for i in rows], "documents": [self.documents[i] for i in rows],
                "metadatas": [self.metadatas[i] for i in rows]}


class PrecomputedEmbedder:
    """Looks up query vectors computed at export time; falls back to the real BGE model if it is installed."""

    def __init__(self, queries: List[str], vectors: np.ndarray):
        self.vectors = {q: v for q, v in zip(queries, vectors.astype(np.float32))}

    @classmethod
    def load(cls, index_dir: Path = None) -> "PrecomputedEmbedder":
        index_dir = Path(index_dir or config.KB_INDEX_DIR)
        queries = json.loads((index_dir / "queries.json").read_text(encoding="utf-8"))
        return cls(queries, np.load(index_dir / "queries.npy"))

    def embed_query(self, text: str) -> List[float]:
        if text in self.vectors:
            return self.vectors[text].tolist()
        try:
            from src.rag.embeddings import get_embedder
        except ImportError:
            get_embedder = None
        try:
            return get_embedder().embed_query(text)
        except Exception as e:
            raise KeyError(f"query not in kb_index/queries.json and no embedding model available: {text!r}. "
                           "Re-run `python -m src.rag.index_store` after changing check queries.") from e


def index_available(index_dir: Path = None) -> bool:
    index_dir = Path(index_dir or config.KB_INDEX_DIR)
    return all((index_dir / f).exists() for f in ("chunks.json", "embeddings.npy", "queries.json", "queries.npy"))


@lru_cache(maxsize=1)
def load_index():
    return NumpyCollection.load(), PrecomputedEmbedder.load()


# --------------------------------------------------------------------------- export

def all_check_queries() -> List[str]:
    from src.agents.checks import COMMON_CHECKS, TYPE_CHECKS

    queries = [c.query for c in COMMON_CHECKS] + [c.query for checks in TYPE_CHECKS.values() for c in checks]
    return list(dict.fromkeys(queries))


def export(collection=None, embedder=None, queries: Iterable[str] = None, index_dir: Path = None) -> Path:
    """Write kb_index/ from a Chroma collection (vectors are copied, not recomputed)."""
    if collection is None:
        from src.rag.ingest import get_collection

        collection = get_collection()
    if embedder is None:
        from src.rag.embeddings import get_embedder

        embedder = get_embedder()
    index_dir = Path(index_dir or config.KB_INDEX_DIR)
    index_dir.mkdir(parents=True, exist_ok=True)

    data = collection.get(include=["documents", "metadatas", "embeddings"])
    order = sorted(range(len(data["ids"])), key=lambda i: data["ids"][i])  # stable file contents across exports
    (index_dir / "chunks.json").write_text(json.dumps({
        "ids": [data["ids"][i] for i in order],
        "documents": [data["documents"][i] for i in order],
        "metadatas": [data["metadatas"][i] for i in order],
    }, ensure_ascii=False), encoding="utf-8")
    np.save(index_dir / "embeddings.npy", np.asarray(data["embeddings"], dtype=np.float32)[order])

    queries = list(queries) if queries is not None else all_check_queries()
    (index_dir / "queries.json").write_text(json.dumps(queries, ensure_ascii=False, indent=0), encoding="utf-8")
    np.save(index_dir / "queries.npy", np.asarray([embedder.embed_query(q) for q in queries], dtype=np.float32))
    print(f"Exported {len(order)} chunks and {len(queries)} check queries to {index_dir}")
    return index_dir


if __name__ == "__main__":
    export()
