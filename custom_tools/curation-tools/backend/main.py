import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import datasets, episodes, tasks, rerun, videos, scalars, hf_sync, dataset_ops
from backend.services import rerun_service
from backend.services.hf_sync_service import hf_sync_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Rerun is optional — video player is the primary visualization
    if settings.enable_rerun:
        try:
            rerun_service.init_rerun(
                grpc_port=settings.rerun_grpc_port,
                web_port=settings.rerun_web_port,
            )
            logger.info("Rerun viewer available at http://localhost:%d", settings.rerun_web_port)
        except Exception as e:
            logger.warning("Rerun init failed: %s (video player still works)", e)
    else:
        logger.info("Rerun disabled — using native video player")

    # HF sync: initialize and start background sync loop
    derived_path = str(Path(settings.derived_dataset_path).expanduser())
    hf_sync_service.init(settings.hf_org, settings.dataset_path, state_dir=derived_path)
    sync_task = asyncio.create_task(hf_sync_service.run_sync_loop(settings.sync_interval_seconds))

    yield

    # Cleanup: cancel the sync loop
    sync_task.cancel()


app = FastAPI(
    title="LeRobot Curation Tools",
    description="Local curation tool for LeRobot datasets with Rerun visualization",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

app.include_router(datasets.router)
app.include_router(episodes.router)
app.include_router(tasks.router)
app.include_router(rerun.router)
app.include_router(videos.router)
app.include_router(scalars.router)
app.include_router(hf_sync.router)
app.include_router(dataset_ops.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def start():
    """Entry point for pyproject.toml scripts."""
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.fastapi_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    start()
