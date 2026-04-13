from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.services.dataset_service import dataset_service

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("/{episode_index}/cameras")
async def list_cameras(episode_index: int):
    """Return available camera keys for an episode."""
    try:
        loc = dataset_service.get_episode_file_location(episode_index)
    except (KeyError, RuntimeError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    features = dataset_service.get_features()
    video_keys = [
        key for key, meta in features.items()
        if meta.get("dtype") == "video"
    ]

    dataset_path = Path(dataset_service.get_dataset_path())
    cameras = []
    for vkey in video_keys:
        vid_info = loc.get("videos", {}).get(vkey, {})
        chunk_idx = vid_info.get("chunk_index", loc["data_chunk_index"])
        file_idx = vid_info.get("file_index", loc["data_file_index"])
        video_path = dataset_path / f"videos/{vkey}/chunk-{chunk_idx:03d}/file-{file_idx:03d}.mp4"
        if video_path.exists():
            cameras.append({
                "key": vkey,
                "label": vkey.replace("observation.images.", "").replace("observation.image.", ""),
                "url": f"/api/videos/{episode_index}/stream/{vkey}",
            })
    return cameras


@router.get("/{episode_index}/stream/{camera_key:path}")
async def stream_video(episode_index: int, camera_key: str):
    """Stream MP4 video file for an episode camera. Supports range requests via FileResponse."""
    try:
        loc = dataset_service.get_episode_file_location(episode_index)
    except (KeyError, RuntimeError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # C1: Validate camera_key against dataset features to prevent path traversal
    features = dataset_service.get_features()
    video_keys = [
        key for key, meta in features.items()
        if meta.get("dtype") == "video"
    ]
    if camera_key not in video_keys:
        raise HTTPException(status_code=404, detail=f"Unknown camera: {camera_key}")

    dataset_path = Path(dataset_service.get_dataset_path())
    vid_info = loc.get("videos", {}).get(camera_key, {})
    chunk_idx = vid_info.get("chunk_index", loc["data_chunk_index"])
    file_idx = vid_info.get("file_index", loc["data_file_index"])

    video_path = dataset_path / f"videos/{camera_key}/chunk-{chunk_idx:03d}/file-{file_idx:03d}.mp4"

    # C1: Verify resolved path stays under dataset directory
    if not video_path.resolve().is_relative_to(dataset_path.resolve()):
        raise HTTPException(status_code=400, detail="Invalid camera path")

    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {camera_key}")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=f"episode_{episode_index}_{camera_key.replace('/', '_')}.mp4",
    )
