"""Generate synthetic test PDFs into tests/samples/ (gitignored).

Usage: python tests/make_samples.py [output_dir]
Only pymupdf, pillow and numpy. Fixed seeds: output is reproducible.
Each sample is under 2 MB and shows the problem named in its file name.
"""
import io
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "samples"
W, H = 1240, 1754  # A4 at 150 dpi
PAGE = pymupdf.paper_rect("a4")

# name -> what it tests (printed by main)
SAMPLES = {}


def sample(desc):
    def deco(fn):
        SAMPLES[fn.__name__.removeprefix("make_") + ".pdf"] = (desc, fn)
        return fn
    return deco


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # old Pillow
        return ImageFont.load_default()


def _rng(seed):
    return np.random.default_rng(seed)


def _paper(mode="L", bg=255):
    return Image.new(mode, (W, H), bg if mode == "L" else (bg, bg, bg))


def _text_lines(d, fill, n=40, seed=1, x0=100, y0=140, size=26, width=W):
    """Draw fake statement lines (table-like rows with amounts)."""
    r = _rng(seed)
    f = _font(size)
    d.text((x0, 60), "Sample Bank Ltd - Statement of Account", font=_font(40), fill=fill)
    for i in range(n):
        y = y0 + i * 36
        d.text((x0, y), f"{i + 1:03d}  12-Mar-2026  Transfer ref {int(r.integers(10**8, 10**9))}", font=f, fill=fill)
        d.text((width - 380, y), f"{int(r.integers(100, 99999)):>8,}.00", font=f, fill=fill)


def _speckle(img, seed, sigma=6):
    """Scanner noise + slight tilt of paper tone."""
    a = np.asarray(img).astype(np.int16)
    a = a + _rng(seed).normal(0, sigma, a.shape).astype(np.int16)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _png(img):
    b = io.BytesIO()
    img.save(b, "PNG", optimize=True)
    return b.getvalue()


def _jpeg(img, q=85):
    b = io.BytesIO()
    img.save(b, "JPEG", quality=q)
    return b.getvalue()


def _new(path, img_bytes=None):
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE.width, height=PAGE.height)
    if img_bytes:
        page.insert_image(page.rect, stream=img_bytes)
    return doc, page


_ID = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]")


def _save(doc, path, **kw):
    doc.save(path, garbage=3, deflate=True, **kw)
    doc.close()
    if "user_pw" not in kw and "owner_pw" not in kw:
        # PyMuPDF writes a random trailer /ID, which made every run differ by a few bytes.
        # The trailer sits after all offsets, so a fixed-text replacement keeps the file valid.
        # (Encrypted files are skipped: the /ID is part of the key, and they stay fixed-size anyway.)
        data = Path(path).read_bytes()
        fixed = b"/ID[<" + b"00" * 16 + b"><" + b"11" * 16 + b">]"
        Path(path).write_bytes(_ID.sub(lambda m: fixed, data))


@sample("Tiny 1-bit text page at 150 dpi that is already optimal (Flate). Must be copied unchanged (Q8).")
def make_scan_bw_tiny(path):
    img = _paper("L")
    _text_lines(ImageDraw.Draw(img), 0)
    img = _speckle(img, 2, 8).point(lambda v: 255 if v > 140 else 0).convert("1")
    doc, _ = _new(path, _png(img))
    _save(doc, path)


