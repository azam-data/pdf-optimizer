"""PDF Optimizer - desktop GUI (single file + folder mode). Everything runs locally."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "PDF Optimizer"
APP_VERSION = "1.2"

SCAN_CHOICES = [("Auto (recommended)", "auto"), ("Black & white only", "bw"), ("Off", "off")]
GRAIN_CHOICES = [("Off", 0), ("Light", 1), ("Medium", 2), ("Strong", 3)]
MUTED = "#8a8a8a"


# ------------------------------------------------------------------ helpers
def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def settings_path():
    p = os.path.join(app_dir(), "settings.json")             # portable: next to the exe
    try:
        with open(p, "a"):
            pass
        return p
    except OSError:                                           # read-only location -> user profile
        d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PDFOptimizer")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(settings_path(), "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)
    except Exception:
        pass


def windows_uses_dark_theme():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def open_in_explorer(path):
    try:
        if os.name == "nt":
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
    except Exception:
        pass


# ------------------------------------------------------------------ app
class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.cancel_flag = threading.Event()
        self.worker = None
        self.last_output = None
        self.last_report = None
        self.st = load_settings()

        # imported here so the window appears fast; engine import takes a moment
        from pdfopt_core import find_jbig2, find_tessdata
        self.jbig2 = find_jbig2()
        self.tessdata = find_tessdata()

        root.title(APP_NAME)
        root.minsize(680, 600)
        root.geometry(self.st.get("geometry", "760x680"))
        self._build()
        self._load_fields()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._poll)

    # ---------- layout
    def _build(self):
        pad = {"padx": 18}
        outer = ttk.Frame(self.root, padding=(0, 14, 0, 14))
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x", **pad)
        ttk.Label(head, text=APP_NAME, font=("Segoe UI Semibold", 18)).pack(side="left")
        ttk.Label(head, text="   Offline. Nothing leaves this computer.", foreground=MUTED).pack(
            side="left", pady=(9, 0))

        # mode switch
        self.mode = tk.StringVar(value=self.st.get("mode", "single"))
        sw = ttk.Frame(outer)
        sw.pack(fill="x", pady=(14, 8), **pad)
        for text, val in (("Single file", "single"), ("Folder (batch)", "folder")):
            ttk.Radiobutton(sw, text=text, value=val, variable=self.mode, style="Toggle.TButton",
                            command=self._mode_changed, width=16).pack(side="left", padx=(0, 6))

        # paths card
        card = ttk.LabelFrame(outer, text=" Files ", padding=12)
        card.pack(fill="x", pady=(4, 8), **pad)
        card.columnconfigure(1, weight=1)
        self.in_lbl = ttk.Label(card, text="Input PDF")
        self.in_lbl.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        self.in_var = tk.StringVar()
        ttk.Entry(card, textvariable=self.in_var).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(card, text="Browse…", command=self._browse_in).grid(row=0, column=2, padx=(8, 0))
        self.out_lbl = ttk.Label(card, text="Save as")
        self.out_lbl.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        self.out_var = tk.StringVar()
        ttk.Entry(card, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(card, text="Browse…", command=self._browse_out).grid(row=1, column=2, padx=(8, 0))

        # options card
        opt = ttk.LabelFrame(outer, text=" Options ", padding=12)
        opt.pack(fill="x", pady=(0, 8), **pad)
        ttk.Label(opt, text="Scanned pages").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.scan_var = tk.StringVar()
        ttk.Combobox(opt, textvariable=self.scan_var, state="readonly", width=22,
                     values=[c[0] for c in SCAN_CHOICES]).grid(row=0, column=1, sticky="w")
        ttk.Label(opt, text="Grain removal").grid(row=0, column=2, sticky="w", padx=(24, 10))
        self.grain_var = tk.StringVar()
        ttk.Combobox(opt, textvariable=self.grain_var, state="readonly", width=10,
                     values=[c[0] for c in GRAIN_CHOICES]).grid(row=0, column=3, sticky="w")
        self.ocr_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Make scanned pages searchable (OCR, English) — slower",
                        variable=self.ocr_var).grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.skip_var = tk.BooleanVar(value=False)
        self.skip_chk = ttk.Checkbutton(opt, text="Skip files already in the output folder (resume)",
                                        variable=self.skip_var)
        self.skip_chk.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        jb = "JBIG2: built in" if self.jbig2 else "JBIG2: not found (CCITT G4 used instead)"
        oc = "OCR: English built in" if self.tessdata else "OCR: language file not found"
        ttk.Label(opt, text=f"{jb}    ·    {oc}", foreground=MUTED).grid(row=3, column=0, columnspan=4,
                                                                         sticky="w", pady=(8, 0))

        # actions
        act = ttk.Frame(outer)
        act.pack(fill="x", pady=(4, 6), **pad)
        self.run_btn = ttk.Button(act, text="Optimize", style="Accent.TButton", width=16,
                                  command=self._start)
        self.run_btn.pack(side="left")
        self.cancel_btn = ttk.Button(act, text="Cancel", width=10, command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.report_btn = ttk.Button(act, text="Open report", command=self._open_report, state="disabled")
        self.report_btn.pack(side="right")
        self.open_btn = ttk.Button(act, text="Show output", command=self._open_output, state="disabled")
        self.open_btn.pack(side="right", padx=8)

        self.pbar = ttk.Progressbar(outer, mode="determinate", maximum=1000)
        self.pbar.pack(fill="x", pady=(6, 2), **pad)
        self.status = ttk.Label(outer, text="Ready.", foreground=MUTED)
        self.status.pack(fill="x", **pad)

        # log
        lf = ttk.Frame(outer)
        lf.pack(fill="both", expand=True, pady=(8, 0), **pad)
        self.log = tk.Text(lf, height=10, wrap="none", relief="flat", borderwidth=0,
                           font=("Cascadia Mono", 9) if os.name == "nt" else ("DejaVu Sans Mono", 9),
                           padx=10, pady=8, state="disabled")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._style_log()

    def _style_log(self):
        dark = self.root.tk.call("ttk::style", "theme", "use") == "sun-valley-dark"
        bg, fg = ("#1c1c1c", "#e6e6e6") if dark else ("#f7f7f7", "#1f1f1f")
        self.log.configure(background=bg, foreground=fg, insertbackground=fg, selectbackground="#3a6ea5")
        self.log.tag_configure("ok", foreground="#2e9e5b" if not dark else "#5fd38d")
        self.log.tag_configure("warn", foreground="#b7791f" if not dark else "#f0b35a")
        self.log.tag_configure("err", foreground="#c0392b" if not dark else "#ff7b72")
        self.log.tag_configure("dim", foreground="#808080")

    # ---------- fields / settings
    def _load_fields(self):
        st = self.st
        self.scan_var.set(dict((v, k) for k, v in SCAN_CHOICES).get(st.get("scan", "auto"), SCAN_CHOICES[0][0]))
        self.grain_var.set(dict((v, k) for k, v in GRAIN_CHOICES).get(st.get("grain", 2), "Medium"))
        self.skip_var.set(bool(st.get("skip_existing", False)))
        self.ocr_var.set(bool(st.get("ocr", False)))
        self._mode_changed(initial=True)

    def _store(self):
        self.st.update(mode=self.mode.get(),
                       scan=dict(SCAN_CHOICES)[self.scan_var.get()],
                       grain=dict(GRAIN_CHOICES)[self.grain_var.get()],
                       skip_existing=self.skip_var.get(), ocr=self.ocr_var.get(),
                       geometry=self.root.geometry())
        key = "single" if self.mode.get() == "single" else "folder"
        self.st[f"{key}_in"], self.st[f"{key}_out"] = self.in_var.get(), self.out_var.get()
        save_settings(self.st)

    def _mode_changed(self, initial=False):
        if not initial:
            other = "folder" if self.mode.get() == "single" else "single"
            self.st[f"{other}_in"], self.st[f"{other}_out"] = self.in_var.get(), self.out_var.get()
        single = self.mode.get() == "single"
        self.in_lbl.configure(text="Input PDF" if single else "Input folder")
        self.out_lbl.configure(text="Save as" if single else "Output folder")
        key = "single" if single else "folder"
        self.in_var.set(self.st.get(f"{key}_in", ""))
        self.out_var.set(self.st.get(f"{key}_out", ""))
        self.skip_chk.configure(state="disabled" if single else "normal")
        self.report_btn.configure(state="disabled")

    def _browse_in(self):
        if self.mode.get() == "single":
            p = filedialog.askopenfilename(title="Choose a PDF", filetypes=[("PDF files", "*.pdf")],
                                           initialdir=os.path.dirname(self.in_var.get()) or None)
            if p:
                p = os.path.normpath(p)
                self.in_var.set(p)
                self.out_var.set(os.path.splitext(p)[0] + "_optimized.pdf")
        else:
            p = filedialog.askdirectory(title="Choose the input folder", initialdir=self.in_var.get() or None)
            if p:
                p = os.path.normpath(p)
                self.in_var.set(p)
                if not self.out_var.get():
                    self.out_var.set(p.rstrip("\\/") + "_optimized")

    def _browse_out(self):
        if self.mode.get() == "single":
            cur = self.out_var.get()
            p = filedialog.asksaveasfilename(title="Save optimized PDF as", defaultextension=".pdf",
                                             filetypes=[("PDF files", "*.pdf")],
                                             initialdir=os.path.dirname(cur) or None,
                                             initialfile=os.path.basename(cur) or None)
        else:
            p = filedialog.askdirectory(title="Choose the output folder", initialdir=self.out_var.get() or None)
        if p:
            self.out_var.set(os.path.normpath(p))

    # ---------- run
    def _settings(self):
        return {"scan_mode": dict(SCAN_CHOICES)[self.scan_var.get()],
                "scan_despeckle": dict(GRAIN_CHOICES)[self.grain_var.get()],
                "ocr": self.ocr_var.get()}

    def _start(self):
        src, dst = self.in_var.get().strip().strip('"'), self.out_var.get().strip().strip('"')
        single = self.mode.get() == "single"
        if not src or not dst:
            messagebox.showwarning(APP_NAME, "Please choose both the input and the output.")
            return
        if single:
            if not os.path.isfile(src):
                messagebox.showerror(APP_NAME, f"File not found:\n{src}")
                return
            if os.path.abspath(src) == os.path.abspath(dst):
                messagebox.showerror(APP_NAME, "The output file must be different from the input file.")
                return
            if os.path.exists(dst) and not messagebox.askyesno(APP_NAME, f"{os.path.basename(dst)} exists.\nReplace it?"):
                return
        else:
            if not os.path.isdir(src):
                messagebox.showerror(APP_NAME, f"Folder not found:\n{src}")
                return
        self._store()
        self._clear_log()
        self.cancel_flag.clear()
        self.last_output, self.last_report = dst, None
        self._busy(True)
        if single:
            target, args = self._run_single, (src, dst, self._settings())
        else:
            target, args = self._run_folder, (src, dst, self._settings(), self.skip_var.get())
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _run_single(self, src, dst, settings):
        from pdfopt_core import OptimizerCancelled, human, optimize_pdf
        self.q.put(("log", f"Optimizing {os.path.basename(src)}", "dim"))

        def prog(done, total, stage="images"):
            if self.cancel_flag.is_set():
                raise OptimizerCancelled()
            frac = done / total if total else 1.0
            if stage == "ocr":
                self.q.put(("progress", frac * 0.5, f"Reading text (OCR) page {done + 1}/{total}"))
                return
            base, span = (0.5, 0.4) if settings.get("ocr") else (0.0, 0.9)
            txt = f"Processing images {done}/{total}" if done < total else "Checking pages…"
            self.q.put(("progress", base + frac * span, txt))
        try:
            r = optimize_pdf(src, dst, settings, self.jbig2, progress=prog)
        except OptimizerCancelled:
            self.q.put(("done", "Cancelled. Nothing was written.", "warn"))
            return
        except Exception as e:
            self.q.put(("done", f"Error: {e}", "err"))
            return
        tag = "ok" if r["status"] == "optimized" else "warn"
        lines = [f"{r['status']}:  {human(r['size_in'])}  →  {human(r['size_out'])}   (saved {r['saving_pct']}%)",
                 f"Scanned pages rebuilt: {r.get('scan_pages', 0)}    Images re-encoded: {r['images_changed']}/{r['images']}",
                 f"Fonts: {r['font_note'] or '-'}",
                 f"OCR: {r['ocr_note'] or 'off'}",
                 f"Check: {r['note'] or '-'}",
                 f"Time: {r['seconds']} s"]
        if r["size_out"] > 10 * 1024 * 1024:
            lines.append("Note: still above 10 MB")
        for ln in lines:
            self.q.put(("log", ln, tag if ln is lines[0] else None))
        self.q.put(("done", f"Done: {human(r['size_in'])} → {human(r['size_out'])}", tag))

    def _run_folder(self, src, dst, settings, skip_existing):
        from pdfopt_batch import run_folder
        from pdfopt_core import human

        def on_file(k, n, rel, row):
            pct = row["saving_pct"]
            tag = "ok" if row["status"] == "optimized" else ("err" if "error" in row["status"] else "warn")
            self.q.put(("log", f"[{k}/{n}] {rel}", None))
            self.q.put(("log", f"        {human(row['size_in'])} → {human(row['size_out'])}   "
                               f"saved {pct}%   {row['status']}", tag))

        def on_progress(frac, text):
            self.q.put(("progress", frac, text))
        try:
            rows, report, summary, stopped = run_folder(
                src, dst, settings, self.jbig2, skip_existing=skip_existing,
                on_file=on_file, on_progress=on_progress, cancelled=self.cancel_flag.is_set)
        except Exception as e:
            self.q.put(("done", f"Error: {e}", "err"))
            return
        self.last_report = report
        self.q.put(("log", "", None))
        for ln in summary.splitlines():
            self.q.put(("log", ln, "warn" if stopped else None))
        if report:
            self.q.put(("log", f"Report: {report}", "dim"))
        self.q.put(("done", "Cancelled." if stopped else "Folder finished.", "warn" if stopped else "ok"))

    # ---------- UI updates from the worker
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append(msg[1], msg[2])
                elif kind == "progress":
                    self.pbar["value"] = max(0, min(1000, int(msg[1] * 1000)))
                    self.status.configure(text=msg[2])
                elif kind == "done":
                    self.pbar["value"] = 1000
                    self.status.configure(text=msg[1])
                    self._busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _append(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", (tag,) if tag else ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.pbar["value"] = 0

    def _busy(self, busy):
        self.run_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        self.open_btn.configure(state="disabled" if busy or not self.last_output else "normal")
        self.report_btn.configure(state="normal" if (not busy and self.last_report) else "disabled")
        if busy:
            self.status.configure(text="Working…")

    def _cancel(self):
        self.cancel_flag.set()
        self.status.configure(text="Cancelling after the current step…")
        self.cancel_btn.configure(state="disabled")

    def _open_output(self):
        if self.last_output:
            open_in_explorer(self.last_output if os.path.exists(self.last_output) else os.path.dirname(self.last_output))

    def _open_report(self):
        if self.last_report and os.path.exists(self.last_report):
            try:
                os.startfile(self.last_report)
            except Exception:
                open_in_explorer(self.last_report)

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Optimization is still running. Stop and close?"):
                return
            self.cancel_flag.set()
        self._store()
        self.root.destroy()


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)              # crisp text on high-DPI screens
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFOptimizer.App")
        except Exception:
            pass
    root = tk.Tk()
    try:
        root.iconbitmap(default=resource("assets", "icon.ico"))
    except Exception:
        pass
    try:
        import sv_ttk
        sv_ttk.set_theme("dark" if windows_uses_dark_theme() else "light")
    except Exception:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
