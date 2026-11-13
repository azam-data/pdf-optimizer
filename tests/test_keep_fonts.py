"""Q7: "Keep fonts unchanged" (--keep-fonts in the CLI, a checkbox in the GUI) turns the font pass off."""
import json

import app_cli


def _sample_with_fonts(samples_dir, runs):
    for p in sorted(samples_dir.glob("*.pdf")):
        note = runs(p.name).get("font_note") or ""
        if note.startswith("fonts "):
            return p
    raise AssertionError("no sample has a font pass")


def test_Q7_keep_fonts_skips_font_pass(samples_dir, runs, tmp_path, capsys):
    src = _sample_with_fonts(samples_dir, runs)
    app_cli.main([str(src), str(tmp_path / "a.pdf"), "--json"])
    assert json.loads(capsys.readouterr().out).get("font_note", "").startswith("fonts ")
    app_cli.main([str(src), str(tmp_path / "b.pdf"), "--json", "--keep-fonts"])
    assert not json.loads(capsys.readouterr().out).get("font_note")