@sample("600 dpi noisy 1-bit text page stored as Flate (~1 MB). The bitonal path must re-encode it as CCITT-G4 and save a lot.")
def make_scan_bw(path):
    k = 4                                                   # 600 dpi = 4 x the 150 dpi canvas
    img = Image.new("L", (W * k, H * k), 255)
    d = ImageDraw.Draw(img)
    r = _rng(15)
    f = _font(26 * k)
    d.text((100 * k, 60 * k), "Sample Bank Ltd - Statement of Account", font=_font(40 * k), fill=0)
    for i in range(40):
        y = (140 + i * 36) * k
        d.text((100 * k, y), f"{i + 1:03d}  12-Mar-2026  Transfer ref {int(r.integers(10**8, 10**9))}", font=f, fill=0)
        d.text(((W - 380) * k, y), f"{int(r.integers(100, 99999)):>8,}.00", font=f, fill=0)
    a = np.asarray(img)
    a = np.where(r.random(a.shape) < 0.014, 255 - a, a)     # salt-and-pepper scanner noise
    img = Image.fromarray(a.astype(np.uint8)).point(lambda v: 255 if v > 128 else 0).convert("1")
    doc, page = _new(path, _png(img))
    _save(doc, path)


@sample("Grey scan: anti-aliased text with noise. Grey page must not turn into harsh black-and-white.")
def make_scan_grey(path):
    img = _paper("L", 238)
    _text_lines(ImageDraw.Draw(img), 40)
    doc, _ = _new(path, _png(_speckle(img, 3, 5)))
    _save(doc, path)


@sample("Colour scan with a blue signature and red stamp. Both colours must survive scan mode.")
def make_scan_color_sig_stamp(path):
    img = _paper("RGB", 245)
    d = ImageDraw.Draw(img)
    _text_lines(d, (30, 30, 30), n=30, seed=4)
    pts = [(150 + i * 6, 1450 + int(60 * np.sin(i / 3.0)) - i) for i in range(60)]
    d.line(pts, fill=(20, 40, 200), width=5)  # blue signature
    d.ellipse((800, 1380, 1050, 1630), outline=(200, 20, 30), width=8)  # red stamp
    d.ellipse((830, 1410, 1020, 1600), outline=(200, 20, 30), width=3)
    d.text((865, 1485), "RECEIVED", font=_font(34), fill=(200, 20, 30))
    doc, _ = _new(path, _jpeg(_speckle(img, 5, 4), 88))
    _save(doc, path)


@sample("Scanned page with a colour logo and a red seal. Scan mode must rebuild it with a picture layer that keeps both.")
def make_logo_seal(path):
    img = _paper("RGB", 248)
    d = ImageDraw.Draw(img)
    _text_lines(d, (30, 30, 30), n=30, seed=14)
    d.rectangle((90, 40, 250, 200), fill=(90, 150, 215))                      # logo block (mid-tone)
    d.text((270, 100), "SAMPLE BANK", font=_font(48), fill=(0, 70, 140))
    d.ellipse((820, 1300, 1120, 1600), fill=(235, 150, 160), outline=(150, 20, 40), width=6)   # seal (mid-tone)
    d.ellipse((860, 1340, 1080, 1560), outline=(150, 20, 40), width=3)
    d.text((910, 1435), "OFFICIAL", font=_font(34), fill=(150, 20, 40))
    doc, _ = _new(path, _jpeg(_speckle(img, 14, 3), 88))
    _save(doc, path)


@sample("Page with a continuous-tone photo. Photo should be recompressed, text kept as text.")
def make_photo_page(path):
    r = _rng(6)
    y, x = np.mgrid[0:900, 0:1200]
    base = np.stack([120 + 80 * np.sin(x / 150), 100 + 60 * np.cos(y / 120), 140 + 50 * np.sin((x + y) / 200)], -1)
    photo = Image.fromarray(np.clip(base + r.normal(0, 12, base.shape), 0, 255).astype(np.uint8))
    doc, page = _new(path)
    page.insert_text((50, 60), "Applicant photograph and supporting text", fontsize=14)
    page.insert_image(pymupdf.Rect(50, 80, 545, 450), stream=_jpeg(photo, 95))
    for i in range(20):
        page.insert_text((50, 480 + i * 14), f"Note {i + 1}: photo captured at branch counter.", fontsize=10)
    _save(doc, path)


