#!/usr/bin/env python3
"""Parse benchmark scoring results and update the leaderboard."""
import argparse
import os
import subprocess
from datetime import date
from pathlib import Path

import yaml


BENCHMARK_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BENCHMARK_DIR / "results"
SUBMISSIONS_DIR = BENCHMARK_DIR / "submissions"
LEADERBOARD_YAML = BENCHMARK_DIR / "leaderboard.yaml"
LEADERBOARD_MD = BENCHMARK_DIR / "LEADERBOARD.md"
NUM_CONFIGS = 5
TRIALS_PER_CONFIG = 3
TOTAL_TRIALS = NUM_CONFIGS * TRIALS_PER_CONFIG


def extract_class_name(policy_module: str) -> str:
    """Extract class name from module path. e.g. 'pkg.ros.CheatCode' -> 'CheatCode'"""
    return policy_module.rsplit(".", 1)[-1]


def parse_scoring_yaml(path: str) -> list[dict]:
    """Parse a scoring.yaml and return per-trial score dicts."""
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    trials = []
    for key in sorted(data.keys()):
        if not key.startswith("trial_"):
            continue
        trial = data[key]
        t1 = float(trial.get("tier_1", {}).get("score", 0))
        t2 = float(trial.get("tier_2", {}).get("score", 0))
        t3 = float(trial.get("tier_3", {}).get("score", 0))
        trials.append({
            "tier1": t1,
            "tier2": t2,
            "tier3": t3,
            "total": t1 + t2 + t3,
        })
    return trials


def compute_averages(all_trials: list[dict]) -> dict:
    """Compute average scores across all trials."""
    if not all_trials:
        return {
            "avg_score": 0.0, "tier1_avg": 0.0, "tier2_avg": 0.0,
            "tier3_avg": 0.0, "min_score": 0.0, "max_score": 0.0,
            "trials_completed": 0,
        }
    n = len(all_trials)
    totals = [t["total"] for t in all_trials]
    return {
        "avg_score": round(sum(totals) / n, 2),
        "tier1_avg": round(sum(t["tier1"] for t in all_trials) / n, 2),
        "tier2_avg": round(sum(t["tier2"] for t in all_trials) / n, 2),
        "tier3_avg": round(sum(t["tier3"] for t in all_trials) / n, 2),
        "min_score": min(totals),
        "max_score": max(totals),
        "trials_completed": n,
    }


def update_leaderboard(lb_path: str, entry: dict) -> None:
    """Update or insert an entry in the leaderboard YAML.

    Only updates if the new entry has a higher avg_score than the existing one.
    """
    if os.path.isfile(lb_path):
        with open(lb_path) as f:
            lb = yaml.safe_load(f) or {}
    else:
        lb = {}
    if "entries" not in lb:
        lb["entries"] = []
    existing = [e for e in lb["entries"] if e["policy"] == entry["policy"]]
    if existing and existing[0]["avg_score"] >= entry["avg_score"]:
        print(f"  Existing score ({existing[0]['avg_score']}) >= new score ({entry['avg_score']}), leaderboard unchanged.")
        return
    lb["entries"] = [e for e in lb["entries"] if e["policy"] != entry["policy"]]
    lb["entries"].append(entry)
    lb["entries"].sort(key=lambda e: e["avg_score"], reverse=True)
    for e in lb["entries"]:
        if "CheatCode" in e["policy"]:
            lb["baseline_score"] = e["avg_score"]
            break
    with open(lb_path, "w") as f:
        yaml.dump(lb, f, default_flow_style=False, sort_keys=False)


