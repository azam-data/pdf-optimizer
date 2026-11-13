"""Q2: mid-tone ink (pencil notes, faint stamps, grey text between 60% and 88% of paper
brightness) must not vanish when scan mode rebuilds a page."""
import numpy as np
import pymupdf
import pytest

import make_samples


def _gray(path, dpi=100):
    doc = pymupdf.open(path)
    try:
        pix = doc[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).astype(np.float32)
    finally:
        doc.close()


def _marks(g, box, dpi=100):
    """Pixels in box (150-dpi sample pixels) clearly darker than this page's paper."""
    paper = float(np.percentile(g, 90))
    f = dpi / 150
    x0, y0, x1, y1 = (int(round(v * f)) for v in box)
    return int((g[y0:y1, x0:x1] < paper - 25).sum())


@pytest.mark.parametrize("box", ["PENCIL_BOX", "STAMP_BOX"])
def test_Q2_mid_tone_ink_survives_scan_mode(runs, samples_dir, box):
    name = "scan_pencil_note.pdf"
    r = runs(name)
    assert r["scan_pages"] == 1, (r["status"], r["note"], r["image_log"])   # scan mode did run
    rect = getattr(make_samples, box)
    before = _marks(_gray(samples_dir / name), rect)
    after = _marks(_gray(r["_dst"]), rect)
    assert before > 200, before                                  # the sample really has marks there
    assert after >= 0.6 * before, f"{box}: {before} marked pixels became {after} ({r['image_log']})"
