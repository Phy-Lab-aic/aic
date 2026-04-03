#!/usr/bin/env python3
"""Merge all submission files into leaderboard.yaml and regenerate LEADERBOARD.md.

Reads every YAML file in benchmark/submissions/, merges entries
(newest wins per policy), sorts by avg_score descending, and writes
the canonical leaderboard files. Designed to run in GitHub Actions
after a PR merge so that YAML merge conflicts never occur.
"""
import sys
from pathlib import Path

import yaml

BENCHMARK_DIR = Path(__file__).resolve().parent.parent
SUBMISSIONS_DIR = BENCHMARK_DIR / "submissions"
LEADERBOARD_YAML = BENCHMARK_DIR / "leaderboard.yaml"
LEADERBOARD_MD = BENCHMARK_DIR / "LEADERBOARD.md"
TOTAL_TRIALS = 15


def extract_class_name(policy_module: str) -> str:
    return policy_module.rsplit(".", 1)[-1]


def normalize_entry(entry: dict) -> dict:
    """Remove deprecated fields from leaderboard entries."""
    normalized = dict(entry)
    normalized.pop("branch", None)
    return normalized


def load_submissions() -> list[dict]:
    """Load all submission YAML files, keeping only the highest score per policy."""
    by_policy: dict[str, dict] = {}
    for path in sorted(SUBMISSIONS_DIR.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        if data and "policy" in data:
            data = normalize_entry(data)
            policy = data["policy"]
            if policy not in by_policy or data.get("avg_score", 0) > by_policy[policy].get("avg_score", 0):
                by_policy[policy] = data
    return list(by_policy.values())


def load_existing_leaderboard() -> list[dict]:
    """Load entries from current leaderboard.yaml."""
    if not LEADERBOARD_YAML.is_file():
        return []
    with open(LEADERBOARD_YAML) as f:
        lb = yaml.safe_load(f) or {}
    return [normalize_entry(entry) for entry in lb.get("entries", [])]


def merge_entries(existing: list[dict], submissions: list[dict]) -> list[dict]:
    """Merge submissions into existing entries. Highest avg_score wins per policy."""
    by_policy: dict[str, dict] = {}
    for entry in existing:
        by_policy[entry["policy"]] = normalize_entry(entry)
    for entry in submissions:
        entry = normalize_entry(entry)
        policy = entry["policy"]
        if policy in by_policy:
            existing_entry = by_policy[policy]
            # Backfill github_id in whichever direction has it
            if entry.get("github_id") and not existing_entry.get("github_id"):
                existing_entry["github_id"] = entry["github_id"]
            elif existing_entry.get("github_id") and not entry.get("github_id"):
                entry["github_id"] = existing_entry["github_id"]
        if policy not in by_policy or entry.get("avg_score", 0) > by_policy[policy].get("avg_score", 0):
            by_policy[policy] = entry
    merged = list(by_policy.values())
    merged.sort(key=lambda e: e.get("avg_score", 0), reverse=True)
    return merged


def write_leaderboard(entries: list[dict]) -> None:
    """Write leaderboard.yaml."""
    baseline = None
    for e in entries:
        if "CheatCode" in e.get("policy", ""):
            baseline = e["avg_score"]
            break
    lb = {"baseline_score": baseline, "entries": entries}
    with open(LEADERBOARD_YAML, "w") as f:
        yaml.dump(lb, f, default_flow_style=False, sort_keys=False)


def generate_markdown(entries: list[dict], baseline) -> str:
    """Generate LEADERBOARD.md content."""
    lines = [
        "# Cheatcode Benchmark Leaderboard",
        "",
        f"> 5 configs x 3 trials = {TOTAL_TRIALS} trials per policy. "
        "Score: average total across all trials (max 100).",
        "",
        f"**Baseline (CheatCode): {baseline if baseline is not None else 'N/A'} / 100**",
        "",
        "| Rank | Policy | Author | Avg | Min | Max | T1 | T2 | T3 | Trials | Date |",
        "|------|--------|--------|-----|-----|-----|----|----|----|--------|------|",
    ]
    for i, e in enumerate(entries, 1):
        name = extract_class_name(e["policy"])
        github_id = e.get("github_id", "")
        author = f"[@{github_id}](https://github.com/{github_id})" if github_id else ""
        lines.append(
            f"| {i} | {name} | {author} | {e['avg_score']} | {e['min_score']} | "
            f"{e['max_score']} | {e['tier1_avg']} | {e['tier2_avg']} | "
            f"{e['tier3_avg']} | {e['trials_completed']}/{e['trials_total']} | "
            f"{e['date']} |"
        )
    if not entries:
        lines.append("")
        lines.append("*No entries yet. Run the benchmark to populate.*")
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
    existing = load_existing_leaderboard()
    submissions = load_submissions()

    if not submissions and not existing:
        print("No submissions or existing entries found.")
        return

    merged = merge_entries(existing, submissions)
    write_leaderboard(merged)

    baseline = None
    for e in merged:
        if "CheatCode" in e.get("policy", ""):
            baseline = e["avg_score"]
            break

    md = generate_markdown(merged, baseline)
    with open(LEADERBOARD_MD, "w") as f:
        f.write(md)

    print(f"Merged {len(submissions)} submissions + {len(existing)} existing -> {len(merged)} entries")
    for i, e in enumerate(merged, 1):
        print(f"  #{i} {extract_class_name(e['policy'])}: {e['avg_score']}")


if __name__ == "__main__":
    main()
