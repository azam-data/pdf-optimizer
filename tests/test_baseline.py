"""Run optimize_pdf on every generated sample (defaults, scan_mode=auto, ocr=True)
and compare with tests/baseline.json.

Update the baseline (only when a task says results should change, and say why in the commit):
    python -m pytest tests/test_baseline.py --update-baseline
"""
import json
import shutil
from pathlib import Path

import pymupdf
import pytest

import pdfopt_core as core
import make_samples

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "baseline.json"
SETTINGS = dict(scan_mode="auto", ocr=True)
TOLERANCE = 0.05
PASSWORD = "test"
NAMES = sorted(make_samples.SAMPLES)

_results = {}   # name -> result dict (filled as tests run, used by --update-baseline)


def _ocr_available():
    return core.find_tessdata(None, "eng") is not None


def _load():
    return json.loads(BASELINE.read_text()) if BASELINE.exists() else {"samples": {}}


@pytest.fixture(scope="module")
def runs(samples_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("out")

    def run(name):
        if name not in _results:
            dst = out / name
            r = core.optimize_pdf(str(samples_dir / name), str(dst), dict(SETTINGS), jbig2_exe=None)
            r["_dst"] = dst
            _results[name] = r
        return _results[name]
    return run


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
        assert dst.read_bytes() == src.read_bytes()      # copied unchanged

    # size within 5% of baseline. Sizes depend on whether OCR ran, so compare only like with like.
    if base["meta"]["ocr_available"] != _ocr_available():
        pytest.skip("baseline was made with ocr_available=%s, here it is %s"
                    % (base["meta"]["ocr_available"], _ocr_available()))
    assert abs(r["size_out"] - entry["size_out"]) <= TOLERANCE * entry["size_out"], \
        f"{name}: {r['size_out']} bytes vs baseline {entry['size_out']}"
    assert r["scan_pages"] == entry["scan_pages"]
    assert r["ocr_pages"] == entry["ocr_pages"]


def test_write_baseline(request, runs):
    """Only does something with --update-baseline."""
    if not request.config.getoption("--update-baseline"):
        pytest.skip("pass --update-baseline to rewrite tests/baseline.json")
    data = {"meta": {"settings": SETTINGS, "tolerance": TOLERANCE, "ocr_available": _ocr_available(),
                     "jbig2": False, "pymupdf": pymupdf.__version__},
            "samples": {}}
    for name in NAMES:
        r = runs(name)
        data["samples"][name] = {k: r[k] for k in ("status", "size_in", "size_out", "scan_pages", "ocr_pages")}
    BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
