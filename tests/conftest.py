import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def pytest_addoption(parser):
    parser.addoption("--update-baseline", action="store_true",
                     help="rewrite tests/baseline.json from the current engine results")


@pytest.fixture(scope="session")
def samples_dir():
    import make_samples
    return make_samples.main(ROOT / "tests" / "samples")


SETTINGS = dict(scan_mode="auto", ocr=True, use_jbig2=False)   # no JBIG2: same bytes on macOS and Windows


@pytest.fixture(scope="session")
def runs(samples_dir, tmp_path_factory):
    """runs(name) -> result dict of optimize_pdf on that sample (cached for the whole session).
    result["_dst"] is the output path. jbig2_exe=None is what really disables JBIG2."""
    import pdfopt_core as core
    out = tmp_path_factory.mktemp("out")
    cache = {}

    def run(name):
        if name not in cache:
            dst = out / name
            r = core.optimize_pdf(str(samples_dir / name), str(dst), dict(SETTINGS), jbig2_exe=None)
            r["_dst"] = dst
            r["identical_to_input"] = dst.read_bytes() == (samples_dir / name).read_bytes()
            cache[name] = r
        return cache[name]
    return run
