# ============================================================================
# PDF OPTIMIZER ENGINE  (offline re-implementation of the pdfcompressor.com approach)
# ----------------------------------------------------------------------------
# 1. Classify every image: bitonal / grayscale / colour / leave-alone
# 2. Downsample only if effective DPI > target x 1.4  (bitonal 300, gray/colour 200)
# 3. Colour & gray -> JPEG, quality 75, raised to 85 when "Gradient Energy
#    Detection" finds text / thin lines in the image
# 4. Bitonal -> lossless JBIG2 (if jbig2.exe is available) / CCITT G4 / Flate,
#    smallest wins; every lossless candidate is decoded back and must match
#    the source bit-for-bit before it is accepted
# 5. Fonts: subset to the glyphs actually used, strip TrueType hinting
#    programs and unneeded tables (verified: pages must render identically)
# 6. Deduplicate objects, compress object streams, drop page thumbnails
# 7. Optional SCAN MODE: full-page colour/gray scans of documents are rebuilt
#    as a sharp 1-bit text layer (JBIG2/CCITT) plus, only if the page has
#    coloured ink (stamps, blue signatures), a tiny low-res colour layer.
#    Pages with photos/graphics are never converted.
# 8. Optional OCR: invisible English text layer on image-only pages (search/copy)
# 9. Render every page before/after at low resolution and compare; if anything
#    looks wrong, or the file did not get smaller, the ORIGINAL is kept
# Needs only:  pymupdf, pillow, numpy, fonttools   (all pip wheels, no installers)
# ============================================================================
import io, os, re, math, time, zlib, shutil, tempfile, subprocess
import numpy as np
from PIL import Image

try:
    import pymupdf
except ImportError:          # older PyMuPDF versions
    import fitz as pymupdf

DEFAULTS = dict(
    target_dpi_color=200,    # colour images are downsampled to this...
    target_dpi_gray=200,     # grayscale images
    target_dpi_bitonal=300,  # black & white (1-bit) images
    downsample_factor=1.4,   # ...but only when actual DPI > target x 1.4
    jpeg_q_base=75,          # JPEG quality for photos / smooth images
    jpeg_q_detail=85,        # JPEG quality when text or thin lines are detected
    ged_threshold=12.0,      # gradient-energy level (95th pct of 16x16 blocks) that counts as "detail"
    min_side=32,             # images narrower/shorter than this are left alone
    min_pixels=1024,         # tiny images are left alone
    jpeg_chroma_444=False,   # True = full colour resolution in JPEGs (bigger files); False = standard 4:2:0
    jpeg_min_gain=0.10,      # an existing JPEG is only re-encoded (no resize) if it saves >= 10%
    optimize_fonts=True,     # font pass (needs fonttools)
    subset_fonts=True,       # drop glyphs never used in the document
    strip_font_hinting=True, # remove TrueType hinting programs & extra tables (invisible in PDF viewers)
    use_jbig2=True,          # use jbig2.exe (lossless generic mode) if it can be found
    jbig2_path=None,         # full path to jbig2 / jbig2.exe, or None to search PATH
    # ---- scan mode: rebuild full-page colour/gray scans of documents as sharp black text
    scan_mode="off",         # "off" | "auto" (B&W, or B&W + ink colours when the page has coloured ink) | "bw" (always black only)
    scan_dpi=300,            # resolution of the black/white text layer
    scan_min_dpi=150,        # scans below this are too coarse to binarize safely -> left to normal pass
    scan_min_cover=0.70,     # only images covering >= 70% of the page (i.e. page scans, not logos/photos)
    scan_max_ink=0.30,
    scan_picture_min_blocks=12,  # >= ~1 cm2 of continuous mid-tones (logo, seal, photo) is kept as an image...
    scan_max_picture_share=0.35, # ...unless pictures cover > 35% of the page: then the page is not converted
    scan_picture_dpi=150,        # resolution of the colour layer when it carries pictures       # pages with more than 30% "ink" are photos/dark -> not converted
    scan_k=0.25,
    scan_despeckle=2,        # grain removal: 0 off, 1 light, 2 medium, 3 strong             # Sauvola sensitivity (lower = bolder text, higher = thinner)
    scan_window_mm=4.5,      # Sauvola window size
    scan_color_dpi=100,      # resolution of the ink-colour layer in "auto" mode
    scan_color_quality=70,   # JPEG quality of the ink-colour layer
    scan_min_color_blocks=8, # coloured ink areas (~2.7 mm squares) needed before colour is kept
    scan_min_recall=0.97,    # legibility check: share of clearly dark strokes that must survive
    scan_min_corr=0.80,      # legibility check: correlation with the original page (0-1)
    # ---- OCR: add an invisible, searchable English text layer to pages that are only images
    ocr=False,
    ocr_language="eng",
    ocr_dpi=300,
    tessdata=None,           # folder holding eng.traineddata; None = "tessdata" next to the app/notebook or TESSDATA_PREFIX
    remove_thumbnails=True,  # embedded page thumbnails are dead weight
    remove_xmp=False,        # XMP metadata: keep by default (PDF/A needs it)
    skip_signed=True,        # digitally signed PDFs are copied unchanged (rewriting breaks signatures)
    verify_pages=True,       # render before/after and compare every page
    verify_dpi=40,
    verify_font_max_mae=0.5, # font pass must render (almost) pixel-identical
    verify_max_mae=12.0,     # max mean abs. pixel difference (0-255) per page; catches gross errors (inverted, wrong colours, missing)
    min_file_gain=0.01,      # if the result is not at least 1% smaller, keep the original
)

_SKIP_CS = ("/Indexed", "/Separation", "/DeviceN", "/Lab", "/CalRGB", "/CalGray", "/Pattern")


# --------------------------------------------------------------------------- helpers
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)     # no console flash from a GUI app on Windows


class OptimizerCancelled(Exception):
    """Raised from a progress callback to stop processing."""


def _app_dirs():
    import sys
    dirs = []
    if getattr(sys, "frozen", False):                             # PyInstaller build
        dirs += [os.path.dirname(sys.executable), getattr(sys, "_MEIPASS", "")]
    here = globals().get("__file__")                              # not defined inside a notebook
    if here:
        dirs.append(os.path.dirname(os.path.abspath(here)))
    dirs.append(os.getcwd())
    return [d for d in dirs if d]


