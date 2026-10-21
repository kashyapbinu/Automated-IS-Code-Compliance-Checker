"""Build the IS 456 / SP 34 knowledge base.

Sources
  kb_sources/*.pdf   original codebooks (IS456*.pdf, SP34*.pdf). Text, tables and figures are extracted
                     per page with PyMuPDF; figures can be described by Gemini (--describe-figures).
  SP34_md/*.md       existing OCR markdown of SP 34 + hand-written drawing-reading guides.

Every chunk carries: source, doc, page, page_end, section, clause, clause_title, type (text|table|figure),
label (e.g. "table 16", "fig 4.3") and refs (labels/clauses it mentions) so the retriever can
pull in referenced tables and figures.

Usage:  python -m src.rag.ingest [--reset] [--describe-figures] [--skip-markdown]
"""
import argparse
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from src import config

# Clause heading: "26.4.2.2 For footings ..." (title must start with a capital, so "2.5 times d" is not a clause).
CLAUSE_RE = re.compile(r"^(?:#+\s*)?([1-9]\d?(?:\.\d{1,2}){1,3}|[A-H]-\d{1,2}(?:\.\d{1,2}){0,3})\.?\s*([A-Z(].{0,120})")  # OCR may drop the space; annex clauses "B-2.1"
ANNEX_RE = re.compile(r"^#+\s*ANNEX\s+([A-H])\b\s*(.*)$")
# Upper-case "SECTION 5" heading only: drawing callouts ("Section A-A", "Sections - 1:50") and
# table-of-contents lines ("Section 4 General detailing ..... 27") are not document sections.
SECTION_RE = re.compile(r"^(?:#+\s*)?SECTION\s+(\d{1,2})\b(?!.*\.{4})\s*(.*)$")
TABLE_LABEL_RE = re.compile(r"\bTABLE\s+(\d+(?:\.\d+)?[A-Z]?)\b", re.IGNORECASE)
FIG_LABEL_RE = re.compile(r"\bFIG(?:URE)?\.?\s*(\d+(?:\.\d+)*[A-Z]?)\b", re.IGNORECASE)
CLAUSE_REF_RE = re.compile(r"\b(?:clause|cl\.|see)\s+(\d{1,2}(?:\.\d{1,2})+)", re.IGNORECASE)
PAGE_RANGE_RE = re.compile(r"p(\d{3,4})-(\d{3,4})")
FIGURE_TAG_RE = re.compile(r'^<figure(?:\s+label="([^"]*)")?>(.*)</figure>$')

TABLE_MAX_CHARS = 2500


@dataclass
class Block:
    kind: str                 # "text" | "table" | "figure"
    text: str
    page: Optional[int] = None
    label: str = ""


@dataclass
class Chunk:
    id: str
    text: str
    metadata: Dict[str, object] = field(default_factory=dict)


def table_label(text: str) -> str:
    m = TABLE_LABEL_RE.search(text)
    return f"table {m.group(1).lower()}" if m else ""


def fig_label(text: str) -> str:
    m = FIG_LABEL_RE.search(text)
    return f"fig {m.group(1).lower()}" if m else ""


def find_refs(text: str) -> List[str]:
    refs = {f"table {m.lower()}" for m in TABLE_LABEL_RE.findall(text)}
    refs |= {f"fig {m.lower()}" for m in FIG_LABEL_RE.findall(text)}
    refs |= set(CLAUSE_REF_RE.findall(text))
    return sorted(refs)


def source_for(path: Path) -> str:
    name = re.sub(r"[^A-Z0-9]", "", path.stem.upper())  # "is.sp.34.1987" -> "ISSP341987"
    if "456" in name:
        return "IS456"
    if "SP34" in name or "OCR" in name:
        return "SP34"
    return "GUIDE"


# --------------------------------------------------------------------------- block extraction

