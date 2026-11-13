"""E2: an output file that is open in another program must not abort a batch."""
import os
import shutil

import pdfopt_batch as batch
import pdfopt_core as core


def test_E2_locked_output_is_recorded_and_batch_continues(samples_dir, tmp_path, monkeypatch):
    inp, out = tmp_path / "in", tmp_path / "out"
    inp.mkdir()
    pdfs = sorted(samples_dir.glob("*.pdf"))[:2]
    names = ["a_locked.pdf", "b_ok.pdf"]
    for p, n in zip(pdfs, names):
        shutil.copy(p, inp / n)

    real_replace, real_copy2 = os.replace, shutil.copy2

    def locked(dst):
        return os.path.basename(str(dst)).startswith("a_locked.pdf")

    def fake_replace(a, b, *args, **kw):
        if locked(b):
            raise PermissionError(13, "in use")
        return real_replace(a, b, *args, **kw)

    def fake_copy2(a, b, *args, **kw):
        if locked(b):
            raise PermissionError(13, "in use")
        return real_copy2(a, b, *args, **kw)

    monkeypatch.setattr(core.os, "replace", fake_replace)
    monkeypatch.setattr(core.shutil, "copy2", fake_copy2)
    monkeypatch.setattr(batch.shutil, "copy2", fake_copy2)

    rows, report, summary, cancelled = batch.run_folder(str(inp), str(out))
    by = {r["file"]: r for r in rows}
    assert by["a_locked.pdf"]["status"] == "failed (output in use)"
    assert by["b_ok.pdf"]["status"] != "failed (output in use)"
    assert (out / "b_ok.pdf").exists()
    assert not list(out.glob("*pdfopt"))
