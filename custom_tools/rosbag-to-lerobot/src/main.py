"""CLI entry point for standalone MCAP-to-LeRobot conversion.

Reads raw training data (~/aic_data/raw/) directly, performs score filtering,
generates metacard metadata, converts to LeRobot v3, and moves completed
data to done/ or skipped/.

No intermediate input directory needed — replaces prepare_for_lerobot.py.
"""

import json
import logging
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from v3_conversion.constants import (
    CONFIG_PATH,
    DONE_PATH,
    INPUT_PATH,
    OUTPUT_PATH,
    SKIPPED_PATH,
)
from v3_conversion.data_converter import frames_to_episode
from v3_conversion.data_creator import DataCreator
from v3_conversion.hz_checker import validate_from_timestamps
from v3_conversion.mcap_reader import (
    build_extraction_config,
    extract_frames,
    validate_mcap_topics,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = CONFIG_PATH


# ------------------------------------------------------------------
# Config loading
# ------------------------------------------------------------------

def _load_config(config_path: str) -> dict:
    """Load and validate JSON config file.

    Config-level fields (camera_topic_map, joint_names, state_topic,
    action_topics_map) serve as defaults when metacard.json is absent.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    task_name = config.get("task") or config.get("task_name")
    if not task_name:
        raise ValueError("Config must have 'task' or 'task_name'")

    # repo_id for HuggingFace Hub (must be "namespace/dataset-name" format)
    repo_id = config.get("repo_id", "")

    folders = config.get("folders", [])
    if folders == "all":
        # Scan INPUT_PATH for all subdirectories containing .mcap files
        if INPUT_PATH.is_dir():
            folders = sorted([
                d.name for d in INPUT_PATH.iterdir()
                if d.is_dir() and any(d.glob("*.mcap"))
            ])
        else:
            folders = []
    elif not isinstance(folders, list):
        raise ValueError(
            f"'folders' must be a list of folder names or 'all', got: {type(folders).__name__}"
        )

    robot_type = config.get("robot") or config.get("robot_type") or ""
    fps = config.get("fps", None)

    return {
        "task_name": task_name,
        "repo_id": repo_id,
        "folders": folders,
        "robot_type": robot_type,
        "fps": fps,
        "min_score": float(config.get("min_score", 0.0)),
        "move_after_convert": bool(config.get("move_after_convert", True)),
        # Config-level defaults used when metacard.json is missing
        "camera_topic_map": config.get("camera_topic_map", {}),
        "joint_names": config.get("joint_names", []),
        "state_topic": config.get("state_topic", ""),
        "action_topics_map": config.get("action_topics_map", {}),
        "task_instruction": config.get("task_instruction", []),
        "tags": config.get("tags", []),
    }


# ------------------------------------------------------------------
# Score helpers
# ------------------------------------------------------------------

def _trial_score(scoring: dict, trial_key: str) -> float:
    """Extract total score (tier1+tier2+tier3) for a specific trial."""
    td = scoring.get(trial_key, {})
    t1 = float(td.get("tier_1", {}).get("score", 0))
    t2 = float(td.get("tier_2", {}).get("score", 0))
    t3 = float(td.get("tier_3", {}).get("score", 0))
    return t1 + t2 + t3


# ------------------------------------------------------------------
# Raw directory scanning
# ------------------------------------------------------------------

def _scan_raw_episodes(
    raw_dir: Path,
    min_score: float = 0.0,
) -> tuple[list[dict], list[dict]]:
    """Scan raw/ directory and return (episodes_to_convert, episodes_to_skip).

    Each episode is a dict with: config_name, trial_key, mcap_path,
    task_instruction, tags, score.

    Raw directory structure:
        raw/config_0000/
            config.yaml
            task_metadata.yaml
            scoring.yaml
            engine_results/bag_trial_1_*/xxx_0.mcap
    """
    episodes = []
    skipped = []

    if not raw_dir.is_dir():
        logger.warning("Raw directory not found: %s", raw_dir)
        return episodes, skipped

    for config_dir in sorted(raw_dir.iterdir()):
        if not config_dir.is_dir() or config_dir.name in ("logs",):
            continue

        engine_results = config_dir / "engine_results"
        if not engine_results.exists():
            continue

        # Load scoring
        scoring: dict = {}
        scoring_path = config_dir / "scoring.yaml"
        if scoring_path.exists():
            with open(scoring_path) as f:
                scoring = yaml.safe_load(f) or {}

        # Load task metadata
        task_meta = None
        task_meta_path = config_dir / "task_metadata.yaml"
        if task_meta_path.exists():
            with open(task_meta_path) as f:
                task_meta = yaml.safe_load(f)

        # Find all bag_trial_* directories
        for bag_dir in sorted(engine_results.iterdir()):
            if not bag_dir.is_dir() or not bag_dir.name.startswith("bag_trial_"):
                continue

            mcap_files = sorted(bag_dir.glob("*.mcap"))
            if not mcap_files:
                continue

            trial_num = bag_dir.name.split("_")[2]
            trial_key = f"trial_{trial_num}"
            score = _trial_score(scoring, trial_key) if scoring else 0.0

            # Build task instruction from metadata
            task_instruction = ""
            tags = [config_dir.name, trial_key]
            if task_meta:
                trial_meta = task_meta.get("trials", {}).get(trial_key, {})
                task_info = trial_meta.get("task", {})
                config_type = task_meta.get("config_type", "")

                cable_type = task_info.get("cable_type", "")
                port_name = task_info.get("port_name", "")
                target_module = task_info.get("target_module_name", "")

                if cable_type and port_name:
                    task_instruction = f"Insert {cable_type} into {port_name} on {target_module}"
                if config_type:
                    tags.append(config_type)

            episode_info = {
                "config_name": config_dir.name,
                "trial_key": trial_key,
                "episode_name": f"{config_dir.name}_{trial_key}",
                "mcap_path": mcap_files[0],
                "task_instruction": task_instruction,
                "tags": tags,
                "score": score,
            }

            if min_score > 0 and score < min_score:
                skipped.append(episode_info)
            else:
                episodes.append(episode_info)

    return episodes, skipped


# ------------------------------------------------------------------
# Metacard loading (from raw episode info or legacy metacard.json)
# ------------------------------------------------------------------

def _build_metadata(
    episode_info: dict,
    config_defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build metadata dict from episode info + config defaults.

    Replaces the old _load_metacard that required a separate input directory.
    """
    defaults = config_defaults or {}

    ti = episode_info.get("task_instruction", "")
    ti_list = [ti] if ti else defaults.get("task_instruction", [])
    if not isinstance(ti_list, list):
        ti_list = [str(ti_list)] if ti_list else []

    return {
        "folder_dir": episode_info["episode_name"],
        "fps": int(defaults.get("fps") or 30),
        "robot_type": str(defaults.get("robot_type", "")),
        "task_instruction": ti_list,
        "tags": episode_info.get("tags", defaults.get("tags", [])),
        "camera_topic_map": defaults.get("camera_topic_map", {}),
        "joint_topic_map": defaults.get("joint_topic_map", {}),
        "joint_names": defaults.get("joint_names", []),
        "action_topics_map": defaults.get("action_topics_map", {}),
        "state_topic": defaults.get("state_topic", ""),
    }


# ------------------------------------------------------------------
# Config validation
# ------------------------------------------------------------------

def _prepare_config(
    folder_name: str,
    metadata: Dict[str, Any],
    mcap_path: Path,
    robot_type_override: str = "",
    fps_override: Optional[int] = None,
):
    """Validate metadata and build extraction config.

    Required fields: camera_topic_map, joint_names, action_topics_map,
    state_topic.  When any of these are empty the folder is skipped.
    """

    camera_topic_map = metadata.get("camera_topic_map")
    if not isinstance(camera_topic_map, dict):
        camera_topic_map = {}
    if not camera_topic_map:
        logger.info("  camera_topic_map is empty [folder=%s], skipping cameras", folder_name)

    joint_names = metadata.get("joint_names")
    if not isinstance(joint_names, list) or not joint_names:
        raise ValueError(
            f"joint_names is empty or missing [folder={folder_name}]. "
            "Provide it in metacard.json or config.json."
        )

    action_topics_map = metadata.get("action_topics_map")
    if not isinstance(action_topics_map, dict) or not action_topics_map:
        raise ValueError(
            f"action_topics_map is empty or missing [folder={folder_name}]. "
            "Provide it in metacard.json or config.json."
        )

    state_topic = metadata.get("state_topic")
    if not isinstance(state_topic, str) or not state_topic.strip():
        raise ValueError(
            f"state_topic is empty or missing [folder={folder_name}]. "
            "Provide it in metacard.json or config.json."
        )

    fps = fps_override if fps_override is not None else int(metadata.get("fps", 30))
    robot_type = robot_type_override if robot_type_override else str(metadata.get("robot_type", "")).strip()

    config = build_extraction_config(
        detail=metadata,
        fps=fps,
        robot_type=robot_type,
    )

    # Validate: observation and action dimension count
    obs_names = list(config.joint_order.get("obs", []))
    action_cfg = config.joint_order.get("action", {})
    action_names = []
    for key in config.action_order:
        action_names += action_cfg.get(key, [])
    if set(obs_names) != set(action_names):
        logger.warning(
            "  obs/action joint names differ [folder=%s]: "
            "observation.state(%d)=%s, action(%d)=%s",
            folder_name, len(obs_names), obs_names,
            len(action_names), action_names,
        )

    return mcap_path, config


# ------------------------------------------------------------------
# Main conversion
# ------------------------------------------------------------------

def _move_config_dir(config_name: str, dest_base: Path) -> None:
    """Move a config directory from raw/ to dest_base/ (done/ or skipped/)."""
    src = INPUT_PATH / config_name
    if not src.is_dir():
        return
    dest_base.mkdir(parents=True, exist_ok=True)
    dest = dest_base / config_name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(src), str(dest))
    logger.info("  Moved %s -> %s/", config_name, dest_base)


