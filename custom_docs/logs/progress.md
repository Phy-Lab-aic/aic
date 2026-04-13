# AIC Project Progress Log

---

## 1. robostack-kilted ros2-distro-mutex 빌드 충돌 해결

**날짜**: 2026-04-07

### 문제
`pixi clean` 후 `pixi install` 시 모든 로컬 패키지 빌드 실패.
```
ros-kilted-aic-control-interfaces requires ros2-distro-mutex >=0.13.0,<0.14.0a0
ros-kilted-lerobot-robot-aic requires ros2-distro-mutex >=0.14.0,<0.15.0a0
```

### 원인
- `robostack-kilted` 채널에 `ros2-distro-mutex 0.14.0` (kilted_17)이 **2026-04-07** 신규 추가됨
- `pixi-build-ros`가 각 로컬 패키지를 독립적으로 빌드할 때, 빌드 순서/타이밍에 따라 일부는 0.13, 일부는 0.14를 선택
- 이전에는 `.pixi/envs/` 캐시에 0.13 기반으로 resolve된 환경이 있어 문제 없었음
- `pixi clean`이 캐시를 삭제하면서 재빌드 시 충돌 발생
- **fresh git clone에서도 동일 문제 발생** (upstream 문제)

### 확인 과정
1. `my_policy` 폴더를 상위로 이동 후 테스트 → 동일 에러 (my_policy 무관 확인)
2. `/tmp/aic_test/`에 fresh `git clone` 후 `pixi install` → 동일 에러 (upstream 확인)
3. `conda.anaconda.org/robostack-kilted` repodata 조회로 0.14.0 게시 시점 확인 (당일)
4. 채널 snapshot URL 시도 → `pixi-build-ros`가 `robostack-<distro>` 패턴 자동감지에 의존하여 불가
5. 테스트 폴더에서 `[package.host-dependencies]`에 pin 추가하여 해결 검증

### 해결
모든 로컬 패키지(8개)의 `pixi.toml`에 `[package.host-dependencies]` 추가:

```toml
# 모든 로컬 패키지 공통
ros2-distro-mutex = ">=0.13.0,<0.14.0a0"

# interface 패키지(msg 생성)에만 추가
ros-kilted-rosidl-generator-rs = "*"
```

**수정 파일 목록**:
- `aic_interfaces/aic_control_interfaces/pixi.toml` — distro-mutex + rosidl-generator-rs
- `aic_interfaces/aic_model_interfaces/pixi.toml` — distro-mutex + rosidl-generator-rs
- `aic_interfaces/aic_task_interfaces/pixi.toml` — distro-mutex + rosidl-generator-rs
- `aic_model/pixi.toml` — distro-mutex
- `aic_example_policies/pixi.toml` — distro-mutex
- `aic_utils/aic_teleoperation/pixi.toml` — distro-mutex
- `aic_utils/lerobot_robot_aic/pixi.toml` — distro-mutex
- `my_policy/pixi.toml` — distro-mutex

### 비고
- `rosidl_generator_rs` 에러는 0.13 빌드 환경에서 Rust 바인딩 생성기가 빌드 과정에 포함되지만 Python 모듈이 누락된 문제. interface 패키지의 host-dep에 명시적으로 추가하여 해결.
- 향후 `ros2-distro-mutex`가 0.15 등으로 올라가면 pin 업데이트 필요할 수 있음.

---

## 2. 학습용 Single-Trial Config 자동 생성 도구 구축

**날짜**: 2026-04-08

### 목적
강화학습/모방학습 데이터 수집을 위해, 다양한 NIC/SC rail 조합의 config를 대량으로 자동 생성하는 스크립트 개발.

### 구현 내용
`custom_tools/gen_training_configs/gen_single_trial_configs.py` 스크립트 작성:
- **SFP(Small Form-factor Pluggable)** / **SC(Subscriber Connector)** 두 task type을 **짝수/홀수 번호로 교대 배치**
- `sample_config.yaml`을 템플릿으로 사용하여 task별 파라미터(rail, connector 등)를 랜덤 샘플링
- train / test 모드 지원
- 재현성을 위한 seed 기반 랜덤 생성
- 생성 결과를 `configs_log.xlsx`에 Excel 로그로 자동 기록

### 생성 결과 (train, 200개)
| 구분 | 개수 | 비고 |
|------|------|------|
| SFP config (짝수번) | 100개 | 5개 NIC rail 균등 분포 |
| SC config (홀수번) | 100개 | 2개 SC rail 균등 분포 |
| **합계** | **200개** | `config_0000.yaml` ~ `config_0199.yaml` |

**NIC rail 분포 (SFP, n=100)**:
| Rail | 선택 횟수 | 비율 |
|------|-----------|------|
| nic_rail_0 | 58 | 58% |
| nic_rail_1 | 58 | 58% |
| nic_rail_2 | 54 | 54% |
| nic_rail_3 | 56 | 56% |
| nic_rail_4 | 61 | 61% |

