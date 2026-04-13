#!/usr/bin/env python3
"""
merge_results.py

Aggregates all collected training data results into a summary CSV and YAML.
Useful for analyzing which configurations the policy succeeds/fails on.

Usage:
    python3 merge_results.py <data_dir>

Output:
    <data_dir>/summary.csv
    <data_dir>/summary.yaml
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml


def parse_config_results(config_dir: Path) -> dict | None:
    """Parse results from a single config output directory."""
    scoring_file = config_dir / "scoring.yaml"
    metadata_file = config_dir / "task_metadata.yaml"

    if not scoring_file.exists():
        return None

    result: dict = {
        "config_name": config_dir.name,
        "config_type": "",
        "trials": {},
        "score_avg": 0.0,
        "has_extra_bag": (config_dir / "extra_bag").exists(),
    }

    # Parse scoring
    with open(scoring_file) as f:
        scoring = yaml.safe_load(f)

    if not scoring:
        return result

    trial_keys = sorted([k for k in scoring if k.startswith("trial_")])
    total_score = 0.0
    for tk in trial_keys:
        td = scoring[tk]
        t1 = float(td.get("tier_1", {}).get("score", 0))
        t2 = float(td.get("tier_2", {}).get("score", 0))
        t3 = float(td.get("tier_3", {}).get("score", 0))
        trial_total = t1 + t2 + t3
        total_score += trial_total
        result["trials"][tk] = {
            "tier_1": t1,
            "tier_2": t2,
            "tier_3": t3,
            "total": trial_total,
        }
    result["score_avg"] = total_score / len(trial_keys) if trial_keys else 0.0

    # Parse metadata if available
    if metadata_file.exists():
        with open(metadata_file) as f:
            meta = yaml.safe_load(f)
        if meta:
            result["config_type"] = meta.get("config_type", "")
            for tk in trial_keys:
                trial_meta = meta.get("trials", {}).get(tk, {})
                task_info = trial_meta.get("task", {})
                if task_info and tk in result["trials"]:
                    result["trials"][tk]["cable_type"] = task_info.get("cable_type", "")
                    result["trials"][tk]["plug_type"] = task_info.get("plug_type", "")
                    result["trials"][tk]["port_name"] = task_info.get("port_name", "")
                    result["trials"][tk]["target_module"] = task_info.get("target_module_name", "")

    return result


def write_csv(results: list[dict], output_path: Path) -> None:
    """Write results as a flat CSV (one row per trial)."""
    fieldnames = [
        "config_name", "config_type", "trial",
        "tier_1", "tier_2", "tier_3", "total",
        "cable_type", "plug_type", "port_name", "target_module",
        "has_extra_bag",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in results:
            for tk, td in sorted(r["trials"].items()):
                writer.writerow({
                    "config_name": r["config_name"],
                    "config_type": r["config_type"],
                    "trial": tk,
                    "tier_1": td.get("tier_1", 0),
                    "tier_2": td.get("tier_2", 0),
                    "tier_3": td.get("tier_3", 0),
                    "total": td.get("total", 0),
                    "cable_type": td.get("cable_type", ""),
                    "plug_type": td.get("plug_type", ""),
                    "port_name": td.get("port_name", ""),
                    "target_module": td.get("target_module", ""),
                    "has_extra_bag": r["has_extra_bag"],
                })


def write_yaml_summary(results: list[dict], output_path: Path) -> None:
    """Write a YAML summary with aggregate statistics."""
    total_configs = len(results)
    sfp_configs = [r for r in results if r["config_type"] == "sfp"]
    sc_configs = [r for r in results if r["config_type"] == "sc"]

    all_scores = [r["score_avg"] for r in results if r["score_avg"] > 0]

    summary = {
        "total_configs": total_configs,
        "sfp_configs": len(sfp_configs),
        "sc_configs": len(sc_configs),
        "configs_with_extra_bag": sum(1 for r in results if r["has_extra_bag"]),
        "score_statistics": {},
        "per_config": {},
    }

    if all_scores:
        summary["score_statistics"] = {
            "mean": round(sum(all_scores) / len(all_scores), 4),
            "min": round(min(all_scores), 4),
            "max": round(max(all_scores), 4),
            "num_scored": len(all_scores),
        }

    for r in results:
        summary["per_config"][r["config_name"]] = {
            "type": r["config_type"],
            "score_avg": round(r["score_avg"], 4),
            "num_trials": len(r["trials"]),
            "has_extra_bag": r["has_extra_bag"],
        }

    with open(output_path, "w") as f:
        yaml.dump(summary, f, default_flow_style=False, sort_keys=False)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <data_dir>", file=sys.stderr)
        sys.exit(1)

    data_dir = Path(sys.argv[1])
    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    # Find all config output directories
    results: list[dict] = []
    for config_dir in sorted(data_dir.iterdir()):
        if not config_dir.is_dir():
            continue
        # Skip non-config directories
        if config_dir.name in ("logs",):
            continue
        r = parse_config_results(config_dir)
        if r is not None:
            results.append(r)

    if not results:
        print("No results found.", file=sys.stderr)
        sys.exit(0)

    # Write outputs
    csv_path = data_dir / "summary.csv"
    yaml_path = data_dir / "summary.yaml"

    write_csv(results, csv_path)
    write_yaml_summary(results, yaml_path)

    print(f"Summary: {len(results)} configs", file=sys.stderr)
    print(f"  CSV:  {csv_path}", file=sys.stderr)
    print(f"  YAML: {yaml_path}", file=sys.stderr)

    # Print quick stats
    all_scores = [r["score_avg"] for r in results if r["score_avg"] > 0]
    if all_scores:
        mean = sum(all_scores) / len(all_scores)
        print(f"  Mean score: {mean:.2f} (n={len(all_scores)})", file=sys.stderr)


if __name__ == "__main__":
    main()