@sample("Scan with pastel bar chart, highlighter band, light grey text. Scan mode must not wipe pastel colours (Q1).")
def make_scan_pastel_chart(path):
    img = _paper("RGB", 250)
    d = ImageDraw.Draw(img)
    _text_lines(d, (60, 60, 60), n=12, seed=7)
    d.rectangle((90, 300, 1150, 340), fill=(255, 250, 150))  # highlighter
    d.text((100, 305), "Highlighted line: total outstanding balance", font=_font(26), fill=(60, 60, 60))
    pastel = [(226, 222, 213), (200, 225, 240), (240, 205, 210), (210, 235, 205)]
    for i, c in enumerate(pastel):
        h = 250 + i * 90
        d.rectangle((150 + i * 250, 1150 - h, 330 + i * 250, 1150), fill=c)
    d.text((100, 1200), "Light grey footnote text that is easy to lose.", font=_font(26), fill=(185, 185, 185))
    doc, _ = _new(path, _jpeg(_speckle(img, 8, 3), 88))
    _save(doc, path)


@sample("Black-and-white scan stored as an ImageMask (stencil mask). Engine currently skips it; must be handled (M1).")
def make_scan_stencil_mask(path):
    img = _paper("L")
    _text_lines(ImageDraw.Draw(img), 0, seed=9)
    img = _speckle(img, 9, 8).point(lambda v: 255 if v > 140 else 0).convert("1")
    doc, page = _new(path, _png(img))
    xref = page.get_images()[0][0]
    doc.xref_set_key(xref, "ImageMask", "true")
    doc.xref_set_key(xref, "ColorSpace", "null")
    doc.xref_set_key(xref, "BitsPerComponent", "1")
    _save(doc, path)


ROT_WORD = "Sample"             # first word of the title, drawn at (100, 60) px on the displayed page
ROT_W, ROT_H = H, W             # displayed page is landscape: 1754 x 1240 px at 150 dpi


def rotated_word_rect():
    """Where ROT_WORD is drawn, in points on the DISPLAYED page (top-left origin)."""
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((100, 60), ROT_WORD, font=_font(40))
    sc = 72 / 150
    return pymupdf.Rect(*(v * sc for v in box))


@sample("Pure scan on a /Rotate 270 page (no real text). Output keeps its orientation and OCR boxes line up with the words.")
def make_rotated_270(path):
    img = Image.new("L", (ROT_W, ROT_H), 240)
    _text_lines(ImageDraw.Draw(img), 30, n=25, seed=10, width=ROT_W)
    # the page is stored portrait and shown rotated 270: store the image turned the opposite way
    stored = _speckle(img, 10, 4).rotate(-90, expand=True)
    doc, page = _new(path, _png(stored))
    page.set_rotation(270)
    _save(doc, path)


@sample("Scan whose CropBox is offset from the MediaBox origin. Rendering and OCR coordinates must stay aligned.")
def make_offset_cropbox(path):
    img = _paper("L", 240)
    _text_lines(ImageDraw.Draw(img), 30, n=25, seed=11)
    doc, page = _new(path, _png(_speckle(img, 11, 4)))
    page.set_cropbox(pymupdf.Rect(60, 80, PAGE.width - 40, PAGE.height - 100))
    _save(doc, path)


@sample("Scan plus a real-text 'Page 7' stamp. Page counts as image-only, so OCR must still run (Q4).")
def make_scan_digital_pagenumber(path):
    img = _paper("L", 240)
    _text_lines(ImageDraw.Draw(img), 30, n=25, seed=12)
    doc, page = _new(path, _png(_speckle(img, 12, 4)))
    page.insert_text((270, 825), "Page 7", fontsize=10)
    _save(doc, path)