**SC rail 분포 (SC, n=100)**:
| Rail | 선택 횟수 | 비율 |
|------|-----------|------|
| sc_rail_0 | 63 | 63% |
| sc_rail_1 | 61 | 61% |

### 출력 경로
- Config 파일: `custom_tools/gen_training_configs/configs/train/config_XXXX.yaml`
- Excel 로그: `custom_tools/gen_training_configs/configs/train/configs_log.xlsx`

### 의의
- 대규모 데이터 수집 파이프라인의 **첫 단계** 완성
- 다양한 rail/connector 조합에 대한 균등 샘플링으로 학습 데이터의 편향 방지
- 자동화된 config 생성으로 수작업 설정 오류 제거

---

## 3. PilzPolicy 튜닝 및 성능 최적화

**날짜**: 2026-04-08

### 내용
PilzPolicy의 Cartesian limits와 수렴 파라미터를 UR5e 컨트롤러 사양에 맞게 최적화.

- PILZ planner의 속도/가속도가 aic_controller 한계(0.25 m/s)를 초과하여 trajectory tracking error 발생 → 속도를 컨트롤러 한계의 60%로 조정
- 수렴 tolerance를 impedance controller의 정적 오프셋 한계(0.005~0.008 rad)에 맞게 0.002 → 0.006으로 완화

### 결과
- Benchmark 01 (sfp_basic) 평균 **94점** 달성
- Trial별: tier_1(1) + tier_2(~18) + tier_3(75) = ~94점
- 케이블 삽입 성공률 100% (3/3 trials)

### 튜닝 상세

#### 문제 진단

| 항목 | Fast config | Slow config |
|------|------------|-------------|
| Phase 1 SFP waypoints | 16 wp, 1.40s | 76 wp, 7.41s |
| 실행 중 max joint error | **0.10~0.14 rad** | **0.006~0.028 rad** |
| Phase 2 LIN | **항상 실패** → PTP fallback | **성공** |
| Phase 2 수렴 | TIMEOUT (0.005~0.008 rad 고착) | TIMEOUT (동일) |

근본 원인:
1. **Fast**: `max_trans_vel=1.0 m/s`가 controller 한계 `0.25 m/s`의 4배 초과 → joint error 폭증
2. **Slow**: `joint max_acc=0.05 rad/s²`가 너무 낮아 9초+ 소요
3. **공통**: `converge_tol=0.002 rad`은 compliance controller 정적 오프셋 한계(0.005~0.008 rad)보다 작아 달성 불가

#### 참조 사양

- UR5e 관절 max_velocity: 3.14 rad/s (acceleration limits 비공개)
- aic_controller max_translational_velocity: ±0.25 m/s
- aic_controller max_rotational_velocity: 2.0 rad/s

#### 변경 내용

`pilz_cartesian_limits.yaml`:

| 설정 | Fast | Slow | **New** | 근거 |
|------|------|------|---------|------|
| max_trans_vel | 1.0 | 0.05 | **0.15** m/s | controller 0.25의 60% |
| max_trans_acc | 2.25 | 0.01 | **0.50** m/s² | 중간값 |
| max_rot_vel | 1.57 | 0.05 | **0.80** rad/s | controller 2.0의 40% |
| joint max_acc | 1.396 | 0.05 | **0.30** rad/s² | 실측 기반 보수적 중간값 |

`PilzPolicy.py`:

| 설정 | Before | After | 근거 |
|------|--------|-------|------|
| converge_tol | 0.002 rad | **0.006 rad** | 정적 오프셋 한계 고려 |
| converge_timeout | max(10, dur×3) | **max(5, dur×2)** | tol 초과 시 더 기다려도 무의미 |

---

## 4. E2E 학습 데이터 수집 파이프라인 구축

**날짜**: 2026-04-08

### 목적
VLA(Vision-Language-Action) 모델 학습을 위한 전체 데이터 파이프라인 구축.
시뮬레이션 데이터 수집 → LeRobot 변환 → HuggingFace 업로드까지 자동화.

### 구축한 파이프라인

```
Config 생성 → 시뮬레이션 수집 → LeRobot 변환 → HuggingFace 업로드
```

### 구현 내용

#### 4-1. aic_engine 수정 (record_all_topics) — *backup에서 복원 (2026-04-13)*
- `ScoringTier2`에 `record_all_topics` 파라미터 복원 (upstream 2026-04-12 제거 → backup에서 재적용)
- Engine 내부에서 모든 토픽(카메라, 관절, 힘/토크, action 등)을 직접 기록
- `StartRecording()` ~ `StopRecording()` 구간만 정확히 기록 (idle 프레임 없음)
- zstd 압축 적용 (`zstd_fast` preset)
- 수정 파일: `ScoringTier2.hh`, `ScoringTier2.cc`, `aic_engine.cpp` (backup에서 cp)
- `collect_training_data.sh`에서 `-p record_all_topics:=true` 자동 전달

