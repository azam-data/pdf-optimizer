"""Tests that reproduce known problems from docs/ROADMAP.md.
Each is xfail(strict) with its task ID: when the fix lands the test XPASSes, strict mode
fails the suite, and the fixing task removes the marker."""
import os
from pathlib import Path

import pymupdf
import pytest

import pdfopt_core as core
import pdfopt_batch as batch


def _case_insensitive_fs(tmp_path):
    d = tmp_path / "CaseProbe"
    d.mkdir()
    return (tmp_path / "caseprobe").exists()


def test_E1_output_inside_input_different_case(tmp_path):
    if not _case_insensitive_fs(tmp_path):
        pytest.skip("needs a case-insensitive file system (Windows, default macOS)")
    inp = tmp_path / "Docs"
    inp.mkdir()
    out = tmp_path / "docs" / "out"          # same folder as inp\out, spelled differently
    with pytest.raises(ValueError):
        batch.plan_folder(str(inp), str(out))


def _rgb_at(path, x_pt, y_pt):
    doc = pymupdf.open(path)
    try:
        pix = doc[0].get_pixmap(dpi=72, colorspace=pymupdf.csRGB)
        return pix.pixel(int(x_pt), int(y_pt))
    finally:
        doc.close()


def test_Q1_pastel_chart_survives_scan_mode(samples_dir, tmp_path):
    src = samples_dir / "scan_pastel_chart.pdf"
    dst = tmp_path / "out.pdf"
    r = core.optimize_pdf(str(src), str(dst), dict(scan_mode="auto"))
    assert r["scan_pages"] == 1, (r["status"], r["note"], r["image_log"])   # scan mode did run
    # first bar: pixel (240, 1100) at 150 dpi -> point (115, 528)
    before, after = _rgb_at(src, 115, 528), _rgb_at(dst, 115, 528)
    assert max(abs(a - b) for a, b in zip(before, after)) <= 12, f"bar colour {before} became {after}"
    # highlighter band, away from its text: pixel (1000, 320) at 150 dpi -> point (480, 153)
    before, after = _rgb_at(src, 480, 153), _rgb_at(dst, 480, 153)
    assert max(abs(a - b) for a, b in zip(before, after)) <= 12, f"highlighter {before} became {after}"


def test_Q4_scan_with_page_number_needs_ocr(samples_dir):
    doc = pymupdf.open(samples_dir / "scan_digital_pagenumber.pdf")
    try:
        assert core._needs_ocr(doc[0])
    finally:
        doc.close()


def test_M1_stencil_mask_image_is_processed(samples_dir, tmp_path):
    r = core.optimize_pdf(str(samples_dir / "scan_stencil_mask.pdf"), str(tmp_path / "out.pdf"),
                          dict(scan_mode="auto"))
    assert r["images_changed"] >= 1, (r["status"], r["note"], r["image_log"])


def test_M1_stencil_mask_keeps_flag_and_rendering(samples_dir, tmp_path):
    src, dst = samples_dir / "scan_stencil_mask.pdf", tmp_path / "out.pdf"
    core.optimize_pdf(str(src), str(dst), dict(scan_mode="off", ocr=False), jbig2_exe=None)
    a, b = pymupdf.open(src), pymupdf.open(dst)
    try:
        x = b.get_page_images(0)[0][0]
        assert b.xref_get_key(x, "ImageMask")[1] == "true"
        pa = a[0].get_pixmap(dpi=50, colorspace=pymupdf.csGRAY)
        pb = b[0].get_pixmap(dpi=50, colorspace=pymupdf.csGRAY)
        assert (pa.width, pa.height) == (pb.width, pb.height)
        assert abs(sum(pa.samples) / len(pa.samples) - sum(pb.samples) / len(pb.samples)) < 2
    finally:
        a.close(); b.close()


def test_Q8_ocr_text_survives_when_file_did_not_shrink(runs):
    r = runs("scan_bw_tiny.pdf")
    assert r["size_out"] <= 1.10 * r["size_in"]       # a text layer may add a little, never a lot
    doc = pymupdf.open(r["_dst"])
    try:
        # OCR reads "Sample Bank Ltd - Statement of Account ..." on this sample (checked by hand)
        assert doc[0].search_for("Statement"), "output has no OCR text layer"
    finally:
        doc.close()


def test_Q8_counters_are_zero_when_output_is_the_input(runs):
    import make_samples
    bad = {}
    for name in sorted(make_samples.SAMPLES):
        r = runs(name)
        if r["identical_to_input"]:
            counters = {k: r[k] for k in ("scan_pages", "ocr_pages", "images_changed") if r[k]}
            if counters:
                bad[name] = counters
    assert not bad, bad


def test_M3_palette_image_is_downsampled_and_renders_the_same(samples_dir, tmp_path):
    src, dst = samples_dir / "palette_image.pdf", tmp_path / "out.pdf"
    r = core.optimize_pdf(str(src), str(dst), dict(scan_mode="off", ocr=False), jbig2_exe=None)
    assert r["images_changed"] >= 1, (r["status"], r["note"], r["image_log"])
    assert r["size_out"] < 0.8 * r["size_in"]
    a, b = pymupdf.open(src), pymupdf.open(dst)
    try:
        pa = a[0].get_pixmap(dpi=60, colorspace=pymupdf.csRGB)
        pb = b[0].get_pixmap(dpi=60, colorspace=pymupdf.csRGB)
        assert (pa.width, pa.height) == (pb.width, pb.height)
        import numpy as np
        d = np.abs(np.frombuffer(pa.samples, np.uint8).astype(int) - np.frombuffer(pb.samples, np.uint8).astype(int))
        assert d.mean() < 4
    finally:
        a.close(); b.close()