def find_jbig2(path=None):
    """Return a working jbig2 executable path or None."""
    cands = [path] if path else (
        [os.path.join(d, n) for d in _app_dirs() for n in ("jbig2.exe", "jbig2")]
        + [os.path.join(d, "third_party", "jbig2", n) for d in _app_dirs() for n in ("jbig2.exe", "jbig2")]
        + [shutil.which("jbig2"), shutil.which("jbig2.exe")])
    for c in cands:
        if c and os.path.isfile(c):
            try:
                subprocess.run([c, "--version"], capture_output=True, timeout=10, creationflags=_NO_WINDOW)
                return c
            except Exception:
                pass
    return None


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def _key(doc, xref, k):
    return doc.xref_get_key(xref, k)


def _colorspace_kind(doc, xref):
    """'gray' | 'rgb' | ('skip', reason)"""
    t, v = _key(doc, xref, "ColorSpace")
    if t == "null":
        return ("skip", "no colour space (JPX/mask)")
    cs = v
    if t == "xref":
        cs = doc.xref_object(int(v.split()[0]), compressed=True)
    for s in _SKIP_CS:
        if s in cs:
            return ("skip", f"colour space {s[1:]}")
    if "/DeviceCMYK" in cs:
        return ("skip", "CMYK")
    if "/DeviceGray" in cs:
        return "gray"
    if "/DeviceRGB" in cs:
        return "rgb"
    m = re.search(r"/ICCBased\s+(\d+)\s+0\s+R", cs)
    if m:
        nt, nv = _key(doc, int(m.group(1)), "N")
        n = int(nv) if nt == "int" else 0
        return {1: "gray", 3: "rgb"}.get(n, ("skip", f"ICC N={n}"))
    return ("skip", f"colour space {cs[:30]}")


def _classify(doc, xref):
    if _key(doc, xref, "Subtype")[1] != "/Image":
        return ("skip", "not an image")
    if _key(doc, xref, "ImageMask")[1] == "true":
        return ("skip", "stencil mask")
    if _key(doc, xref, "Mask")[0] == "array":
        return ("skip", "colour-key mask")
    kind = _colorspace_kind(doc, xref)
    if isinstance(kind, tuple):
        return kind
    bt, bv = _key(doc, xref, "BitsPerComponent")
    bpc = int(bv) if bt == "int" else 8
    if kind == "gray" and bpc == 1:
        return "bitonal"
    if _key(doc, xref, "Decode")[0] != "null":
        return ("skip", "custom Decode array")
    return kind


def _placements(doc):
    """xref -> {'dpi': lowest effective DPI, 'cover': largest share of a page it covers}"""
    out = {}
    for page in doc:
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            continue
        parea = abs(page.rect)
        for info in infos:
            x = info.get("xref", 0)
            if not x or x <= 0:
                continue
            a, b, c, d, _, _ = info["transform"]
            wpt, hpt = math.hypot(a, b), math.hypot(c, d)
            if wpt < 0.5 or hpt < 0.5:
                continue
            dpi = min(info["width"] / (wpt / 72.0), info["height"] / (hpt / 72.0))
            cover = abs(pymupdf.Rect(info["bbox"]) & page.rect) / parea if parea else 0
            o = out.setdefault(x, {"dpi": 1e9, "cover": 0.0})
            o["dpi"] = min(o["dpi"], dpi)
            o["cover"] = max(o["cover"], cover)
    return out


def _effective_dpi(doc):
    """xref -> lowest effective DPI over all placements on all pages."""
    eff = {}
    for page in doc:
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            continue
        for info in infos:
            x = info.get("xref", 0)
            if not x or x <= 0:
                continue
            a, b, c, d, _, _ = info["transform"]
            wpt, hpt = math.hypot(a, b), math.hypot(c, d)
            if wpt < 0.5 or hpt < 0.5:
                continue
            dpi = min(info["width"] / (wpt / 72.0), info["height"] / (hpt / 72.0))
            eff[x] = min(eff.get(x, 1e9), dpi)
    return eff


def _gradient_quality(img, s):
    """Gradient Energy Detection: 95th percentile of 16x16 block gradient energy."""
    a = np.asarray(img.convert("L"), dtype=np.float32)
    if a.shape[0] < 17 or a.shape[1] < 17:
        return s["jpeg_q_detail"], 0.0
    g = np.abs(np.diff(a, axis=1))[:-1, :] + np.abs(np.diff(a, axis=0))[:, :-1]
    bh, bw = g.shape[0] // 16, g.shape[1] // 16
    blocks = g[: bh * 16, : bw * 16].reshape(bh, 16, bw, 16).mean(axis=(1, 3))
    p95 = float(np.percentile(blocks, 95))
    q = s["jpeg_q_detail"] if p95 >= s["ged_threshold"] else s["jpeg_q_base"]
    return q, p95


def _decode_test(dict_str, data, keys):
    """Decode a candidate stream in a scratch PDF and return its pixels (uint8 array)."""
    sd = pymupdf.open()
    try:
        x = sd.get_new_xref()
        sd.update_object(x, dict_str)
        sd.update_stream(x, data, compress=False)
        for k, v in keys.items():
            sd.xref_set_key(x, k, v)
        pix = pymupdf.Pixmap(sd, x)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    finally:
        sd.close()


def _encode_ccitt(img1):
    buf = io.BytesIO()
    img1.save(buf, format="TIFF", compression="group4", tiffinfo={278: img1.height})
    t = Image.open(io.BytesIO(buf.getvalue()))
    offs, cnts = t.tag_v2[273], t.tag_v2[279]
    if len(offs) != 1:
        return None
    raw = buf.getvalue()[offs[0] : offs[0] + cnts[0]]
    photometric = t.tag_v2.get(262, 0)
    return raw, photometric


