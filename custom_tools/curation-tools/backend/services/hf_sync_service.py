"""HuggingFace dataset sync service.

Polls an HF org for dataset repos and manages their mount lifecycle via hf-mount.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api"


def _find_hf_mount() -> str:
    """Find hf-mount binary across all environments."""
    found = shutil.which("hf-mount")
    if found:
        return found
    try:
        for user in os.listdir("/home"):
            candidate = f"/home/{user}/.local/bin/hf-mount"
            if os.path.isfile(candidate):
                return candidate
    except OSError:
        pass
    return "hf-mount"


class HFSyncService:
    """Singleton service that syncs HuggingFace dataset repos via hf-mount."""

    def __init__(self) -> None:
        self._mounted: dict[str, dict] = {}  # repo_id -> {mount_point, mounted_at}
        self._failed: set[str] = set()  # repo_ids that failed to mount (skip in auto-poll)
        self._last_scan: Optional[float] = None
        self._errors: list[str] = []
        self._state_path: Optional[Path] = None
        self._org: str = ""
        self._mount_base: str = ""
        self._hf_mount_bin: str = _find_hf_mount()
        self._hf_token: str = os.environ.get("HF_TOKEN", "")
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init(self, org: str, dataset_path: str, state_dir: str | None = None) -> None:
        """Initialize with org name and dataset_path (sets mount base and state file).

        Args:
            org: HuggingFace organization name.
            dataset_path: Root path for mounted datasets.
            state_dir: Directory for sync-state.json. Defaults to /tmp/derived-datasets
                       (user-writable) since mount dirs may be root-owned.
        """
        if not re.match(r'^[A-Za-z0-9_.-]+$', org):
            raise ValueError(f"Invalid org name: {org}")
        self._org = org
        self._mount_base = f"/tmp/hf-mounts/{org}"
        # State file in a user-writable location
        if state_dir:
            sd = Path(state_dir)
        else:
            sd = Path.home() / ".cache" / "curation-tools"
        sd.mkdir(parents=True, exist_ok=True)
        self._state_path = sd / "sync-state.json"
        self._initialized = True
        self._load_state()
        # Detect repos already mounted (e.g., by systemd service running as root)
        self._detect_existing_mounts()

    def _detect_existing_mounts(self) -> None:
        """Scan the mount base directory for repos already mounted (e.g., by systemd/root).

        Populates _mounted for any mount point that exists on disk but isn't tracked yet.
        """
        dataset_dir = Path(self._mount_base) / "dataset"
        if not dataset_dir.exists():
            return
        try:
            for child in dataset_dir.iterdir():
                if not child.is_dir():
                    continue
                # Only treat as mounted if it's an actual mount point, not just an empty dir
                if not os.path.ismount(str(child)):
                    continue
                repo_id = f"{self._org}/{child.name}"
                if repo_id not in self._mounted:
                    self._mounted[repo_id] = {
                        "mount_point": str(child),
                        "mounted_at": "pre-existing",
                    }
                    logger.info("Detected pre-existing mount: %s -> %s", repo_id, child)
        except PermissionError:
            logger.warning("Cannot read %s (permission denied), skipping mount detection", dataset_dir)
        if self._mounted:
            self._save_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if self._state_path and self._state_path.exists():
            try:
                with self._state_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self._mounted = data.get("mounted", {})
                self._last_scan = data.get("last_scan")
                self._errors = data.get("errors", [])
            except Exception as exc:
                logger.warning("Could not load sync state from %s: %s", self._state_path, exc)

    def _save_state(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "mounted": self._mounted,
                        "last_scan": self._last_scan,
                        "errors": self._errors[-50:],  # keep last 50
                    },
                    fh,
                    indent=2,
                )
            tmp.replace(self._state_path)
        except Exception as exc:
            logger.warning("Could not save sync state: %s", exc)

    # ------------------------------------------------------------------
    # HF API
    # ------------------------------------------------------------------

    async def _fetch_dataset_repos(self) -> list[str]:
        """Return list of repo_ids ('{org}/{name}') for all datasets in the org."""
        url = f"{HF_API_BASE}/datasets?author={self._org}&limit=1000"

        backoff = 1.0
        for attempt in range(5):
            cmd = ["curl", "-s", "-w", "\n%{http_code}", "--max-time", "30", url]
            if self._hf_token:
                cmd += ["-H", f"Authorization: Bearer {self._hf_token}"]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            raw = stdout.decode("utf-8", errors="replace")
            lines = raw.rsplit("\n", 1)
            body = lines[0]
            http_code = lines[1].strip() if len(lines) > 1 else "0"

            if http_code == "429":
                logger.warning("HF API rate limited (429), backing off %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue

            if proc.returncode != 0 or http_code not in ("200", ""):
                logger.warning("HF API request failed (http %s)", http_code)
                return []

            try:
                items = json.loads(body)
                return [item["id"] for item in items if "id" in item]
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("HF API parse error: %s", exc)
                return []

        logger.error("HF API repeatedly rate-limited; giving up")
        return []

    # ------------------------------------------------------------------
    # Mount helpers
    # ------------------------------------------------------------------

    def _mount_point(self, repo_id: str) -> str:
        """Return mount path for a dataset repo_id like 'Phy-lab/my-dataset'."""
        repo_name = repo_id.split("/")[-1]
        return f"{self._mount_base}/dataset/{repo_name}"

    async def _run_with_sudo(self, cmd: list[str], password: str | None = None) -> tuple[int, str, str]:
        """Run a command with sudo. Uses -S (stdin) if password provided, -n (no prompt) otherwise."""
        if password:
            sudo_cmd = ["sudo", "-S", *cmd]
            proc = await asyncio.create_subprocess_exec(
                *sudo_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(input=f"{password}\n".encode())
        else:
            sudo_cmd = ["sudo", "-n", *cmd]
            proc = await asyncio.create_subprocess_exec(
                *sudo_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        return (
            proc.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _run_hf_mount(self, *args: str, password: str | None = None) -> tuple[int, str, str]:
        """Run hf-mount with sudo (required for FUSE/NFS)."""
        return await self._run_with_sudo([self._hf_mount_bin, *args], password=password)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def mount_repo(self, repo_id: str, password: str | None = None) -> bool:
        """Mount a single dataset repo. Returns True on success."""
        mount_point = self._mount_point(repo_id)
        try:
            Path(mount_point).mkdir(parents=True, exist_ok=True)
        except PermissionError:
            rc, _, stderr = await self._run_with_sudo(["mkdir", "-p", mount_point], password=password)
            if rc != 0:
                err = f"mount_repo({repo_id}): cannot create {mount_point}: Permission denied"
                logger.error(err)
                self._errors.append(f"[{datetime.now(timezone.utc).isoformat()}] {err}")
                return False

        prefixed = f"datasets/{repo_id}"
        # HF_TOKEN env var is set by config.py at startup; hf-mount-nfs reads it automatically
        args = ("start", "--", "repo", prefixed, mount_point)

        rc, stdout, stderr = await self._run_hf_mount(*args, password=password)
        combined = stdout + stderr

        if rc != 0 and "already running" not in combined:
            err = f"mount_repo({repo_id}): {combined.strip()}"
            logger.error(err)
            self._errors.append(f"[{datetime.now(timezone.utc).isoformat()}] {err}")
            return False

        self._mounted[repo_id] = {
            "mount_point": mount_point,
            "mounted_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()
        logger.info("Mounted %s -> %s", repo_id, mount_point)
        return True

    async def unmount_repo(self, repo_id: str, password: str | None = None) -> bool:
        """Unmount a dataset repo. Returns True on success."""
        info = self._mounted.get(repo_id)
        mount_point = info["mount_point"] if info else self._mount_point(repo_id)

        rc, stdout, stderr = await self._run_hf_mount("stop", mount_point, password=password)
        combined = stdout + stderr

        if rc != 0:
            err = f"unmount_repo({repo_id}): {combined.strip()}"
            logger.error(err)
            self._errors.append(f"[{datetime.now(timezone.utc).isoformat()}] {err}")
            return False

        self._mounted.pop(repo_id, None)
        self._save_state()
        logger.info("Unmounted %s", repo_id)
        return True

    async def delete_repo(
        self, repo_id: str, password: str | None = None
    ) -> tuple[bool, str | None]:
        """Unmount a dataset repo and delete it from HF Hub.

        Returns (success, error_message).
        """
        # Unmount first (ignore failure if not mounted)
        if repo_id in self._mounted:
            await self.unmount_repo(repo_id, password=password)

        # Delete from HF Hub
        try:
            from huggingface_hub import HfApi
            api = HfApi()
            api.delete_repo(repo_id=repo_id, repo_type="dataset")
            logger.info("Deleted repo from HF Hub: %s", repo_id)
        except Exception as exc:
            err = f"delete_repo({repo_id}): {exc}"
            logger.error(err)
            self._errors.append(f"[{datetime.now(timezone.utc).isoformat()}] {err}")
            return False, str(exc)

        # Clean up empty mount point directory
        mount_point = Path(self._mount_point(repo_id))
        if mount_point.exists() and not any(mount_point.iterdir()):
            mount_point.rmdir()

        return True, None

    async def scan(self, force: bool = False, password: str | None = None) -> dict:
        """Discover dataset repos from HF API and mount any that aren't yet mounted.

        Args:
            force: If True, retry previously failed repos. Used by manual scan endpoint.
                   Auto-polling passes False to avoid spamming sudo errors every 60s.
            password: Optional sudo password for mounting. Only used with manual scan.

        Returns a summary dict with new_mounts, already_mounted, and errors.
        """
        if not self._initialized:
            raise RuntimeError("HFSyncService.init() must be called before scan()")

        if force:
            self._failed.clear()

        logger.info("Scanning HF org '%s' for dataset repos", self._org)
        repo_ids = await self._fetch_dataset_repos()

        new_mounts: list[str] = []
        failed: list[str] = []

        for repo_id in repo_ids:
            if repo_id in self._mounted:
                continue
            if repo_id in self._failed:
                failed.append(repo_id)
                continue
            ok = await self.mount_repo(repo_id, password=password)
            if ok:
                new_mounts.append(repo_id)
            else:
                self._failed.add(repo_id)
                failed.append(repo_id)

        self._last_scan = time.time()
        self._save_state()

        summary = {
            "scanned": len(repo_ids),
            "new_mounts": new_mounts,
            "already_mounted": [r for r in repo_ids if r in self._mounted and r not in new_mounts],
            "failed": failed,
        }
        logger.info(
            "Scan complete: %d repos found, %d newly mounted, %d failed",
            len(repo_ids),
            len(new_mounts),
            len(failed),
        )
        return summary

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def get_mount_point(self, repo_id: str) -> str | None:
        """Return the mount point for a repo_id, or None if not mounted."""
        info = self._mounted.get(repo_id)
        return info["mount_point"] if info else None

    def get_status(self) -> dict:
        """Return current sync state."""
        return {
            "org": self._org,
            "mounted_repos": list(self._mounted.keys()),
            "mount_details": dict(self._mounted),
            "last_scan": (
                datetime.fromtimestamp(self._last_scan, tz=timezone.utc).isoformat()
                if self._last_scan
                else None
            ),
            "errors": self._errors[-10:],  # return last 10 errors
            "hf_mount_bin": self._hf_mount_bin,
            "initialized": self._initialized,
        }

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run_sync_loop(self, interval_seconds: int = 60) -> None:
        """Coroutine that calls scan() every interval_seconds. Run from FastAPI lifespan."""
        if not self._initialized:
            logger.warning("HFSyncService not initialized; sync loop will not run")
            return

        logger.info("HF sync loop started (interval=%ds)", interval_seconds)
        while True:
            try:
                await self.scan()
            except Exception as exc:
                err = f"scan() error: {exc}"
                logger.exception(err)
                self._errors.append(f"[{datetime.now(timezone.utc).isoformat()}] {err}")
                self._save_state()
            await asyncio.sleep(interval_seconds)


# Module-level singleton
hf_sync_service = HFSyncService()