def run_conversion(config_path: str) -> int:
    """Run the full conversion pipeline.

    Reads directly from raw/ directory, filters by score, converts to
    LeRobot, and moves completed configs to done/ or skipped/.

    Returns exit code: 0=success, 1=all failed, 2=partial success.
    """
    cfg = _load_config(config_path)
    task_name = cfg["task_name"]
    repo_id = cfg["repo_id"] or task_name
    robot_type = cfg["robot_type"]
    fps_override = cfg["fps"]
    min_score = cfg["min_score"]
    move_after = cfg["move_after_convert"]

    config_defaults = {
        "robot_type": robot_type,
        "fps": fps_override,
        "camera_topic_map": cfg.get("camera_topic_map", {}),
        "joint_names": cfg.get("joint_names", []),
        "state_topic": cfg.get("state_topic", ""),
        "action_topics_map": cfg.get("action_topics_map", {}),
        "task_instruction": cfg.get("task_instruction", []),
        "tags": cfg.get("tags", []),
    }

    # Scan raw/ directory
    episodes, skipped_episodes = _scan_raw_episodes(INPUT_PATH, min_score)

    # Move skipped (low-score) configs
    if move_after and skipped_episodes:
        skipped_configs = set(ep["config_name"] for ep in skipped_episodes)
        # Only move if ALL trials in that config are skipped
        episode_configs = set(ep["config_name"] for ep in episodes)
        for config_name in skipped_configs - episode_configs:
            _move_config_dir(config_name, SKIPPED_PATH)
        logger.info(
            "Score filter (>= %.1f): %d episodes to convert, %d skipped",
            min_score, len(episodes), len(skipped_episodes),
        )

    if not episodes:
        logger.info("No episodes to convert in %s", INPUT_PATH)
        return 1

    logger.info(
        "Starting conversion: task=%s, episodes=%d, min_score=%.1f",
        task_name, len(episodes), min_score,
    )

    output_root = str(OUTPUT_PATH / task_name)
    creator: Optional[DataCreator] = None
    converted_count = 0
    failed_count = 0
    failed_episodes: List[str] = []
    converted_configs: set[str] = set()

    for idx, ep_info in enumerate(episodes):
        ep_name = ep_info["episode_name"]
        logger.info("[%d/%d] Converting: %s (score=%.1f)", idx + 1, len(episodes), ep_name, ep_info["score"])

        try:
            # 1. Build metadata from episode info + config defaults
            metadata = _build_metadata(ep_info, config_defaults)

            # 2. Validate and build config
            mcap_path = ep_info["mcap_path"]
            _, config = _prepare_config(
                ep_name, metadata, mcap_path, robot_type, fps_override
            )

            # 3. Initialize DataCreator on first successful config
            if creator is None:
                creator = DataCreator(
                    repo_id=repo_id,
                    root=output_root,
                    robot_type=config.robot_type,
                    action_order=config.action_order,
                    joint_order=config.joint_order,
                    camera_names=config.camera_names,
                    fps=config.fps,
                )

            # 4. Pre-check: all expected topics exist in MCAP
            validation = validate_mcap_topics(str(mcap_path), config.topic_map)
            if validation["missing_topics"]:
                raise ValueError(
                    f"MCAP topic pre-check failed [{ep_name}]: "
                    f"missing {validation['missing_topics']}"
                )

            # 5. Extract frames
            frames, timestamps = extract_frames(
                bag_path=str(mcap_path), config=config,
            )

            # 6. Hz validation
            logger.info("  [Hz] validating %s (target=%dHz)", ep_name, config.fps)
            hz_result = validate_from_timestamps(
                timestamps=timestamps,
                target_hz=float(config.fps),
                min_ratio=config.hz_min_ratio,
                camera_names=config.camera_names,
            )
            if not hz_result.is_valid:
                raise ValueError(f"[{ep_name}] {hz_result.overall_message}")
            logger.info("  [Hz] PASSED: %s", ep_name)

            if not frames:
                raise ValueError(
                    f"No frames extracted [{ep_name}] from {mcap_path}."
                )

            # 7. Transform to episode
            task_instruction = ep_info.get("task_instruction") or "default_task"

            episode = frames_to_episode(
                frames=frames,
                action_order=config.action_order,
                camera_names=config.camera_names,
                task=task_instruction,
            )

            # 8. Convert episode with custom metadata
            custom_metadata = {
                "Serial_number": ep_name,
                "tags": ep_info.get("tags", []),
                "grade": "",
            }
            creator.convert_episode(episode, custom_metadata=custom_metadata)

            converted_count += 1
            converted_configs.add(ep_info["config_name"])
            logger.info("  Converted successfully: %s", ep_name)

        except Exception as e:
            failed_count += 1
            failed_episodes.append(ep_name)
            logger.error("  Failed to convert %s: %s\n%s", ep_name, e, traceback.format_exc())
            if creator is not None:
                try:
                    creator.recover_dataset_state()
                except Exception as recover_err:
                    logger.error("  Recovery failed: %s", recover_err)
                    creator.dataset = None

    # Finalize dataset
    if creator is not None and creator.dataset is not None:
        try:
            creator.dataset.finalize()
            logger.info("Dataset finalized")
            creator.correct_video_timestamps()
            logger.info("Video timestamps corrected")
            creator.patch_episodes_metadata()
            logger.info("Episode custom metadata patched")
        except Exception as e:
            logger.error("Failed to finalize dataset: %s", e)

        # Push to HuggingFace Hub
        if "/" in repo_id:
            try:
                from lerobot.datasets.lerobot_dataset import LeRobotDataset

                ds = LeRobotDataset(repo_id=repo_id, root=output_root)
                ds.push_to_hub(tags=cfg.get("tags") or None, push_videos=True)
                logger.info("Pushed dataset to HuggingFace Hub: %s", repo_id)
            except Exception as e:
                logger.error("Failed to push to Hub: %s", e)
        else:
            logger.warning(
                "Skipping push_to_hub: repo_id '%s' is not in 'namespace/name' format.",
                repo_id,
            )

    # Move converted configs from raw/ to done/
    if move_after and converted_configs:
        for config_name in sorted(converted_configs):
            _move_config_dir(config_name, DONE_PATH)

    # Summary
    logger.info(
        "Conversion complete: %d converted, %d failed, %d skipped (score < %.1f)",
        converted_count, failed_count, len(skipped_episodes), min_score,
    )
    if failed_episodes:
        logger.info("Failed episodes: %s", failed_episodes)

    if converted_count == 0:
        return 1
    if failed_count > 0:
        return 2
    return 0


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_CONFIG)
    exit_code = run_conversion(config_path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
