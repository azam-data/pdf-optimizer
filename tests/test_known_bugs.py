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


@pytest.mark.xfail(strict=True, reason="E1: plan_folder compares paths case-sensitively")
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


@pytest.mark.xfail(strict=True, reason="Q1: scan mode erases pastel chart fills")
def test_Q1_pastel_chart_survives_scan_mode(samples_dir, tmp_path):
    src = samples_dir / "scan_pastel_chart.pdf"
    dst = tmp_path / "out.pdf"
    r = core.optimize_pdf(str(src), str(dst), dict(scan_mode="auto"))
    assert r["scan_pages"] == 1                      # scan mode did run on this page
    # first bar: pixel (240, 1100) at 150 dpi -> point (115, 528)
    before, after = _rgb_at(src, 115, 528), _rgb_at(dst, 115, 528)
    assert max(abs(a - b) for a, b in zip(before, after)) <= 12, f"bar colour {before} became {after}"


@pytest.mark.xfail(strict=True, reason="Q4: a digital 'Page 7' stamp stops OCR on a scanned page")
def test_Q4_scan_with_page_number_needs_ocr(samples_dir):
    doc = pymupdf.open(samples_dir / "scan_digital_pagenumber.pdf")
    try:
        assert core._needs_ocr(doc[0])
    finally:
        doc.close()


@pytest.mark.xfail(strict=True, reason="M1: stencil-mask scans are skipped")
def test_M1_stencil_mask_image_is_processed(samples_dir, tmp_path):
    r = core.optimize_pdf(str(samples_dir / "scan_stencil_mask.pdf"), str(tmp_path / "out.pdf"),
                          dict(scan_mode="auto"))
    assert r["images_changed"] >= 1
