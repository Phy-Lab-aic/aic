# OptimalPolicy — Cable Insertion Policy

---

## 📌 Overview


| Phase 1 | → Phase 3 (연속) |
| --- | --- |
| Approach (보간 이동) | Descent + Insertion (하강 → 진입 → 삽입 완료) |

PilzPolicy(4단계, MoveIt+JointMotionUpdate)와 달리, **Phase 분리를 최소화**하고 **연속 Cartesian impedance 제어**로 smoothness를 확보.

---

## 📌 V1 vs V2

| | V1 | V2 |
| --- | --- | --- |
| **Approach 보간** | linear frac | S-curve |
| **Stiffness 전환** | 급변 (z=-0.02 기준) | 점진적 보간 (z=-0.04~-0.02) |
| **SFP 20 config 평균** | **97.47** | **97.47** |
| **성공률** | **20/20** | **20/20** |
|

---

## 🏗️ Architecture

### 제어 스택

```
OptimalPolicy (decision, 20Hz closed-loop)
    │
    ├─ calc_gripper_pose()    → PI integrator + SLERP + port 좌표계 투영
    ├─ F/T baseline + EMA    → 순수 접촉력 추출
    │
    ▼
MotionUpdate (Cartesian pose + impedance parameters)
    │  frame_id = "base_link"
    │  target_stiffness (6x6 diagonal)
    │  wrench_feedback_gains = [0.5, 0.5, 0.5, 0, 0, 0]
    ▼
aic_controller (impedance control + IK)
    │
    ▼
UR5e + Gazebo Simulation
```

### 사용 인터페이스

| 구분 | 인터페이스 | 용도 |
| --- | --- | --- |
| 명령 출력 | `MotionUpdate` → `/aic_controller/pose_commands` | Cartesian pose + stiffness/damping |
| 관측 입력 | `get_observation()` → joint_states, wrist_wrench | FTS 힘, 관절 상태 |
| TF | `base_link → port_frame`, `base_link → plug_frame` | 위치/방향 계산 |
| Planning | 없음 (MoveIt 미사용) | controller가 IK 처리 |

### PilzPolicy와의 차이

| | PilzPolicy | OptimalPolicy |
| --- | --- | --- |
| 제어 방식 | MoveIt trajectory → JointMotionUpdate | **set_pose_target → MotionUpdate** |
| 경로 계획 | PILZ PTP/LIN planner | **없음** (impedance controller 직접) |
| IK | MoveItPy `set_from_ik()` | **controller 내부 처리** |
| Impedance | Joint space (고정) | **Cartesian space (Phase별 가변)** |
| Phase 수 | 4단계 | **2단계** (approach + 연속 하강) |
| XY 보정 | 없음 | **PI integrator** (실시간 closed-loop) |
| F/T 활용 | force slope + 안전 정지 | **baseline 보상 + EMA + safety 후퇴** |
| Smoothness | jerk ~15 m/s³ | **jerk ~6 m/s³** |

---

## 🔄 Phase별 동작

### Phase 1 — Approach

**목표**: 현재 TCP → port 앞 8cm (z_offset = -0.08)

```python
for t in range(approach_steps):
    frac = t / approach_steps          # V1: linear, V2: S-curve
    pose = calc_gripper_pose(
        slerp_fraction=frac,           # orientation: 현재 → port 방향
        position_fraction=frac,        # position: 현재 → 목표
        z_offset=-0.08,
        reset_xy_integrator=True,      # approach 중 PI 비활성
    )
    set_pose_target(pose, stiffness=[90,90,90,50,50,50])
```

- **스텝 수**: `max(40, dist / (0.05 × 0.05))` — 거리 비례, 최소 2초
- **orientation**: SLERP으로 plug이 port 방향에 점진 정렬
- **position**: 현재 TCP와 목표를 `frac`으로 blend
- PI integrator: 비활성 (approach 중에는 정렬 불필요)

### Phase 2, 3 — Descent + Insertion (연속)

**목표**: z_offset을 -0.08 → 삽입 완료까지 연속 증가

```python
while z_offset < INSERT_Z_LIMIT:
    pose = calc_gripper_pose(z_offset=z_offset)   # PI 보정 포함
    set_pose_target(pose, stiffness=stiffness)
    
    # 2단계 속도
    if depth > -0.035:   # 진입 완료
        step = 0.002     # 빠르게 (2mm/step)
    else:
        step = 0.0005    # 느리게 (0.5mm/step, 정렬 시간 확보)
    
    z_offset += step
```

**핵심 메커니즘**:

