# OptimalPolicy — Cable Insertion Policy

AutoCode 기반 closed-loop Cartesian 제어 + F/T sensor feedback + 채점 최적화를 결합한 cable insertion policy.

## 성능

| Policy | SFP 평균 (20 configs) | 성공률 | 비고 |
|--------|----------------------|--------|------|
| CheatCode (baseline) | 91.01 | 20/20 | 기본 제공 |
| AutoCode (baseline) | 93.53 | 20/20 | 기본 제공 |
| **OptimalPolicyV1** | **97.47** | **20/20** | 권장 |
| **OptimalPolicyV2** | **97.47** | **20/20** | V1 + smoothness 실험 |

## 실행 방법

```bash
# V1 (권장)
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.OptimalPolicyV1 --type sfp --ground-truth

# V2
./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.OptimalPolicyV2 --type sfp --ground-truth
```

---

## OptimalPolicyV1 (권장)

**파일**: `aic_example_policies/ros/OptimalPolicyV1.py`

### 핵심 구조

```
Phase 1: Approach (linear 보간, 고정 스텝)
  → 현재 TCP에서 port 상방(-0.08m)으로 이동
  → SLERP orientation 정렬 + position 보간
  → PI integrator 비활성 (approach 중에는 정렬 불필요)

Phase 3: Descent + Insertion (연속 하강)
  → z_offset을 -0.08 → 삽입 완료까지 연속 증가
  → 2단계 속도: 진입 전 느리게(0.0005m/step) + 진입 후 빠르게(0.002m/step)
  → PI integrator 활성화 (XY 실시간 보정)
  → F/T sensor 기반 safety (18N 안전 후퇴)
  → Stall detection + retry
  → Adaptive stiffness ([90,90,90] → [20,20,150])
```

### AutoCode 대비 개선점

| 항목 | AutoCode | OptimalPolicyV1 |
|------|----------|-----------------|
| 좌표계 | base_link XY (로봇 기준) | **port 로컬 좌표계** (port 방향 무관) |
| 삽입 완료 감지 | z_offset 고정값 | **depth 기반** (실제 plug 위치) |
| F/T sensor | 미사용 | **baseline 보상 + EMA filtering** |
| 하강 속도 | 0.0005 균일 | **2단계** (진입 전 0.0005 / 후 0.002) |
| Approach 스텝 | 75 고정 | **거리 기반** (min 40, 속도 0.05m/s) |
| Force safety | 없음 | **18N 0.5초 → 자동 후퇴** (20N penalty 방지) |
| Stall detection | 없음 | **50-sample window** + retry |

### 주요 파라미터

```python
# Approach
APPROACH_Z_OFFSET = -0.08     # port z축 방향 접근 offset (m)
APPROACH_VELOCITY = 0.05      # 이동 속도 (m/s)
APPROACH_MIN_STEPS = 40       # 최소 스텝

# Descent (2단계)
DESCENT_STEP_SLOW = 0.0005   # 진입 전 (0.5mm/step)
DESCENT_STEP_FAST = 0.002    # 진입 후 (2mm/step)
ENTRY_DEPTH = -0.035          # 진입 완료 판단 기준

# Stiffness
STIFFNESS_DEFAULT = [90, 90, 90, 50, 50, 50]
STIFFNESS_INSERT  = [20, 20, 150, 50, 50, 50]  # XY 유연, Z pushing

# PI Controller
PI_I_GAIN = 0.15
PI_WINDUP_MAX = 0.08

# F/T Feedback
FORCE_ALPHA = 0.3             # EMA filter
FORCE_SAFETY_THRESHOLD = 18.0 # 안전 후퇴 (N)

# Depth Thresholds
DEPTH_THRESHOLD_SFP = 0.0    # SFP 삽입 완료
DEPTH_THRESHOLD_SC = -0.0008  # SC 삽입 완료
```

### 채점 상세 (20 config 평균)

