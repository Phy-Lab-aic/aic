# Cheatcode Benchmark Leaderboard

> 5 configs x 3 trials = 15 trials per policy. Score: average total across all trials (max 100).

**Baseline (CheatCode): 58.98 / 100**

| Rank | Policy | Author | Avg | Min | Max | T1 | T2 | T3 | Trials | Date |
|------|--------|--------|-----|-----|-----|----|----|----|--------|------|
| 1 | AutoCode | [@weedmo](https://github.com/weedmo) | 71.96 | 44.18661433953373 | 95.99283947546087 | 1.0 | 19.66 | 51.3 | 15/15 | 2026-04-05 |
| 2 | CheatCode | [@weedmo](https://github.com/weedmo) | 58.98 | 24.559954128460088 | 93.29406747263644 | 1.0 | 16.92 | 41.06 | 15/15 | 2026-04-04 |

## How to Run

1. Create a policy module under your package, for example `your_package/ros/MyPolicy.py`.
2. Make sure the policy is importable as `your_package.ros.MyPolicy` from the benchmark environment.
3. Run the full benchmark runner to build, launch simulation, execute all 5 configs, and collect scores.

```bash
# Run benchmark for your policy
./benchmark/scripts/run_benchmark.sh your_package.ros.YourPolicy

# CheatCode baseline (needs --ground-truth)
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --ground-truth
```

4. Inspect generated artifacts:
   - Per-config scoring: `benchmark/results/<PolicyName>/`
   - Submission history: `benchmark/submissions/`
   - Leaderboard files: `benchmark/leaderboard.yaml`, `benchmark/LEADERBOARD.md`
5. Commit your policy, submission YAML, and regenerated leaderboard files to your branch.
6. Push the branch and open a PR, or merge according to your repository workflow.

```bash
# Example: commit benchmark outputs and push your branch
git add benchmark/submissions benchmark/leaderboard.yaml benchmark/LEADERBOARD.md
git add your_package
git commit -m "Add MyPolicy benchmark submission"
git push origin <your-branch>
```