#### 4-2. 데이터 수집 스크립트 (`collect_training_data.sh`)
- Config를 순차 실행하며 자동 수집
- headless 모드 + 카메라 모니터링 (`--monitor`)
- progress.yaml 기반 resume (중단 후 이어하기)
- 자동 score 표시 및 metadata 추출

#### 4-3. LeRobot 변환 도구 — *2026-04-12 리팩토링: prepare_for_lerobot.py deprecated*
- 변환기(main.py)가 `~/aic_data/raw/`에서 직접 읽고 score 필터링 + 자동 이동 수행
- 데이터 구조: raw/ → done/ (변환 완료) / skipped/ (90점 미만)
- `pixi run convert` 한 줄로 변환 + HuggingFace 업로드

### 수집 현황
- 48개 config 수집 완료 (90점 이상)
- LeRobot 변환 및 HuggingFace 업로드 진행 중

### 관련 문서
- 전체 파이프라인: [custom_tools/README.md](../custom_tools/README.md)
- 수집 상세: [collect_training_data/README.md](../custom_tools/collect_training_data/README.md)
- Config 생성 설계: [gen_training_configs/design.md](../custom_tools/gen_training_configs/design.md)

---

## 5. PilzPolicy 리팩토링 및 wrist effort limit 대응

**날짜**: 2026-04-13

### 내용

#### 5-1. 코드 정리
- 기존 PilzPolicy v1~v5를 `src/backup/`으로 이동, PilzPolicyV6를 `PilzPolicy`로 통합
- `my_policy_util` (dead code) 및 `utils.py` (미사용)도 backup으로 이동
- 모든 하드코딩 값을 파일 상단 상수로 추출 + 주석 작성
- 관련 md 파일 7개 일괄 수정

#### 5-2. wrist_1_joint effort limit 초과 문제 대응
Gazebo에서 `wrist_1_joint` effort 28Nm 한계 초과 에러 발생.

**원인**: KDL torque check는 정적 gravity torque만 검사하지만, 실제 effort는 gravity + impedance force(stiffness × position_error) + damping force의 합산. stiffness가 높으면 작은 추적 오차에도 큰 힘이 추가되어 한계 초과.

**대응**: Phase 1 (장거리 접근)의 wrist stiffness/damping 축소.
- Phase 1: stiffness [400,400,400,**50,50,50**], damping [60,60,60,**10,10,10**]
- Phase 2: stiffness [400,400,400,150,150,150], damping [60,60,60,30,30,30] (원래 값 유지)
- Phase 3: 별도 insertion용 impedance 유지

#### 5-3. Planning Scene collision check 비활성화
추가해야 할 구조물이 남아있어 임시 비활성화. Enclosure collision 코드 삭제 (도달 범위 내 충돌 불가).

#### 5-4. 안정화 시간 축소
Phase별 안정화: 1초 → 0.1초 (합계 3초 → 0.3초)

---

## 6. VLA 모델 통합 설계 (검토 중)

**날짜**: 2026-04-13

### 배경
Pi0.5 등 VLA 모델 활용 검토. rule-based PilzPolicy의 시연 데이터로 학습.

### VLA 모델 출력
- Joint position (absolute, 6 joints) × action chunk (예: 10 steps)
- `JointMotionUpdate` (MODE_POSITION)으로 발행

### Impedance 설계 과제
VLA는 phase 구분 없이 end-to-end이므로 **전 구간 고정 impedance** 필요.
compliance는 impedance 파라미터가 아닌 **action trajectory 자체**에 녹아있음 (삽입 구간에서 모델이 작은 delta 출력 → 자연스럽게 부드러운 삽입).

권장 설정 (검토 중):
```
stiffness = [150, 150, 150, 40, 40, 40]
damping   = [50,  50,  50,  20, 20, 20]
wrench_feedback_gains = [0.3, 0.3, 0.3, 0.0, 0.0, 0.0]
```

### 핵심 제약
**데이터 수집 시 impedance와 추론 시 impedance가 동일해야 함** — 다르면 distribution shift 발생.
→ PilzPolicy로 데이터 수집 시 Phase 1/2/3 모두 VLA용 고정 impedance로 통일 필요.

### 코드 설계 방향 (미구현)
```
my_policy/
├── PilzPolicy.py              # rule-based (데이터 수집 겸용)
├── VLAPolicy.py               # VLA 추론 policy
├── vla/
│   ├── config.py              # 공유 impedance 설정
│   ├── preprocessor.py        # Observation → 모델 입력
│   ├── model_wrapper.py       # 모델 로드/추론
│   └── postprocessor.py       # 모델 출력 → JointMotionUpdate
```

### 다음 단계
1. PilzPolicy impedance를 VLA용 고정값으로 통일 후 수집 테스트
2. 수집 데이터로 VLA 모델 학습
3. VLAPolicy 구현 및 추론 테스트

---

## 7. (다음 항목)

