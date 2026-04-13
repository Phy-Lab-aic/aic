"""Service for reading and writing episode metadata in LeRobot v3.0 parquet files.

Episode base data is read from parquet files (read-only).
Grade/tags annotations are stored in a local JSON sidecar file so that
read-only dataset mounts (e.g. HuggingFace FUSE) are fully supported.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from backend.config import settings
from backend.models.schemas import Episode
from backend.services.dataset_service import dataset_service

logger = logging.getLogger(__name__)


class EpisodeNotFoundError(Exception):
    """Raised when an episode_index cannot be located in any parquet file."""


def _get_annotations_path() -> Path:
    """Return the directory for storing annotation sidecar files."""
    if settings.annotations_path:
        p = Path(settings.annotations_path)
    else:
        p = Path.home() / ".local" / "share" / "curation-tools" / "annotations"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sidecar_file(dataset_path: Path) -> Path:
    """Return the sidecar JSON path for a given dataset."""
    # C4: Use hash of full path to avoid filename collisions between datasets
    # with the same directory name but different parents.
    path_hash = hashlib.sha256(str(dataset_path.resolve()).encode()).hexdigest()[:16]
    name = f"{dataset_path.name}_{path_hash}.json"
    return _get_annotations_path() / name


def _load_sidecar(dataset_path: Path) -> dict[str, Any]:
    """Load the sidecar JSON. Returns {episode_index_str: {grade, tags}}."""
    path = _sidecar_file(dataset_path)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt sidecar file %s, starting fresh", path)
    return {}


def _save_sidecar(dataset_path: Path, data: dict[str, Any]) -> None:
    """Atomically write the sidecar JSON."""
    path = _sidecar_file(dataset_path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


class EpisodeService:
    """Reads episode base data from parquet, merges annotations from sidecar JSON."""

    async def get_episodes(self) -> list[dict[str, Any]]:
        if dataset_service.episodes_cache is not None:
            return list(dataset_service.episodes_cache.values())

        episodes: dict[int, dict[str, Any]] = {}
        tasks_map = await dataset_service.get_tasks_map()
        sidecar = await asyncio.to_thread(_load_sidecar, dataset_service.dataset_path)

        for file_path in dataset_service.iter_episode_parquet_files():
            table = await asyncio.to_thread(pq.read_table, file_path)
            for row in _iter_rows(table):
                ep = _row_to_episode(row, tasks_map)
                # Merge sidecar annotations
                ann = sidecar.get(str(ep["episode_index"]))
                if ann:
                    ep["grade"] = ann.get("grade")
                    ep["tags"] = ann.get("tags", [])
                episodes[ep["episode_index"]] = ep

        dataset_service.episodes_cache = episodes
        return list(episodes.values())

    async def get_episode(self, episode_index: int) -> dict[str, Any]:
        if dataset_service.episodes_cache is not None:
            try:
                return dataset_service.episodes_cache[episode_index]
            except KeyError:
                raise EpisodeNotFoundError(
                    f"Episode {episode_index} not found in cache."
                )

        tasks_map = await dataset_service.get_tasks_map()
        file_path = dataset_service.get_file_for_episode(episode_index)
        if file_path is None:
            raise EpisodeNotFoundError(
                f"Episode {episode_index} not found in any parquet file."
            )

        table = await asyncio.to_thread(pq.read_table, file_path)
        sidecar = await asyncio.to_thread(_load_sidecar, dataset_service.dataset_path)

        for row in _iter_rows(table):
            if row.get("episode_index") == episode_index:
                ep = _row_to_episode(row, tasks_map)
                ann = sidecar.get(str(episode_index))
                if ann:
                    ep["grade"] = ann.get("grade")
                    ep["tags"] = ann.get("tags", [])
                return ep

        raise EpisodeNotFoundError(
            f"Episode {episode_index} not found in {file_path}."
        )

    async def update_episode(
        self,
        episode_index: int,
        grade: str | None,
        tags: list[str],
    ) -> dict[str, Any]:
        """Persist grade and tags to the sidecar JSON file (not parquet)."""
        # Verify episode exists
        if dataset_service.episodes_cache is not None:
            if episode_index not in dataset_service.episodes_cache:
                raise EpisodeNotFoundError(
                    f"Episode {episode_index} not found."
                )
        else:
            file_path = dataset_service.get_file_for_episode(episode_index)
            if file_path is None:
                raise EpisodeNotFoundError(
                    f"Episode {episode_index} not found."
                )

        # C2: Use file lock to prevent race condition on concurrent PATCH requests
        lock = dataset_service.get_file_lock(_sidecar_file(dataset_service.dataset_path))
        async with lock:
            sidecar = await asyncio.to_thread(_load_sidecar, dataset_service.dataset_path)
            sidecar[str(episode_index)] = {"grade": grade, "tags": tags}
            await asyncio.to_thread(_save_sidecar, dataset_service.dataset_path, sidecar)

        # Update cache
        if dataset_service.episodes_cache is not None:
            ep = dataset_service.episodes_cache.get(episode_index)
            if ep:
                ep["grade"] = grade
                ep["tags"] = tags
                return ep

        # Fallback: re-read the episode
        return await self.get_episode(episode_index)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_rows(table: pa.Table):
    """Yield each row of *table* as a plain Python dict."""
    col_names = table.schema.names
    for batch in table.to_batches():
        col_arrays = {name: batch.column(name).to_pylist() for name in col_names}
        n = batch.num_rows
        for i in range(n):
            yield {name: col_arrays[name][i] for name in col_names}


def _row_to_episode(
    row: dict[str, Any],
    tasks_map: dict[int, str],
) -> dict[str, Any]:
    """Convert a raw parquet row dict into an Episode-compatible dict."""
    task_index: int = row.get("task_index", 0)
    task_instruction: str = tasks_map.get(task_index, "")

    raw_tags = row.get("tags")
    tags: list[str] = raw_tags if isinstance(raw_tags, list) else []

    return Episode(
        episode_index=row["episode_index"],
        length=int(row.get("dataset_to_index", 0)) - int(row.get("dataset_from_index", 0)),
        task_index=task_index,
        task_instruction=task_instruction,
        chunk_index=int(row.get("data/chunk_index", 0)),
        file_index=int(row.get("data/file_index", 0)),
        dataset_from_index=int(row.get("dataset_from_index", 0)),
        dataset_to_index=int(row.get("dataset_to_index", 0)),
        grade=row.get("grade"),
        tags=tags,
    ).model_dump()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

episode_service = EpisodeService()