def _encode_jbig2(img1, exe):
    """Run jbig2 in a temp dir with a relative file name, so a non-English user name in the
    temp path cannot break it. Returns the data, or None (and logs why)."""
    with tempfile.TemporaryDirectory() as td:
        name = "page.pbm"                      # PBM: readable by every jbig2 build
        img1.save(os.path.join(td, name))
        r = subprocess.run([exe, "-p", name], capture_output=True, timeout=300, cwd=td, creationflags=_NO_WINDOW)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        import logging
        logging.getLogger("pdfopt").warning(
            "JBIG2 encoder failed (exit %s); using CCITT/Flate instead", r.returncode)
        return None



# --------------------------------------------------------------------------- fonts
def _font_files(doc):
    """{xref: key} of embedded font programs."""
    out = {}
    for x in range(1, doc.xref_length()):
        try:
            if _key(doc, x, "Type")[1] != "/FontDescriptor":
                continue
        except Exception:
            continue
        for k in ("FontFile", "FontFile2", "FontFile3"):
            t, v = _key(doc, x, k)
            if t == "xref":
                out[int(v.split()[0])] = k
    return out


def _optimize_fonts(doc, s):
    """Returns a short note. Modifies doc in place."""
    try:
        import logging
        from fontTools.ttLib import TTFont
        from fontTools import subset as ftsubset
        logging.getLogger("fontTools").setLevel(logging.CRITICAL)
    except ImportError:
        return "fonttools not installed: font pass skipped"
    notes = []
    if not _font_files(doc):
        return "no embedded fonts"
    before = sum(len(doc.xref_stream_raw(x) or b"") for x in _font_files(doc))
    if s["subset_fonts"] and not doc.is_form_pdf:      # never subset fonts that form fields may need
        try:
            doc.subset_fonts()
            notes.append("subset")
        except Exception as e:
            notes.append(f"subset failed ({type(e).__name__})")
    if s["strip_font_hinting"]:
        n_ok = 0
        for x, kind in _font_files(doc).items():
            if kind != "FontFile2":                      # TrueType only
                continue
            try:
                raw = doc.xref_stream_raw(x) or b""
                f = TTFont(io.BytesIO(doc.xref_stream(x)), lazy=False)
                o = ftsubset.Options()
                o.hinting = False            # drop fpgm / prep / cvt / glyph instructions
                o.retain_gids = True         # glyph numbers must not change (CID fonts index by GID)
                o.notdef_outline = True
                o.glyph_names = True         # keep 'post' names (simple fonts may select glyphs by name)
                o.legacy_cmap = True         # keep (1,0) Mac cmap
                o.symbol_cmap = True         # keep (3,0) symbol cmap
                o.layout_features = []
                o.drop_tables += ["DSIG", "hdmx", "LTSH", "VDMX", "kern", "GPOS", "GSUB", "GDEF", "JSTF", "meta"]
                o.recalc_bounds = False
                o.recalc_timestamp = False
                sub = ftsubset.Subsetter(o)
                sub.populate(gids=list(range(len(f.getGlyphOrder()))))   # keep every glyph
                sub.subset(f)
                b = io.BytesIO(); f.save(b); new = b.getvalue()
                if len(zlib.compress(new, 9)) < len(raw):
                    doc.update_stream(x, new, compress=True)
                    doc.xref_set_key(x, "Length1", str(len(new)))
                    n_ok += 1
            except Exception:
                pass
        notes.append(f"hinting stripped in {n_ok} fonts")
    after = sum(len(doc.xref_stream_raw(x) or b"") for x in _font_files(doc))
    return f"fonts {human(before)} -> {human(after)} ({', '.join(notes)})"


# --------------------------------------------------------------------------- scan mode
def _sauvola(L, window, k, R=128.0):
    """Adaptive threshold map (Sauvola) using integral images. L: float32 2-D array."""
    h, w = L.shape
    r = window // 2
    P = np.pad(L, r + 1, mode="reflect").astype(np.float64)
    I1 = P.cumsum(0).cumsum(1)
    I2 = (P * P).cumsum(0).cumsum(1)
    def boxsum(I):
        return (I[window:window + h, window:window + w] - I[0:h, window:window + w]
                - I[window:window + h, 0:w] + I[0:h, 0:w])
    n = float(window * window)
    m = boxsum(I1) / n
    v = np.maximum(boxsum(I2) / n - m * m, 0)
    return (m * (1 + k * (np.sqrt(v) / R - 1))).astype(np.float32)


def _neighbours(b):
    """Number of set 8-neighbours for each pixel of a boolean array."""
    p = np.pad(b, 1).astype(np.uint8)
    return (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] + p[1:-1, :-2] + p[1:-1, 2:]
            + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:])


def _box_count(b, window):
    """Number of set pixels in a window x window square around each pixel (integral image)."""
    h, w = b.shape
    r = window // 2
    P = np.pad(b.astype(np.int32), r + 1)
    I = P.cumsum(0).cumsum(1)
    return (I[window:window + h, window:window + w] - I[0:h, window:window + w]
            - I[window:window + h, 0:w] + I[0:h, 0:w])


_DESPECKLE_AREA = {0: 0, 1: 9, 2: 20, 3: 36}    # max speck size in pixels at 300 dpi (~3x3, ~4.5x4.5, 6x6)


def _despeckle(ink, dpi, level):
    """Remove small specks that have nothing else within ~1 mm (grain, dust, paper texture).
    Full stops, decimal points, i-dots and dotted lines always have neighbours, so they stay."""
    area = _DESPECKLE_AREA.get(int(level), 0)
    if not area:
        return ink, 0
    area = max(1, int(round(area * (dpi / 300.0) ** 2)))
    window = max(9, int(round(2.0 / 25.4 * dpi)) | 1)             # ~2 mm square
    speck = ink & (_box_count(ink, window) <= area)
    return ink & ~speck, int(speck.sum())


def _corr(a, b):
    a = a.astype(np.float64).ravel(); b = b.astype(np.float64).ravel()
    a -= a.mean(); b -= b.mean()
    d = math.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