@sample("Many separately embedded fonts (12 faces, one per name). Font handling and size accounting.")
def make_many_fonts(path):
    doc, page = _new(path)
    faces = ["helv", "heit", "hebo", "hebi", "tiro", "tibo", "tiit", "tibi", "cour", "cobo", "coit", "cobi"]
    for i, face in enumerate(faces):
        name = f"Emb{i:02d}"
        page.insert_font(fontname=name, fontbuffer=pymupdf.Font(face).buffer)
        page.insert_text((50, 80 + i * 40), f"Embedded font {name} ({face}): The quick brown fox 0123456789",
                         fontname=name, fontsize=12)
    _save(doc, path)


@sample("Password-protected (AES-256, user password 'test'). Must be reported cleanly, never crash or leak.")
def make_password_protected(path):
    doc, page = _new(path)
    for i in range(10):
        page.insert_text((50, 80 + i * 16), f"Confidential line {i + 1}", fontsize=11)
    _save(doc, path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="test", owner_pw="owner")


@sample("Embedded CMYK JPEG photo. Colours must stay right when recompressed (M2: CMYK images are skipped).")
def make_cmyk_image(path):
    r = _rng(13)
    y, x = np.mgrid[0:600, 0:800]
    cmyk = np.stack([x / 800 * 255, y / 600 * 255, 128 + 100 * np.sin(x / 90), 20 + 0 * x], -1)
    cmyk = np.clip(cmyk + r.normal(0, 8, cmyk.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(cmyk, "CMYK")
    doc, page = _new(path)
    page.insert_text((50, 60), "CMYK image below", fontsize=14)
    page.insert_image(pymupdf.Rect(50, 80, 450, 380), stream=_jpeg(img, 90))
    _save(doc, path)


@sample("Oversized indexed-colour (palette) screenshot, ~550 dpi on the page. Engine skips palette images today (M3).")
def make_palette_image(path):
    w, h = 3200, 2000
    img = Image.new("RGB", (w, h), (245, 247, 250))
    d = ImageDraw.Draw(img)
    r = _rng(16)
    d.rectangle((0, 0, w, 140), fill=(36, 99, 235))                          # title bar
    d.text((40, 40), "Online Banking - Account Overview", font=_font(64), fill=(255, 255, 255))
    d.rectangle((0, 140, 520, h), fill=(230, 234, 242))                      # side menu
    for i, name in enumerate(["Accounts", "Transfers", "Cards", "Loans", "Statements", "Settings"]):
        d.text((50, 200 + i * 110), name, font=_font(48), fill=(40, 50, 70))
    for row in range(14):
        y = 220 + row * 120
        d.rectangle((580, y, w - 60, y + 100), fill=(255, 255, 255) if row % 2 == 0 else (238, 242, 250),
                    outline=(205, 210, 222))
        d.text((620, y + 28), f"2026-03-{row + 1:02d}  Payment ref {int(r.integers(10**7, 10**8))}", font=_font(44), fill=(30, 35, 50))
        d.text((w - 560, y + 28), f"{int(r.integers(100, 99999)):>9,}.00", font=_font(44),
               fill=(20, 140, 70) if row % 3 else (200, 40, 50))
    img = img.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)   # mode "P"
    doc, page = _new(path)
    page.insert_image(pymupdf.Rect(40, 60, 40 + 400, 60 + 250), stream=_png(img))
    # PyMuPDF turns a palette PNG into ICCBased RGB; write it back as a real /Indexed image
    xref = page.get_images()[0][0]
    pal = img.getpalette()[:64 * 3]
    doc.update_stream(xref, np.asarray(img, dtype=np.uint8).tobytes())
    doc.xref_set_key(xref, "ColorSpace", "[/Indexed /DeviceRGB 63 <%s>]" % bytes(pal).hex())
    doc.xref_set_key(xref, "SMask", "null")
    _save(doc, path)


def main(out=OUT):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, (desc, fn) in SAMPLES.items():
        p = out / name
        fn(str(p))
        print(f"{name:36s} {p.stat().st_size / 1024:7.0f} KB  {desc}")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else OUT)
