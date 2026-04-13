"""Tests for Dataset Ops API router — mocks dataset_ops_service methods."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.main import app
from backend.services.dataset_ops_service import dataset_ops_service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /api/datasets/split
# ---------------------------------------------------------------------------


class TestSplitDataset:
    @pytest.mark.asyncio
    async def test_split_returns_202_with_job(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        with patch.object(
            dataset_ops_service,
            "split_dataset",
            new_callable=AsyncMock,
            return_value="abc-123",
        ):
            resp = await client.post(
                "/api/datasets/split",
                json={
                    "source_path": str(source),
                    "episode_ids": [0, 1, 5],
                    "target_name": "my-split",
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "abc-123"
        assert data["operation"] == "split"
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_split_404_if_source_missing(self, client):
        resp = await client.post(
            "/api/datasets/split",
            json={
                "source_path": "/nonexistent/path",
                "episode_ids": [0],
                "target_name": "new-split",
            },
        )
        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_split_422_if_episode_ids_empty(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        resp = await client.post(
            "/api/datasets/split",
            json={
                "source_path": str(source),
                "episode_ids": [],
                "target_name": "new-split",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/datasets/split-into
# ---------------------------------------------------------------------------


class TestSplitIntoDataset:
    @pytest.mark.asyncio
    async def test_split_into_new_returns_202(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        with patch.object(
            dataset_ops_service,
            "split_dataset",
            new_callable=AsyncMock,
            return_value="new-job-1",
        ):
            resp = await client.post(
                "/api/datasets/split-into",
                json={
                    "source_path": str(source),
                    "episode_ids": [0, 1],
                    "target_name": "new-split",
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "new-job-1"
        assert data["operation"] == "split"

    @pytest.mark.asyncio
    async def test_split_into_existing_returns_202(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()
        target = tmp_path / "target-ds"
        target.mkdir()

        with patch.object(
            dataset_ops_service,
            "split_and_merge",
            new_callable=AsyncMock,
            return_value="merge-job-2",
        ):
            resp = await client.post(
                "/api/datasets/split-into",
                json={
                    "source_path": str(source),
                    "episode_ids": [3, 5],
                    "target_name": "target-ds",
                    "target_path": str(target),
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "merge-job-2"
        assert data["operation"] == "split_and_merge"

    @pytest.mark.asyncio
    async def test_split_into_404_source_missing(self, client):
        resp = await client.post(
            "/api/datasets/split-into",
            json={
                "source_path": "/nonexistent/source",
                "episode_ids": [0],
                "target_name": "x",
            },
        )
        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_split_into_404_target_missing(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        resp = await client.post(
            "/api/datasets/split-into",
            json={
                "source_path": str(source),
                "episode_ids": [0],
                "target_name": "x",
                "target_path": "/nonexistent/target",
            },
        )
        assert resp.status_code == 404
        assert "Target path not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_split_into_422_empty_episodes(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        resp = await client.post(
            "/api/datasets/split-into",
            json={
                "source_path": str(source),
                "episode_ids": [],
                "target_name": "x",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/datasets/merge
# ---------------------------------------------------------------------------


class TestMergeDatasets:
    @pytest.mark.asyncio
    async def test_merge_returns_202_with_job(self, client, tmp_path):
        src_a = tmp_path / "ds-a"
        src_b = tmp_path / "ds-b"
        src_a.mkdir()
        src_b.mkdir()

        with patch.object(
            dataset_ops_service,
            "merge_datasets",
            new_callable=AsyncMock,
            return_value="merge-job-999",
        ):
            resp = await client.post(
                "/api/datasets/merge",
                json={
                    "source_paths": [str(src_a), str(src_b)],
                    "target_name": "merged-out",
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "merge-job-999"
        assert data["operation"] == "merge"
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_merge_404_if_source_missing(self, client, tmp_path):
        existing = tmp_path / "ds-a"
        existing.mkdir()

        resp = await client.post(
            "/api/datasets/merge",
            json={
                "source_paths": [str(existing), "/nonexistent/ds-b"],
                "target_name": "merged-out",
            },
        )
        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/datasets/ops/status/{job_id}
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_returns_job_status(self, client):
        job = {
            "id": "job-abc",
            "operation": "split",
            "status": "complete",
            "created_at": "2024-01-01T00:00:00+00:00",
            "completed_at": "2024-01-01T00:01:00+00:00",
            "error": None,
            "result_path": "/tmp/derived/my-split",
        }
        with patch.object(dataset_ops_service, "get_job_status", return_value=job):
            resp = await client.get("/api/datasets/ops/status/job-abc")

        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-abc"
        assert data["operation"] == "split"
        assert data["status"] == "complete"
        assert data["completed_at"] == "2024-01-01T00:01:00+00:00"
        assert data["result_path"] == "/tmp/derived/my-split"
        assert data["error"] is None

    @pytest.mark.asyncio
    async def test_returns_queued_job(self, client):
        job = {
            "id": "job-xyz",
            "operation": "merge",
            "status": "queued",
            "created_at": "2024-01-01T00:00:00+00:00",
            "completed_at": None,
            "error": None,
            "result_path": None,
        }
        with patch.object(dataset_ops_service, "get_job_status", return_value=job):
            resp = await client.get("/api/datasets/ops/status/job-xyz")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["completed_at"] is None
        assert data["result_path"] is None

    @pytest.mark.asyncio
    async def test_returns_404_if_job_missing(self, client):
        with patch.object(dataset_ops_service, "get_job_status", return_value=None):
            resp = await client.get("/api/datasets/ops/status/nonexistent-job")

        assert resp.status_code == 404
        assert "Job not found" in resp.json()["detail"]
