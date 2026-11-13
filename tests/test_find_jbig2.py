"""P0.5: find_jbig2 looks in <app dir>/third_party/jbig2/ and skips files that cannot run."""
import os
import shutil
import sys

import pytest

import pdfopt_core as core

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in")


@pytest.fixture
def appdir(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_app_dirs", lambda: [str(tmp_path)])
    monkeypatch.setattr(shutil, "which", lambda name: None)
    return tmp_path


def _fake(path, runnable):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"#!/bin/sh\nexit 0\n" if runnable else b"MZ not an executable for this OS")
    path.chmod(0o755)
    return str(path)


def test_non_runnable_file_is_skipped(appdir):
    _fake(appdir / "third_party" / "jbig2" / "jbig2.exe", runnable=False)
    assert core.find_jbig2() is None


@posix_only
def test_finds_exe_in_third_party(appdir):
    exe = _fake(appdir / "third_party" / "jbig2" / "jbig2.exe", runnable=True)
    assert core.find_jbig2() == exe


@posix_only
def test_next_to_app_wins_over_third_party(appdir):
    near = _fake(appdir / "jbig2.exe", runnable=True)
    _fake(appdir / "third_party" / "jbig2" / "jbig2.exe", runnable=True)
    assert core.find_jbig2() == near


@posix_only
def test_non_runnable_first_candidate_falls_through(appdir):
    _fake(appdir / "jbig2.exe", runnable=False)
    far = _fake(appdir / "third_party" / "jbig2" / "jbig2.exe", runnable=True)
    assert core.find_jbig2() == far
