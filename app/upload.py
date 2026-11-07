"""Phone photos: the pages of one letter, photographed one after the other, become one PDF. A single PDF passes as it
is."""

from __future__ import annotations

import io
import time

from PIL import Image, ImageOps, UnidentifiedImageError

from app.texts import t

MAX_PAGES = 30
MAX_BYTES = 20 * 1024 * 1024


class UploadError(Exception):
    pass


def to_pdf(files: list[tuple[str, bytes]]) -> tuple[str, bytes]:
    """[(name, bytes)] → (name, pdf bytes)."""
    if not files:
        raise UploadError(t("upload.empty"))
    if len(files) > MAX_PAGES:
        raise UploadError(t("upload.too_many", n=MAX_PAGES))
    if any(len(data) > MAX_BYTES for _, data in files):
        raise UploadError(t("upload.too_big"))
    if len(files) == 1 and files[0][1][:5] == b"%PDF-":
        return files[0]
    pages = []
    for name, data in files:
        if data[:5] == b"%PDF-":
            raise UploadError(t("upload.pdf_alone"))
        try:
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)  # phones store the rotation apart from the pixels
        except (UnidentifiedImageError, OSError) as e:
            raise UploadError(t("upload.not_an_image", name=name)) from e
        img.thumbnail((2480, 3508))  # A4 at 300 dpi is enough for OCR
        pages.append(img.convert("RGB"))
    out = io.BytesIO()
    # a fixed date keeps the bytes the same for the same photos, so sending them twice is caught as a duplicate
    fixed = time.gmtime(946684800)  # 2000-01-01
    pages[0].save(
        out, format="PDF", save_all=True, append_images=pages[1:], resolution=200.0, creationDate=fixed, modDate=fixed
    )
    return "scan.pdf", out.getvalue()
