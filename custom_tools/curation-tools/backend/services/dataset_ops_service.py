"""Service for dataset split and merge operations using LeRobot dataset_tools.

Wraps LeRobot's split_dataset and merge_datasets with async job tracking
and provenance metadata. All blocking LeRobot operations run in a thread
executor to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _set_writable_cache() -> None:
    """Redirect HF datasets cache to a writable location."""
    cache_dir = Path(tempfile.gettempdir()) / "hf-datasets-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_DATASETS_CACHE"] = str(cache_dir)
    os.environ["HF_HOME"] = str(cache_dir / "hub")


def _make_writable_mirror(source: Path) -> Path:
    """Create a writable mirror of a read-only dataset using symlinks.

    The datasets library creates .cache dirs next to parquet files.
    FUSE mounts are read-only so this fails. We create a temp directory
    that mirrors the structure with symlinks to actual files, allowing
    .cache creation while reading the original data.

    Returns path to the writable mirror. Caller must clean up with shutil.rmtree().
    """
    mirror = Path(tempfile.mkdtemp(prefix="ds-mirror-"))
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = mirror / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(item)
    return mirror

logger = logging.getLogger(__name__)


class DatasetOpsService:
    """Manages dataset split/merge operations with async job tracking."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Job tracking
    # ------------------------------------------------------------------

    def _create_job(self, operation: str) -> dict[str, Any]:
        job: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "operation": operation,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error": None,
            "result_path": None,
        }
        self._jobs[job["id"]] = job
        return job

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def split_dataset(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_name: str,
    ) -> str:
        """Queue a split job. Returns the job ID."""
        job = self._create_job("split")
        job_id = job["id"]

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_split,
            job_id,
            Path(source_path),
            episode_ids,
            target_name,
        )
        return job_id

    async def split_and_merge(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_path: str | Path,
        target_name: str,
    ) -> str:
        """Queue a split-into-existing job. Returns the job ID."""
        job = self._create_job("split_and_merge")
        job_id = job["id"]

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_split_and_merge,
            job_id,
            Path(source_path),
            episode_ids,
            Path(target_path),
            target_name,
        )
        return job_id

    async def merge_datasets(
        self,
        source_paths: list[str | Path],
        target_name: str,
    ) -> str:
        """Queue a merge job. Returns the job ID."""
        job = self._create_job("merge")
        job_id = job["id"]

        resolved = [(Path(p)) for p in source_paths]
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_merge,
            job_id,
            resolved,
            target_name,
        )
        return job_id

    # ------------------------------------------------------------------
    # Blocking workers (run in thread executor)
    # ------------------------------------------------------------------

    def _run_split(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        target_name: str,
    ) -> None:
        from backend.config import settings

        job = self._jobs[job_id]
        job["status"] = "running"
        temp_dir: Path | None = None

        try:
            _set_writable_cache()
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import split_dataset

            derived_root = Path(settings.derived_dataset_path).expanduser()
            derived_root.mkdir(parents=True, exist_ok=True)

            temp_dir = Path(tempfile.mkdtemp(dir=derived_root, prefix="split-"))

            # Build HF repo_id: {org}/{target_name}
            repo_id = f"{settings.hf_org}/{target_name}"

            source_repo_id = f"{settings.hf_org}/{source_path.name}"
            mirror = _make_writable_mirror(source_path)
            try:
                dataset = LeRobotDataset(repo_id=source_repo_id, root=mirror)
                result = split_dataset(dataset, splits={"selected": episode_ids}, output_dir=temp_dir)
                split_ds = result["selected"]

                # Push to HF Hub — sync service will auto-detect and mount
                split_ds.repo_id = repo_id
                split_ds.push_to_hub(private=False)
                logger.info("Pushed split result to HF Hub: %s", repo_id)
            finally:
                shutil.rmtree(mirror, ignore_errors=True)

            # Clean up temp dir
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir = None

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = f"https://huggingface.co/datasets/{repo_id}"
            logger.info("Split job %s complete: %s", job_id, repo_id)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split job %s failed", job_id)
            if temp_dir is not None and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_merge(
        self,
        job_id: str,
        source_paths: list[Path],
        target_name: str,
    ) -> None:
        from backend.config import settings

        job = self._jobs[job_id]
        job["status"] = "running"
        temp_dir: Path | None = None

        try:
            _set_writable_cache()
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import merge_datasets

            derived_root = Path(settings.derived_dataset_path).expanduser()
            derived_root.mkdir(parents=True, exist_ok=True)

            repo_id = f"{settings.hf_org}/{target_name}"

            temp_dir = Path(tempfile.mkdtemp(dir=derived_root, prefix="merge-"))

            mirrors = []
            try:
                ds_list = []
                for p in source_paths:
                    m = _make_writable_mirror(p)
                    mirrors.append(m)
                    ds_list.append(LeRobotDataset(repo_id=f"{settings.hf_org}/{p.name}", root=m))

                merged_ds = merge_datasets(ds_list, output_repo_id=repo_id, output_dir=temp_dir)

                # Push to HF Hub
                merged_ds.push_to_hub(private=False)
                logger.info("Pushed merged result to HF Hub: %s", repo_id)
            finally:
                for m in mirrors:
                    shutil.rmtree(m, ignore_errors=True)

            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir = None

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = f"https://huggingface.co/datasets/{repo_id}"
            logger.info("Merge job %s complete: %s", job_id, repo_id)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Merge job %s failed", job_id)
            if temp_dir is not None and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_split_and_merge(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        target_path: Path,
        target_name: str,
    ) -> None:
        from backend.config import settings

        job = self._jobs[job_id]
        job["status"] = "running"
        split_tmp: Path | None = None
        merge_tmp: Path | None = None

        try:
            _set_writable_cache()
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import split_dataset, merge_datasets

            derived_root = Path(settings.derived_dataset_path).expanduser()
            derived_root.mkdir(parents=True, exist_ok=True)

            # target_name should be the HF repo_id of the existing target (e.g. Phy-lab/changyong)
            repo_id = target_name

            # Step 1: Mirror read-only sources
            source_mirror = _make_writable_mirror(source_path)
            target_mirror = _make_writable_mirror(target_path)
            try:
                # Step 2: Split selected episodes
                split_tmp = Path(tempfile.mkdtemp(dir=derived_root, prefix="split-tmp-"))
                source_ds = LeRobotDataset(repo_id=f"{settings.hf_org}/{source_path.name}", root=source_mirror)
                split_result = split_dataset(source_ds, splits={"selected": episode_ids}, output_dir=split_tmp)
                split_ds = split_result["selected"]

                # Step 3: Merge split result with existing target
                merge_tmp = Path(tempfile.mkdtemp(dir=derived_root, prefix="merge-tmp-"))
                target_ds = LeRobotDataset(repo_id=f"{settings.hf_org}/{target_path.name}", root=target_mirror)
                merged_ds = merge_datasets([target_ds, split_ds], output_repo_id=repo_id, output_dir=merge_tmp)

                # Step 4: Push merged result to HF Hub
                merged_ds.push_to_hub(private=False)
                logger.info("Pushed split-and-merge result to HF Hub: %s", repo_id)
            finally:
                shutil.rmtree(source_mirror, ignore_errors=True)
                shutil.rmtree(target_mirror, ignore_errors=True)

            # Clean up temp dirs
            if split_tmp is not None and split_tmp.exists():
                shutil.rmtree(split_tmp, ignore_errors=True)
            shutil.rmtree(merge_tmp, ignore_errors=True)
            merge_tmp = None

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = f"https://huggingface.co/datasets/{repo_id}"
            logger.info("Split-and-merge job %s complete: %s", job_id, repo_id)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split-and-merge job %s failed", job_id)
            if split_tmp is not None and split_tmp.exists():
                shutil.rmtree(split_tmp, ignore_errors=True)
            if merge_tmp is not None and merge_tmp.exists():
                shutil.rmtree(merge_tmp, ignore_errors=True)


dataset_ops_service = DatasetOpsService()
