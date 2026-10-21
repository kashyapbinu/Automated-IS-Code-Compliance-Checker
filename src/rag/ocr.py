"""Re-OCR codebook PDF pages with Gemini vision into clean per-page markdown.

The text layer of scanned codebooks (e.g. IS 456) is often unusable ("Minimwn injorceIMnt").
Each page becomes kb_md/<pdf stem>/p0001.md with text, markdown tables and one-line figure
descriptions (<figure label="Fig. 4">...</figure>). Pages already converted are skipped, so the
run can be resumed.

Usage:  python -m src.rag.ocr kb_sources/is.456.2000.pdf [--pages 1-40] [--workers 4]
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional

from src import config, llm, preprocess

PROMPT = """Transcribe this page of an Indian Standard concrete codebook into markdown. Rules:
- Reproduce the text exactly, fixing only obvious OCR-style breaks. Keep clause numbers exactly (e.g. "26.4.2.2").
- Start each clause on its own line beginning with its number: "26.5.1.1 Minimum reinforcement - ...".
- Section headings as "# SECTION 3 GENERAL DESIGN CONSIDERATION".
- Tables as markdown tables, preceded by their title line, e.g. "TABLE 16 NOMINAL COVER ...".
- Each figure/diagram as ONE line: <figure label="Fig. 4">what it shows: dimensions, bar arrangement, limits</figure>
- Use plain text for maths, e.g. "Ld = phi * sigma_s / (4 * tau_bd)".
- Omit running headers/footers and page numbers. Output only the markdown."""


def page_dir(pdf: Path) -> Path:
    return config.KB_OCR_DIR / pdf.stem


def page_path(pdf: Path, pno: int) -> Path:
    return page_dir(pdf) / f"p{pno:04d}.md"


def ocr_page(pdf: Path, pno: int) -> Path:
    img = preprocess.normalize_image(preprocess.pdf_page_image(pdf, pno))
    text = llm.chat("figure", "You transcribe engineering standards precisely.", PROMPT,
                    image_urls=[preprocess.to_data_url(img)], max_tokens=8000)
    out = page_path(pdf, pno)
    out.write_text(text.strip().removeprefix("```markdown").removesuffix("```").strip() + "\n", encoding="utf-8")
    return out


def parse_pages(spec: Optional[str], total: int) -> List[int]:
    if not spec:
        return list(range(1, total + 1))
    pages = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return sorted(p for p in pages if 1 <= p <= total)


def run(pdf: Path, pages: Iterable[int], workers: int = 4):
    page_dir(pdf).mkdir(parents=True, exist_ok=True)
    todo = [p for p in pages if not page_path(pdf, p).exists()]
    print(f"{pdf.name}: {len(todo)} page(s) to OCR")
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(ocr_page, pdf, p): p for p in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            p = futures[fut]
            try:
                fut.result()
                print(f"  [{n}/{len(todo)}] page {p} ok", flush=True)
            except Exception as e:
                failed.append(p)
                print(f"  [{n}/{len(todo)}] page {p} FAILED: {str(e)[:150]}", flush=True)
    if failed:
        print(f"Failed pages (re-run to retry): {sorted(failed)}")


def main():
    import pymupdf

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--pages", help="e.g. 1-40,55")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    with pymupdf.open(args.pdf) as doc:
        total = len(doc)
    run(args.pdf, parse_pages(args.pages, total), args.workers)


if __name__ == "__main__":
    main()