| 항목 | 만점 | V1 점수 | 비고 |
|------|------|---------|------|
| Tier 1 (모델 유효성) | 1.0 | 1.0 | |
| Duration | 12.0 | 10.49 | ~12초 |
| Smoothness | 6.0 | 5.27 | jerk ~6 m/s³ |
| Efficiency | 6.0 | 5.71 | 경로 약간 우회 |
| Force penalty | 0.0 | 0.0 | penalty 없음 |
| Contact penalty | 0.0 | 0.0 | 충돌 없음 |
| Tier 3 (삽입) | 75.0 | **75.0** | **만점** |
| **합계** | **100.0** | **97.47** | |

---

## OptimalPolicyV2

**파일**: `aic_example_policies/ros/OptimalPolicyV2.py`

### V1 대비 추가 변경

1. **S-curve approach**: linear frac → `0.5 * (1 - cos(π * frac))` cosine ease-in-out
   - 시작/끝 가감속을 부드럽게 하여 jerk 감소 의도
2. **점진적 stiffness 전환**: z=-0.04~-0.02 구간에서 [90,90,90] → [20,20,150] 선형 보간
   - 급변 대신 부드러운 전환으로 stiffness 변경 시 jerk 감소 의도

### V1 vs V2 비교

| 카테고리 | V1 | V2 | 차이 |
|----------|-----|-----|------|
| Duration | 10.49 | 10.55 | +0.06 |
| Smoothness | **5.27** | 5.20 | -0.07 |
| Efficiency | 5.71 | 5.71 | 0.00 |
| **Total** | **97.47** | **97.47** | 0.00 |

S-curve와 점진적 stiffness 전환은 이론적으로 smoothness를 개선해야 하지만, full benchmark에서 총점 차이가 없습니다. Smoothness가 -0.07 악화되고 Duration이 +0.06 개선되어 상쇄됩니다. **추가 복잡성 대비 효과가 없으므로 V1(단순 버전)을 권장합니다.**

---

## 아키텍처

```
insert_cable()
  │
  ├── F/T baseline calibration (10 samples)
  │
  ├── Phase 1: Approach
  │     └── calc_gripper_pose() × N steps
  │           ├── SLERP orientation 정렬
  │           ├── position_fraction 보간 (현재→목표)
  │           └── port 로컬 좌표계 기반 목표 계산
  │
  ├── F/T baseline 재측정 (삽입 자세)
  │
  └── Phase 3: Descent + Insertion
        └── while z_offset < limit:
              ├── calc_gripper_pose(z_offset) + PI 보정
              ├── F/T monitoring (baseline 보상 + EMA)
              ├── 삽입 완료 판정 (depth >= threshold)
              ├── Stall detection (50-sample, retract+retry)
              ├── Force safety (18N → 후퇴)
              ├── 2단계 속도 (진입 전 0.0005 / 후 0.002)
              └── Adaptive stiffness ([90]→[20,20,150])
```

## 주요 설계 결정과 근거

| 결정 | 근거 | 실험 |
|------|------|------|
| port 로컬 좌표계 사용 | port가 기울어져도 정확한 정렬 | AutoCode는 base_link XY만 사용 |
| 진입 전 0.0005 유지 | 0.001에서 일부 config 실패 | Exp003 vs full benchmark |
| 진입 후 0.002 가속 | depth>-0.035 이후 저항 없음 | 전 성공 config 로그 분석 |
| APPROACH_MIN_STEPS=40 | 75→40 시 일부 config +2초 단축 | full benchmark 비교 |
| 18N safety threshold | 20N 1초 초과 시 -12점 penalty | scoring 기준 |
| depth 기반 완료 판정 | SFP>0.0, SC>-0.0008 시 만점 | 사용자 제공 기준 |

## 실험 이력

상세 실험 기록: [`research/EXPERIMENT_INDEX.md`](../../research/EXPERIMENT_INDEX.md)

파라미터 튜닝 로그: [`research/TUNING_LOG.md`](../../research/TUNING_LOG.md)
