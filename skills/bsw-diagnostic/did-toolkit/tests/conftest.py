"""pytest configuration for the did-toolkit test suite.

Provides:

* ``--update-goldens`` CLI flag to rewrite every file under
  ``tests/golden/`` from the latest actual output instead of asserting.
* ``assert_golden`` fixture that either regenerates or normalizes-and-diffs.
* ``project_root`` / ``scripts_dir`` / ``fixtures_dir`` / ``golden_dir`` path
  fixtures so every test can stay agnostic of its own location.
* A ``sys.path`` fix-up so ``import generate_implementation`` / ``pipeline``
  / ``generate_fscs`` / ``generate_arxml`` / ``review_fscs`` / ``setup`` work
  without making ``scripts/`` a real package (matches the skill's current
  flat layout).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
FIXTURES_DIR = TESTS_DIR / "fixtures"
GOLDEN_DIR = TESTS_DIR / "golden"

# Expose scripts/ on sys.path for every test. Must come before any helper
# import because several tests do ``from generate_implementation import ...``
# at module scope.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
# Also expose tests/ so ``from helpers.normalize import ...`` works.
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


def _preload_review_fscs() -> None:
    """Import review_fscs with sandboxed stdout/stderr.

    ``scripts/review_fscs.py`` rewraps ``sys.stdout/sys.stderr`` with
    ``io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`` at
    import time (Windows UTF-8 console workaround). Under pytest, that
    wrapper keeps a reference to pytest's capture buffer and closes
    it during GC, which then crashes pytest's global teardown
    (``ValueError: I/O operation on closed file``).

    Pre-import the module here with dummy streams so the wrappers
    target throwaway buffers instead of pytest's capture plumbing.
    After the import we restore the real streams; any later
    ``import review_fscs`` is a no-op thanks to Python's module cache.
    """
    import io

    try:
        saved_out, saved_err = sys.stdout, sys.stderr
        dummy_out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)
        dummy_err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)
        sys.stdout = dummy_out
        sys.stderr = dummy_err
        try:
            import review_fscs  # noqa: F401
        finally:
            sys.stdout = saved_out
            sys.stderr = saved_err
    except Exception:  # pragma: no cover - defensive; import errors surface in tests
        pass


_preload_review_fscs()

from helpers.normalize import normalize_text, unified_diff  # noqa: E402


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help=(
            "Rewrite every golden file in tests/golden/ from the latest "
            "actual output instead of asserting. Use after intentional "
            "generator changes, then eyeball the diff before committing."
        ),
    )


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return GOLDEN_DIR


@pytest.fixture
def update_goldens(request) -> bool:
    return bool(request.config.getoption("--update-goldens"))


@pytest.fixture
def assert_golden(update_goldens):
    """Compare ``actual_path`` against ``golden_path`` with moderate normalization.

    When ``--update-goldens`` is on, the golden is overwritten from the
    actual file (directory created if needed) and no assertion happens.
    Otherwise both sides are normalized (see helpers.normalize) and a
    readable unified diff is attached to the AssertionError on mismatch.
    """

    def _assert(actual_path: Path, golden_path: Path) -> None:
        actual_path = Path(actual_path)
        golden_path = Path(golden_path)
        assert actual_path.is_file(), f"Actual output missing: {actual_path}"
        if update_goldens:
            golden_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(actual_path, golden_path)
            return
        assert golden_path.is_file(), (
            f"Golden file missing: {golden_path}\n"
            f"Run with --update-goldens to create it from {actual_path}."
        )
        expected = normalize_text(golden_path.read_text(encoding="utf-8"))
        actual = normalize_text(actual_path.read_text(encoding="utf-8"))
        if expected != actual:
            raise AssertionError(
                unified_diff(expected, actual, str(golden_path), str(actual_path))
            )

    return _assert
