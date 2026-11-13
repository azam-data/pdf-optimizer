"""Run optimize_pdf on every generated sample (defaults, scan_mode=auto, ocr=True)
and compare with tests/baseline.json.

Update the baseline (only when a task says results should change, and say why in the commit):
    python -m pytest tests/test_baseline.py --update-baseline
"""
import json
import os
import shutil
from pathlib import Path

import pymupdf
import pytest

import pdfopt_core as core
import make_samples

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "baseline.json"
from conftest import SETTINGS
TOLERANCE = 0.05
PASSWORD = "test"
NAMES = sorted(make_samples.SAMPLES)

# Known gaps, written into baseline.json for whoever reads it (not asserted).
NOTES = {
    "cmyk_image.pdf": "M2: CMYK images are skipped, so the file is copied",
    "palette_image.pdf": "M3: palette (Indexed) images are skipped, so the file is copied",
    "scan_stencil_mask.pdf": "M1: stencil-mask scans are skipped; Q8: kept because the OCR text layer adds <10%",
    "scan_bw_tiny.pdf": "already optimal; Q8: kept because the OCR text layer adds <10%",
    "scan_pastel_chart.pdf": "Q1: pastel fills are erased by scan mode; baseline records the current (wrong) result",
    "scan_digital_pagenumber.pdf": "Q4: real-text page number stops OCR",
}


def _ocr_available():
    return core.find_tessdata(None, "eng") is not None


def _load():
    return json.loads(BASELINE.read_text()) if BASELINE.exists() else {"samples": {}}


@pytest.mark.parametrize("name", NAMES)
def test_sample(name, runs, samples_dir):
    r = runs(name)
    src, dst = samples_dir / name, r["_dst"]

    # output opens, same number of pages
    a, b = pymupdf.open(src), pymupdf.open(dst)
    try:
        if a.needs_pass:
            assert b.needs_pass
            assert a.authenticate(PASSWORD) and b.authenticate(PASSWORD)
        assert b.page_count == a.page_count
    finally:
        a.close(); b.close()

    base = _load()
    entry = base["samples"].get(name)
    if entry is None:
        pytest.fail(f"{name} missing from baseline.json (run with --update-baseline)")
    assert r["status"] == entry["status"]
    if entry["status"] != "optimized":
        assert r["identical_to_input"]                   # copied unchanged

    # Sizes depend on OCR. Without eng.traineddata: skip locally, but fail on CI.
    if not _ocr_available():
        if os.environ.get("CI"):
            pytest.fail("eng.traineddata not found (third_party/tessdata): CI must run the OCR baseline")
        pytest.skip("eng.traineddata not found: size check skipped")
    assert base["meta"]["ocr_available"], "baseline.json was made without OCR; regenerate it"
    assert abs(r["size_out"] - entry["size_out"]) <= TOLERANCE * entry["size_out"], \
        f"{name}: {r['size_out']} bytes vs baseline {entry['size_out']}"
    assert r["scan_pages"] == entry["scan_pages"]
    assert r["ocr_pages"] == entry["ocr_pages"]
    assert r["images_changed"] == entry["images_changed"]
    assert r["identical_to_input"] == entry["identical_to_input"]


def test_jbig2_optional(samples_dir, tmp_path):
    """JBIG2 path: only where a jbig2 executable exists. Output must still be valid and not larger."""
    exe = core.find_jbig2()
    if not exe:
        if os.environ.get("CI"):
            pytest.fail("no jbig2 executable found: CI must run the JBIG2 test")
        pytest.skip("no jbig2 executable found")
    src = samples_dir / "scan_bw.pdf"
    r = core.optimize_pdf(str(src), str(tmp_path / "j.pdf"), dict(SETTINGS, use_jbig2=True), jbig2_exe=exe)
    assert r["size_out"] <= r["size_in"]
    assert pymupdf.open(tmp_path / "j.pdf").page_count == 1


def test_write_baseline(request, runs):
    """Only does something with --update-baseline."""
    if not request.config.getoption("--update-baseline"):
        pytest.skip("pass --update-baseline to rewrite tests/baseline.json")
    data = {"meta": {"settings": SETTINGS, "tolerance": TOLERANCE, "ocr_available": _ocr_available(),
                     "jbig2": False, "pymupdf": pymupdf.__version__, "notes": NOTES},
            "samples": {}}
    for name in NAMES:
        r = runs(name)
        data["samples"][name] = {k: r[k] for k in ("status", "size_in", "size_out", "scan_pages", "ocr_pages", "images_changed", "identical_to_input")}
    BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def test_rotated_270_ocr_boxes_line_up(runs):
    """OCR on a /Rotate 270 pure scan: the hit for a known word sits where the word is drawn."""
    r = runs("rotated_270.pdf")
    assert r["scan_pages"] == 1 and r["ocr_pages"] == 1, "OCR must run on this page"
    doc = pymupdf.open(r["_dst"])
    try:
        page = doc[0]
        assert page.rotation == 270
        hits = page.search_for(make_samples.ROT_WORD)
        assert hits, "word not found: no OCR text layer"
        want = make_samples.rotated_word_rect()
        # search_for returns unrotated page coordinates; bring the hit to the displayed page.
        # The hit box is the font's line box (taller than the glyphs), so compare the left and
        # right edges and the vertical centre, each within 4 points.
        got = min((h * page.rotation_matrix for h in hits),
                  key=lambda g: abs(g.x0 - want.x0) + abs(g.y0 + g.y1 - want.y0 - want.y1))
        centre = lambda q: (q.y0 + q.y1) / 2
        assert abs(got.x0 - want.x0) <= 4, (got, want)
        assert abs(got.x1 - want.x1) <= 4, (got, want)
        assert abs(centre(got) - centre(want)) <= 4, (got, want)
    finally:
        doc.close()
