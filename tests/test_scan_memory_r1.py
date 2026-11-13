"""R1: very large scans must not exhaust memory in scan mode. Pages above a pixel cap are not
converted (with a clear reason), the adaptive threshold is computed in strips, and an
out-of-memory error is reported plainly while the image still gets the normal pass."""
import numpy as np

import pdfopt_core as core

SETTINGS = dict(scan_mode="auto", ocr=False, use_jbig2=False)


def _sauvola_full(L, window, k, R=128.0):
    """The original whole-page Sauvola, as the reference."""
    h, w = L.shape
    r = window // 2
    P = np.pad(L, r + 1, mode="reflect").astype(np.float64)
    I1 = P.cumsum(0).cumsum(1)
    I2 = (P * P).cumsum(0).cumsum(1)

    def boxsum(I):
        return (I[window:window + h, window:window + w] - I[0:h, window:window + w]
                - I[window:window + h, 0:w] + I[0:h, 0:w])
    n = float(window * window)
    m = boxsum(I1) / n
    v = np.maximum(boxsum(I2) / n - m * m, 0)
    return (m * (1 + k * (np.sqrt(v) / R - 1))).astype(np.float32)


def test_R1_sauvola_in_strips_matches_whole_page():
    L = (np.random.default_rng(1).random((157, 203)) * 255).astype(np.float32)
    ref = _sauvola_full(L, 31, 0.25)
    for rows in (1, 7, 64, 10**6):
        got = core._sauvola(L, 31, 0.25, rows=rows)
        assert got.shape == ref.shape
        assert np.allclose(got, ref, atol=1e-3), rows


def _scan_entries(log):
    return [e for e in log if e[1] == "scan"]


def test_R1_page_over_pixel_cap_is_not_converted_and_says_why(samples_dir, tmp_path):
    called = []
    orig = core._scan_convert
    try:
        core._scan_convert = lambda *a, **k: called.append(1) or orig(*a, **k)
        r = core.optimize_pdf(str(samples_dir / "scan_grey.pdf"), str(tmp_path / "out.pdf"),
                              dict(SETTINGS, scan_max_megapixels=0.5), jbig2_exe=None)
    finally:
        core._scan_convert = orig
    assert r["scan_pages"] == 0
    msgs = [e[2] for e in _scan_entries(r["image_log"])]
    assert any("too large for scan mode" in m for m in msgs), r["image_log"]
    assert not called                                     # decided before decoding the page
    assert not any(e[1] == "error" for e in r["image_log"]), r["image_log"]


def test_R1_default_cap_allows_a3_at_300_dpi():
    assert core.DEFAULTS["scan_max_megapixels"] * 1e6 >= 3508 * 4961


def test_R1_out_of_memory_is_reported_and_normal_pass_runs(samples_dir, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise MemoryError()
    monkeypatch.setattr(core, "_sauvola", boom)
    r = core.optimize_pdf(str(samples_dir / "scan_grey.pdf"), str(tmp_path / "out.pdf"),
                          dict(SETTINGS), jbig2_exe=None)
    msgs = [e[2] for e in _scan_entries(r["image_log"])]
    assert any("out of memory" in m for m in msgs), r["image_log"]
    assert not any(e[1] == "error" for e in r["image_log"]), r["image_log"]
    assert any(e[1] in ("changed", "kept") for e in r["image_log"]), r["image_log"]   # normal pass ran
