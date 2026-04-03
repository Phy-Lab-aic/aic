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
SCORE_HISTORY_SVG = BENCHMARK_DIR / "score_history.svg"
NUM_CONFIGS = 5
TRIALS_PER_CONFIG = 3
TOTAL_TRIALS = NUM_CONFIGS * TRIALS_PER_CONFIG
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


def policy_color(index: int, total: int) -> str:
    """Generate a stable visually distinct color per policy."""
    hue = int((index * 360) / max(total, 1))
    return f"hsl({hue}, 70%, 45%)"


def generate_score_history_svg(history: dict[str, list[dict]]) -> str:
    """Generate a single SVG line chart for all policy histories."""
    if not history:
        return ""

    labels = sorted({point["label"] for points in history.values() for point in points})
    width = 1200
    height = 520
    left = 80
    right = 220
    top = 50
    bottom = 70
    plot_w = width - left - right
    plot_h = height - top - bottom

    def x_pos(i: int) -> float:
        if len(labels) == 1:
            return left + plot_w / 2
        return left + (plot_w * i / (len(labels) - 1))

    def y_pos(score: float) -> float:
        return top + plot_h - (score / 100.0) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Policy score history">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="80" y="28" font-size="20" font-family="Arial, sans-serif" fill="#111827">'
        'Policy Score History</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#374151" stroke-width="2"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#374151" stroke-width="2"/>',
    ]

    for tick in range(0, 101, 20):
        y = y_pos(tick)
        parts.append(
            f'<line x1="{left}" y1="{y}" x2="{left + plot_w}" y2="{y}" stroke="#e5e7eb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 12}" y="{y + 5}" text-anchor="end" font-size="12" '
            f'font-family="Arial, sans-serif" fill="#4b5563">{tick}</text>'
        )

    for i, label in enumerate(labels):
        x = x_pos(i)
        parts.append(
            f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top + plot_h}" stroke="#f3f4f6" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x}" y="{top + plot_h + 22}" text-anchor="end" '
            f'transform="rotate(-35 {x} {top + plot_h + 22})" font-size="11" '
            f'font-family="Arial, sans-serif" fill="#4b5563">{label}</text>'
        )

    policies = sorted(history.items())
    for index, (policy, points) in enumerate(policies):
        color = policy_color(index, len(policies))
        by_label = {point["label"]: point["avg_score"] for point in points}
        ordered = [(x_pos(i), y_pos(by_label[label])) for i, label in enumerate(labels) if label in by_label]
        if not ordered:
            continue
        path = " ".join(
            f'{"M" if i == 0 else "L"} {x:.2f} {y:.2f}'
            for i, (x, y) in enumerate(ordered)
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for x, y in ordered:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="{color}" stroke="white" stroke-width="1.5"/>')

    legend_x = left + plot_w + 24
    legend_y = top + 10
    for index, (policy, _) in enumerate(policies):
        color = policy_color(index, len(policies))
        name = extract_class_name(policy)
        y = legend_y + index * 22
        parts.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 18}" y2="{y}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<circle cx="{legend_x + 9}" cy="{y}" r="4" fill="{color}" stroke="white" stroke-width="1"/>')
        parts.append(
            f'<text x="{legend_x + 26}" y="{y + 4}" font-size="12" font-family="Arial, sans-serif" fill="#111827">{name}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def write_score_history_svg(history: dict[str, list[dict]]) -> None:
    """Write score history SVG for GitHub markdown embedding."""
    if not history:
        if SCORE_HISTORY_SVG.exists():
            SCORE_HISTORY_SVG.unlink()
        return
    SCORE_HISTORY_SVG.write_text(generate_score_history_svg(history))


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
    history = history if history is not None else load_submission_history()
    lines = [
        "# Cheatcode Benchmark Leaderboard",
        "",
        f"> 5 configs x 3 trials = {TOTAL_TRIALS} trials per policy. "
        "Score: average total across all trials (max 100).",
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
    if history:
        lines.extend([
            "",
            "## Score History",
            "",
            "![Policy Score History](score_history.svg)",
        ])
    lines.extend([
        "",
        "## How to Run",
        "",
        "1. Create a policy module under your package, for example `your_package/ros/MyPolicy.py`.",
        "2. Make sure the policy is importable as `your_package.ros.MyPolicy` from the benchmark environment.",
        "3. Run the full benchmark runner to build, launch simulation, execute all 5 configs, and collect scores.",
        "",
        "```bash",
        "# Run benchmark for your policy",
        "./benchmark/scripts/run_benchmark.sh your_package.ros.YourPolicy",
        "",
        "# CheatCode baseline (needs --ground-truth)",
        "./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --ground-truth",
        "```",
        "",
        "4. Inspect generated artifacts:",
        "   - Per-config scoring: `benchmark/results/<PolicyName>/`",
        "   - Submission history: `benchmark/submissions/`",
        "   - Leaderboard files: `benchmark/leaderboard.yaml`, `benchmark/LEADERBOARD.md`, `benchmark/score_history.svg`",
        "5. Commit your policy, submission YAML, and regenerated leaderboard files to your branch.",
        "6. Push the branch and open a PR, or merge according to your repository workflow.",
        "",
        "```bash",
        "# Example: commit benchmark outputs and push your branch",
        "git add benchmark/submissions benchmark/leaderboard.yaml benchmark/LEADERBOARD.md benchmark/score_history.svg",
        "git add your_package",
        "git commit -m \"Add MyPolicy benchmark submission\"",
        "git push origin <your-branch>",
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
    history = load_submission_history()
    write_score_history_svg(history)
    md_content = generate_markdown(lb, history)
    with open(LEADERBOARD_MD, "w") as f:
        f.write(md_content)
    print(f"Markdown updated: {LEADERBOARD_MD}")


if __name__ == "__main__":
    main()
