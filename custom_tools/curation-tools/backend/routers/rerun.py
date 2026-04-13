from fastapi import APIRouter, HTTPException

from backend.services import rerun_service

router = APIRouter(prefix="/api/rerun", tags=["rerun"])


@router.post("/visualize/{episode_index}")
async def visualize_episode(episode_index: int):
    try:
        await rerun_service.visualize_episode(episode_index)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "ok", "episode_index": episode_index}
