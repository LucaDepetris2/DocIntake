"""Text extraction from PDFs.

Strategy per page: use the embedded text layer (pdfplumber, fast and exact). If a page
has no text layer (a scan), fall back to OCR with Tesseract when it is installed.
"""

import io
import shutil
from dataclasses import dataclass, field
from functools import cache

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError

MIN_CHARS_PER_PAGE = 20  # less than this on a page -> treat it as a scan
OCR_RESOLUTION = 300


class ExtractionError(Exception):
    """The file cannot be parsed as a PDF (permanent: retrying won't help)."""


@dataclass
class ExtractionResult:
    text: str
    page_count: int
    ocr_pages: list[int] = field(default_factory=list)


@cache
def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_page(page: "pdfplumber.page.Page") -> str:
    import pytesseract  # imported lazily: optional system dependency

    image = page.to_image(resolution=OCR_RESOLUTION).original
    return str(pytesseract.image_to_string(image))


def extract_text(data: bytes) -> ExtractionResult:
    parts: list[str] = []
    ocr_pages: list[int] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if len(text.strip()) < MIN_CHARS_PER_PAGE and ocr_available():
                    ocr_text = _ocr_page(page)
                    if len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                        ocr_pages.append(number)
                parts.append(f"[page {number}]\n{text.strip()}")
            page_count = len(pdf.pages)
    except (PDFSyntaxError, ValueError, KeyError, TypeError) as exc:
        raise ExtractionError(f"Unreadable PDF: {type(exc).__name__}") from exc
    except Exception as exc:  # pdfminer raises a zoo of exception types
        if type(exc).__module__.startswith(("pdfminer", "pdfplumber")):
            raise ExtractionError(f"Unreadable PDF: {type(exc).__name__}") from exc
        raise
    return ExtractionResult(text="\n\n".join(parts), page_count=page_count, ocr_pages=ocr_pages)
