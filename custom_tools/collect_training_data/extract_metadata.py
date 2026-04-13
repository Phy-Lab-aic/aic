#!/usr/bin/env python3
"""
extract_metadata.py

Parses an AIC training config YAML and extracts task metadata
into a clean, analysis-friendly YAML file.

Usage:
    python3 extract_metadata.py <config_yaml> <output_yaml>
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def extract_trial_metadata(trial_key: str, trial_data: dict) -> dict:
    """Extract metadata from a single trial."""
    scene = trial_data.get("scene", {})
    tasks = trial_data.get("tasks", {})
    task_board = scene.get("task_board", {})
    cables = scene.get("cables", {})

    # Determine task type and extract task info
    trial_meta: dict = {"trial_key": trial_key}

    # Task info
    if tasks:
        task_key = list(tasks.keys())[0]
        task = tasks[task_key]
        trial_meta["task"] = {
            "cable_type": task.get("cable_type", ""),
            "cable_name": task.get("cable_name", ""),
            "plug_type": task.get("plug_type", ""),
            "plug_name": task.get("plug_name", ""),
            "port_type": task.get("port_type", ""),
            "port_name": task.get("port_name", ""),
            "target_module_name": task.get("target_module_name", ""),
            "time_limit": task.get("time_limit", 180),
        }

        # Determine config type from cable_type
        cable_type = task.get("cable_type", "")
        plug_type = task.get("plug_type", "")
        if plug_type == "sfp":
            trial_meta["type"] = "sfp"
        elif plug_type == "sc":
            trial_meta["type"] = "sc"
        else:
            trial_meta["type"] = "unknown"

    # Task board pose
    if "pose" in task_board:
        trial_meta["task_board_pose"] = task_board["pose"]

    # NIC rails present
    nic_present = []
    for i in range(5):
        rail = task_board.get(f"nic_rail_{i}", {})
        if rail.get("entity_present", False):
            nic_present.append({
                "rail": i,
                "entity_name": rail.get("entity_name", ""),
                "translation": rail.get("entity_pose", {}).get("translation", 0.0),
                "yaw": rail.get("entity_pose", {}).get("yaw", 0.0),
            })
    if nic_present:
        trial_meta["nic_rails"] = nic_present

    # SC rails present
    sc_present = []
    for i in range(2):
        rail = task_board.get(f"sc_rail_{i}", {})
        if rail.get("entity_present", False):
            sc_present.append({
                "rail": i,
                "entity_name": rail.get("entity_name", ""),
                "translation": rail.get("entity_pose", {}).get("translation", 0.0),
            })
    if sc_present:
        trial_meta["sc_rails"] = sc_present

    # Cable/gripper info
    for cable_key, cable_data in cables.items():
        pose = cable_data.get("pose", {})
        trial_meta["cable"] = {
            "key": cable_key,
            "cable_type": cable_data.get("cable_type", ""),
            "attach_to_gripper": cable_data.get("attach_cable_to_gripper", False),
            "gripper_offset": pose.get("gripper_offset", {}),
            "orientation": {
                "roll": pose.get("roll", 0.0),
                "pitch": pose.get("pitch", 0.0),
                "yaw": pose.get("yaw", 0.0),
            },
        }
        break  # Only first cable

    return trial_meta


def extract_metadata(config_path: Path) -> dict:
    """Extract all metadata from a config YAML."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    config_name = config_path.stem
    # Determine type from filename prefix
    if config_name.startswith("sfp_"):
        config_type = "sfp"
    elif config_name.startswith("sc_"):
        config_type = "sc"
    else:
        config_type = "unknown"

    metadata: dict = {
        "config_name": config_name,
        "config_type": config_type,
        "config_file": str(config_path),
    }

    # Task board limits
    if "task_board_limits" in cfg:
        metadata["task_board_limits"] = cfg["task_board_limits"]

    # Robot home position
    if "robot" in cfg:
        metadata["robot"] = cfg["robot"]

    # Trials
    trials = cfg.get("trials", {})
    metadata["trials"] = {}
    for trial_key in sorted(trials.keys()):
        trial_data = trials[trial_key]
        metadata["trials"][trial_key] = extract_trial_metadata(trial_key, trial_data)

    # Summary stats
    metadata["summary"] = {
        "num_trials": len(trials),
        "trial_types": [
            metadata["trials"][k].get("type", "unknown")
            for k in sorted(metadata["trials"].keys())
        ],
    }

    return metadata


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <config_yaml> <output_yaml>", file=sys.stderr)
        sys.exit(1)

    config_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not config_path.exists():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    metadata = extract_metadata(config_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    main()
