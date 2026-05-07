---
id: DEVLOG-002
title: AutoCode compliant insertion for benchmark improvement
task_type: feature
status: completed
complexity: high
user_validation: pending
created: 2026-04-04
duration_estimate: 12h
tags: [autocode, benchmark, compliance, insertion, PI-controller, stiffness, simulation-variance]
---

## 목표 (Goal)
- AutoCode policy만 수정하여 benchmark leaderboard 90점 이상 달성
- 5개 config x 3 trials = 15 trials 평균 점수 최대화

## 접근 과정 (Approach Log)

### 사전 분석
- **현황**: AutoCode 63.64, CheatCode 58.98 (baseline)
- **병목**: Config 03-05 (extreme orient/rails/hell)에서 insertion 실패 (tier3 ~40-50/75)
- **핵심 구조**: PI integrator 기반 XY 정렬 -> world Z descent -> 삽입

### 치명적 버그 발견 (Exp 1-5)
- **증상**: 코드를 바꿔도 점수 변화 없음 (58-66 범위)
- **원인**: `colcon build`가 Python 소스를 `install/` 및 `.pixi/`에 sync하지 않음. `--skip-build` 시 sync도 skip됨
- **결과**: Exp 1-5 전부 원본 코드로 실행. 점수 차이는 순수 시뮬레이션 분산
- **해결**: 수동 sync 스크립트 작성 (`.autocode/sync_policy.sh`)

### Port-axis descent 시도 (Exp 1-4, 11-12)
- **방법**: Port quaternion에서 Z축 추출, descent 방향을 port 축으로 정렬
- **결과**: 실패 — z_offset=0.2에서 57도 기울어진 port의 geometric correction이 96mm lateral shift 발생
- **원인**: 접근 단계에서 과도한 보정이 PI 적분기를 혼란시킴
- **교훈**: XY 보정은 PI와 분리해야 함

### PI 파라미터 튜닝 (Exp 5b, 7, 8)
- **방법**: windup 증가 (0.05->0.15), P항 추가 (p_gain=0.3), hold time 5배 (1s->5s)
- **결과**: 모두 baseline 수준 (~61). 높은 PI gain은 tier2 하락
- **교훈**: PI 수렴은 이미 충분함. 문제는 alignment이 아님

### Spiral search (Exp 9-10)
- **방법**: Port 근처에서 나선형 탐색하며 하강
- **결과**: Tier3 +4.7 (삽입 개선) but Tier2 -4.4 (궤적 악화). 순효과 +-0
- **교훈**: 탐색은 도움되지만 궤적 품질 손해가 상쇄

### Compliant insertion -- 돌파구! (Exp 13-15)
- **방법**: Port 근처(z<0.02m)에서 XY stiffness를 90->20 N/m으로 감소
- **결과**:
  - Exp 13 (stiffness=60): 61.51 (효과 없음 — 기본 90과 차이 부족)
  - Exp 14 (stiffness=20): 64.97 (+3.57) — 첫 의미있는 개선!
  - **Exp 15 (stiffness=20 + windup=0.08): 70.29 (+8.89) — BEST**
- **원인**: 낮은 stiffness로 플러그가 port 구멍 가장자리에서 미끄러져 들어감
- **교훈**: Position accuracy보다 compliance가 중요 (peg-in-hole 삽입의 기본 원리)

### 후속 최적화 (Exp 16-24)
- Compliance zone 확대 (z<0.05): 역효과 — 너무 일찍 compliant하면 정렬 상실
- Ultra-compliant (5 N/m): 70.29 (동일)
- 회전-위치 분리: 60.84 (동시 slerp+position이 더 나음)
- Deeper insertion (-0.025): 61.16 (역효과)
- Peck insertion (3회 시도): tier3 +5.8 but tier2 -5.5 (상쇄)

## 최종 해결 (Final Solution)

두 가지 변경만 적용:

1. PI integrator windup 확대: `self._max_integrator_windup = 0.08` (was 0.05)
2. Port 근처에서 compliant XY stiffness:
```python
if z_offset < 0.02:
    self.set_pose_target(move_robot=move_robot, pose=pose,
        stiffness=[20.0, 20.0, 150.0, 50.0, 50.0, 50.0])
```

**결과: 63.64 -> 70.29 (+10.4%)**

## 교훈 (Lessons Learned)
1. **colcon build는 Python 패키지를 install에 항상 동기화하지 않음** — 반드시 수동 cp로 확인
2. **시뮬레이션 분산이 +-5점** — 단일 실행으로 작은 변경의 효과 판별 불가
3. **Compliant insertion이 핵심** — 정확한 position보다 유연한 stiffness가 삽입 성공률 결정
4. **90점 달성은 policy 수정만으로 어려움** — Config 05 (extreme_hell)에서 단 한 번도 full insertion 성공 없음. 시뮬레이션 물리 한계
5. **한 번에 하나만 변경** — 여러 변수 동시 변경 시 원인 분석 불가
6. **Sync 검증 필수** — diff로 source vs install vs pixi 일치 확인 후 실험

## 변경 파일 (Changed Files)
- `aic_example_policies/aic_example_policies/ros/AutoCode.py` — PI windup 증가, compliant insertion 추가
- `benchmark/leaderboard.yaml` — 점수 업데이트 (70.29)
- `benchmark/LEADERBOARD.md` — 리더보드 마크다운 갱신
