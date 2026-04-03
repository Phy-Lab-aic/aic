# Cheatcode Benchmark Leaderboard

> 5 configs x 3 trials = 15 trials per policy. Score: average total across all trials (max 100).

**Baseline (CheatCode): 70.46 / 100**

| Rank | Policy | Avg | Min | Max | T1 | T2 | T3 | Trials | Date | Branch |
|------|--------|-----|-----|-----|----|----|----|--------|------|--------|
| 1 | CheatCode | 70.46 | 25.244954956583868 | 93.37511998463496 | 1.0 | 16.84 | 52.62 | 15/15 | 2026-04-04 | cheatcode-leaderboard |

## How to Run

```bash
# Run benchmark for your policy
./benchmark/scripts/run_benchmark.sh your_package.ros.YourPolicy

# CheatCode baseline (needs --ground-truth)
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --ground-truth
```
