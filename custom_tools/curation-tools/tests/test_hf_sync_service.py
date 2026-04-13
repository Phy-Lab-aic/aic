"""Tests for HFSyncService — mocks subprocess and HF API."""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend package is importable from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.hf_sync_service import HFSyncService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(tmp_path: Path, org: str = "TestOrg") -> HFSyncService:
    """Create a fresh HFSyncService initialized against a tmp directory."""
    dataset_path = str(tmp_path / org / "dataset" / "my-dataset")
    state_dir = str(tmp_path / "state")
    svc = HFSyncService()
    svc._hf_mount_bin = "/usr/bin/hf-mount"  # fixed path for tests
    svc._hf_token = ""
    svc.init(org=org, dataset_path=dataset_path, state_dir=state_dir)
    return svc


def _make_proc(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Return a mock asyncio subprocess that yields fixed outputs."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# init / state persistence
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_sets_org_and_paths(self, tmp_path):
        svc = _make_service(tmp_path, org="MyOrg")
        assert svc._org == "MyOrg"
        assert svc._mount_base == "/tmp/hf-mounts/MyOrg"
        assert svc._initialized is True

    def test_state_file_path(self, tmp_path):
        dataset_path = str(tmp_path / "MyOrg" / "dataset" / "ds1")
        state_dir = str(tmp_path / "mystate")
        svc = HFSyncService()
        svc.init(org="MyOrg", dataset_path=dataset_path, state_dir=state_dir)
        expected = tmp_path / "mystate" / "sync-state.json"
        assert svc._state_path == expected

    def test_invalid_org_name_rejected(self):
        svc = HFSyncService()
        with pytest.raises(ValueError, match="Invalid org name"):
            svc.init(org="../../etc", dataset_path="/tmp/test")

    def test_is_initialized_property(self, tmp_path):
        svc = HFSyncService()
        assert svc.is_initialized is False
        svc.init(org="TestOrg", dataset_path=str(tmp_path / "ds"))
        assert svc.is_initialized is True

    def test_get_mount_point_returns_none_if_not_mounted(self, tmp_path):
        svc = _make_service(tmp_path)
        assert svc.get_mount_point("TestOrg/unknown") is None

    def test_get_mount_point_returns_path_if_mounted(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._mounted["TestOrg/ds1"] = {"mount_point": "/tmp/hf-mounts/TestOrg/dataset/ds1", "mounted_at": "2024-01-01"}
        assert svc.get_mount_point("TestOrg/ds1") == "/tmp/hf-mounts/TestOrg/dataset/ds1"

    def test_loads_existing_state(self, tmp_path):
        dataset_path = str(tmp_path / "MyOrg" / "dataset" / "ds1")
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "sync-state.json"
        state_file.write_text(json.dumps({
            "mounted": {"MyOrg/ds1": {"mount_point": "/tmp/x", "mounted_at": "2024-01-01T00:00:00"}},
            "last_scan": 1234567890.0,
            "errors": ["old error"],
        }))

        svc = HFSyncService()
        svc.init(org="MyOrg", dataset_path=dataset_path, state_dir=str(state_dir))
        assert "MyOrg/ds1" in svc._mounted
        assert svc._last_scan == 1234567890.0


class TestStatePersistence:
    def test_save_and_reload(self, tmp_path):
        svc = _make_service(tmp_path, "Org")
        svc._mounted["Org/repo1"] = {"mount_point": "/tmp/x", "mounted_at": "now"}
        svc._save_state()

        svc2 = _make_service(tmp_path, "Org")
        assert "Org/repo1" in svc2._mounted

    def test_save_truncates_errors_to_50(self, tmp_path):
        svc = _make_service(tmp_path, "Org")
        svc._errors = [f"err{i}" for i in range(100)]
        svc._save_state()

        state_path = svc._state_path
        with state_path.open() as fh:
            data = json.load(fh)
        assert len(data["errors"]) == 50


# ---------------------------------------------------------------------------
# _fetch_dataset_repos (HF API with rate-limit handling)
# ---------------------------------------------------------------------------

class TestFetchDatasetRepos:
    @pytest.mark.asyncio
    async def test_returns_repo_ids(self, tmp_path):
        svc = _make_service(tmp_path)
        payload = json.dumps([{"id": "TestOrg/repo1"}, {"id": "TestOrg/repo2"}]).encode()
        proc = _make_proc(stdout=payload + b"\n200")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await svc._fetch_dataset_repos()

        assert result == ["TestOrg/repo1", "TestOrg/repo2"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_parse_error(self, tmp_path):
        svc = _make_service(tmp_path)
        proc = _make_proc(stdout=b"not-json\n200")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await svc._fetch_dataset_repos()

        assert result == []

    @pytest.mark.asyncio
    async def test_rate_limit_backoff_then_success(self, tmp_path):
        svc = _make_service(tmp_path)
        payload = json.dumps([{"id": "TestOrg/repo1"}]).encode()

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_proc(stdout=b"rate limited\n429")
            return _make_proc(stdout=payload + b"\n200")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await svc._fetch_dataset_repos()

        assert result == ["TestOrg/repo1"]
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_rate_limited_returns_empty(self, tmp_path):
        svc = _make_service(tmp_path)
        proc_429 = _make_proc(stdout=b"rate limited\n429")

        with patch("asyncio.create_subprocess_exec", return_value=proc_429):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await svc._fetch_dataset_repos()

        assert result == []


# ---------------------------------------------------------------------------
# mount_repo / unmount_repo
# ---------------------------------------------------------------------------

class TestMountRepo:
    @pytest.mark.asyncio
    async def test_mount_success(self, tmp_path):
        svc = _make_service(tmp_path)
        proc = _make_proc(returncode=0, stdout=b"started\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with patch("pathlib.Path.mkdir"):
                ok = await svc.mount_repo("TestOrg/my-dataset")

        assert ok is True
        assert "TestOrg/my-dataset" in svc._mounted

    @pytest.mark.asyncio
    async def test_mount_already_running_is_success(self, tmp_path):
        svc = _make_service(tmp_path)
        proc = _make_proc(returncode=1, stdout=b"already running\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with patch("pathlib.Path.mkdir"):
                ok = await svc.mount_repo("TestOrg/my-dataset")

        assert ok is True

    @pytest.mark.asyncio
    async def test_mount_failure(self, tmp_path):
        svc = _make_service(tmp_path)
        proc = _make_proc(returncode=1, stderr=b"connection refused\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with patch("pathlib.Path.mkdir"):
                ok = await svc.mount_repo("TestOrg/my-dataset")

        assert ok is False
        assert "TestOrg/my-dataset" not in svc._mounted
        assert len(svc._errors) == 1

    @pytest.mark.asyncio
    async def test_mount_includes_hf_token_in_cmd(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._hf_token = "mytoken"
        proc = _make_proc(returncode=0)
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            with patch("pathlib.Path.mkdir"):
                await svc.mount_repo("TestOrg/ds")

        # Token is now passed via HF_TOKEN env var, not CLI args
        assert "--hf-token" not in captured_cmd
        assert "mytoken" not in captured_cmd

    @pytest.mark.asyncio
    async def test_unmount_success(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._mounted["TestOrg/ds"] = {
            "mount_point": "/tmp/hf-mounts/TestOrg/dataset/ds",
            "mounted_at": "2024-01-01",
        }
        proc = _make_proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            ok = await svc.unmount_repo("TestOrg/ds")

        assert ok is True
        assert "TestOrg/ds" not in svc._mounted

    @pytest.mark.asyncio
    async def test_unmount_failure_records_error(self, tmp_path):
        svc = _make_service(tmp_path)
        proc = _make_proc(returncode=1, stderr=b"not mounted\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            ok = await svc.unmount_repo("TestOrg/ds")

        assert ok is False
        assert len(svc._errors) == 1


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------

class TestScan:
    @pytest.mark.asyncio
    async def test_scan_mounts_new_repos(self, tmp_path):
        svc = _make_service(tmp_path)

        async def fake_fetch():
            return ["TestOrg/repo1", "TestOrg/repo2"]

        async def fake_mount(repo_id, **kwargs):
            svc._mounted[repo_id] = {"mount_point": f"/tmp/x/{repo_id}", "mounted_at": "now"}
            return True

        svc._fetch_dataset_repos = fake_fetch
        svc.mount_repo = fake_mount

        result = await svc.scan()

        assert set(result["new_mounts"]) == {"TestOrg/repo1", "TestOrg/repo2"}
        assert result["scanned"] == 2
        assert svc._last_scan is not None

    @pytest.mark.asyncio
    async def test_scan_skips_already_mounted(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._mounted["TestOrg/repo1"] = {"mount_point": "/tmp/x", "mounted_at": "now"}

        async def fake_fetch():
            return ["TestOrg/repo1", "TestOrg/repo2"]

        async def fake_mount(repo_id, **kwargs):
            svc._mounted[repo_id] = {"mount_point": f"/tmp/x/{repo_id}", "mounted_at": "now"}
            return True

        svc._fetch_dataset_repos = fake_fetch
        svc.mount_repo = fake_mount

        result = await svc.scan()

        assert "TestOrg/repo1" not in result["new_mounts"]
        assert "TestOrg/repo2" in result["new_mounts"]

    @pytest.mark.asyncio
    async def test_scan_records_failures(self, tmp_path):
        svc = _make_service(tmp_path)

        async def fake_fetch():
            return ["TestOrg/bad-repo"]

        async def fake_mount(repo_id, **kwargs):
            return False

        svc._fetch_dataset_repos = fake_fetch
        svc.mount_repo = fake_mount

        result = await svc.scan()

        assert "TestOrg/bad-repo" in result["failed"]
        assert result["new_mounts"] == []

    @pytest.mark.asyncio
    async def test_scan_raises_if_not_initialized(self):
        svc = HFSyncService()
        with pytest.raises(RuntimeError, match="init()"):
            await svc.scan()


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_get_status_structure(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._mounted["TestOrg/ds"] = {"mount_point": "/tmp/x", "mounted_at": "now"}
        svc._errors = ["err1"]
        svc._last_scan = 1700000000.0

        status = svc.get_status()

        assert status["org"] == "TestOrg"
        assert "TestOrg/ds" in status["mounted_repos"]
        assert status["last_scan"] is not None
        assert status["errors"] == ["err1"]
        assert status["initialized"] is True

    def test_get_status_no_scan_yet(self, tmp_path):
        svc = _make_service(tmp_path)
        status = svc.get_status()
        assert status["last_scan"] is None
        assert status["mounted_repos"] == []


# ---------------------------------------------------------------------------
# mount_point convention
# ---------------------------------------------------------------------------

class TestMountPointConvention:
    def test_mount_point_format(self, tmp_path):
        svc = _make_service(tmp_path, org="Phy-lab")
        mp = svc._mount_point("Phy-lab/lerobot-dataset-v1")
        assert mp == "/tmp/hf-mounts/Phy-lab/dataset/lerobot-dataset-v1"


# ---------------------------------------------------------------------------
# run_sync_loop
# ---------------------------------------------------------------------------

class TestRunSyncLoop:
    @pytest.mark.asyncio
    async def test_loop_calls_scan_repeatedly(self, tmp_path):
        svc = _make_service(tmp_path)
        call_count = 0

        async def fake_scan():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError()
            return {}

        svc.scan = fake_scan

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await svc.run_sync_loop(interval_seconds=1)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_loop_does_not_run_if_not_initialized(self, tmp_path):
        svc = HFSyncService()
        scan_called = False

        async def fake_scan():
            nonlocal scan_called
            scan_called = True
            return {}

        svc.scan = fake_scan
        # Should return immediately without running scan
        await svc.run_sync_loop(interval_seconds=1)
        assert scan_called is False
