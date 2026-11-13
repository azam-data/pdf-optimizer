"""R4: Cancel during OCR / final check, off-screen window, zero-byte skip, very long paths."""
import os
import shutil

import pytest

import pdfopt_batch as batch
import pdfopt_core as core


def test_R4_cancel_is_honoured_during_final_check(samples_dir, tmp_path):
    src = sorted(samples_dir.glob("*.pdf"))[0]
    dst = tmp_path / "out.pdf"
    stages = []

    def prog(done, total, stage="images"):
        stages.append(stage)
        if stage == "verify":
            raise core.OptimizerCancelled()

    s = dict(scan_mode="off", use_jbig2=False, min_file_gain=-10, verify_pages=True)
    with pytest.raises(core.OptimizerCancelled):
        core.optimize_pdf(str(src), str(dst), s, jbig2_exe=None, progress=prog)
    assert "verify" in stages
    assert not dst.exists()
    assert not [f for f in os.listdir(tmp_path) if f.endswith("_pdfopt")]


def test_R4_cancel_is_checked_after_each_ocr_page(monkeypatch, samples_dir, tmp_path):
    src = sorted(samples_dir.glob("*.pdf"))[0]
    calls = []
    monkeypatch.setattr(core, "find_tessdata", lambda *a, **k: "x")
    monkeypatch.setattr(core, "_needs_ocr", lambda p: True)
    monkeypatch.setattr(core, "_ocr_words", lambda *a, **k: calls.append(1) or [])

    def prog(done, total, stage="images"):
        if calls:                       # first page was read; cancel now
            raise core.OptimizerCancelled()

    with pytest.raises(core.OptimizerCancelled):
        core.optimize_pdf(str(src), str(tmp_path / "o.pdf"), dict(ocr=True, use_jbig2=False),
                          jbig2_exe=None, progress=prog)
    assert len(calls) == 1


def test_R4_offscreen_geometry_is_moved_back():
    import app_gui
    f = app_gui.clamp_geometry
    assert f("760x680+100+50", 1920, 1080) == "760x680+100+50"
    assert f("760x680+5000+50", 1920, 1080) == "760x680+1820+50"
    assert f("760x680+-3000+-900", 1920, 1080) == "760x680+0+0"
    assert f("760x680", 1920, 1080) == "760x680"
    assert f("garbage", 1920, 1080) == "760x680"


def test_R4_skip_existing_ignores_zero_byte_output(samples_dir, tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir(); out.mkdir()
    shutil.copy(sorted(samples_dir.glob("*.pdf"))[0], inp / "a.pdf")
    (out / "a.pdf").write_bytes(b"")
    rows, *_ = batch.run_folder(str(inp), str(out), skip_existing=True)
    assert not rows[0]["status"].startswith("skipped")
    assert (out / "a.pdf").stat().st_size > 0


def test_R4_path_over_260_chars(samples_dir, tmp_path):
    deep = tmp_path
    for _ in range(4):
        deep = deep / ("папка с пробелом " + "x" * 50)
    deep.mkdir(parents=True)
    src = deep / "файл.pdf"
    shutil.copy(sorted(samples_dir.glob("*.pdf"))[0], src)
    dst = tmp_path / "o" / deep.relative_to(tmp_path) / "файл.pdf"
    assert len(str(src)) > 260
    dst.parent.mkdir(parents=True)
    r = core.optimize_pdf(str(src), str(dst), dict(use_jbig2=False), jbig2_exe=None)
    assert dst.exists() and r["status"]
