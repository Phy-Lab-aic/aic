"""Rerun visualization service for LeRobot dataset episodes."""

import logging
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import rerun as rr

from backend.services.dataset_service import dataset_service

logger = logging.getLogger(__name__)


def init_rerun(grpc_port: int, web_port: int) -> None:
    """Initialize Rerun with gRPC server and web viewer."""
    rr.init("curation_tools")
    server_uri = rr.serve_grpc(grpc_port=grpc_port)
    rr.serve_web_viewer(open_browser=False, web_port=web_port, connect_to=server_uri)
    logger.info("Rerun initialized — gRPC port %d, web port %d", grpc_port, web_port)


def _extract_video_frames(
    video_path: Path, start_frame: int, num_frames: int
) -> list[np.ndarray]:
    """Extract frames from MP4. Returns list of RGB numpy arrays or empty on failure."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frames: list[np.ndarray] = []
        for _ in range(num_frames):
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        cap.release()
        return frames
    except ImportError:
        return []


def _log_scalar_columns(entity_prefix: str, row: dict, columns: list[str]) -> None:
    """Log numeric columns as Rerun Scalar/BarChart entities."""
    for col in columns:
        value = row.get(col)
        if value is None:
            continue
        arr = np.asarray(value, dtype=float).ravel()
        entity = f"{entity_prefix}/{col}"
        if arr.size == 1:
            rr.log(entity, rr.Scalars(float(arr[0])))
        elif arr.size > 1:
            rr.log(entity, rr.BarChart(arr))


async def visualize_episode(episode_index: int) -> None:
    """Visualize a single episode in Rerun."""
    import asyncio

    loc = dataset_service.get_episode_file_location(episode_index)
    dataset_path = Path(dataset_service.get_dataset_path())
    features = dataset_service.get_features()

    from_idx = loc["dataset_from_index"]
    to_idx = loc["dataset_to_index"]
    chunk_idx = loc["data_chunk_index"]
    file_idx = loc["data_file_index"]

    # Clear previous visualization
    rr.log("world", rr.Clear(recursive=True))

    # Read data parquet file
    data_path = dataset_path / f"data/chunk-{chunk_idx:03d}/file-{file_idx:03d}.parquet"
    if not data_path.exists():
        raise FileNotFoundError(f"Data parquet not found: {data_path}")

    table = await asyncio.to_thread(pq.read_table, data_path)
    df = table.to_pydict()
    all_columns = list(df.keys())

    # Classify columns by feature type
    image_columns: list[str] = []
    state_columns: list[str] = []
    action_columns: list[str] = []

    for col, feature in features.items():
        dtype = feature.get("dtype", "")
        if dtype in ("image", "video") or col.startswith("observation.image"):
            image_columns.append(col)
        elif col.startswith("observation.") and col in all_columns:
            state_columns.append(col)
        elif col.startswith("action") and col in all_columns:
            action_columns.append(col)

    # Catch remaining numeric columns
    categorised = set(image_columns) | set(state_columns) | set(action_columns)
    for col in all_columns:
        if col in categorised or col not in features:
            continue
        dtype = features[col].get("dtype", "")
        if dtype in ("float32", "float64", "int32", "int64", "bool"):
            state_columns.append(col)

    # Per-frame scalar logging
    num_frames = to_idx - from_idx
    for global_idx in range(from_idx, min(to_idx, len(df.get(all_columns[0], [])))):
        rr.set_time("frame", sequence= global_idx - from_idx)
        row = {col: df[col][global_idx] for col in all_columns if global_idx < len(df[col])}
        _log_scalar_columns("observation", row, state_columns)
        _log_scalar_columns("action", row, action_columns)

    # Video frame logging
    video_features = {
        col: meta for col, meta in features.items()
        if meta.get("dtype") == "video"
    }

    for vkey, _meta in video_features.items():
        vid_info = loc.get("videos", {}).get(vkey, {})
        vid_chunk = vid_info.get("chunk_index", chunk_idx)
        vid_file = vid_info.get("file_index", file_idx)

        video_path = dataset_path / f"videos/{vkey}/chunk-{vid_chunk:03d}/file-{vid_file:03d}.mp4"
        if not video_path.exists():
            logger.warning("Video not found, skipping %s: %s", vkey, video_path)
            continue

        try:
            # Video files are per-episode, so start from frame 0 (not global from_idx)
            frames = _extract_video_frames(video_path, 0, num_frames)
        except Exception as exc:
            logger.warning("Video extraction failed for %s: %s", vkey, exc)
            continue

        if not frames:
            continue

        entity = f"camera/{vkey.replace('.', '/')}"
        for i, frame_rgb in enumerate(frames):
            rr.set_time("frame", sequence= i)
            rr.log(entity, rr.Image(frame_rgb))

    logger.info("Visualized episode %d (%d frames)", episode_index, num_frames)