def _scan_convert(doc, xref, kind, dpi, s, jbig2_exe):
    """Rebuild a page scan as a 1-bit text layer (+ optional low-res ink colours).
    Returns (data, keys, mask_obj or None, note) or (None, reason)."""
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    mode = "RGB" if pix.n == 3 else "L"
    if pix.n not in (1, 3):
        return None, "unsupported pixel format"
    src = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    scale = s["scan_dpi"] / dpi
    scale = min(scale, 3.0)
    W, H = max(1, round(src.width * scale)), max(1, round(src.height * scale))
    work = src.resize((W, H), Image.LANCZOS) if abs(scale - 1) > 0.05 else src
    W, H = work.size
    rgb = np.asarray(work.convert("RGB"), dtype=np.float32)
    L = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    out_dpi = dpi * W / src.width

    # --- binarize: adaptive (Sauvola) + guards
    paper = float(np.percentile(L, 90))
    window = max(15, int(round(s["scan_window_mm"] / 25.4 * out_dpi)) | 1)
    T = _sauvola(L, window, s["scan_k"])
    ink = (L < T) & (L < paper - 0.12 * paper)          # ignore faint paper texture
    ink |= L < 0.35 * paper                             # solid dark areas are always ink
    nb = _neighbours(ink)
    ink &= nb >= 2                                      # drop isolated specks
    ink |= (~ink) & (nb >= 7)                           # fill pin-holes inside strokes
    ink, n_specks = _despeckle(ink, out_dpi, s["scan_despeckle"])
    # --- photo / graphic guard: solid patches of mid-tones are pictures, not text
    B = max(8, int(round(out_dpi * 0.107)))                             # ~2.7 mm blocks
    h2, w2 = H // B * B, W // B * B
    mid = ((L > 0.25 * paper) & (L < 0.75 * paper)).astype(np.float32)
    mid_share = mid[:h2, :w2].reshape(h2 // B, B, w2 // B, B).mean(axis=(1, 3))
    pic_blk = mid_share > 0.5
    pic_blocks = int(pic_blk.sum())
    pic = None                       # pixels kept as a picture (logos, seals, photos), not binarized
    if pic_blocks >= s["scan_picture_min_blocks"]:
        share = pic_blocks / pic_blk.size
        if share > s["scan_max_picture_share"]:
            return None, f"mostly picture ({share:.0%} of the page)"
        g = pic_blk.copy()                                              # grow by one block so the
        for _ in range(2):                                              # whole logo/seal/photo is kept
            g2 = g.copy()
            g2[1:, :] |= g[:-1, :]; g2[:-1, :] |= g[1:, :]
            g2[:, 1:] |= g[:, :-1]; g2[:, :-1] |= g[:, 1:]
            g = g2
        pic = np.zeros((H, W), bool)
        pic[:h2, :w2] = np.repeat(np.repeat(g, B, axis=0), B, axis=1)
    cover = float(ink.mean())
    if cover > s["scan_max_ink"]:
        return None, f"too much ink ({cover:.0%}): photo or dark page"
    if cover < 0.0005:
        return None, "blank page"

    # --- legibility guard 1: clearly dark strokes in the scan must all be in the text layer
    dark = L < 0.6 * paper
    n_dark = int(dark.sum())
    kept = ink if pic is None else (ink | pic)                  # picture areas are kept as image
    recall = float((kept & dark).sum()) / n_dark if n_dark else 1.0
    if recall < s["scan_min_recall"]:
        return None, f"text-loss check failed ({recall:.1%} of dark strokes kept)"

    # --- colour decision: look for coloured REGIONS (stamps, signatures), not scanner colour noise
    colour = False
    if s["scan_mode"] == "auto" and kind == "rgb":
        core = (ink & (_neighbours(ink) == 8)).astype(np.float32)   # stroke centres, no colour fringes
        def bsum(a):
            return a[:h2, :w2].reshape(h2 // B, B, w2 // B, B).sum(axis=(1, 3))
        n = bsum(core)
        mean = np.stack([bsum(rgb[:, :, i] * core) / np.maximum(n, 1) for i in range(3)], -1)
        cblocks = int(((n >= 20) & ((mean.max(-1) - mean.min(-1)) > 70)).sum())
        colour = cblocks >= s["scan_min_color_blocks"]
    if pic is not None:
        colour = True                                                   # pictures need the colour layer
    if pic is not None:
        pic &= L < 0.92 * paper                     # inside pictures, paint only non-paper pixels:
    final = ink if pic is None else (ink | pic)     # no visible box edge, white text stays crisp

    img1 = Image.fromarray(np.where(final, 0, 255).astype(np.uint8)).convert("1")
    best = _best_bitonal(img1, jbig2_exe)
    if best is None:
        return None, "no verified bitonal encoding"
    name, mdata, mkeys = best

    # --- legibility check on a ~100 dpi reconstruction
    f = max(1, int(round(out_dpi / 100)))
    def small(a):
        im = Image.fromarray(a.astype(np.uint8))
        return np.asarray(im.resize((max(1, W // f), max(1, H // f)), Image.BOX), dtype=np.float32)

    if not colour:
        rec = np.where(ink, 0, 255)
        c = _corr(small(L), small(rec))
        if c < s["scan_min_corr"]:
            return None, f"legibility check failed (corr {c:.2f})"
        keys = dict(mkeys, Width=str(W), Height=str(H), BitsPerComponent="1",
                    ColorSpace="/DeviceGray", Decode="null", Mask="null", SMask="null")
        return mdata, keys, None, f"scan -> B&W {out_dpi:.0f} dpi {name} (strokes kept {recall:.1%})"

    # colour layer: weighted average colour of ink per block, paper tint removed
    layer_dpi = s["scan_picture_dpi"] if pic is not None else s["scan_color_dpi"]
    fw = max(1, int(round(out_dpi / layer_dpi)))
    cw, ch = max(1, W // fw), max(1, H // fw)
    wgt = (ink * (255.0 - L) ** 2).astype(np.float32)
    den = np.asarray(Image.fromarray(wgt).resize((cw, ch), Image.BOX), dtype=np.float32)
    col = np.zeros((ch, cw, 3), np.float32)
    nonink = ~ink
    for i in range(3):
        num = np.asarray(Image.fromarray(rgb[:, :, i] * wgt).resize((cw, ch), Image.BOX), dtype=np.float32)
        white = float(np.percentile(rgb[:, :, i][nonink], 90)) if nonink.any() else 255.0
        black = float(np.percentile(rgb[:, :, i][ink], 2))
        v = np.where(den > 0, num / np.maximum(den, 1e-6), 0)
        col[:, :, i] = np.clip((v - black) * 255.0 / max(white - black, 1), 0, 255)
    neutral = (col.max(axis=2) - col.min(axis=2)) < 60
    if pic is not None:
        pcell = np.asarray(Image.fromarray(pic.astype(np.float32)).resize((cw, ch), Image.BOX)) > 0.01
        col[neutral & ~pcell] = 0                                        # neutral ink -> black
        pw = pic.astype(np.float32)                                      # average painted picture pixels only
        pden = np.asarray(Image.fromarray(pw).resize((cw, ch), Image.BOX), dtype=np.float32)
        for i in range(3):
            white = float(np.percentile(rgb[:, :, i][nonink], 90)) if nonink.any() else 255.0
            pnum = np.asarray(Image.fromarray(np.ascontiguousarray(rgb[:, :, i] * pw)).resize((cw, ch), Image.BOX),
                              dtype=np.float32)
            plain = np.where(pden > 0, pnum / np.maximum(pden, 1e-6), 255)
            ci = col[:, :, i]
            sel = pcell & (pden > 0)
            ci[sel] = np.clip(plain[sel] * 255.0 / max(white, 1), 0, 255)
        quality = max(s["scan_color_quality"], 75)
    else:
        col[neutral] = 0                                                 # neutral ink -> black (smallest JPEG)
        quality = s["scan_color_quality"]
    cimg = Image.fromarray(col.astype(np.uint8))
    b = io.BytesIO()
    cimg.save(b, format="JPEG", quality=quality, optimize=True, subsampling=2)
    cdata = b.getvalue()
    up = np.asarray(cimg.resize((W, H), Image.NEAREST), dtype=np.float32)
    recL = 0.299 * up[:, :, 0] + 0.587 * up[:, :, 1] + 0.114 * up[:, :, 2]
    rec = np.where(final, recL, 255)
    c = _corr(small(L), small(rec))
    if c < s["scan_min_corr"]:
        return None, f"legibility check failed (corr {c:.2f})"
    mask_obj = (f"<< /Type /XObject /Subtype /Image /Width {W} /Height {H} "
                f"/ImageMask true /BitsPerComponent 1 >>", mdata, mkeys)
    keys = {"Filter": "/DCTDecode", "DecodeParms": "null", "Width": str(cw), "Height": str(ch),
            "BitsPerComponent": "8", "ColorSpace": "/DeviceRGB", "Decode": "null", "SMask": "null"}
    extra = f", {pic_blocks} picture blocks kept as image" if pic is not None else ""
    return cdata, keys, mask_obj, (f"scan -> B&W {out_dpi:.0f} dpi {name} + colour layer "
                                   f"{out_dpi / fw:.0f} dpi (strokes kept {recall:.1%}{extra})")


# --------------------------------------------------------------------------- OCR
_PDF_ESC = str.maketrans({"(": r"\(", ")": r"\)", "\\": r"\\"})


def find_tessdata(path=None, lang="eng"):
    """Folder that contains <lang>.traineddata, or None."""
    cands = [path] if path else ([os.path.join(d, sub) for d in _app_dirs()
                                  for sub in ("tessdata", os.path.join("third_party", "tessdata"))]
                                 + [os.environ.get("TESSDATA_PREFIX", "")])
    for c in cands:
        if c and os.path.isfile(os.path.join(c, f"{lang}.traineddata")):
            return c
    return None


def _needs_ocr(page):
    """Pages that show a scan (big image) and whose own text covers little of the page
    (a stamped page number does not count as a text layer)."""
    try:
        parea = abs(page.rect)
        covered = sum(abs(pymupdf.Rect(w[:4]) & page.rect) for w in page.get_text("words"))
        if covered >= 0.10 * parea:
            return False
        return any(abs(pymupdf.Rect(i["bbox"]) & page.rect) >= 0.5 * parea for i in page.get_image_info())
    except Exception:
        return False


def _ocr_words(page, tessdata, lang, dpi):
    """OCR the page exactly as displayed; returns words in page (display) coordinates."""
    pix = page.get_pixmap(dpi=dpi)                     # RGB: gray pixmaps return no text in pdfocr
    pix.set_dpi(dpi, dpi)
    o = pymupdf.open("pdf", pix.pdfocr_tobytes(language=lang, tessdata=tessdata))
    try:
        sx, sy = page.rect.width / o[0].rect.width, page.rect.height / o[0].rect.height
        return _clean_ocr_words([(w[0] * sx, w[1] * sy, w[2] * sx, w[3] * sy, w[4]) for w in o[0].get_text("words")])
    finally:
        o.close()


def _clean_ocr_words(words):
    """Drop OCR noise: words that are half or more '?' (unreadable non-Latin text) or mostly symbols."""
    keep = []
    for w in words:
        t = w[4].strip()
        if not t or t.count("?") * 2 >= len(t):
            continue
        if len(t) >= 2 and sum(c.isalnum() for c in t) < 0.4 * len(t):
            continue
        keep.append(w)
    return keep


def _add_text_layer(doc, page, words):
    """Write words as invisible text (render mode 3) under the page, correct for any page rotation."""
    font = pymupdf.Font("helv")
    Q = page.derotation_matrix * ~page.transformation_matrix     # display coords -> PDF user space
    o0 = pymupdf.Point(0, 0) * Q
    def lin(v):
        p = pymupdf.Point(v) * Q
        return p.x - o0.x, p.y - o0.y
    U, V = lin((1, 0)), lin((0, -1))                              # reading direction, "up"
    ops, n = ["BT", "3 Tr"], 0
    for x0, y0, x1, y1, t in words:
        t = t.encode("cp1252", "replace").decode("cp1252").translate(_PDF_ESC)
        h = y1 - y0
        if h <= 0 or x1 <= x0 or not t.strip():
            continue
        fs = h * 0.92
        tl = font.text_length(t, fs)
        if tl <= 0:
            continue
        sx = (x1 - x0) / tl
        P = pymupdf.Point(x0, y1 - h * 0.22) * Q
        ops.append(f"/helv {fs:.2f} Tf {U[0]*sx:.4f} {U[1]*sx:.4f} {V[0]:.4f} {V[1]:.4f} "
                   f"{P.x:.2f} {P.y:.2f} Tm ({t}) Tj")
        n += 1
    if not n:
        return 0
    ops.append("ET")
    page.insert_font(fontname="helv")                            # Helvetica (no embedding needed)
    def stream(data):
        x = doc.get_new_xref()
        doc.update_object(x, "<<>>")
        doc.update_stream(x, data)
        return x
    old = page.get_contents()
    qx, Qx = stream(b"q"), stream(b"Q")                          # keep the page's own graphics state apart
    cx = stream("\n".join(ops).encode("cp1252", "replace"))
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in [qx, *old, Qx, cx]) + "]")
    return n

# --------------------------------------------------------------------------- per image
def _best_bitonal(img1, jbig2_exe):
    """Smallest of JBIG2 / CCITT G4 / Flate that decodes back bit-for-bit. Returns (name, data, keys) or None."""
    W, H = img1.size
    want = np.asarray(img1.convert("L"), dtype=np.uint8)
    base = f"<< /Type /XObject /Subtype /Image /Width {W} /Height {H} /ColorSpace /DeviceGray /BitsPerComponent 1 >>"

    cands = []
    # Flate (always available)
    cands.append(("Flate", zlib.compress(img1.tobytes(), 9), {"Filter": "/FlateDecode", "DecodeParms": "null"}))
    # CCITT G4
    try:
        r = _encode_ccitt(img1)
        if r:
            raw, phot = r
            for blk in ("false", "true"):
                cands.append(("CCITT-G4", raw, {"Filter": "/CCITTFaxDecode",
                              "DecodeParms": f"<< /K -1 /Columns {W} /Rows {H} /BlackIs1 {blk} >>"}))
    except Exception:
        pass
    # JBIG2 lossless (generic region coding = no symbol matching = no Xerox problem)
    if jbig2_exe:
        try:
            raw = _encode_jbig2(img1, jbig2_exe)
            if raw:
                cands.append(("JBIG2", raw, {"Filter": "/JBIG2Decode", "DecodeParms": "null"}))
        except Exception:
            pass

    best = None
    for name, data, keys in sorted(cands, key=lambda c: len(c[1])):
        try:
            got = _decode_test(base, data, keys)[:, :, 0]
        except Exception:
            continue
        if got.shape == want.shape and np.array_equal(got, want):   # bit-for-bit check
            best = (name, data, keys)
            break
    return best


def _process_bitonal(doc, xref, eff_dpi, s, jbig2_exe):
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0]
    src = Image.fromarray(np.where(a >= 128, 255, 0).astype(np.uint8))
    action = "re-encoded"
    tgt = s["target_dpi_bitonal"]
    if eff_dpi > tgt * s["downsample_factor"]:
        sc = tgt / eff_dpi
        nw, nh = max(1, round(src.width * sc)), max(1, round(src.height * sc))
        src = src.resize((nw, nh), Image.LANCZOS)
        action = f"downsampled {eff_dpi:.0f}->{tgt} dpi"
    img1 = src.point(lambda v: 255 if v >= 128 else 0).convert("1")
    W, H = img1.size
    best = _best_bitonal(img1, jbig2_exe)
    if best is None:
        return None
    name, data, keys = best
    keys = dict(keys, Width=str(W), Height=str(H), BitsPerComponent="1", Decode="null")
    return data, keys, f"{action} -> {name} (lossless, verified)"


def _process_contone(doc, xref, kind, eff_dpi, s, orig_filter):
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    n = 1 if kind == "gray" else 3
    if pix.n != n:
        return None
    mode = "L" if n == 1 else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    tgt = s["target_dpi_gray"] if kind == "gray" else s["target_dpi_color"]
    resized = False
    action = "re-encoded"
    if eff_dpi > tgt * s["downsample_factor"]:
        sc = tgt / eff_dpi
        nw, nh = max(1, round(img.width * sc)), max(1, round(img.height * sc))
        img = img.resize((nw, nh), Image.LANCZOS)
        resized = True
        action = f"downsampled {eff_dpi:.0f}->{tgt} dpi"
    q, p95 = _gradient_quality(img, s)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=q, optimize=True, subsampling=0 if s["jpeg_chroma_444"] else 2)
    data = buf.getvalue()
    keys = {"Filter": "/DCTDecode", "DecodeParms": "null", "Width": str(img.width),
            "Height": str(img.height), "BitsPerComponent": "8"}
    # sanity check: decode back and compare with what we meant to store
    base = (f"<< /Type /XObject /Subtype /Image /Width {img.width} /Height {img.height} "
            f"/ColorSpace /{'DeviceGray' if n == 1 else 'DeviceRGB'} /BitsPerComponent 8 >>")
    got = _decode_test(base, data, {"Filter": "/DCTDecode"})
    want = np.asarray(img, dtype=np.uint8).reshape(img.height, img.width, n)
    if got.shape != want.shape or float(np.abs(got.astype(np.int16) - want).mean()) > 8:
        return None
    return data, keys, f"{action} -> JPEG q{q} (GED {p95:.0f})", resized


MARK_KEY = "PdfOptimizer"


def _info_xref(doc):
    kind, val = doc.xref_get_key(-1, "Info")
    return int(val.split()[0]) if kind == "xref" else 0


def _is_marked(doc):
    """True if this file is already the output of the optimizer."""
    x = _info_xref(doc)
    return bool(x) and doc.xref_get_key(x, MARK_KEY)[0] != "null"


def _set_mark(doc):
    x = _info_xref(doc)
    if not x:
        x = doc.get_new_xref()
        doc.update_object(x, "<< >>")
        doc.xref_set_key(-1, "Info", f"{x} 0 R")
    doc.xref_set_key(x, MARK_KEY, "(1)")


def _optimize_images(doc, s, jbig2_exe, log, progress=None):
    marked = _is_marked(doc)         # output of an earlier run: never re-encode its JPEGs (lossy)
    plc = _placements(doc)
    stats = {"images": len(plc), "changed": 0, "skipped": 0, "kept": 0, "scan_xrefs": set()}
    for n_done, (xref, info) in enumerate(plc.items()):
        if progress:
            progress(n_done, len(plc), "images")   # may raise OptimizerCancelled
        dpi = info["dpi"]
        try:
            cls = _classify(doc, xref)
            if isinstance(cls, tuple):
                stats["skipped"] += 1
                log.append((xref, "skipped", cls[1]))
                continue
            wt, wv = _key(doc, xref, "Width")
            ht, hv = _key(doc, xref, "Height")
            w, h = int(wv), int(hv)
            if min(w, h) < s["min_side"] or w * h <= s["min_pixels"]:
                stats["skipped"] += 1
                log.append((xref, "skipped", "tiny image"))
                continue
            old = doc.xref_stream_raw(xref) or b""
            ft, fv = _key(doc, xref, "Filter")
            orig_filter = fv if ft != "null" else ""
            if marked and "DCTDecode" in orig_filter:
                stats["kept"] += 1
                log.append((xref, "kept", "JPEG already optimized by an earlier run"))
                continue
            if (s["scan_mode"] != "off" and cls in ("rgb", "gray") and info["cover"] >= s["scan_min_cover"]
                    and dpi >= s["scan_min_dpi"] and _key(doc, xref, "SMask")[0] == "null"
                    and _key(doc, xref, "Mask")[0] == "null"):
                r = _scan_convert(doc, xref, cls, dpi, s, jbig2_exe)
                if r[0] is not None:
                    data, keys, mask_obj, note = r
                    new_total = len(data) + (len(mask_obj[1]) if mask_obj else 0)
                    if new_total < len(old):
                        if mask_obj:
                            mx = doc.get_new_xref()
                            doc.update_object(mx, mask_obj[0])
                            doc.update_stream(mx, mask_obj[1], compress=False)
                            for k, v in mask_obj[2].items():
                                doc.xref_set_key(mx, k, v)
                            keys = dict(keys, Mask=f"{mx} 0 R")
                        doc.update_stream(xref, data, compress=False)
                        for k, v in keys.items():
                            doc.xref_set_key(xref, k, v)
                        stats["changed"] += 1
                        stats["scan_xrefs"].add(xref)
                        log.append((xref, "changed", f"{note}: {human(len(old))} -> {human(new_total)}"))
                        continue
                    log.append((xref, "scan", f"scan result not smaller ({human(new_total)}); normal pass"))
                else:
                    log.append((xref, "scan", f"not converted: {r[1]}; normal pass"))
            if cls == "bitonal":
                r = _process_bitonal(doc, xref, dpi, s, jbig2_exe)
                if r is None:
                    stats["kept"] += 1; log.append((xref, "kept", "no verified encoding")); continue
                data, keys, note = r
                need = len(old)
            else:
                r = _process_contone(doc, xref, cls, dpi, s, orig_filter)
                if r is None:
                    stats["kept"] += 1; log.append((xref, "kept", "re-encode check failed")); continue
                data, keys, note, resized = r
                need = len(old)
                if "DCTDecode" in orig_filter and not resized:
                    need = int(len(old) * (1 - s["jpeg_min_gain"]))
            if len(data) >= need:
                stats["kept"] += 1
                log.append((xref, "kept", f"original smaller ({human(len(old))} vs {human(len(data))})"))
                continue
            doc.update_stream(xref, data, compress=False)   # NB: this drops /Filter...
            for k, v in keys.items():                         # ...so set the keys afterwards
                doc.xref_set_key(xref, k, v)
            stats["changed"] += 1
            log.append((xref, "changed", f"{note}: {human(len(old))} -> {human(len(data))}"))
        except OptimizerCancelled:
            raise
        except Exception as e:
            stats["kept"] += 1
            log.append((xref, "error", repr(e)[:120]))
    return stats


def _pages_match(path_a, path_b, s, max_mae=None, check_text=False, scan_pages=(), progress=None):
    max_mae = s["verify_max_mae"] if max_mae is None else max_mae
    a, b = pymupdf.open(path_a), pymupdf.open(path_b)
    try:
        if a.page_count != b.page_count:
            return False, "page count changed"
        worst = 0.0
        for i in range(a.page_count):
            if progress:
                progress(i, a.page_count, "verify")      # may raise OptimizerCancelled
            pa = a[i].get_pixmap(dpi=s["verify_dpi"], colorspace=pymupdf.csGRAY, annots=True)
            pb = b[i].get_pixmap(dpi=s["verify_dpi"], colorspace=pymupdf.csGRAY, annots=True)
            if (pa.width, pa.height) != (pb.width, pb.height):
                return False, f"page {i+1} size changed"
            x = np.frombuffer(pa.samples, np.uint8).astype(np.int16)
            y = np.frombuffer(pb.samples, np.uint8).astype(np.int16)
            if i in scan_pages:                 # converted scan: paper is now white, compare structure
                c = _corr(x, y)
                if c < s["scan_min_corr"] - 0.05:
                    return False, f"page {i+1} (scan mode) failed legibility check (corr {c:.2f})"
                continue
            mae = float(np.abs(x - y).mean())
            worst = max(worst, mae)
            if check_text and a[i].get_text() != b[i].get_text():
                return False, f"page {i+1} text changed"
            if mae > max_mae:
                return False, f"page {i+1} looks different (diff {mae:.1f})"
        extra = f", {len(scan_pages)} rebuilt as text scans" if scan_pages else ""
        return True, f"all {a.page_count} pages verified (max diff {worst:.2f}{extra})"
    finally:
        a.close(); b.close()


# --------------------------------------------------------------------------- public API
def _save(doc, path):
    kw = dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1)
    if doc.is_encrypted or doc.metadata.get("encryption"):
        kw["encryption"] = pymupdf.PDF_ENCRYPT_KEEP
    try:
        doc.save(path, **kw)
    except TypeError:                           # very old PyMuPDF without use_objstms
        kw.pop("use_objstms", None)
        doc.save(path, **kw)


def optimize_pdf(src, dst, settings=None, jbig2_exe=None, progress=None):
    """Optimize one PDF. Always produces dst (optimized, or a copy of the original).
    Returns a dict describing what happened."""
    s = dict(DEFAULTS, **(settings or {}))
    t0 = time.time()
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if src == dst:
        raise ValueError("Output path must differ from input path")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    size_in = os.path.getsize(src)
    res = dict(file=src, output=dst, size_in=size_in, size_out=size_in, saving_pct=0.0,
               status="", note="", font_note="", ocr_note="", ocr_pages=0, scan_pages=0, images=0, images_changed=0, seconds=0.0, image_log=[])
    tmp_f, tmp = dst + ".fonts_pdfopt", dst + ".tmp_pdfopt"

    def cleanup():
        for p in (tmp_f, tmp):
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass

    def output_in_use(e):
        cleanup()
        res.update(status="failed (output in use)", note=repr(e)[:160], size_out=0, saving_pct=0.0)
        res["seconds"] = round(time.time() - t0, 1)
        return res

    def keep_original(status, note):
        cleanup()
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            return output_in_use(e)
        res.update(status=status, note=note, size_out=size_in, saving_pct=0.0)
        res["seconds"] = round(time.time() - t0, 1)
        return res

    try:
        doc = pymupdf.open(src)
    except Exception as e:
        return keep_original("copied (unreadable)", repr(e)[:120])
    try:
        if doc.needs_pass:
            return keep_original("copied (password protected)", "remove the password first")
        if not doc.is_pdf:
            return keep_original("copied (not a PDF)", "")
        if not (doc.permissions & pymupdf.PDF_PERM_MODIFY):
            return keep_original("copied (protected)", "owner has disallowed changes; file left as it was")
        if doc.is_repaired:
            return keep_original("copied (damaged)", "file needed repair; left as it was")
        if s["skip_signed"] and doc.get_sigflags() > 0:
            return keep_original("copied (digitally signed)", "rewriting would invalidate the signature")

        # ---- stage 1: fonts (strict check: pages must render identically, text unchanged)
        if s["optimize_fonts"]:
            try:
                res["font_note"] = _optimize_fonts(doc, s)
                if res["font_note"] == "no embedded fonts":
                    raise StopIteration                  # nothing changed: skip the save + render check
                _save(doc, tmp_f)
                ok, msg = _pages_match(src, tmp_f, s, max_mae=s["verify_font_max_mae"], check_text=True)
                doc.close()
                if ok:
                    doc = pymupdf.open(tmp_f)
                else:
                    res["font_note"] = f"font pass rejected ({msg}); fonts left as they were"
                    doc = pymupdf.open(src)
            except StopIteration:
                pass
            except Exception as e:
                res["font_note"] = f"font pass skipped ({type(e).__name__})"
                try: doc.close()
                except Exception: pass
                doc = pymupdf.open(src)

        # ---- stage 2: OCR (read the pages before their images are rebuilt)
        ocr_words = {}
        if s["ocr"]:
            td = find_tessdata(s["tessdata"], s["ocr_language"])
            if not td:
                res["ocr_note"] = f"OCR skipped: {s['ocr_language']}.traineddata not found"
            else:
                todo = [p.number for p in doc if _needs_ocr(p)]
                for k, pno in enumerate(todo):
                    if progress:
                        progress(k, len(todo), "ocr")
                    try:
                        ocr_words[pno] = _ocr_words(doc[pno], td, s["ocr_language"], s["ocr_dpi"])
                    except OptimizerCancelled:
                        raise
                    except Exception:
                        pass
                if progress and todo:
                    progress(len(todo), len(todo), "ocr")   # lets Cancel act after the last page
                res["ocr_note"] = (f"{len(todo)} page(s) read" if todo
                                   else "no image-only pages (text already present)")

        # ---- stage 3: images
        stats = _optimize_images(doc, s, jbig2_exe, res["image_log"], progress)
        res["images"], res["images_changed"] = stats["images"], stats["changed"]
        scan_pages = set()
        if stats["scan_xrefs"]:
            for page in doc:
                if any(im[0] in stats["scan_xrefs"] for im in page.get_images(full=True)):
                    scan_pages.add(page.number)
        res["scan_pages"] = len(scan_pages)

        # ---- stage 4: invisible text layer from OCR
        for pno, words in ocr_words.items():
            try:
                if _add_text_layer(doc, doc[pno], words):
                    res["ocr_pages"] += 1
            except Exception:
                pass
        if ocr_words:
            res["ocr_note"] = f"text layer added to {res['ocr_pages']} page(s)"

        # ---- stage 5: housekeeping + save (dedup, object streams)
        if s["remove_thumbnails"]:
            for page in doc:
                if _key(doc, page.xref, "Thumb")[0] != "null":
                    doc.xref_set_key(page.xref, "Thumb", "null")
        if s["remove_xmp"]:
            doc.del_xml_metadata()
        _set_mark(doc)
        _save(doc, tmp)
        doc.close()
    except OptimizerCancelled:
        try: doc.close()
        except Exception: pass
        cleanup()
        raise
    except Exception as e:
        try: doc.close()
        except Exception: pass
        return keep_original("copied (error)", repr(e)[:160])

    size_out = os.path.getsize(tmp)
    if s["verify_pages"]:
        try:
            ok, msg = _pages_match(src, tmp, s, scan_pages=scan_pages, progress=progress)
        except OptimizerCancelled:
            cleanup()
            raise
        except Exception as e:
            ok, msg = False, f"verification error {e!r}"[:160]
        if not ok:
            return keep_original("copied (verification failed)", msg)
        res["note"] = msg
    if size_out > size_in * (1 - s["min_file_gain"]):
        return keep_original("copied (no gain)", f"optimized would be {human(size_out)}")
    try:
        os.replace(tmp, dst)
    except OSError as e:                                # destination open in another program
        return output_in_use(e)
    cleanup()
    res.update(status="optimized", size_out=size_out,
               saving_pct=round(100 * (1 - size_out / size_in), 1),
               seconds=round(time.time() - t0, 1))
    return res
