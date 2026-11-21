"""Phone photos: the pages of one letter, photographed one after the other, become one PDF. A single PDF passes as it
is.

The tools share 1 GB, so a letter is put together one page at a time: a photo is read from its upload file, decoded
only as far as the page needs (JPEG at 1/2, 1/4 or 1/8 of its size where that is still big enough, `Image.draft`),
shrunk to A4 at 300 dpi and turned into a one-page PDF before the next photo is opened; pypdf joins the pages. At most
about 60 MB per letter, 20 MB per file and 40 megapixels per photo. Blocking work: callers run it in a thread, under
`pipeline.HEAVY`."""

from __future__ import annotations

import io
import time
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter

from app.texts import t

MAX_PAGES = 30
MAX_BYTES = 20 * 1024 * 1024  # per file
MAX_TOTAL = 60 * 1024 * 1024  # per letter
MAX_PIXELS = 40_000_000
PAGE = (2480, 3508)  # A4 at 300 dpi is enough for OCR
ORIENTATION = 0x0112  # EXIF: phones store the rotation apart from the pixels
TURNED = (5, 6, 7, 8)
# a fixed date keeps the bytes the same for the same photos, so sending them twice is caught as a duplicate
FIXED = time.gmtime(946684800)  # 2000-01-01


class UploadError(Exception):
    pass


def _size(f: BinaryIO) -> int:
    f.seek(0, io.SEEK_END)
    size = f.tell()
    f.seek(0)
    return size


def _fit(size: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    scale = min(box[0] / size[0], box[1] / size[1], 1.0)
    return max(1, int(size[0] * scale)), max(1, int(size[1] * scale))


def _page(name: str, f: BinaryIO) -> bytes:
    """One photo → a one-page PDF. Only this photo is decoded while it runs."""
    f.seek(0)
    try:
        img = Image.open(f)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise UploadError(t("upload.not_an_image", name=name)) from e
    with img:
        if img.width * img.height > MAX_PIXELS:
            raise UploadError(t("upload.too_many_pixels", name=name, mp=MAX_PIXELS // 1_000_000))
        box = PAGE[::-1] if img.getexif().get(ORIENTATION) in TURNED else PAGE
        try:
            img.draft(None, _fit(img.size, box))
            img.thumbnail(box)
            ImageOps.exif_transpose(img, in_place=True)  # in place: no second copy of the page
        except (OSError, ValueError, SyntaxError) as e:  # a truncated or broken file
            raise UploadError(t("upload.not_an_image", name=name)) from e
        page = img if img.mode in ("RGB", "L") else img.convert("RGB")
        out = io.BytesIO()
        page.save(out, format="PDF", resolution=200.0, creationDate=FIXED, modDate=FIXED)
        page.close()
    return out.getvalue()


def to_pdf(files: list[tuple[str, BinaryIO]]) -> tuple[str, bytes]:
    """[(name, file)] → (name, pdf bytes)."""
    if not files:
        raise UploadError(t("upload.empty"))
    if len(files) > MAX_PAGES:
        raise UploadError(t("upload.too_many", n=MAX_PAGES))
    sizes = [_size(f) for _, f in files]
    if any(size > MAX_BYTES for size in sizes):
        raise UploadError(t("upload.too_big"))
    if sum(sizes) > MAX_TOTAL:
        raise UploadError(t("upload.too_big_total", mb=MAX_TOTAL // (1024 * 1024)))
    heads = [f.read(5) for _, f in files]
    if len(files) == 1 and heads[0] == b"%PDF-":
        return files[0][0], heads[0] + files[0][1].read()
    if b"%PDF-" in heads:
        raise UploadError(t("upload.pdf_alone"))
    writer = PdfWriter()
    for name, f in files:
        writer.append(PdfReader(io.BytesIO(_page(name, f))))
    out = io.BytesIO()
    writer.write(out)
    return "scan.pdf", out.getvalue()
