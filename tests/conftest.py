"""Shared pytest fixtures for ams-extract."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def synthetic_rbm() -> Path:
    """Path to the committed minimal synthetic .rbm fixture."""
    path = FIXTURES_DIR / "synthetic_minimal.rbm"
    assert path.exists(), (
        f"missing synthetic fixture {path}; regenerate with "
        "`uv run python scripts/make_synthetic_fixture.py`"
    )
    return path


@pytest.fixture
def real_rbm() -> Path:
    """Path to the real client .rbm. Test is skipped if ``RBM_TEST_FILE`` is unset."""
    env_path = os.environ.get("RBM_TEST_FILE")
    if not env_path:
        pytest.skip("RBM_TEST_FILE not set; integration test skipped")
    path = Path(env_path)
    if not path.exists():
        pytest.skip(f"RBM_TEST_FILE points to a missing path: {path}")
    return path
