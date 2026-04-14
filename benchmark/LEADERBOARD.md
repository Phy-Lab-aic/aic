# Cheatcode Benchmark Leaderboard

> Score: average total across all trials (max 100).

**Baseline (CheatCode): 91.01 / 100**

| Rank | Policy | Author | Avg | Min | Max | T1 | T2 | T3 | Trials | Date |
|------|--------|--------|-----|-----|-----|----|----|----|--------|------|
| 1 | OptimalPolicy | [@JJhyeongg](https://github.com/JJhyeongg) | 97.47 | 96.81587792947846 | 98.01029593846964 | 1.0 | 21.47 | 75.0 | 20/20 | 2026-04-15 |
| 2 | AutoCode | [@JJhyeongg](https://github.com/JJhyeongg) | 93.53 | 93.28367222888124 | 93.92752455347886 | 1.0 | 17.53 | 75.0 | 20/20 | 2026-04-14 |
| 3 | CheatCode | [@JJhyeongg](https://github.com/JJhyeongg) | 91.01 | 55.867792021257856 | 93.16639523133605 | 1.0 | 16.86 | 73.15 | 20/20 | 2026-04-14 |
| 4 | PilzPolicy | [@JJhyeongg](https://github.com/JJhyeongg) | 76.84 | 28.811664174620667 | 96.44722159949384 | 1.0 | 15.83 | 60.01 | 36/36 | 2026-04-14 |

## How to Run

### Config 생성

```bash
# SFP 단일 trial 10개 생성
python3 benchmark/scripts/gen_benchmark_configs.py --type sfp --n 10

# SC 단일 trial 10개 생성
python3 benchmark/scripts/gen_benchmark_configs.py --type sc --n 10

# Mixed 3-trial (SFP×2 + SC×1) 5개 생성
python3 benchmark/scripts/gen_benchmark_configs.py --type mixed --n 5

# Seed 고정 (재현성)
python3 benchmark/scripts/gen_benchmark_configs.py --type sfp --n 10 --seed 42
```

### Benchmark 실행

```bash
# PilzPolicy — SFP configs만 실행
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy --type sfp --skip-build

# PilzPolicy — SC configs만 실행
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy --type sc --skip-build

# PilzPolicy — mixed (3-trial) configs 실행
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy --type mixed

# PilzPolicy — 전체 configs 실행 (sfp + sc + mixed)
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy

# CheatCode baseline (needs --ground-truth)
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --type mixed --ground-truth
```

### Config 디렉토리 구조

```
benchmark/configs/
├── sfp/       benchmark_XXXX_*.yaml   (1 trial, SFP only)
├── sc/        benchmark_XXXX_*.yaml   (1 trial, SC only)
└── mixed/     benchmark_XXXX_*.yaml   (3 trials, SFP×2 + SC×1)
```

### 결과 확인

실행 결과는 타임스탬프 기반으로 분리 저장됩니다:

```
benchmark/results/PilzPolicy_sfp_20260414_153022/
benchmark/logs/PilzPolicy_sfp_20260414_153022/
```

- Per-config scoring: `benchmark/results/<Policy>_<type>_<timestamp>/`
- Logs: `benchmark/logs/<Policy>_<type>_<timestamp>/`
- Submission history: `benchmark/submissions/`
- Leaderboard: `benchmark/leaderboard.yaml`, `benchmark/LEADERBOARD.md`
