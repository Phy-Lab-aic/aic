# Cheatcode Benchmark Leaderboard

> 5 configs x 3 trials = 15 trials per policy. Score: average total across all trials (max 100).

**Baseline (CheatCode): 70.46 / 100**

| Rank | Policy | Author | Avg | Min | Max | T1 | T2 | T3 | Trials | Date | Branch |
|------|--------|--------|-----|-----|-----|----|----|----|--------|------|--------|
| 1 | CheatCode | [@weedmo](https://github.com/weedmo) | 70.46 | 25.244954956583868 | 93.37511998463496 | 1.0 | 16.84 | 52.62 | 15/15 | 2026-04-04 | cheatcode-leaderboard |

## How to Submit Your Policy

### Step 1: Create your policy

Add your policy file under `aic_example_policies/aic_example_policies/ros/YourPolicy.py`.
The class name must match the filename (e.g. `AutoCode` in `AutoCode.py`).

```python
from aic_model.policy import Policy

class YourPolicy(Policy):
    def insert_cable(self, task, get_observation, move_robot, send_feedback):
        # Your implementation here
        ...
        return True
```

### Step 2: Run the benchmark

```bash
# Run benchmark (5 configs x 3 trials = 15 trials)
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.YourPolicy

# CheatCode baseline (needs --ground-truth)
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --ground-truth

# Options:
#   --ground-truth    Use ground truth TF (required for CheatCode)
#   --skip-build      Skip colcon build step
```

The script will:
1. Build the policy package (`colcon build`)
2. Run each benchmark config with up to 5 retries on failure
3. Display per-config score tables
4. Generate a submission file in `benchmark/submissions/`
5. Update `leaderboard.yaml` and `LEADERBOARD.md` (only if the new score beats the existing record)

### Step 3: Push to trigger the leaderboard

```bash
# Stage and commit your policy + submission
git add aic_example_policies/aic_example_policies/ros/YourPolicy.py
git add benchmark/submissions/YourPolicy*.yaml
git add benchmark/leaderboard.yaml benchmark/LEADERBOARD.md
git commit -m "feat(benchmark): add YourPolicy submission"

# Push to the phy-lab remote (cheatcode-leaderboard branch)
git push phy-lab cheatcode-leaderboard
```

The GitHub Actions workflow triggers on push to `cheatcode-leaderboard` when `benchmark/submissions/*.yaml` changes. It merges all submissions and updates the leaderboard.

### Prerequisites

- `aic_eval` Docker container running
- `pixi` environment set up
- Ground truth TF enabled for CheatCode-based policies