def blocks_from_markdown(text: str, page: Optional[int] = None) -> List[Block]:
    """Split OCR markdown into text and table blocks. Tables are runs of lines starting with '|'."""
    blocks: List[Block] = []
    buf: List[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            if buf:
                blocks.append(Block("text", "\n".join(buf), page))
                buf = []
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            table = "\n".join(rows)
            context = "\n".join(lines[max(0, i - len(rows) - 4) : i - len(rows)])
            blocks.append(Block("table", table, page, table_label(table.splitlines()[0]) or table_label(context)))
            continue
        fig = FIGURE_TAG_RE.match(lines[i].strip())
        if fig:  # one-line figure description written by src.rag.ocr
            if buf:
                blocks.append(Block("text", "\n".join(buf), page))
                buf = []
            blocks.append(Block("figure", f"{fig.group(1)}: {fig.group(2)}".strip(": "), page, fig_label(fig.group(1))))
            i += 1
            continue
        buf.append(lines[i])
        i += 1
    if buf:
        blocks.append(Block("text", "\n".join(buf), page))
    return blocks


def _intersects(a, b) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def blocks_from_pdf(path: Path, describe: Optional[Callable[[bytes, str], str]] = None,
                    skip_text_pages: Optional[set] = None) -> List[Block]:
    """Per page: tables (PyMuPDF find_tables -> markdown), remaining text, and figures (optionally described).
    Pages in skip_text_pages only contribute figures."""
    import pymupdf

    skip_text_pages = skip_text_pages or set()

    blocks: List[Block] = []
    doc = pymupdf.open(path)
    try:
        for page in doc:
            pno = page.number + 1
            text_blocks = [b for b in page.get_text("blocks") if b[6] == 0]
            if pno in skip_text_pages:
                tables = []
            else:
                try:
                    tables = page.find_tables().tables
                except Exception:
                    tables = []

            table_boxes = []
            for t in tables:
                md = t.to_markdown()
                if not md.strip():
                    continue
                table_boxes.append(t.bbox)
                above = [b[4] for b in text_blocks if b[3] <= t.bbox[1] + 2 and b[3] >= t.bbox[1] - 60]
                blocks.append(Block("table", md, pno, table_label(md.splitlines()[0]) or table_label(" ".join(above))))

            body = [b[4] for b in text_blocks if not any(_intersects(b[:4], tb) for tb in table_boxes)]
            if body and pno not in skip_text_pages:
                blocks.append(Block("text", "\n".join(body), pno))

            if describe:
                captions = [b[4].strip() for b in text_blocks if FIG_LABEL_RE.match(b[4].strip())]
                for n, img in enumerate(page.get_images(full=True)):
                    info = doc.extract_image(img[0])
                    if info.get("width", 0) < 150 or info.get("height", 0) < 150:
                        continue
                    caption = captions[n] if n < len(captions) else ""
                    description = describe(info["image"], caption)
                    if description:
                        blocks.append(Block("figure", f"{caption}\n{description}".strip(), pno, fig_label(caption)))
    finally:
        doc.close()
    return blocks


def gemini_describer(image_bytes: bytes, caption: str) -> str:
    import base64

    from src import llm

    url = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    prompt = (
        "This figure is from an Indian concrete codebook (IS 456 / SP 34)"
        + (f", captioned '{caption}'" if caption else "")
        + ". Describe the detailing rule it shows: dimensions, bar arrangement, limits, notations. "
        "Plain text, max 150 words. If it is a logo or decoration reply with an empty string."
    )
    try:
        return llm.chat("figure", "You describe engineering figures precisely.", prompt, image_urls=[url], max_tokens=400).strip()
    except Exception as e:
        print(f"  figure description failed: {e}")
        return ""


# --------------------------------------------------------------------------- chunking

def _splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)


