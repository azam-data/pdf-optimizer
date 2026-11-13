"""E3: temp files left by a crashed run must not stay in the output folder."""
import shutil

import pdfopt_batch as batch


def test_E3_stale_temp_files_removed_at_start(samples_dir, tmp_path):
    inp, out = tmp_path / "in", tmp_path / "out"
    (out / "sub").mkdir(parents=True)
    inp.mkdir()
    shutil.copy(sorted(samples_dir.glob("*.pdf"))[0], inp / "a.pdf")
    stale = [out / "x.pdf.tmp_pdfopt", out / "x.pdf.fonts_pdfopt",
             out / "sub" / "y.pdf.tmp_pdfopt"]
    for p in stale:
        p.write_bytes(b"junk")
    batch.run_folder(str(inp), str(out))
    assert not [p for p in out.rglob("*") if p.name.endswith(("_pdfopt",))]
