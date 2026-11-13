"""Regenerate the engine cell of the notebooks from pdfopt_core.py.

Only the engine code cell is replaced (the cell whose source contains ENGINE_MARK).
Every other cell, including the batch-logic cell of the Batch notebook, is left alone.

    python tools/build_notebooks.py           # rewrite notebooks
    python tools/build_notebooks.py --check   # exit 1 if they are out of date
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "pdfopt_core.py"
NOTEBOOKS = [ROOT / "notebooks" / "PDF_Optimizer_Single.ipynb",
             ROOT / "notebooks" / "PDF_Optimizer_Batch.ipynb"]
ENGINE_MARK = "# PDF OPTIMIZER ENGINE"


def core_source():
    text = CORE.read_text(encoding="utf-8").rstrip("\n")
    return text.splitlines(keepends=True)


def engine_cell(nb):
    cells = [c for c in nb["cells"]
             if c["cell_type"] == "code" and ENGINE_MARK in "".join(c["source"][:3])]
    if len(cells) != 1:
        raise RuntimeError(f"expected exactly one engine cell, found {len(cells)}")
    return cells[0]


def render(path):
    """Return the notebook text with the engine cell replaced."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    engine_cell(nb)["source"] = core_source()
    return json.dumps(nb, indent=1, ensure_ascii=False) + "\n"


def stale():
    return [p for p in NOTEBOOKS if render(p) != p.read_text(encoding="utf-8")]


def main(argv):
    if "--check" in argv:
        bad = stale()
        for p in bad:
            print("out of date:", p.name)
        return 1 if bad else 0
    for p in NOTEBOOKS:
        p.write_text(render(p), encoding="utf-8", newline="\n")
        print("wrote", p.name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
