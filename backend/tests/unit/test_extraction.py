import io
import shutil

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.processing.extraction import ExtractionError, extract_text


def _pdf(pages: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    for lines in pages:
        y = 720
        for line in lines:
            c.drawString(72, y, line)
            y -= 14
        c.showPage()
    c.save()
    return buf.getvalue()


def test_extracts_text_from_every_page() -> None:
    result = extract_text(_pdf([["ITEMIZED STATEMENT"], ["BALANCE DUE: $1,200.00"]]))

    assert result.page_count == 2
    assert "ITEMIZED STATEMENT" in result.text
    assert "BALANCE DUE" in result.text
    assert result.ocr_pages == []


def test_pages_are_separated_with_markers() -> None:
    result = extract_text(_pdf([["first"], ["second"]]))
    assert "[page 1]" in result.text
    assert "[page 2]" in result.text


def test_blank_page_without_ocr_engine_yields_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.processing.extraction.ocr_available", lambda: False)
    result = extract_text(_pdf([[]]))
    assert result.text.strip() == "[page 1]"
    assert result.ocr_pages == []


def test_invalid_pdf_raises_extraction_error() -> None:
    with pytest.raises(ExtractionError):
        extract_text(b"%PDF-1.4 garbage that is not a real pdf")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_image_only_page_uses_ocr() -> None:
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader

    img = Image.new("L", (1700, 400), color=255)
    ImageDraw.Draw(img).text(
        (60, 150), "NOTICE OF LIEN", fill=0, font=ImageFont.load_default(size=60)
    )
    png = io.BytesIO()
    img.save(png, format="PNG")
    png.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.drawImage(ImageReader(png), 0, 400, width=612, height=144)
    c.showPage()
    c.save()

    result = extract_text(buf.getvalue())

    assert result.ocr_pages == [1]
    assert "LIEN" in result.text.upper()
