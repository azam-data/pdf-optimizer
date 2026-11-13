"""R2: jbig2 must get a relative file name (cwd = temp dir) and failures must be logged."""
import subprocess
from types import SimpleNamespace

from PIL import Image

import pdfopt_core as core


def test_jbig2_gets_relative_path(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return SimpleNamespace(returncode=0, stdout=b"data")

    monkeypatch.setattr(subprocess, "run", fake_run)
    img = Image.new("1", (16, 16))
    assert core._encode_jbig2(img, "jbig2") == b"data"
    arg = seen["cmd"][-1]
    assert arg == "page.pbm"
    assert seen["cwd"]


def test_jbig2_failure_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=b""))
    assert core._encode_jbig2(Image.new("1", (16, 16)), "jbig2") is None
    assert "JBIG2" in caplog.text