def _split_table(text: str) -> List[str]:
    if len(text) <= TABLE_MAX_CHARS:
        return [text]
    lines = text.splitlines()
    header, rows = lines[:2], lines[2:]
    parts, cur = [], []
    for row in rows:
        if cur and len("\n".join(header + cur + [row])) > TABLE_MAX_CHARS:
            parts.append("\n".join(header + cur))
            cur = []
        cur.append(row)
    if cur:
        parts.append("\n".join(header + cur))
    return parts


def _chunk_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def chunk_blocks(blocks: Iterable[Block], source: str, doc: str, page_end: Optional[int] = None) -> List[Chunk]:
    """Walk blocks in reading order, tracking section/clause, and emit metadata-rich chunks."""
    splitter = _splitter()
    chunks: List[Chunk] = []
    state = {"section": "", "clause": "", "clause_title": ""}

    def meta(kind: str, page, label: str, text: str) -> Dict[str, object]:
        return {
            "source": source,
            "doc": doc,
            "page": page if page is not None else -1,
            "page_end": page_end if page_end is not None else (page if page is not None else -1),
            "section": state["section"],
            "clause": state["clause"],
            "clause_title": state["clause_title"],
            "type": kind,
            "label": label,
            "refs": ",".join(find_refs(text)),
        }

    def header() -> str:
        bits = [source]
        if state["clause"]:
            bits.append(f"Cl. {state['clause']} {state['clause_title']}".strip())
        elif state["section"]:
            bits.append(state["section"])
        return "[" + " | ".join(bits) + "]\n"

    def emit_text(lines: List[str], page):
        body = "\n".join(lines).strip()
        single_line = sum(1 for ln in lines if ln.strip()) < 2
        is_title = body.startswith("#") or (len(body) < 80 and not body.endswith((".", ":", ";")))
        if len(body) < 30 or (single_line and is_title):
            return  # empty or heading-only segment
        for n, piece in enumerate(splitter.split_text(body)):
            text = header() + piece
            chunks.append(Chunk(_chunk_id(doc, page, "text", state["clause"], n, piece), text, meta("text", page, "", piece)))

    for block in blocks:
        if block.kind == "text":
            seg: List[str] = []
            for line in block.text.splitlines():
                s = line.strip()
                sec = SECTION_RE.match(s) or ANNEX_RE.match(s)
                cl = CLAUSE_RE.match(s)
                if not (sec or cl) and s.startswith("#") and re.fullmatch(r"Section \d+", state["section"]):
                    state["section"] += " " + s.strip("# $").title()  # OCR puts the section title on the next heading
                if sec or cl:
                    emit_text(seg, block.page)
                    seg = []
                    if sec:
                        kind = "Annex" if sec.re is ANNEX_RE else "Section"
                        state["section"] = f"{kind} {sec.group(1)} {sec.group(2).strip(' #$')}".strip()
                        state["clause"], state["clause_title"] = "", ""
                    else:
                        state["clause"] = cl.group(1)
                        state["clause_title"] = re.split(r"[.\-–—:]\s", cl.group(2))[0][:80].strip(" #")
                seg.append(line)
            emit_text(seg, block.page)
        else:
            for n, piece in enumerate(_split_table(block.text) if block.kind == "table" else [block.text]):
                prefix = f"[{source} | {block.kind.upper()} {block.label.split(' ', 1)[-1] if block.label else ''}]\n"
                chunks.append(
                    Chunk(_chunk_id(doc, block.page, block.kind, block.label, n, piece), prefix + piece,
                          meta(block.kind, block.page, block.label, piece))
                )
    return chunks


# --------------------------------------------------------------------------- driver

