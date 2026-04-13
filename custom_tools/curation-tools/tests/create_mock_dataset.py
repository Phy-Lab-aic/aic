"""Script to create the mock LeRobot v3.0 dataset parquet files."""

import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).parent / "mock_dataset"


def create_tasks_parquet() -> None:
    table = pa.table({
        "task_index": pa.array([0, 1], type=pa.int64()),
        "task": pa.array(["Pick up the red cube", "Place the cube on the plate"], type=pa.string()),
    })
    pq.write_table(table, ROOT / "meta" / "tasks.parquet")
    print("Created meta/tasks.parquet")


def create_episodes_parquet() -> None:
    table = pa.table({
        "episode_index": pa.array([0, 1, 2, 3, 4], type=pa.int64()),
        "task_index": pa.array([0, 0, 1, 1, 0], type=pa.int64()),
        "data/chunk_index": pa.array([0, 0, 0, 0, 0], type=pa.int64()),
        "data/file_index": pa.array([0, 0, 0, 0, 0], type=pa.int64()),
        "dataset_from_index": pa.array([0, 100, 200, 300, 400], type=pa.int64()),
        "dataset_to_index": pa.array([100, 200, 300, 400, 500], type=pa.int64()),
    })
    dest = ROOT / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    pq.write_table(table, dest)
    print("Created meta/episodes/chunk-000/file-000.parquet")


def create_data_parquet() -> None:
    rng = np.random.default_rng(42)
    n = 500

    # 100 rows per episode, episodes 0-4
    episode_index = np.repeat(np.arange(5, dtype=np.int64), 100)
    timestamp = np.arange(n, dtype=np.float32) * (1.0 / 30.0)

    # observation.state and action as list<float> columns
    obs_state = rng.random((n, 6)).astype(np.float32)
    action = rng.random((n, 6)).astype(np.float32)

    obs_state_list = pa.array(obs_state.tolist(), type=pa.list_(pa.float32()))
    action_list = pa.array(action.tolist(), type=pa.list_(pa.float32()))

    table = pa.table({
        "episode_index": pa.array(episode_index, type=pa.int64()),
        "timestamp": pa.array(timestamp, type=pa.float32()),
        "observation.state": obs_state_list,
        "action": action_list,
    })
    dest = ROOT / "data" / "chunk-000" / "file-000.parquet"
    pq.write_table(table, dest)
    print("Created data/chunk-000/file-000.parquet")


if __name__ == "__main__":
    create_tasks_parquet()
    create_episodes_parquet()
    create_data_parquet()
    print("Mock dataset created successfully.")
