"""Tests for DatasetOpsService — mocks LeRobot imports via sys.modules."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.dataset_ops_service import DatasetOpsService


@pytest.fixture()
def service() -> DatasetOpsService:
    return DatasetOpsService()


@pytest.fixture()
def derived_dir(tmp_path: Path) -> Path:
    d = tmp_path / "derived-datasets"
    d.mkdir()
    return d


@pytest.fixture()
def mock_lerobot():
    """Inject mock lerobot modules into sys.modules so local imports resolve."""
    mock_LeRobotDataset = MagicMock()
    def _fake_split(dataset, splits, output_dir=None):
        """Mock split that creates the expected output_dir/selected/ subdirectory."""
        if output_dir is not None:
            selected_dir = Path(output_dir) / "selected"
            selected_dir.mkdir(parents=True, exist_ok=True)
        mock_ds = MagicMock()
        mock_ds.push_to_hub = MagicMock()
        return {"selected": mock_ds}

    mock_split_dataset = MagicMock(side_effect=_fake_split)
    mock_merged_ds = MagicMock()
    mock_merged_ds.push_to_hub = MagicMock()
    mock_merge_datasets = MagicMock(return_value=mock_merged_ds)

    # Build fake module hierarchy matching lerobot package structure
    mod_lerobot = MagicMock()
    mod_datasets_pkg = MagicMock()
    mod_lerobot_dataset = MagicMock()
    mod_dataset_tools = MagicMock()

    mod_lerobot_dataset.LeRobotDataset = mock_LeRobotDataset
    mod_dataset_tools.split_dataset = mock_split_dataset
    mod_dataset_tools.merge_datasets = mock_merge_datasets

    saved = {}
    modules_to_set = {
        "lerobot": mod_lerobot,
        "lerobot.datasets": mod_datasets_pkg,
        "lerobot.datasets.lerobot_dataset": mod_lerobot_dataset,
        "lerobot.datasets.dataset_tools": mod_dataset_tools,
    }

    for key, val in modules_to_set.items():
        saved[key] = sys.modules.get(key)
        sys.modules[key] = val

    yield {
        "LeRobotDataset": mock_LeRobotDataset,
        "split_dataset": mock_split_dataset,
        "merge_datasets": mock_merge_datasets,
    }

    for key, old_val in saved.items():
        if old_val is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = old_val


# ------------------------------------------------------------------
# Job tracking
# ------------------------------------------------------------------


class TestJobTracking:
    def test_get_job_status_unknown(self, service: DatasetOpsService) -> None:
        assert service.get_job_status("nonexistent") is None

    def test_create_job_fields(self, service: DatasetOpsService) -> None:
        job = service._create_job("split")
        assert job["operation"] == "split"
        assert job["status"] == "queued"
        assert job["completed_at"] is None
        assert job["error"] is None
        assert job["result_path"] is None
        assert service.get_job_status(job["id"]) is job


# ------------------------------------------------------------------
# split_dataset
# ------------------------------------------------------------------


class TestSplitDataset:
    @pytest.mark.asyncio
    async def test_split_returns_job_id(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.split_dataset(
                source_path="/tmp/source-ds",
                episode_ids=[0, 1, 5],
                target_name="my-split",
            )
            assert isinstance(job_id, str)
            assert len(job_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_split_runs_to_complete(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)
            mock_settings.hf_org = "TestOrg"

            job_id = await service.split_dataset(
                source_path="/tmp/source-ds",
                episode_ids=[0, 1, 5],
                target_name="split-test",
            )

            # Wait for the executor to finish
            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "complete"
            assert job["error"] is None
            assert job["result_path"] == "https://huggingface.co/datasets/TestOrg/split-test"

    @pytest.mark.asyncio
    async def test_split_failure_cleans_up(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        mock_lerobot["split_dataset"].side_effect = RuntimeError("split failed")

        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.split_dataset(
                source_path="/tmp/source-ds",
                episode_ids=[0],
                target_name="fail-split",
            )

            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "failed"
            assert "split failed" in job["error"]

            # Temp dir should be cleaned up
            remaining = [p for p in derived_dir.iterdir() if p.name.startswith(".split-")]
            assert len(remaining) == 0


# ------------------------------------------------------------------
# merge_datasets
# ------------------------------------------------------------------


class TestMergeDatasets:
    @pytest.mark.asyncio
    async def test_merge_runs_to_complete(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)
            mock_settings.hf_org = "TestOrg"

            job_id = await service.merge_datasets(
                source_paths=["/tmp/ds-a", "/tmp/ds-b"],
                target_name="merged-test",
            )

            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "complete"
            assert job["result_path"] == "https://huggingface.co/datasets/TestOrg/merged-test"

    @pytest.mark.asyncio
    async def test_merge_failure_cleans_up(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        mock_lerobot["merge_datasets"].side_effect = RuntimeError("merge boom")

        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.merge_datasets(
                source_paths=["/tmp/ds-a"],
                target_name="fail-merge",
            )

            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "failed"
            assert "merge boom" in job["error"]

            remaining = [p for p in derived_dir.iterdir() if p.name.startswith(".merge-")]
            assert len(remaining) == 0


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------


def test_singleton_import() -> None:
    from backend.services.dataset_ops_service import dataset_ops_service

    assert isinstance(dataset_ops_service, DatasetOpsService)
