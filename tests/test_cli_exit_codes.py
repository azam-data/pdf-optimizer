"""E4: pdfopt-cli exit codes (0 optimized, 3 original kept, 1 error) and --json."""
import json

import app_cli


def _optimized_sample(samples_dir, runs):
    for p in sorted(samples_dir.glob("*.pdf")):
        if runs(p.name)["status"] == "optimized":
            return p
    raise AssertionError("no sample is optimized")


def test_E4_optimized_exits_0_and_json(samples_dir, runs, tmp_path, capsys):
    src = _optimized_sample(samples_dir, runs)
    rc = app_cli.main([str(src), str(tmp_path / "o.pdf"), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert d["status"] == "optimized" and d["exit_code"] == 0


def test_E4_original_kept_exits_3(tmp_path, capsys):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    rc = app_cli.main([str(bad), str(tmp_path / "o.pdf"), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 3
    assert d["status"].startswith("copied") and d["exit_code"] == 3


def test_E4_error_exits_1(tmp_path, capsys):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"x")
    rc = app_cli.main([str(bad), str(bad), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert d["exit_code"] == 1 and "error" in d
