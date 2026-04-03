# Cheatcode Benchmark Leaderboard

> 5 configs x 3 trials = 15 trials per policy. Score: average total across all trials (max 100).

**Baseline (CheatCode): N/A / 100**

| Rank | Policy | Avg | Min | Max | T1 | T2 | T3 | Trials | Date | Branch |
|------|--------|-----|-----|-----|----|----|----|--------|------|--------|

*No entries yet. Run the benchmark to populate.*

## How to Run

```bash
# Run benchmark for your policy
./benchmark/scripts/run_benchmark.sh your_package.ros.YourPolicy

# CheatCode baseline (needs --ground-truth)
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --ground-truth
```