| 기능 | 동작 |
| --- | --- |
| **PI integrator** | plug-port XY 오차를 port 로컬 좌표계로 투영 → 누적 보정 (i_gain=0.15) |
| **2단계 속도** | 진입 전 0.0005m/step (정렬) → 진입 후 0.002m/step (빠른 삽입) |
| **Adaptive stiffness** | z>-0.02에서 [90,90,90]→[20,20,150] (XY 유연, Z pushing) |
| **F/T safety** | 18N 0.5초 초과 → 자동 후퇴 (20N penalty 방지) |
| **Stall detection** | depth 변화 없음 2.5초 + force>3N → 후퇴 + retry (최대 10회) |
| **적응형 재정렬** | 80스텝마다 XY 오차 확인, 30% 악화 시 hold |

---

## 📐 좌표계

### port 로컬 좌표계 기반 제어

AutoCode는 `base_link XY`에서 오차를 계산하지만, OptimalPolicy는 **port 로컬 좌표계**에서 계산:

```python
R_port = quat_to_matrix(port_rotation)
port_x = R_port[:, 0]   # port 로컬 x축
port_y = R_port[:, 1]   # port 로컬 y축
port_z = R_port[:, 2]   # 삽입 방향

error_vec = port_pos - plug_pos
tip_x_error = dot(error_vec, port_x)   # port x축 방향 오차
tip_y_error = dot(error_vec, port_y)   # port y축 방향 오차
```

→ **port가 roll pitch로 기울어져 있어도 정확한 정렬(base_link XY와 port 수직면이 다를 때), 
→ evaluation에서는 yaw만 존재하긴 함.**

### z_offset 부호 체계

```
z_offset = -0.08  → port 앞 8cm (시작)
z_offset = -0.035 → port 앞 3.5cm (ENTRY_DEPTH, 진입 완료 판단)
z_offset = -0.02  → port 앞 2cm (stiffness 전환점)
z_offset =  0.0   → port 원점 (SFP 삽입 완료)
z_offset = +0.02  → port 통과 (INSERT_Z_LIMIT)
```



---

## 🛑 종료 조건

### ✅ 삽입 완료

| 조건 | SFP | SC |
| --- | --- | --- |
| depth threshold | > 0.0m | > -0.0008m |

- depth가 threshold를 넘으면 즉시 종료. force 조건 없이 **depth 단독 판정** (가장 안정적)
 - force 조건의 경우 상황에 따라 고려해야할 사항이 달라져 종료 조건에 대한 일반화가 어려움.

## 🛑 추가 종료 조건
해당 상황 발생시 점수가 낮을것이라 데이터 수집에는 필요없을 것 임. (망했을 때 빠른 종료)

### ⚠️ Stall 정지 (어딘가 부딪혀서 못나아갈 때)

depth가 2.5초간 변화 < 0.5mm **and** force > 3N → 후퇴 2mm + retry. 10회 소진 시 종료.

### 🚨 안전 후퇴

|force| > 18N이 0.5초 지속 → z_offset 1mm 후퇴. 종료하지 않고 계속 시도.
(채점 기준: 20N 1초 초과 시 -12점 → 18N/0.5초로 선제 대응)

### 📏 z_offset 한계

z_offset ≥ 0.02m 도달 → 종료 (삽입 실패 fallback).

---

## 🔊 F/T Sensor 활용

### Baseline 보상

```python
# 삽입 자세에서 10 sample 평균 → baseline 기록
f_baseline = mean(f_raw[:10])

# 이후 모든 읽기에서 차감
f_contact = f_raw - f_baseline
```

tool 무게, 케이블 장력 등 정적 성분을 제거하여 순수 접촉력만 추출.
Phase 1 완료 후 삽입 자세에서 재측정 (자세에 따라 baseline 변화).

### EMA Filtering

```python
f_filtered = α × f_raw + (1-α) × f_prev    # α = 0.3
```

sensor noise 완화. threshold 판단 시 false trigger 방지.

---

## ⚙️ Impedance 설정

### Phase별 Cartesian Stiffness

| 구간 | Stiffness | Damping (base class) | 용도 |
| --- | --- | --- | --- |
| Approach | [90, 90, 90, 50, 50, 50] | [50, 50, 50, 20, 20, 20] | 정확한 위치 추종 |
| Descent (z < -0.02) | 동일 | 동일 | 빈 공간 이동 |
| Insertion (z ≥ -0.02) | **[20, 20, 150, 50, 50, 50]** | 동일 | **XY 유연 + Z pushing** |

**XY stiffness 20**: port 입구에서 misalignment 시 compliance로 자연 정렬.
**Z stiffness 150**: 삽입 방향으로 충분한 pushing force.
`wrench_feedback_gains = [0.5, 0.5, 0.5, 0, 0, 0]`: controller 내장 force feedback 활성화.

---

## 📁 파일 구조

```
aic_example_policies/ros/
├── OptimalPolicyV1.py        # 권장 — linear approach + 급변 stiffness
└── OptimalPolicyV2.py        # 참고 — S-curve approach + 점진적 stiffness
```

---
