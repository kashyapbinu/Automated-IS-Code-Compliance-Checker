import importlib.util
import os
import re
import uuid

import pytest

from src import config
from src.rag import ingest
from src.rag.retriever import Retriever

# Chunking needs the KB-build deps (requirements-kb.txt); runtime-only installs skip these tests.
needs_splitter = pytest.mark.skipif(importlib.util.find_spec("langchain_text_splitters") is None,
                                    reason="requirements-kb.txt not installed")

SAMPLE_MD = """# SECTION 3 GENERAL DESIGN CONSIDERATION

26.4 Nominal Cover
26.4.2 Nominal Cover to Meet Durability Requirement - Minimum values for the nominal cover of normal weight
aggregate concrete which should be provided to all reinforcement shall be as given in Table 16 for different exposure
conditions. However for a longitudinal reinforcing bar in a column nominal cover shall in any case not be less than 40 mm.
26.4.2.2 For footings minimum cover shall be 50 mm.

| TABLE 16 NOMINAL COVER TO MEET DURABILITY REQUIREMENTS | |
|---|---|
| Exposure | Nominal concrete cover in mm not less than |
| Mild | 20 |
| Moderate | 30 |
| Severe | 45 |

26.5.3.1 Longitudinal reinforcement - The cross-sectional area of longitudinal reinforcement shall be not less than
0.8 percent nor more than 6 percent of the gross cross-sectional area of the column.
"""


def test_markdown_blocks_split_tables():
    blocks = ingest.blocks_from_markdown(SAMPLE_MD, page=27)
    kinds = [b.kind for b in blocks]
    assert kinds == ["text", "table", "text"]
    assert blocks[1].label == "table 16"


@needs_splitter
def test_chunks_carry_clause_metadata():
    chunks = ingest.chunk_blocks(ingest.blocks_from_markdown(SAMPLE_MD, page=27), "IS456", "is456.md")
    by_clause = {c.metadata["clause"]: c for c in chunks if c.metadata["type"] == "text"}
    assert {"26.4.2", "26.4.2.2", "26.5.3.1"} <= set(by_clause)
    cover = by_clause["26.4.2"]
    assert cover.metadata["section"].startswith("Section 3")
    assert cover.metadata["page"] == 27
    assert "table 16" in cover.metadata["refs"].split(",")
    assert cover.text.startswith("[IS456 | Cl. 26.4.2")
    table = next(c for c in chunks if c.metadata["type"] == "table")
    assert table.metadata["label"] == "table 16" and table.metadata["clause"] == "26.4.2.2"
    assert all(len(c.text) < config.CHUNK_SIZE + 120 for c in chunks if c.metadata["type"] == "text")


@needs_splitter
def test_chunk_ids_are_stable():
    a = ingest.chunk_blocks(ingest.blocks_from_markdown(SAMPLE_MD, 1), "IS456", "x.md")
    b = ingest.chunk_blocks(ingest.blocks_from_markdown(SAMPLE_MD, 1), "IS456", "x.md")
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a)


@needs_splitter
def test_repo_markdown_kb_chunks(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "KB_SOURCES_DIR", tmp_path)  # markdown only, don't parse the codebook PDFs
    chunks = ingest.collect_chunks(include_markdown=True)
    assert len(chunks) > 300
    sp34 = [c for c in chunks if c.metadata["source"] == "SP34"]
    assert any(c.metadata["type"] == "table" for c in sp34)
    assert any(c.metadata["clause"] for c in sp34)
    assert all(c.metadata["page"] > 0 for c in sp34)


@pytest.fixture
def mem_collection(fake_embedder):
    chromadb = pytest.importorskip("chromadb")
    client = chromadb.EphemeralClient()
    col = client.create_collection(f"t{uuid.uuid4().hex[:8]}", metadata={"hnsw:space": "cosine"})
    chunks = ingest.chunk_blocks(ingest.blocks_from_markdown(SAMPLE_MD, page=27), "IS456", "is456.md")
    col.add(ids=[c.id for c in chunks], documents=[c.text for c in chunks], metadatas=[c.metadata for c in chunks],
            embeddings=fake_embedder.embed_documents([c.text for c in chunks]))
    return col


