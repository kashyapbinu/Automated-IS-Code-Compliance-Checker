"""PDF/image preprocessing: PyMuPDF rasterisation, PIL size limits, base64 data URLs."""
import base64
import io
from typing import Iterable, List, Union

from PIL import Image

from src import config


def pdf_to_images(pdf: Union[str, bytes], dpi: int = None, max_pages: int = None) -> List[Image.Image]:
    """Rasterise PDF pages (path or raw bytes) into PIL images."""
    import pymupdf

    dpi = dpi or config.PDF_DPI
    max_pages = max_pages or config.MAX_PAGES
    doc = pymupdf.open(stream=pdf, filetype="pdf") if isinstance(pdf, (bytes, bytearray)) else pymupdf.open(pdf)
    try:
        images = []
        for page in list(doc)[:max_pages]:
            pix = page.get_pixmap(dpi=dpi)
            images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
        return images
    finally:
        doc.close()


def pdf_page_image(pdf_path, pno: int, dpi: int = None) -> Image.Image:
    """Rasterise one (1-based) page."""
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        pix = doc[pno - 1].get_pixmap(dpi=dpi or config.PDF_DPI)
        return Image.open(io.BytesIO(pix.tobytes("png")))


def normalize_image(img: Image.Image, max_side: int = None, min_side: int = None) -> Image.Image:
    """Enforce RGB mode and keep the longest side within [min_side, max_side]."""
    max_side = max_side or config.MAX_IMAGE_SIDE
    min_side = min_side or config.MIN_IMAGE_SIDE

    if img.mode != "RGB":
        img = img.convert("RGB")
    longest = max(img.size)
    if longest > max_side:
        scale = max_side / longest
    elif longest < min_side:
        scale = min_side / longest
    else:
        return img
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(new_size, Image.LANCZOS)


def to_data_url(img: Image.Image, fmt: str = "PNG") -> str:
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/{fmt.lower()};base64,{encoded}"


def prepare_images(images: Iterable[Image.Image]) -> List[Image.Image]:
    return [normalize_image(img) for img in images]


def load_inputs(files: Iterable[tuple]) -> List[Image.Image]:
    """files: iterable of (filename, bytes). PDFs are rasterised, images opened directly."""
    images: List[Image.Image] = []
    for name, data in files:
        if name.lower().endswith(".pdf"):
            images.extend(pdf_to_images(data))
        else:
            images.append(Image.open(io.BytesIO(data)))
    return prepare_images(images)
