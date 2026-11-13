"""Q5: OCR output that is mostly '?' or symbols (Bangla, signatures) must not become text-layer words."""
import pdfopt_core as core


def _w(t):
    return (0, 0, 10, 10, t)


def test_Q5_junk_words_dropped_real_words_kept():
    words = [_w(t) for t in ["Statement", "????", "?", "~|/", "a?", "Ltd.", "1,234.50", "-", "??x", "$100", "(abc)", "No."]]
    kept = [w[4] for w in core._clean_ocr_words(words)]
    assert kept == ["Statement", "Ltd.", "1,234.50", "-", "$100", "(abc)", "No."]