def collect_chunks(describe_figures: bool = False, include_markdown: bool = True) -> List[Chunk]:
    """Per PDF page, the best available text wins:
    1. kb_md/<pdf stem>/pNNNN.md (Gemini re-OCR via src.rag.ocr: text, tables and figures),
    2. SP34_md/ OCR markdown covering that page range (text/tables; figures still from the PDF),
    3. the PDF's own text layer (only for PDFs with no re-OCR'd pages)."""
    chunks: List[Chunk] = []
    describe = gemini_describer if describe_figures else None

    md_files = sorted(config.KB_MARKDOWN_DIR.glob("*.md")) if include_markdown and config.KB_MARKDOWN_DIR.is_dir() else []
    md_pages: Dict[str, set] = {}
    for path in md_files:
        m = PAGE_RANGE_RE.search(path.stem)
        if m:
            md_pages.setdefault(source_for(path), set()).update(range(int(m.group(1)), int(m.group(2)) + 1))

    pdfs = sorted(config.KB_SOURCES_DIR.glob("*.pdf")) if config.KB_SOURCES_DIR.is_dir() else []
    for path in pdfs:
        source = source_for(path)
        ocr_pages = {int(p.stem[1:]): p for p in (config.KB_OCR_DIR / path.stem).glob("p[0-9]*.md")}
        print(f"PDF  {path.name} ({source}, {len(ocr_pages)} re-OCR'd page(s))")
        if ocr_pages:
            # A re-OCR'd PDF has an unusable text layer: pages that were not re-OCR'd (front matter,
            # committee lists) are dropped instead of indexing garbled text. PDF figures are still described.
            pdf_blocks = blocks_from_pdf(path, describe, skip_text_pages=set(range(1, 10_000))) if describe else []
        else:
            pdf_blocks = blocks_from_pdf(path, describe, skip_text_pages=md_pages.get(source, set()))
        blocks = [b for b in pdf_blocks if b.page not in ocr_pages]
        for pno, md in ocr_pages.items():
            blocks += blocks_from_markdown(md.read_text(encoding="utf-8"), pno)
        blocks.sort(key=lambda b: b.page or 0)  # stable: keeps reading order within a page
        chunks += chunk_blocks(blocks, source, path.name)

    for path in md_files:
        print(f"MD   {path.name}")
        m = PAGE_RANGE_RE.search(path.stem)
        start, end = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        chunks += chunk_blocks(blocks_from_markdown(path.read_text(encoding="utf-8"), start), source_for(path), path.name, end)

    unique = {c.id: c for c in chunks}
    return list(unique.values())


def get_collection(reset: bool = False):
    import chromadb

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    if reset:
        try:
            client.delete_collection(config.COLLECTION_NAME)
        except Exception:
            pass
    return client.get_or_create_collection(config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


def ingest(reset: bool = False, describe_figures: bool = False, include_markdown: bool = True, embedder=None, batch: int = 64):
    from src.rag.embeddings import get_embedder

    chunks = collect_chunks(describe_figures, include_markdown)
    if not chunks:
        raise SystemExit("No sources found. Put IS456/SP34 PDFs in kb_sources/ or markdown in SP34_md/.")
    embedder = embedder or get_embedder()
    collection = get_collection(reset)
    for i in range(0, len(chunks), batch):
        part = chunks[i : i + batch]
        collection.upsert(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            metadatas=[c.metadata for c in part],
            embeddings=embedder.embed_documents([c.text for c in part]),
        )
        print(f"  upserted {min(i + batch, len(chunks))}/{len(chunks)}")

    by_type: Dict[str, int] = {}
    for c in chunks:
        key = f"{c.metadata['source']}/{c.metadata['type']}"
        by_type[key] = by_type.get(key, 0) + 1
    print(f"Done: {collection.count()} chunks in '{config.COLLECTION_NAME}'. {by_type}")
    return collection


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="drop and rebuild the collection")
    ap.add_argument("--describe-figures", action="store_true", help="describe PDF figures with Gemini (API cost)")
    ap.add_argument("--skip-markdown", action="store_true", help="ignore SP34_md/")
    args = ap.parse_args()
    ingest(args.reset, args.describe_figures, not args.skip_markdown)


if __name__ == "__main__":
    main()
