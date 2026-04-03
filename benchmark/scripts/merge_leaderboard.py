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
SCORE_HISTORY_SVG = BENCHMARK_DIR / "score_history.svg"
TOTAL_TRIALS = 15
DEFAULT_GITHUB_IDS = {
    "aic_example_policies.ros.AutoCode": "weedmo",
}


def extract_class_name(policy_module: str) -> str:
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
    history = load_submission_history()
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

    history = load_submission_history()
    write_score_history_svg(history)
    md = generate_markdown(merged, baseline)
    with open(LEADERBOARD_MD, "w") as f:
        f.write(md)

    print(f"Merged {len(submissions)} submissions + {len(existing)} existing -> {len(merged)} entries")
    for i, e in enumerate(merged, 1):
        print(f"  #{i} {extract_class_name(e['policy'])}: {e['avg_score']}")


if __name__ == "__main__":
    main()
