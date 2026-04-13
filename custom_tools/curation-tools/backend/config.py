import os
import pwd
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dataset_path: str = "/tmp/hf-mounts/Phy-lab/dataset"
    allowed_dataset_roots: list[str] = ["/tmp/hf-mounts", "/data", "/tmp/derived-datasets"]
    host: str = "127.0.0.1"
    fastapi_port: int = 8000
    rerun_grpc_port: int = 9876
    rerun_web_port: int = 9090
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    annotations_path: str = ""
    enable_rerun: bool = False
    debug: bool = False

    # HF sync settings
    hf_org: str = "Phy-lab"
    hf_token: str = ""
    sync_interval_seconds: int = 60
    derived_dataset_path: str = "~/.cache/curation-tools/derived"

    model_config = {"env_prefix": "CURATION_"}


settings = Settings()

def _find_hf_token() -> str:
    """Resolve HF token: CURATION_HF_TOKEN > HF_TOKEN env > token file.

    When running as root (e.g. via sudo), also checks the original user's
    home and the project directory owner's home for the cached token.
    """
    token = os.environ.get("HF_TOKEN", "")
    if token:
        return token

    candidate_homes = [Path.home()]

    # If running via sudo, check the original user's home
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            candidate_homes.append(Path(pwd.getpwnam(sudo_user).pw_dir))
        except KeyError:
            pass

    # Check the project directory owner's home
    try:
        project_owner_uid = Path(__file__).resolve().parent.parent.stat().st_uid
        candidate_homes.append(Path(pwd.getpwuid(project_owner_uid).pw_dir))
    except (KeyError, OSError):
        pass

    for home in dict.fromkeys(candidate_homes):  # deduplicate, preserve order
        token_path = home / ".cache" / "huggingface" / "token"
        if token_path.is_file():
            return token_path.read_text().strip()

    return ""


# Resolve HF token and expose to all libraries (huggingface_hub, lerobot, etc.)
if not settings.hf_token:
    settings.hf_token = _find_hf_token()
if settings.hf_token:
    os.environ["HF_TOKEN"] = settings.hf_token
