---
id: DEVLOG-001
title: Autocode CheatCode scoring optimization
task_type: feature
status: completed
complexity: high
user_validation: pending
created: 2026-04-03
duration_estimate: 6h
tags: [autocode, cheatcode, aic, robotics, cable-insertion, PI-controller, scoring, gazebo]
---

## 목표 (Goal)
- AIC CheatCode 정책의 스코어 최적화 (aic_engine 부여 점수 기준)
- 원본 3-trial config: 3회 평균 최고점 달성
- Extended 13-trial config: 다양한 시나리오에서 성능 개선

## 접근 과정 (Approach Log)

### 1차 시도 (Exp 1): 공격적 속도 변경
- **방법**: z_offset 0.1시작, descent 0.001/step, approach 50steps
- **결과**: 실패 (132.86, baseline 224)
- **원인**: 빠른 하강이 PI controller의 XY 수렴 시간을 부족하게 만듦. 47N 힘 패널티 발생

### 2-4차 시도 (Exp 2-4): 단일 변수 조정
- **방법**: 삽입 깊이 변경(-0.03), PI gain 증가(0.25), integrator windup 증가(0.08)
- **결과**: 모두 baseline 이하
- **원인**: 삽입 깊이는 XY 정렬 문제 (Z가 아님), PI 파라미터는 이미 최적

### 5차 시도 (Exp 5): Approach 단축 + Stabilize 단축
- **방법**: approach 75steps(3.75s), stabilize 2s
- **결과**: 성공 (251.07, +22pt). Trial_3 partial insertion 달성
- **원인**: stabilize 5s→2s가 drift 감소에 기여

### 7차 시도 (Exp 7): 1s XY Hold 추가
- **방법**: approach 후 1s hold (20iter x 50ms)로 PI 수렴 시간 부여
- **결과**: 성공 (280.05, trial_3 완전 삽입!)
- **원인**: Hold 구간이 PI controller에 정렬 수렴 시간을 제공

### 14차 시도 (Exp 14): Adaptive Descent (BEST)
- **방법**: 80step마다 integrator 오차 확인, 악화 시 0.5s 일시정지 후 재정렬
- **결과**: 825.1/1300 (extended 13-trial), 7개 trial 성공
- **원인**: 하강 중 정렬 품질을 모니터링하고 능동적으로 보정

### Research 기반 시도 (Exp 13, 15-18): Impedance/Path 변경
- **시도**: compliant XY stiffness(40), D-gain(0.01), spiral search, high stiffness(120), high Z damping(70), ease-in/ease-out
- **결과**: 모두 Exp14보다 나쁨 (-52 ~ -299)
- **원인**: 기본 impedance 파라미터가 이미 잘 튜닝됨. 물리적 제어 변경보다 행동적 적응이 효과적

## 최종 해결 (Final Solution)
CheatCode.py에 3가지 변경 (누적):
1. **Approach 75 steps** (5s -> 3.75s)
2. **1s XY hold phase** (descent 전 PI controller 수렴 시간)
3. **Adaptive descent** (80step마다 정렬 확인, 악화 시 재정렬 pause)

### 성능 비교
| Config | Baseline | Best (Exp 14) | 개선 |
|--------|----------|---------------|------|
| 원본 3-trial (1회) | 229.0 | 280.05 | +22% |
| 원본 3-trial (3회 avg) | 229.0 | 269.74 | +18% |
| Extended 13-trial | ~549 | 825.1 | +50% |

## 교훈 (Lessons Learned)
- **한 번에 하나씩 변경** -- 여러 변수를 동시에 바꾸면 원인 파악 불가
- **pixi 빌드 캐시 주의** -- pixi install은 colcon과 독립적. CheatCode.py를 pixi env에 수동 복사 필요
- **시뮬레이션 상태 오염** -- 연속 실행 시 Gazebo 상태 degradation. 실행 간 sim restart 필수
- **기본 impedance 파라미터가 최적** -- stiffness/damping 변경은 모두 악화
- **관측 기반 적응이 핵심** -- 물리 파라미터보다 "감지+반응" 전략이 효과적
- **Duration 32s 고정** -- engine 오버헤드 포함. policy 변경만으로 개선 불가

## 변경 파일 (Changed Files)
- `aic_example_policies/aic_example_policies/ros/CheatCode.py` -- approach/hold/adaptive descent 추가
- `aic_engine/config/extended_config.yaml` -- 13-trial 확장 config (신규)
- `.autocode/` -- 실험 인프라 (run_test.sh, results.tsv, lessons, program.md)
