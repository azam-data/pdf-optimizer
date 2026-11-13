"""R3: owner-protected ("no changes allowed") and damaged PDFs are copied unchanged."""
import pymupdf

import pdfopt_core as core


def _make(path, **save_kw):
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page().insert_text((72, 100), f"Statement page {i} " * 5)
    doc.save(path, **save_kw)
    doc.close()


def test_R3_owner_protected_is_copied_unchanged(tmp_path):
    src, dst = tmp_path / "locked.pdf", tmp_path / "out.pdf"
    _make(str(src), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner",
          user_pw="", permissions=int(pymupdf.PDF_PERM_PRINT))
    r = core.optimize_pdf(str(src), str(dst))
    assert r["status"].startswith("copied")
    assert "protect" in r["status"] or "protect" in r["note"]
    assert dst.read_bytes() == src.read_bytes()


def test_R3_damaged_is_copied_unchanged(tmp_path):
    src, dst = tmp_path / "damaged.pdf", tmp_path / "out.pdf"
    _make(str(src))
    data = src.read_bytes()
    i = data.rindex(b"startxref")
    src.write_bytes(data[:i] + b"startxref\n999999\n%%EOF\n")
    r = core.optimize_pdf(str(src), str(dst))
    assert r["status"].startswith("copied")
    assert "damaged" in r["status"] or "damaged" in r["note"]
    assert dst.read_bytes() == src.read_bytes()
