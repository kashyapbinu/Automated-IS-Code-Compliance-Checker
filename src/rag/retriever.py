"""Semantic retrieval over the codebook collection, with metadata filters and cross-reference expansion."""
from dataclasses import dataclass
from typing import Dict, List, Optional

from src import config


@dataclass
class Hit:
    id: str
    text: str
    metadata: Dict[str, object]
    score: Optional[float] = None   # cosine distance (lower = closer); None for expanded refs
    expanded_from: Optional[str] = None

    @property
    def citation(self) -> str:
        m = self.metadata
        parts = [str(m.get("source", "?"))]
        if m.get("type") in ("table", "figure") and m.get("label"):
            parts.append(str(m["label"]).title())
        elif m.get("clause"):
            parts.append(f"Cl. {m['clause']}")
        page = m.get("page", -1)
        if isinstance(page, int) and page > 0:
            end = m.get("page_end", page)
            parts.append(f"p. {page}" if end in (page, -1) else f"pp. {page}-{end}")
        return ", ".join(parts)


def use_numpy_index() -> bool:
    """VECTOR_BACKEND=numpy|chroma; "auto" uses the exported kb_index/ when Chroma or the BGE model is not installed."""
    from src.rag.index_store import index_available

    backend = config.VECTOR_BACKEND
    if backend in ("numpy", "chroma"):
        return backend == "numpy"
    if not index_available():
        return False
    try:
        import chromadb  # noqa: F401
        import sentence_transformers  # noqa: F401
    except ImportError:
        return True
    return False


class Retriever:
    def __init__(self, collection=None, embedder=None):
        if collection is None and embedder is None and use_numpy_index():
            from src.rag.index_store import load_index

            collection, embedder = load_index()
        if collection is None:
            from src.rag.ingest import get_collection

            collection = get_collection()
        if embedder is None:
            from src.rag.embeddings import get_embedder

            embedder = get_embedder()
        self.collection = collection
        self.embedder = embedder

    def retrieve(self, query: str, k: int = None, where: Optional[dict] = None, expand: bool = True) -> List[Hit]:
        k = k or config.RETRIEVE_K
        raw = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=k,
            where=where or None,
        )
        hits = [
            Hit(raw["ids"][0][i], raw["documents"][0][i], raw["metadatas"][0][i] or {},
                raw["distances"][0][i] if raw.get("distances") else None)
            for i in range(len(raw["ids"][0]))
        ]
        if expand:
            hits += self._expand(hits)
        return hits

    def _expand(self, hits: List[Hit], max_extra: int = 2) -> List[Hit]:
        """Pull in tables/figures that the retrieved text explicitly references (e.g. 'see Table 16')."""
        have = {h.id for h in hits}
        wanted: Dict[tuple, str] = {}  # (label, source) -> id of the hit that referenced it
        for h in hits:
            for ref in str(h.metadata.get("refs", "")).split(","):
                ref = ref.strip()
                if ref.startswith(("table ", "fig ")) and ref != h.metadata.get("label"):
                    wanted.setdefault((ref, h.metadata.get("source", "")), h.id)
        if not wanted:
            return []
        clauses = [{"$and": [{"label": label}, {"source": source}]} for label, source in list(wanted)[: max_extra * 2]]
        where = clauses[0] if len(clauses) == 1 else {"$or": clauses}
        got = self.collection.get(where=where, limit=max_extra * 2)
        extra = []
        for i, cid in enumerate(got.get("ids", [])):
            if cid in have:
                continue
            meta = got["metadatas"][i] or {}
            extra.append(Hit(cid, got["documents"][i], meta, None, wanted.get((meta.get("label"), meta.get("source")))))
            have.add(cid)
            if len(extra) >= max_extra:
                break
        return extra