def generate_markdown(lb: dict) -> str:
    """Generate LEADERBOARD.md content from leaderboard data."""
    baseline = lb.get("baseline_score", "N/A")
    lines = [
        "# Cheatcode Benchmark Leaderboard",
        "",
        f"> 5 configs x 3 trials = {TOTAL_TRIALS} trials per policy. "
        "Score: average total across all trials (max 100).",
        "",
        f"**Baseline (CheatCode): {baseline} / 100**",
        "",
        "| Rank | Policy | Author | Avg | Min | Max | T1 | T2 | T3 | Trials | Date | Branch |",
        "|------|--------|--------|-----|-----|-----|----|----|----|--------|------|--------|",
    ]
    for i, e in enumerate(lb.get("entries", []), 1):
        name = extract_class_name(e["policy"])
        author = e.get("github_id", "")
        lines.append(
            f"| {i} | {name} | {author} | {e['avg_score']} | {e['min_score']} | "
            f"{e['max_score']} | {e['tier1_avg']} | {e['tier2_avg']} | "
            f"{e['tier3_avg']} | {e['trials_completed']}/{e['trials_total']} | "
            f"{e['date']} | {e['branch']} |"
        )
    lines.extend([
        "",
        "## How to Run",
        "",
        "```bash",
        "# Run benchmark for your policy",
        "./benchmark/scripts/run_benchmark.sh your_package.ros.YourPolicy",
        "",
        "# CheatCode baseline (needs --ground-truth)",
        "./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --ground-truth",
        "```",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Collect benchmark scores and update leaderboard")
    parser.add_argument("policy", help="Full policy module path (e.g. aic_example_policies.ros.CheatCode)")
    parser.add_argument("--branch", default=None, help="Branch name (auto-detected if not provided)")
    parser.add_argument("--github-id", default=None, help="GitHub username (auto-detected from git config if not provided)")
    args = parser.parse_args()

    class_name = extract_class_name(args.policy)
    results_path = RESULTS_DIR / class_name

    branch = args.branch
    if branch is None:
        try:
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"], text=True
            ).strip()
        except Exception:
            branch = "unknown"

    github_id = args.github_id
    if github_id is None:
        try:
            github_id = subprocess.check_output(
                ["git", "config", "user.name"], text=True
            ).strip()
        except Exception:
            github_id = "unknown"

    all_trials = []
    for scoring_file in sorted(results_path.glob("*_scoring.yaml")):
        trials = parse_scoring_yaml(str(scoring_file))
        all_trials.extend(trials)

    avg = compute_averages(all_trials)
    print(f"Policy: {args.policy} ({class_name})")
    print(f"Trials completed: {avg['trials_completed']}/{TOTAL_TRIALS}")
    print(f"Average score: {avg['avg_score']}")
    print(f"  Tier1: {avg['tier1_avg']}, Tier2: {avg['tier2_avg']}, Tier3: {avg['tier3_avg']}")
    print(f"  Min: {avg['min_score']}, Max: {avg['max_score']}")

    entry = {
        "policy": args.policy,
        "avg_score": avg["avg_score"],
        "tier1_avg": avg["tier1_avg"],
        "tier2_avg": avg["tier2_avg"],
        "tier3_avg": avg["tier3_avg"],
        "min_score": avg["min_score"],
        "max_score": avg["max_score"],
        "date": str(date.today()),
        "github_id": github_id,
        "branch": branch,
        "trials_completed": avg["trials_completed"],
        "trials_total": TOTAL_TRIALS,
    }

    # Write timestamped submission file (accumulates history per policy)
    SUBMISSIONS_DIR.mkdir(exist_ok=True)
    timestamp = date.today().isoformat().replace("-", "") + "_" + \
        __import__("time").strftime("%H%M%S")
    submission_path = SUBMISSIONS_DIR / f"{class_name}_{timestamp}.yaml"
    with open(submission_path, "w") as f:
        yaml.dump(entry, f, default_flow_style=False, sort_keys=False)
    print(f"\nSubmission written: {submission_path}")

    update_leaderboard(str(LEADERBOARD_YAML), entry)
    print(f"Leaderboard updated: {LEADERBOARD_YAML}")

    with open(LEADERBOARD_YAML) as f:
        lb = yaml.safe_load(f)
    md_content = generate_markdown(lb)
    with open(LEADERBOARD_MD, "w") as f:
        f.write(md_content)
    print(f"Markdown updated: {LEADERBOARD_MD}")


if __name__ == "__main__":
    main()
