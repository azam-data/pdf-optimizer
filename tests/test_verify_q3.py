"""Q3: page verification must catch a small missing item, on normal pages and on rebuilt scans."""
import io

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

import pdfopt_core as core
import make_samples as ms

S = dict(core.DEFAULTS)


def _vector_page(path, skip_amount=None):
    """A text statement; skip_amount=i leaves out the amount on row i (a small missing item)."""
    doc = pymupdf.open()
    page = doc.new_page(width=ms.PAGE.width, height=ms.PAGE.height)
    page.insert_text((50, 50), "Sample Bank Ltd - Statement of Account", fontsize=16)
    for i in range(40):
        y = 90 + i * 17
        page.insert_text((50, y), f"{i + 1:03d}  12-Mar-2026  Transfer ref {100000000 + i * 7919}", fontsize=10)
        if i != skip_amount:
            page.insert_text((430, y), f"{(i * 3571) % 99999 + 100:>8,}.00", fontsize=10)
    doc.save(path)
    doc.close()


def _scan_image(erase=None, binarize=False):
    """Grey scan like make_scan_grey; erase=(x0, y0, x1, y1) in 150 dpi pixels whitens that area;
    binarize=True turns it into a white-paper black-text page, like scan mode does."""
    img = ms._paper("L", 238)
    ms._text_lines(ImageDraw.Draw(img), 40)
    img = ms._speckle(img, 3, 5)
    if binarize:
        img = img.point(lambda v: 255 if v > 150 else 0)
    if erase:
        ImageDraw.Draw(img).rectangle(erase, fill=255 if binarize else 238)
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _image_page(path, data):
    doc = pymupdf.open()
    page = doc.new_page(width=ms.PAGE.width, height=ms.PAGE.height)
    page.insert_image(page.rect, stream=data)
    doc.save(path)
    doc.close()


def test_identical_vector_pages_pass(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _vector_page(a); _vector_page(b)
    ok, msg = core._pages_match(str(a), str(b), S)
    assert ok, msg


def test_small_missing_item_on_normal_page_fails(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _vector_page(a); _vector_page(b, skip_amount=20)        # one amount ("71,520.00"-sized) gone
    ok, msg = core._pages_match(str(a), str(b), S)
    assert not ok, msg


def test_rebuilt_scan_with_everything_passes(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _image_page(a, _scan_image()); _image_page(b, _scan_image(binarize=True))
    ok, msg = core._pages_match(str(a), str(b), S, scan_pages={0})
    assert ok, msg


def test_rebuilt_scan_with_missing_amount_fails(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    y = 140 + 20 * 36                                        # row 21 of _text_lines
    _image_page(a, _scan_image())
    _image_page(b, _scan_image(erase=(ms.W - 390, y - 4, ms.W - 60, y + 32), binarize=True))
    ok, msg = core._pages_match(str(a), str(b), S, scan_pages={0})
    assert not ok, msg
