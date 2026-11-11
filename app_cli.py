"""pdfopt-cli: command-line front end (also what microPDF can call).

  pdfopt-cli input.pdf [output.pdf]            single file (default output: <name>_optimized.pdf)
  pdfopt-cli INPUT_FOLDER OUTPUT_FOLDER         folder mode (mirror + report)
  options: --scan auto|bw|off   --grain 0-3   --ocr   --skip-existing
Exit code: 0 = done (optimized or original kept), 1 = error, 2 = bad arguments.
"""
import argparse
import os
import sys

from pdfopt_core import find_jbig2, human, optimize_pdf


def main(argv=None):
    p = argparse.ArgumentParser(prog="pdfopt-cli", description="Offline PDF optimizer")
    p.add_argument("input", help="PDF file or folder")
    p.add_argument("output", nargs="?", help="output PDF (single) or output folder (folder mode)")
    p.add_argument("--scan", choices=["auto", "bw", "off"], default="auto", help="scanned-page mode (default auto)")
    p.add_argument("--grain", type=int, choices=[0, 1, 2, 3], default=2, help="grain removal 0-3 (default 2)")
    p.add_argument("--ocr", action="store_true", help="add a searchable English text layer to scanned pages")
    p.add_argument("--skip-existing", action="store_true", help="folder mode: skip files already in output")
    a = p.parse_args(argv)
    settings = {"scan_mode": a.scan, "scan_despeckle": a.grain, "ocr": a.ocr}
    jb = find_jbig2()

    if os.path.isdir(a.input):
        if not a.output:
            p.error("folder mode needs an OUTPUT_FOLDER")
        from pdfopt_batch import run_folder

        def on_file(k, n, rel, row):
            print(f"[{k}/{n}] {rel}\n        {human(row['size_in'])} -> {human(row['size_out'])}"
                  f"  saved {row['saving_pct']}%  {row['status']}", flush=True)
        try:
            _, report, summary, _ = run_folder(a.input, a.output, settings, jb,
                                               skip_existing=a.skip_existing, on_file=on_file)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print("\n" + summary + (f"\nReport: {report}" if report else ""))
        return 0

    if not os.path.isfile(a.input):
        print(f"ERROR: not found: {a.input}", file=sys.stderr)
        return 2
    out = a.output or os.path.splitext(a.input)[0] + "_optimized.pdf"
    try:
        r = optimize_pdf(a.input, out, settings, jb)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"{r['status']}: {human(r['size_in'])} -> {human(r['size_out'])} (saved {r['saving_pct']}%)")
    print(f"scanned pages rebuilt: {r.get('scan_pages', 0)} | {r['note']}")
    if a.ocr:
        print(f"OCR: {r.get('ocr_note') or '-'}")
    print(f"output: {r['output']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
