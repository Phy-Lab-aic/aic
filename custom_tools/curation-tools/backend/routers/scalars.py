"""Endpoint to return per-frame scalar data (observations, actions) for charts."""

import asyncio
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException

from backend.services.dataset_service import dataset_service

router = APIRouter(prefix="/api/scalars", tags=["scalars"])


@router.get("/{episode_index}")
async def get_scalars(episode_index: int):
    """Return observation and action scalar arrays for an episode."""
    try:
        loc = dataset_service.get_episode_file_location(episode_index)
    except (KeyError, RuntimeError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    dataset_path = Path(dataset_service.get_dataset_path())
    features = dataset_service.get_features()

    from_idx = loc["dataset_from_index"]
    to_idx = loc["dataset_to_index"]
    chunk_idx = loc["data_chunk_index"]
    file_idx = loc["data_file_index"]

    data_path = dataset_path / f"data/chunk-{chunk_idx:03d}/file-{file_idx:03d}.parquet"
    if not data_path.exists():
        raise HTTPException(status_code=404, detail=f"Data file not found: {data_path}")

    # Read only the schema to discover available columns without loading data
    schema = await asyncio.to_thread(pq.read_schema, data_path)
    all_columns = set(schema.names)

    # Classify columns using features metadata (before reading any data)
    state_columns: list[str] = []
    action_columns: list[str] = []

    for col, feature in features.items():
        dtype = feature.get("dtype", "")
        if dtype in ("image", "video"):
            continue
        if col.startswith("observation.") and col in all_columns:
            state_columns.append(col)
        elif col.startswith("action") and col in all_columns:
            action_columns.append(col)

    needed_columns = state_columns + action_columns
    if not needed_columns:
        return {
            "episode_index": episode_index,
            "num_frames": to_idx - from_idx,
            "observations": {},
            "actions": {},
        }

    # Read only the scalar columns we need, then slice to the episode's frame range
    table = await asyncio.to_thread(pq.read_table, data_path, columns=needed_columns)
    table = table.slice(from_idx, to_idx - from_idx)
    df = table.to_pydict()

    def extract_series(columns: list[str]) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {}
        for col in columns:
            values = df.get(col, [])
            series: list[float] = []
            for v in values:
                arr = np.asarray(v, dtype=float).ravel()
                if arr.size == 1:
                    series.append(float(arr[0]))
                elif arr.size > 1:
                    # Multi-dim: split into separate series per dimension
                    for dim in range(arr.size):
                        dim_key = f"{col}[{dim}]"
                        if dim_key not in result:
                            result[dim_key] = []
                        result[dim_key].append(float(arr[dim]))
                    continue
            if series:
                result[col] = series
        return result

    observations = extract_series(state_columns)
    actions = extract_series(action_columns)

    return {
        "episode_index": episode_index,
        "num_frames": to_idx - from_idx,
        "observations": observations,
        "actions": actions,
    }
