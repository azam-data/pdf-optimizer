"""Folder (batch) mode: mirror an input folder into an output folder.
Every PDF is optimized under the same name; every other file is copied unchanged.
A CSV report is written next to (not inside) the output folder."""
import csv
import datetime
import os
import shutil
import time
from collections import Counter

from pdfopt_core import OptimizerCancelled, human, optimize_pdf

FIELDS = ["file", "type", "status", "size_in", "size_out", "saving_pct", "scan_pages", "ocr_pages",
          "images", "images_changed", "seconds", "fonts", "note", "over_email_limit"]


def _row(rel, typ, status, size_in, size_out, **kw):
    r = dict.fromkeys(FIELDS, "")
    r.update(file=rel, type=typ, status=status, size_in=size_in, size_out=size_out, **kw)
    return r


def _is_within(path, parent):
    """True if path is parent or inside it. Case-insensitive on Windows (normcase), follows
    symlinks (realpath), and also asks the file system (samefile) for case-insensitive volumes."""
    p, q = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(parent))
    try:
        if os.path.commonpath([p, q]) == q:
            return True
    except ValueError:        # different drives
        return False
    cur = os.path.realpath(path)
    while True:
        try:
            if os.path.exists(cur) and os.path.samefile(cur, parent):
                return True
        except OSError:
            pass
        up = os.path.dirname(cur)
        if up == cur:
            return False
        cur = up


def plan_folder(input_folder, output_folder):
    """Validate the folders, create the mirrored folder tree, return the list of (src, dst) jobs."""
    inp, out = os.path.abspath(input_folder), os.path.abspath(output_folder)
    if not os.path.isdir(inp):
        raise FileNotFoundError(f"Input folder not found:\n{inp}")
    if _is_within(out, inp):
        raise ValueError("The output folder must not be the input folder or inside it.")
    if _is_within(inp, out):
        raise ValueError("The input folder must not be inside the output folder.")
    jobs = []
    for dirpath, dirnames, filenames in os.walk(inp):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, inp)
        os.makedirs(os.path.join(out, rel_dir), exist_ok=True)
        for name in sorted(filenames):
            jobs.append((os.path.join(dirpath, name), os.path.normpath(os.path.join(out, rel_dir, name))))
    return inp, out, jobs


def _remove_stale_temp(folder):
    """Delete *.tmp_pdfopt / *.fonts_pdfopt left behind by a crashed or closed run."""
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.endswith((".tmp_pdfopt", ".fonts_pdfopt")):
                try: os.remove(os.path.join(root, f))
                except OSError: pass


def run_folder(input_folder, output_folder, settings=None, jbig2_exe=None, skip_existing=False,
               email_limit_mb=10, on_file=None, on_progress=None, cancelled=None):
    """on_file(index, n_pdf, rel_path, row) is called after every PDF.
    on_progress(fraction 0-1, text) is called while working.
    cancelled() -> bool is polled; when it returns True the run stops cleanly.
    Returns (rows, report_path, summary_text, was_cancelled)."""
    inp, out, jobs = plan_folder(input_folder, output_folder)
    _remove_stale_temp(out)
    pdf_jobs =[j for j in jobs if j[0].lower().endswith(".pdf")]
    n_pdf = len(pdf_jobs)
    rows, k, t0, stopped = [], 0, time.time(), False

    for src, dst in jobs:
        if cancelled and cancelled():
            stopped = True
            break
        rel = os.path.relpath(src, inp)
        is_pdf = src.lower().endswith(".pdf")
        if skip_existing and os.path.exists(dst) and os.path.getsize(dst) > 0:
            rows.append(_row(rel, "pdf" if is_pdf else "other", "skipped (already in output)",
                             os.path.getsize(src), os.path.getsize(dst)))
            if is_pdf:
                k += 1
            continue
        if not is_pdf:
            try:
                shutil.copy2(src, dst)
                st = "copied (non-PDF)"
            except Exception as e:
                st = f"copy failed: {e}"[:120]
            sz = os.path.getsize(src)
            rows.append(_row(rel, "other", st, sz, sz))
            continue

        k += 1
        def prog(done, total, stage="images", _k=k, _rel=rel):
            if cancelled and cancelled():
                raise OptimizerCancelled()
            if on_progress:
                frac = ((_k - 1) + (done / total if total else 1)) / max(1, n_pdf)
                what = {"ocr": "reading text (OCR)", "verify": "checking pages"}.get(stage, "images")
                on_progress(frac, f"{_k}/{n_pdf}  {_rel}  -  {what} {done}/{total}")
        if on_progress:
            on_progress((k - 1) / max(1, n_pdf), f"{k}/{n_pdf}  {rel}")
        try:
            r = optimize_pdf(src, dst, settings, jbig2_exe, progress=prog)
        except OptimizerCancelled:
            stopped = True
            break
        except Exception as e:                          # last-resort safety: keep the mirror complete
            sz = os.path.getsize(src)
            try:
                shutil.copy2(src, dst)
                r = dict(status="copied (error)", size_in=sz, size_out=sz, saving_pct=0.0, note=str(e)[:160])
            except OSError as e2:
                r = dict(status="failed (output in use)", size_in=sz, size_out=0, saving_pct=0.0,
                         note=str(e2)[:160])
        row = _row(rel, "pdf", r["status"], r["size_in"], r["size_out"],
                   saving_pct=r.get("saving_pct", ""), scan_pages=r.get("scan_pages", ""),
                   ocr_pages=r.get("ocr_pages", ""),
                   images=r.get("images", ""), images_changed=r.get("images_changed", ""),
                   seconds=r.get("seconds", ""), fonts=r.get("font_note", ""), note=r.get("note", ""))
        rows.append(row)
        if on_file:
            on_file(k, n_pdf, rel, row)

    limit = email_limit_mb * 1024 * 1024
    for row in rows:
        row["over_email_limit"] = "YES" if row["type"] == "pdf" and row["size_out"] > limit else ""

    report = None
    if rows:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report = os.path.join(os.path.dirname(out), f"{os.path.basename(out)}_report_{stamp}.csv")
        try:
            with open(report, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
        except OSError:
            report = None

    pdf_rows = [r for r in rows if r["type"] == "pdf"]
    tin = sum(r["size_in"] for r in pdf_rows)
    tout = sum(r["size_out"] for r in pdf_rows)
    lines = [f"PDFs: {len(pdf_rows)}   {human(tin)} -> {human(tout)}   "
             f"saved {100 * (1 - tout / tin) if tin else 0:.1f}%"]
    for st, c in Counter(r["status"] for r in rows).most_common():
        lines.append(f"  {c:4d}  {st}")
    big = [r["file"] for r in pdf_rows if r["over_email_limit"]]
    if big:
        lines.append(f"Still over {email_limit_mb} MB: {len(big)} file(s)")
        lines += [f"  {f}" for f in big[:20]]
    lines.append(f"Time: {time.time() - t0:.0f} s")
    if stopped:
        lines.insert(0, "CANCELLED - files not reached were not written.")
    return rows, report, "\n".join(lines), stopped
