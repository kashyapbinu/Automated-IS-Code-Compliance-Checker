from pathlib import Path

from PIL import Image

from src import preprocess

SAMPLES = Path(__file__).resolve().parent.parent / "sample_pdfs"


def test_downscales_large_image():
    out = preprocess.normalize_image(Image.new("RGBA", (6000, 3000)), max_side=2048, min_side=800)
    assert out.mode == "RGB"
    assert max(out.size) == 2048
    assert out.size == (2048, 1024)


def test_upscales_small_image():
    out = preprocess.normalize_image(Image.new("L", (400, 200)), max_side=2048, min_side=800)
    assert out.size == (800, 400)


def test_keeps_in_range_image():
    img = Image.new("RGB", (1200, 900))
    assert preprocess.normalize_image(img, max_side=2048, min_side=800) is img


def test_data_url():
    url = preprocess.to_data_url(Image.new("RGB", (10, 10)))
    assert url.startswith("data:image/png;base64,")


def test_pdf_pages_respect_limits():
    pdf = next(SAMPLES.glob("*.pdf"))
    images = preprocess.load_inputs([(pdf.name, pdf.read_bytes())])
    assert images
    for img in images:
        assert img.mode == "RGB"
        assert max(img.size) <= 2048
