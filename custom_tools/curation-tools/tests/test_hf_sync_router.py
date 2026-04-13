"""Tests for HF Sync API router — uses httpx AsyncClient with FastAPI app."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.main import app
from backend.services.hf_sync_service import hf_sync_service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_service_state():
    """Reset singleton state before each test."""
    hf_sync_service._mounted = {}
    hf_sync_service._last_scan = None
    hf_sync_service._errors = []
    hf_sync_service._org = "TestOrg"
    hf_sync_service._mount_base = "/tmp/hf-mounts/TestOrg"
    hf_sync_service._initialized = True
    yield
    # Cleanup after test
    hf_sync_service._initialized = False


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/hf-sync/status
# ---------------------------------------------------------------------------

class TestGetStatus:
    @pytest.mark.asyncio
    async def test_returns_status_structure(self, client):
        hf_sync_service._mounted = {
            "TestOrg/ds1": {"mount_point": "/tmp/x", "mounted_at": "2024-01-01T00:00:00+00:00"}
        }
        hf_sync_service._errors = ["err1"]

        resp = await client.get("/api/hf-sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["org"] == "TestOrg"
        assert "TestOrg/ds1" in data["mounted_repos"]
        assert data["errors"] == ["err1"]
        assert data["initialized"] is True
        assert data["last_scan"] is None

    @pytest.mark.asyncio
    async def test_empty_state(self, client):
        resp = await client.get("/api/hf-sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mounted_repos"] == []
        assert data["errors"] == []
        assert data["last_scan"] is None


# ---------------------------------------------------------------------------
# POST /api/hf-sync/scan
# ---------------------------------------------------------------------------

class TestTriggerScan:
    @pytest.mark.asyncio
    async def test_scan_returns_summary(self, client):
        scan_result = {
            "scanned": 3,
            "new_mounts": ["TestOrg/repo1"],
            "already_mounted": ["TestOrg/repo2"],
            "failed": [],
        }
        with patch.object(hf_sync_service, "scan", new_callable=AsyncMock, return_value=scan_result):
            resp = await client.post("/api/hf-sync/scan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["scanned"] == 3
        assert data["new_mounts"] == ["TestOrg/repo1"]
        assert data["already_mounted"] == ["TestOrg/repo2"]
        assert data["failed"] == []

    @pytest.mark.asyncio
    async def test_scan_raises_400_if_not_initialized(self, client):
        hf_sync_service._initialized = False

        async def raise_runtime(*args, **kwargs):
            raise RuntimeError("HFSyncService.init() must be called before scan()")

        with patch.object(hf_sync_service, "scan", side_effect=raise_runtime):
            resp = await client.post("/api/hf-sync/scan")

        assert resp.status_code == 400
        assert "init()" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/hf-sync/repos/{repo_id}/mount
# ---------------------------------------------------------------------------

class TestMountRepo:
    @pytest.mark.asyncio
    async def test_mount_success(self, client):
        hf_sync_service._mounted["TestOrg/my-dataset"] = {
            "mount_point": "/tmp/hf-mounts/TestOrg/dataset/my-dataset",
            "mounted_at": "2024-01-01T00:00:00+00:00",
        }

        with patch.object(hf_sync_service, "mount_repo", new_callable=AsyncMock, return_value=True):
            resp = await client.post("/api/hf-sync/repos/TestOrg/my-dataset/mount")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["repo_id"] == "TestOrg/my-dataset"
        assert data["mount_point"] == "/tmp/hf-mounts/TestOrg/dataset/my-dataset"

    @pytest.mark.asyncio
    async def test_mount_failure(self, client):
        hf_sync_service._errors = ["mount failed: connection refused"]

        with patch.object(hf_sync_service, "mount_repo", new_callable=AsyncMock, return_value=False):
            resp = await client.post("/api/hf-sync/repos/TestOrg/my-dataset/mount")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["repo_id"] == "TestOrg/my-dataset"
        assert data["error"] == "mount failed: connection refused"

    @pytest.mark.asyncio
    async def test_mount_not_initialized_returns_400(self, client):
        hf_sync_service._initialized = False
        resp = await client.post("/api/hf-sync/repos/TestOrg/ds/mount")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/hf-sync/repos/{repo_id}/unmount
# ---------------------------------------------------------------------------

class TestUnmountRepo:
    @pytest.mark.asyncio
    async def test_unmount_success(self, client):
        with patch.object(hf_sync_service, "unmount_repo", new_callable=AsyncMock, return_value=True):
            resp = await client.post("/api/hf-sync/repos/TestOrg/my-dataset/unmount")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["repo_id"] == "TestOrg/my-dataset"
        assert data["mount_point"] is None

    @pytest.mark.asyncio
    async def test_unmount_failure(self, client):
        hf_sync_service._errors = ["unmount failed"]

        with patch.object(hf_sync_service, "unmount_repo", new_callable=AsyncMock, return_value=False):
            resp = await client.post("/api/hf-sync/repos/TestOrg/my-dataset/unmount")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "unmount failed"

    @pytest.mark.asyncio
    async def test_unmount_not_initialized_returns_400(self, client):
        hf_sync_service._initialized = False
        resp = await client.post("/api/hf-sync/repos/TestOrg/ds/unmount")
        assert resp.status_code == 400
