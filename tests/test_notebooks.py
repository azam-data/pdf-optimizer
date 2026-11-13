import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import build_notebooks  # noqa: E402


def test_notebooks_match_engine():
    """Notebooks must be regenerated (python tools/build_notebooks.py) after editing pdfopt_core.py."""
    bad = [p.name for p in build_notebooks.stale()]
    assert not bad, f"out of date: {bad}; run python tools/build_notebooks.py"
