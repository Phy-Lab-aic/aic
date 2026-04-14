# Benchmark

Policy 성능을 다양한 scene config에 대해 측정하는 벤치마크 도구.

## 디렉토리 구조

```
benchmark/
├── configs/
│   ├── sfp/           SFP 단일 trial configs
│   ├── sc/            SC 단일 trial configs
│   ├── mixed/         3-trial configs (SFP×2 + SC×1)
│   └── zenoh_session_config.json5
├── scripts/
│   ├── gen_benchmark_configs.py   Config 생성
│   ├── run_benchmark.sh           Benchmark 실행
│   ├── collect_scores.py          점수 집계 / 리더보드 업데이트
│   └── merge_leaderboard.py
├── results/           타임스탬프별 scoring 결과
├── logs/              타임스탬프별 실행 로그
├── submissions/       제출 이력
├── leaderboard.yaml
└── LEADERBOARD.md
```

## 1. Config 생성

```bash
cd src/aic

# SFP 단일 trial 10개
python3 benchmark/scripts/gen_benchmark_configs.py --type sfp --n 10

# SC 단일 trial 10개
python3 benchmark/scripts/gen_benchmark_configs.py --type sc --n 10

# Mixed 3-trial (SFP×2 + SC×1) 5개
python3 benchmark/scripts/gen_benchmark_configs.py --type mixed --n 5
```

옵션:

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--type` | `sfp`, `sc`, `mixed` | 필수 |
| `--n` | 생성 개수 | 1 |
| `--seed` | 랜덤 시드 (재현성) | 랜덤 |
| `--name` | 파일명 suffix | type 이름 |

생성 결과 예시:

```
benchmark/configs/sfp/benchmark_0000_sfp_0.yaml
benchmark/configs/sfp/benchmark_0001_sfp_1.yaml
...
```

## 2. Benchmark 실행

```bash
cd src/aic

# PilzPolicy — SFP configs만
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy \
    --type sfp --ground-truth --skip-build

# PilzPolicy — SC configs만
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy \
    --type sc --ground-truth --skip-build

# PilzPolicy — mixed configs
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy \
    --type mixed --ground-truth

# PilzPolicy — 전체 (sfp + sc + mixed)
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy \
    --ground-truth

# CheatCode baseline
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode \
    --type mixed --ground-truth

# CheatCode — SFP configs만
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode \
    --type sfp --ground-truth 

# AutoCode baseline
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.AutoCode \
    --type mixed --ground-truth

# AutoCode — SFP configs만
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.AutoCode \
    --type sfp --ground-truth 

```

옵션:

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--type` | `sfp`, `sc`, `mixed` (생략 시 전체) | all |
| `--ground-truth` | ground truth TF 활성화 (PilzPolicy 필수) | off |
| `--skip-build` | colcon build 건너뛰기 | build |
| `--gui` | Gazebo GUI 표시 | headless |

## 3. 결과 확인

실행 결과는 타임스탬프 기반으로 분리 저장:

```
benchmark/results/PilzPolicy_sfp_20260414_153022/
    benchmark_0000_sfp_0_scoring.yaml
    benchmark_0001_sfp_1_scoring.yaml
    ...

benchmark/logs/PilzPolicy_sfp_20260414_153022/
    benchmark_0000_sfp_0_sim.log
    benchmark_0000_sfp_0_policy.log
    benchmark_0000_sfp_0_engine.log
    ...
```

리더보드:

- `benchmark/leaderboard.yaml` — YAML 데이터
- `benchmark/LEADERBOARD.md` — 마크다운 테이블 (자동 생성)
- `benchmark/submissions/` — 제출 이력 (날짜별)

## 4. 전체 흐름 예시

```bash
cd src/aic

# 1) Config 생성
python3 benchmark/scripts/gen_benchmark_configs.py --type sfp --n 10 --seed 42
python3 benchmark/scripts/gen_benchmark_configs.py --type sc --n 10 --seed 42

# 2) Benchmark 실행 (SFP)
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy \
    --type sfp --ground-truth --skip-build

# 3) Benchmark 실행 (SC)
./benchmark/scripts/run_benchmark.sh my_policy.PilzPolicy \
    --type sc --ground-truth --skip-build
```
