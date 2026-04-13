from fastapi import APIRouter, HTTPException

from backend.models.schemas import Task, TaskUpdate
from backend.services import task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
async def list_tasks():
    try:
        items = task_service.get_tasks()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [Task(task_index=t["task_index"], task_instruction=t["task_instruction"]) for t in items]


@router.patch("/{task_index}", response_model=Task)
async def update_task(task_index: int, update: TaskUpdate):
    try:
        result = await task_service.update_task(task_index, update.task_instruction)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Task(task_index=result["task_index"], task_instruction=result["task_instruction"])
