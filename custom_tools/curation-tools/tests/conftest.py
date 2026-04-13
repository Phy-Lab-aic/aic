"""Shared fixtures for curation-tools tests using real dataset data."""

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

REAL_DATASET_ROOT = Path("/tmp/hf-mounts/Phy-lab/dataset")
BASIC_AIC = REAL_DATASET_ROOT / "basic_aic_cheetcode_dataset"
HOJUN = REAL_DATASET_ROOT / "hojun"


def _copy_dataset(src: Path) -> Path:
    """Copy a dataset to a temp directory so write tests don't mutate originals."""
    tmp = Path(tempfile.mkdtemp(prefix="curation_test_"))
    dest = tmp / src.name
    shutil.copytree(src, dest)
    # Ensure all files and dirs are writable (source may be read-only mount)
    import os, stat
    for root, dirs, files in os.walk(dest):
        for d in dirs:
            os.chmod(os.path.join(root, d), stat.S_IRWXU)
        for f in files:
            os.chmod(os.path.join(root, f), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
    return dest


@pytest.fixture
def basic_aic_path():
    return BASIC_AIC


@pytest.fixture
def hojun_path():
    return HOJUN


@pytest.fixture
def writable_basic_aic():
    """Writable copy of basic_aic dataset for mutation tests."""
    dest = _copy_dataset(BASIC_AIC)
    from backend.config import settings
    original = settings.allowed_dataset_roots
    settings.allowed_dataset_roots = original + ["/tmp"]
    yield dest
    settings.allowed_dataset_roots = original
    shutil.rmtree(dest.parent, ignore_errors=True)


@pytest.fixture
def writable_hojun():
    """Writable copy of hojun dataset for mutation tests."""
    dest = _copy_dataset(HOJUN)
    from backend.config import settings
    original = settings.allowed_dataset_roots
    settings.allowed_dataset_roots = original + ["/tmp"]
    yield dest
    settings.allowed_dataset_roots = original
    shutil.rmtree(dest.parent, ignore_errors=True)


@pytest.fixture
def fresh_dataset_service():
    """Return a fresh DatasetService instance (not the module-level singleton)."""
    from backend.services.dataset_service import DatasetService
    return DatasetService()


@pytest.fixture
def fresh_episode_service():
    """Return a fresh EpisodeService instance."""
    from backend.services.episode_service import EpisodeService
    return EpisodeService()