def test_retrieve_with_filter_and_table_expansion(mem_collection, fake_embedder):
    r = Retriever(mem_collection, fake_embedder)
    hits = r.retrieve("nominal cover durability exposure column 40 mm", k=2, where={"source": "IS456"})
    cover = next(h for h in hits if h.metadata["clause"] == "26.4.2")
    assert cover.citation == "IS456, Cl. 26.4.2, p. 27"
    # text-only search: Table 16 can only arrive through reference expansion
    hits = r.retrieve("nominal cover durability exposure column 40 mm", k=1,
                      where={"$and": [{"source": "IS456"}, {"type": "text"}]})
    expanded = [h for h in hits if h.expanded_from]
    assert expanded and expanded[0].metadata["label"] == "table 16"
    assert r.retrieve("cover", k=2, where={"source": "SP34"}) == []


def test_numpy_index_matches_chroma(mem_collection, fake_embedder, tmp_path):
    from src.rag import index_store

    query = "nominal cover durability exposure column 40 mm"
    index_store.export(mem_collection, fake_embedder, queries=[query], index_dir=tmp_path)
    np_retriever = Retriever(index_store.NumpyCollection.load(tmp_path), index_store.PrecomputedEmbedder.load(tmp_path))
    chroma_retriever = Retriever(mem_collection, fake_embedder)
    for where in ({"source": "IS456"}, {"$and": [{"source": "IS456"}, {"type": "text"}]},
                  {"source": {"$in": ["IS456", "SP34"]}}):
        a = chroma_retriever.retrieve(query, k=2, where=where)
        b = np_retriever.retrieve(query, k=2, where=where)
        assert [h.id for h in a] == [h.id for h in b]
        assert all(abs(x.score - y.score) < 1e-4 for x, y in zip(a, b) if x.score is not None)
    assert np_retriever.retrieve(query, k=2, where={"source": "SP34"}) == []


def test_precomputed_embedder_rejects_unknown_query_without_model(monkeypatch):
    import builtins

    from src.rag.index_store import PrecomputedEmbedder

    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **k: (_ for _ in ()).throw(ImportError(name))
                        if name == "src.rag.embeddings" else real_import(name, *a, **k))
    emb = PrecomputedEmbedder(["known"], __import__("numpy").ones((1, 3)))
    assert emb.embed_query("known") == [1.0, 1.0, 1.0]
    with pytest.raises(KeyError):
        emb.embed_query("unknown query")


@pytest.mark.skipif(not os.getenv("RUN_RECALL"), reason="set RUN_RECALL=1 after building the real KB")
def test_recall_on_real_kb():
    """Content-based: OCR in the IS 456 PDF sometimes garbles clause numbers, so match on the rule text."""
    r = Retriever()
    squash = lambda t: re.sub(r"\s+", "", t).lower()  # OCR drops spaces ("footingsminimumcover")
    cases = [
        ("nominal cover for footings minimum cover", "forfootingsminimumcover"),
        ("longitudinal reinforcement column not less than 0.8 percent of gross cross sectional area", "0.8percent"),
        ("maximum spacing of shear reinforcement vertical stirrups", "0.75d"),
        ("side face reinforcement depth of web exceeds 750 mm", "750mm"),
        ("minimum reinforcement slabs high strength deformed bars", "0.12percent"),
    ]
    misses = []
    for query, phrase in cases:
        hits = r.retrieve(query, k=5, where={"source": "IS456"}, expand=False)
        if not any(phrase in squash(h.text) for h in hits):
            misses.append((query, [h.metadata.get("clause") for h in hits]))
    assert not misses, misses


def test_figure_tag_becomes_figure_block():
    md = 'Text before the figure line.\n<figure label="Fig. 4">Stirrup with 135 degree hooks, 10d extension</figure>\nAfter.'
    blocks = ingest.blocks_from_markdown(md, page=3)
    fig = next(b for b in blocks if b.kind == "figure")
    assert fig.label == "fig 4" and "135 degree" in fig.text and fig.page == 3
