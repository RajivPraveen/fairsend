"""Read text from a receipt image or PDF, entirely in memory.

Receipts are never written to disk: images are piped to tesseract over stdin/stdout, and PDFs are
read (or rendered for OCR) from bytes.
"""

from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass

from PIL import Image, ImageOps

from fairsend.config import tesseract_cmd

MIN_TEXT_LAYER_CHARS = 40


class OCRUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRResult:
    text: str
    method: str   # "pdf text layer" | "tesseract"
    pages: int


def _prepare(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("L")
    # Tesseract works best around 300 dpi; phone screenshots are often small.
    if img.width < 1500:
        scale = 1500 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return ImageOps.autocontrast(img)


def ocr_image(img: Image.Image, psm: int = 4) -> str:
    cmd = tesseract_cmd()
    if not cmd:
        raise OCRUnavailable("tesseract not found; set TESSERACT_CMD or install tesseract")
    buf = io.BytesIO()
    _prepare(img).save(buf, format="PNG")
    proc = subprocess.run([cmd, "stdin", "stdout", "-l", "eng", "--psm", str(psm)],
                          input=buf.getvalue(), capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed: {proc.stderr.decode(errors='ignore')[:300]}")
    return proc.stdout.decode("utf-8", errors="ignore")


def _pdf_text_layer(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


def _pdf_ocr(data: bytes, max_pages: int = 3) -> tuple[str, int]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    try:
        texts = []
        for i in range(min(len(pdf), max_pages)):
            page = pdf[i]
            texts.append(ocr_image(page.render(scale=300 / 72).to_pil()))
            page.close()
        return "\n".join(texts), len(pdf)
    finally:
        pdf.close()


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def extract_text(data: bytes) -> OCRResult:
    if is_pdf(data):
        text, pages = _pdf_text_layer(data)
        if len(text.strip()) >= MIN_TEXT_LAYER_CHARS:
            return OCRResult(text, "pdf text layer", pages)
        text, pages = _pdf_ocr(data)
        return OCRResult(text, "tesseract", pages)
    img = Image.open(io.BytesIO(data))
    return OCRResult(ocr_image(img), "tesseract", 1)
