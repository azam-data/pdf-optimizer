"""M2: CMYK images are re-encoded as CMYK JPEGs; colours must render the same."""
import numpy as np
import pymupdf

import pdfopt_core as core


def _rgb(path):
    doc = pymupdf.open(path)
    try:
        pix = doc[0].get_pixmap(dpi=72, colorspace=pymupdf.csRGB)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).astype(np.int16)
    finally:
        doc.close()


def _image_info(path):
    doc = pymupdf.open(path)
    try:
        x = doc[0].get_images()[0][0]
        return doc.xref_get_key(x, "ColorSpace")[1], doc.xref_get_key(x, "Filter")[1], \
            doc.xref_get_key(x, "Decode")[0]
    finally:
        doc.close()


def test_cmyk_image_recompressed_with_same_colours(runs, samples_dir):
    r = runs("cmyk_image.pdf")
    assert r["status"] == "optimized", (r.get("note"), r["image_log"])
    assert r["images_changed"] == 1
    assert r["size_out"] < 0.9 * r["size_in"]
    cs, filt, dec = _image_info(r["_dst"])
    assert cs == _image_info(samples_dir / "cmyk_image.pdf")[0] and filt == "/DCTDecode"
    _same_colours(samples_dir / "cmyk_image.pdf", r["_dst"])


def _same_colours(src, dst):
    a, b = _rgb(src), _rgb(dst)
    diff = np.abs(a - b)
    assert diff.mean() < 3, diff.mean()                       # colours not inverted or shifted
    assert np.abs(a.mean((0, 1)) - b.mean((0, 1))).max() < 2  # per-channel colour balance kept


def test_cmyk_without_decode_keeps_colours(tmp_path):
    """Plain (non-inverted) CMYK pixels, Flate, no /Decode: the JPEG must not come out inverted."""
    rng = np.random.default_rng(5)
    y, x = np.mgrid[0:400, 0:500]
    cmyk = np.stack([x / 500 * 255, y / 400 * 255, 255 - x / 500 * 200, 30 + 0 * x], -1)
    cmyk = np.clip(cmyk + rng.normal(0, 6, cmyk.shape), 0, 255).astype(np.uint8)
    src, dst = tmp_path / "cmyk flate.pdf", tmp_path / "out.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), "CMYK Flate image", fontsize=14)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False)   # placeholder, replaced below
    x_img = page.insert_image(pymupdf.Rect(50, 80, 450, 400), pixmap=pix)
    doc.update_stream(x_img, cmyk.tobytes())
    for k, v in {"Width": "500", "Height": "400", "ColorSpace": "/DeviceCMYK", "BitsPerComponent": "8",
                 "Filter": "/FlateDecode", "DecodeParms": "null", "Decode": "null", "SMask": "null"}.items():
        doc.xref_set_key(x_img, k, v)
    doc.save(src)
    doc.close()
    r = core.optimize_pdf(str(src), str(dst), dict(scan_mode="auto", use_jbig2=False), jbig2_exe=None)
    assert r["status"] == "optimized", (r.get("note"), r["image_log"])
    assert r["images_changed"] == 1
    _same_colours(src, dst)


def test_cmyk_classified():
    doc = pymupdf.open()
    try:
        x = doc.get_new_xref()
        doc.update_object(x, "<< /Type /XObject /Subtype /Image /Width 4 /Height 4 "
                             "/ColorSpace /DeviceCMYK /BitsPerComponent 8 >>")
        assert core._classify(doc, x) == "cmyk"
        doc.xref_set_key(x, "Decode", "[1 0 1 0 1 0 1 0]")    # Adobe-inverted JPEG convention
        assert core._classify(doc, x) == "cmyk"
        doc.xref_set_key(x, "Decode", "[0 1 0 1 0 1 1 0]")    # anything else: still skipped
        assert isinstance(core._classify(doc, x), tuple)
    finally:
        doc.close()
