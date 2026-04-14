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
DEFAULT_GITHUB_IDS = {
    "aic_example_policies.ros.AutoCode": "weedmo",
}


def extract_class_name(policy_module: str) -> str:
    """Extract class name from module path. e.g. 'pkg.ros.CheatCode' -> 'CheatCode'"""
    return policy_module.rsplit(".", 1)[-1]


def normalize_entry(entry: dict) -> dict:
    """Remove deprecated fields from leaderboard entries."""
    normalized = dict(entry)
    normalized.pop("branch", None)
    if not normalized.get("github_id") or normalized.get("github_id") == "unknown":
        normalized["github_id"] = DEFAULT_GITHUB_IDS.get(normalized.get("policy"), "")
    return normalized


def load_submission_history(submissions_dir: Path = SUBMISSIONS_DIR) -> dict[str, list[dict]]:
    """Load timestamped submission history grouped by policy."""
    history: dict[str, list[dict]] = {}
    for path in sorted(submissions_dir.glob("*.yaml")):
        stem = path.stem
        parts = stem.rsplit("_", 2)
        if len(parts) != 3:
            continue
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data or "policy" not in data:
            continue
        policy = data["policy"]
        history.setdefault(policy, []).append({
            "label": f"{parts[1]}-{parts[2]}",
            "avg_score": round(float(data.get("avg_score", 0.0)), 2),
        })
    return history


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
    lb["entries"] = [normalize_entry(e) for e in lb["entries"]]
    entry = normalize_entry(entry)
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


def generate_markdown(
    lb: dict,
    history: dict[str, list[dict]] | None = None,
) -> str:
    """Generate LEADERBOARD.md content from leaderboard data."""
    baseline = lb.get("baseline_score", "N/A")
    lines = [
        "# Cheatcode Benchmark Leaderboard",
        "",
        "> Score: average total across all trials (max 100).",
        "",
        f"**Baseline (CheatCode): {baseline} / 100**",
        "",
        "| Rank | Policy | Author | Avg | Min | Max | T1 | T2 | T3 | Trials | Date |",
        "|------|--------|--------|-----|-----|-----|----|----|----|--------|------|",
    ]
    for i, e in enumerate(lb.get("entries", []), 1):
        name = extract_class_name(e["policy"])
        github_id = e.get("github_id", "")
        author = f"[@{github_id}](https://github.com/{github_id})" if github_id else ""
        lines.append(
            f"| {i} | {name} | {author} | {e['avg_score']} | {e['min_score']} | "
            f"{e['max_score']} | {e['tier1_avg']} | {e['tier2_avg']} | "
            f"{e['tier3_avg']} | {e['trials_completed']}/{e['trials_total']} | "
            f"{e['date']} |"
        )
    lines.extend([
        "",
        "## How to Run",
        "",
        "### Config 생성",
        "",
        "```bash",
        "# SFP 단일 trial 10개 생성",
        "python3 benchmark/scripts/gen_benchmark_configs.py --type sfp --n 10",
        "",
        "# SC 단일 trial 10개 생성",
        "python3 benchmark/scripts/gen_benchmark_configs.py --type sc --n 10",
        "",
        "# Mixed 3-trial (SFP×2 + SC×1) 5개 생성",
        "python3 benchmark/scripts/gen_benchmark_configs.py --type mixed --n 5",
        "",
        "# Seed 고정 (재현성)",
        "python3 benchmark/scripts/gen_benchmark_configs.py --type sfp --n 10 --seed 42",
        "```",
        "",
        "### Benchmark 실행",
        "",
        "```bash",
        "# PilzPolicy — SFP configs만 실행",
        "./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy --type sfp --skip-build",
        "",
        "# PilzPolicy — SC configs만 실행",
        "./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy --type sc --skip-build",
        "",
        "# PilzPolicy — mixed (3-trial) configs 실행",
        "./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy --type mixed",
        "",
        "# PilzPolicy — 전체 configs 실행 (sfp + sc + mixed)",
        "./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy",
        "",
        "# CheatCode baseline (needs --ground-truth)",
        "./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --type mixed --ground-truth",
        "```",
        "",
        "### Config 디렉토리 구조",
        "",
        "```",
        "benchmark/configs/",
        "├── sfp/       benchmark_XXXX_*.yaml   (1 trial, SFP only)",
        "├── sc/        benchmark_XXXX_*.yaml   (1 trial, SC only)",
        "└── mixed/     benchmark_XXXX_*.yaml   (3 trials, SFP×2 + SC×1)",
        "```",
        "",
        "### 결과 확인",
        "",
        "실행 결과는 타임스탬프 기반으로 분리 저장됩니다:",
        "",
        "```",
        "benchmark/results/PilzPolicy_sfp_20260414_153022/",
        "benchmark/logs/PilzPolicy_sfp_20260414_153022/",
        "```",
        "",
        "- Per-config scoring: `benchmark/results/<Policy>_<type>_<timestamp>/`",
        "- Logs: `benchmark/logs/<Policy>_<type>_<timestamp>/`",
        "- Submission history: `benchmark/submissions/`",
        "- Leaderboard: `benchmark/leaderboard.yaml`, `benchmark/LEADERBOARD.md`",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Collect benchmark scores and update leaderboard")
    parser.add_argument("policy", help="Full policy module path (e.g. aic_example_policies.ros.CheatCode)")
    parser.add_argument("--results-dir", default=None, help="Path to results directory (default: auto-detect from policy name)")
    parser.add_argument("--branch", default=None, help="Branch name (auto-detected if not provided)")
    parser.add_argument("--github-id", default=None, help="GitHub username (auto-detected from git config if not provided)")
    args = parser.parse_args()

    class_name = extract_class_name(args.policy)
    if args.results_dir:
        results_path = Path(args.results_dir)
    else:
        results_path = RESULTS_DIR / class_name

    github_id = args.github_id
    if github_id is None:
        try:
            github_id = subprocess.check_output(
                ["git", "config", "user.name"], text=True
            ).strip()
        except Exception:
            github_id = "unknown"

    all_trials = []
    n_configs = 0
    for scoring_file in sorted(results_path.glob("*_scoring.yaml")):
        trials = parse_scoring_yaml(str(scoring_file))
        all_trials.extend(trials)
        n_configs += 1

    avg = compute_averages(all_trials)
    trials_total = avg["trials_completed"]
    print(f"Policy: {args.policy} ({class_name})")
    print(f"Configs: {n_configs}, Trials completed: {trials_total}")
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
        "trials_completed": trials_total,
        "trials_total": trials_total,
        "configs": n_configs,
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
    md_content = generate_markdown(lb, {})
    with open(LEADERBOARD_MD, "w") as f:
        f.write(md_content)
    print(f"Markdown updated: {LEADERBOARD_MD}")


if __name__ == "__main__":
    main()
