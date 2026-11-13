"""Q6: running the optimizer on its own output must not re-encode JPEGs again."""
import io

import numpy as np
import pymupdf
from PIL import Image

import pdfopt_core as core


def _make(path):
    r = np.random.default_rng(3)
    y, x = np.mgrid[0:900, 0:1200]
    base = np.stack([120 + 80 * np.sin(x / 150), 100 + 60 * np.cos(y / 120), 140 + 50 * np.sin((x + y) / 200)], -1)
    img = Image.fromarray(np.clip(base + r.normal(0, 12, base.shape), 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=98)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Photo page", fontsize=14)
    page.insert_image(pymupdf.Rect(50, 80, 545, 450), stream=buf.getvalue())
    doc.save(path)
    doc.close()


def _jpeg_streams(path):
    doc = pymupdf.open(path)
    try:
        return [doc.xref_stream_raw(im[0]) for p in doc for im in p.get_images(full=True)]
    finally:
        doc.close()


def test_Q6_second_run_does_not_reencode_jpeg(tmp_path):
    src, one, two = tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "c.pdf"
    _make(str(src))
    r1 = core.optimize_pdf(str(src), str(one))
    assert r1["status"] == "optimized" and r1["images_changed"] == 1
    # threshold -1 would accept any re-encode, so only the marker can stop it
    r2 = core.optimize_pdf(str(one), str(two), dict(jpeg_min_gain=-1.0))
    assert r2["images_changed"] == 0
    assert _jpeg_streams(str(two)) == _jpeg_streams(str(one))


def test_Q6_output_is_marked_and_unmarked_files_still_optimized(tmp_path):
    src, one = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _make(str(src))
    # an unmarked file is still re-encoded even with a gain threshold that always accepts
    r0 = core.optimize_pdf(str(src), str(one), dict(jpeg_min_gain=-1.0))
    assert r0["images_changed"] == 1
    doc = pymupdf.open(str(one))
    try:
        kind, val = doc.xref_get_key(-1, "Info")
        assert kind == "xref"
        assert doc.xref_get_key(int(val.split()[0]), "PdfOptimizer")[0] != "null"
    finally:
        doc.close()
