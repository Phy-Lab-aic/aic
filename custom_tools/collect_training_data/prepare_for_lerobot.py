#!/usr/bin/env python3
"""
prepare_for_lerobot.py  [DEPRECATED]

이 스크립트는 더 이상 필요하지 않습니다.
rosbag-to-lerobot/src/main.py가 ~/aic_data/raw/ 에서 직접 읽고,
score 필터링 + metacard 생성 + done/skipped 이동을 자동 처리합니다.

새로운 사용법:
    cd custom_tools/rosbag-to-lerobot
    pixi run convert

이전 사용법 (참고용):
    python3 prepare_for_lerobot.py ~/aic_data/raw ~/aic_lerobot_input --min-score 90
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


CONVERTED_MARKER = ".converted"


def _trial_score(scoring: dict, trial_key: str) -> float:
    """Extract total score (tier1+tier2+tier3) for a specific trial."""
    td = scoring.get(trial_key, {})
    t1 = float(td.get("tier_1", {}).get("score", 0))
    t2 = float(td.get("tier_2", {}).get("score", 0))
    t3 = float(td.get("tier_3", {}).get("score", 0))
    return t1 + t2 + t3


def prepare(
    data_dir: Path,
    output_dir: Path,
    new_only: bool = False,
    min_score: float = 0.0,
) -> list[str]:
    """Prepare symlink structure. Returns list of episode names.

    Args:
        min_score: Minimum trial score to include (default 0 = no filter).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load set of already-converted episodes
    converted_file = output_dir / CONVERTED_MARKER
    converted_set: set[str] = set()
    if converted_file.exists():
        converted_set = set(converted_file.read_text().strip().splitlines())

    new_episodes: list[str] = []
    total_count = 0
    skipped_by_score = 0

    for config_dir in sorted(data_dir.iterdir()):
        if not config_dir.is_dir() or config_dir.name in ("logs",):
            continue

        engine_results = config_dir / "engine_results"
        if not engine_results.exists():
            continue

        # Load scoring data for score filtering
        scoring: dict = {}
        scoring_path = config_dir / "scoring.yaml"
        if scoring_path.exists():
            with open(scoring_path) as f:
                scoring = yaml.safe_load(f) or {}

        # Load task metadata if available
        task_meta_path = config_dir / "task_metadata.yaml"
        task_meta = None
        if task_meta_path.exists():
            with open(task_meta_path) as f:
                task_meta = yaml.safe_load(f)

        # Find all bag_trial_* directories
        for bag_dir in sorted(engine_results.iterdir()):
            if not bag_dir.is_dir() or not bag_dir.name.startswith("bag_trial_"):
                continue

            # Find MCAP file
            mcap_files = sorted(bag_dir.glob("*.mcap"))
            if not mcap_files:
                continue

            # Extract trial key (e.g., "trial_1" from "bag_trial_1_20260408_...")
            trial_num = bag_dir.name.split("_")[2]  # "1"
            trial_key = f"trial_{trial_num}"

            # Score filtering
            if min_score > 0 and scoring:
                score = _trial_score(scoring, trial_key)
                if score < min_score:
                    skipped_by_score += 1
                    continue

            # Episode folder name
            episode_name = f"{config_dir.name}_{trial_key}"
            episode_dir = output_dir / episode_name
            episode_dir.mkdir(exist_ok=True)

            # Symlink MCAP file with canonical name
            mcap_src = mcap_files[0].resolve()
            mcap_dst = episode_dir / f"{episode_name}_0.mcap"
            if mcap_dst.exists() or mcap_dst.is_symlink():
                mcap_dst.unlink()
            mcap_dst.symlink_to(mcap_src)

            # Create metacard.json with task instruction
            metacard: dict = {
                "task_instruction": [],
                "tags": [config_dir.name, trial_key],
            }

            if task_meta:
                trial_meta = task_meta.get("trials", {}).get(trial_key, {})
                task_info = trial_meta.get("task", {})
                config_type = task_meta.get("config_type", "")

                cable_type = task_info.get("cable_type", "")
                port_name = task_info.get("port_name", "")
                target_module = task_info.get("target_module_name", "")

                if cable_type and port_name:
                    instruction = f"Insert {cable_type} into {port_name} on {target_module}"
                    metacard["task_instruction"] = [instruction]

                metacard["tags"].append(config_type)

            metacard_path = episode_dir / "metacard.json"
            with open(metacard_path, "w") as f:
                json.dump(metacard, f, indent=2)

            total_count += 1
            if episode_name not in converted_set:
                new_episodes.append(episode_name)

    score_msg = f" (min_score={min_score}, skipped={skipped_by_score})" if min_score > 0 else ""
    if new_only:
        print(f"New episodes: {len(new_episodes)} / Total: {total_count}{score_msg}", file=sys.stderr)
    else:
        print(f"Prepared {total_count} episodes -> {output_dir}/{score_msg}", file=sys.stderr)

    return new_episodes


def mark_converted(output_dir: Path, episodes: list[str]) -> None:
    """Mark episodes as converted by appending to .converted file."""
    converted_file = output_dir / CONVERTED_MARKER
    existing = set()
    if converted_file.exists():
        existing = set(converted_file.read_text().strip().splitlines())
    existing.update(episodes)
    converted_file.write_text("\n".join(sorted(existing)) + "\n")


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <data_dir> <output_dir> [options]", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"Options:", file=sys.stderr)
        print(f"  --min-score <N>         Minimum trial score to include (default: 0 = all)", file=sys.stderr)
        print(f"  --new-only              Only output new (unconverted) episode names", file=sys.stderr)
        print(f"  --mark-converted <list> Mark episodes as converted (comma-separated)", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"Examples:", file=sys.stderr)
        print(f"  {sys.argv[0]} ~/aic_training_data ~/aic_lerobot_input --min-score 90", file=sys.stderr)
        print(f"  {sys.argv[0]} ~/aic_training_data ~/aic_lerobot_input --min-score 90 --new-only", file=sys.stderr)
        sys.exit(1)

    data_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    new_only = "--new-only" in sys.argv

    # Parse --min-score
    min_score = 0.0
    if "--min-score" in sys.argv:
        idx = sys.argv.index("--min-score")
        if idx + 1 < len(sys.argv):
            min_score = float(sys.argv[idx + 1])

    # --mark-converted: mark specific episodes as done (called after successful conversion)
    if "--mark-converted" in sys.argv:
        idx = sys.argv.index("--mark-converted")
        if idx + 1 < len(sys.argv):
            episodes = sys.argv[idx + 1].split(",")
            mark_converted(output_dir, episodes)
            print(f"Marked {len(episodes)} episodes as converted", file=sys.stderr)
        return

    if not data_dir.exists():
        print(f"Error: {data_dir} not found", file=sys.stderr)
        sys.exit(1)

    new_episodes = prepare(data_dir, output_dir, new_only=new_only, min_score=min_score)

    if new_only:
        # Output new episode names to stdout (for piping to conversion script)
        for ep in new_episodes:
            print(ep)


if __name__ == "__main__":
    main()
