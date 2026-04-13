#!/usr/bin/env python3
"""Auto-mount all HuggingFace repos (models, datasets, spaces) for an organization.

No external dependencies — uses only stdlib + curl for HF API calls.
"""

import json
import os
import shutil
import subprocess
import sys

ORG = "Phy-lab"
MOUNT_BASE = f"/tmp/hf-mounts/{ORG}"
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_API = "https://huggingface.co/api"
def _find_hf_mount() -> str:
    """Find hf-mount binary across all environments (user shell, sudo, systemd)."""
    found = shutil.which("hf-mount")
    if found:
        return found
    # Check SUDO_USER, then scan /home for any user install
    users_to_check = []
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        users_to_check.append(sudo_user)
    try:
        for entry in os.listdir("/home"):
            if entry not in users_to_check:
                users_to_check.append(entry)
    except OSError:
        pass
    for user in users_to_check:
        candidate = f"/home/{user}/.local/bin/hf-mount"
        if os.path.isfile(candidate):
            return candidate
    return "hf-mount"


HF_MOUNT_BIN = _find_hf_mount()


def hf_api_get(url: str) -> list[dict]:
    """Fetch JSON from HF API using curl."""
    cmd = ["curl", "-s", url]
    if HF_TOKEN:
        cmd += ["-H", f"Authorization: Bearer {HF_TOKEN}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def get_all_repos() -> list[dict]:
    """Fetch all repos (models, datasets, spaces) from the org."""
    repos = []

    for item in hf_api_get(f"{HF_API}/models?author={ORG}&limit=1000"):
        repos.append({"id": item["id"], "type": "model"})

    for item in hf_api_get(f"{HF_API}/datasets?author={ORG}&limit=1000"):
        repos.append({"id": item["id"], "type": "dataset"})

    for item in hf_api_get(f"{HF_API}/spaces?author={ORG}&limit=1000"):
        repos.append({"id": item["id"], "type": "space"})

    return repos


def get_mounted_paths() -> set[str]:
    """Get currently mounted paths from hf-mount status (check both root and user daemons)."""
    paths = set()
    # Check as current user (root when sudo)
    result = subprocess.run([HF_MOUNT_BIN, "status"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "→" in line:
            paths.add(line.split("→")[-1].strip())
    # Also check as original user if running under sudo
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        result = subprocess.run(
            ["sudo", "-u", sudo_user, HF_MOUNT_BIN, "status"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if "→" in line:
                paths.add(line.split("→")[-1].strip())
    return paths


def mount_repo(repo_id: str, repo_type: str, mount_point: str) -> bool:
    """Mount a single HF repo using hf-mount."""
    os.makedirs(mount_point, exist_ok=True)

    type_prefix_map = {
        "model": "",
        "dataset": "datasets/",
        "space": "spaces/",
    }
    prefixed_id = f"{type_prefix_map[repo_type]}{repo_id}"

    cmd = [HF_MOUNT_BIN, "start", "--", "repo", prefixed_id, mount_point]
    if HF_TOKEN:
        cmd = [HF_MOUNT_BIN, "start", "--", "repo", "--hf-token", HF_TOKEN, prefixed_id, mount_point]

    print(f"  Mounting {prefixed_id} -> {mount_point}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        output = result.stdout + result.stderr
        if "already running" in output:
            print(f"  [SKIP] Already mounted")
            return True
        print(f"  [ERROR] {output.strip()}")
        return False
    if result.stdout.strip():
        print(f"  {result.stdout.strip()}")
    return True


def main():
    repos = get_all_repos()

    if not repos:
        print(f"No repos found for org '{ORG}'.")
        sys.exit(0)

    print(f"Found {len(repos)} repo(s) in '{ORG}':")
    for r in repos:
        print(f"  [{r['type']}] {r['id']}")
    print()

    mounted = get_mounted_paths()
    success, skipped, failed = 0, 0, 0
    for repo in repos:
        repo_name = repo["id"].split("/")[-1]
        mount_point = os.path.join(MOUNT_BASE, repo["type"], repo_name)

        if mount_point in mounted:
            print(f"  [SKIP] Already mounted: {mount_point}")
            skipped += 1
            continue

        if mount_repo(repo["id"], repo["type"], mount_point):
            success += 1
        else:
            failed += 1

    print(f"\nDone: {success} mounted, {skipped} skipped, {failed} failed")
    print("\nMount status:")
    subprocess.run([HF_MOUNT_BIN, "status"])


if __name__ == "__main__":
    main()
