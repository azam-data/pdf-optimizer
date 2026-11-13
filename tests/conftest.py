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
