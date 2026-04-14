# my_policy 패키지

케이블 삽입 policy 패키지. `aic_model`에서 동적 로딩하여 사용.

## 실행 방법

```bash
pixi run ros2 run aic_model aic_model --ros-args -p policy:=my_policy.PilzPolicy
```

코드 수정 후:
```bash
pixi reinstall ros-kilted-my-policy
```

---

## 파일 구조

```
my_policy/
├── config/                     # MoveIt2 설정 (PILZ policy용)
│   ├── kinematics.yaml
│   ├── pilz_cartesian_limits.yaml
│   ├── pilz_cartesian_limits_slow.yaml
│   └── ur5e.srdf
├── launch/
│   └── moveit_pilz.launch.py
├── my_policy/
│   ├── __init__.py
│   ├── planning_scene.py       # MoveIt2 collision scene
│   └── PilzPolicy.py           # torque-aware cable insertion policy
├── package.xml
├── pixi.toml
└── setup.py
```

> **Note**: 이전 버전 (v1~v5), utils.py, my_policy_util은 `src/backup/` 폴더에 백업되어 있습니다.

---

## 방법론 개요

### 과제

그리퍼에 잡혀있는 케이블 플러그(SFP 또는 SC)를 task board의 port에 삽입.
ground truth TF로 port/plug 위치를 알 수 있음.

### 제어 방식

- **제어 명령**: `JointMotionUpdate` (joint position command) → `/aic_controller/joint_commands`

- **경로 생성**: MoveIt2 PILZ planner (PTP/LIN) — Phase 1, 2
- **삽입 제어**: MoveItPy IK 반복 — Phase 3

### Phase별 목표

```
Phase 1:   PTP 접근 — 현재 위치 → port 위 접근점까지 이동
Phase 1.5: IK 보정 — TCP를 목표에 정밀 수렴 (1mm 이내)
Phase 2:   LIN 하강 — 접근점 → 삽입 직전 위치 (port 근처)
Phase 3:   삽입 — port 방향으로 TCP 증분 이동, force/depth로 완료 판정
```

### Phase별 상세

| Phase | 목표 | 경로 생성 | 실행 방식 | 종료 조건 |
|-------|------|-----------|-----------|-----------|
| **1** | port 위 접근 (SFP: 5cm, SC: 2cm) | PILZ PTP | waypoint 순차 발행 (torque-aware) | trajectory 완료 |
| **1.5** | TCP 정밀 수렴 | MoveItPy IK | 고정 목표에 반복 발행 | 오차 < 1mm |
| **2** | 삽입 직전 위치까지 하강 | PILZ LIN → PTP fallback | fine interpolation (8배 보간) | trajectory 완료 |
| **3** | 케이블 삽입 | MoveItPy IK (증분 TCP) | 20Hz 루프 (10mm/s) | force 감소 감지 또는 안전 정지 |

### Phase 3 종료 조건

삽입 완료와 안전 정지, 2가지 조건:

**삽입 완료** (3개 AND, 즉시 종료):
1. `depth >= threshold` — 최소 깊이 도달 (SFP: 0mm, SC: -0.8mm)
2. `f_insert <= 5N`, `force slope < -2 N/s` — 삽입 방향 저항 발생 지속

**안전 정지**:
- `|force| > 20N`이 1.5초 지속 → 즉시 정지

### Force 측정 방식

```
f_raw    = wrist FTS의 (fx, fy, fz) — 센서 프레임
f_insert = -dot(f_raw, port_z)      — port 삽입 방향 투영 (양수=삽입, 음수=반발)
f_abs    = |f_raw|                   — 벡터 크기 (안전 정지용)
f_slope  = 최근 5 sample 선형 회귀   — force 변화율 (N/s)
```

### Torque Safety

Phase 1-2 trajectory 실행 전 KDL gravity torque 검사:
- 전 waypoint에서 gravity torque가 `EFFORT_LIMITS × TORQUE_SAFETY_MARGIN` 이내인지 확인
- 초과 시 8배 세밀 보간(fine interpolation)으로 안전 실행
- 또는 2-leg merged trajectory (높은 곳에서 XY 이동 후 하강)
  - 케이블이 task board에 접촉시 마찰이 매우 커서 이동에 제약이 생기는 것을 확인 -> 높은 곳에서 하강 시, 케이블의 끌림이 감소.

---

## PilzPolicy 상세 동작 과정

### 0. 상수 정의 (코드 최상단)

| 상수 | 값 | 설명 |
|------|----|------|
| **Impedance** | | |
| `EXEC_STIFFNESS` | [400,400,400,150,150,150] | 전 Phase 통일 joint stiffness |
| `EXEC_DAMPING` | [60,60,60,30,30,30] | 전 Phase 통일 joint damping |
| **Phase 1-2 접근** | | |
| `Z_OFFSET_APPROACH_SFP` | -0.05 m | Phase 1: SFP port 위 5cm 접근 |
| `Z_OFFSET_APPROACH_SC` | -0.02 m | Phase 1: SC port 위 2cm 접근 |
| `Z_OFFSET_PREINSERT_SFP` | -0.01 m | Phase 2: SFP 삽입 직전 위치 |
| `Z_OFFSET_PREINSERT_SC` | -0.001 m | Phase 2: SC 삽입 완료 위치 |
| `SETTLE_DURATION` | 0.5 s | 각 Phase 종료 후 안정화 시간 |
| `FINE_INTERP_FACTOR` | 8 | torque violation 시 waypoint 간 보간 배수 |
| **Phase 1.5 IK 보정** | | |
| `IK_CONVERGE_THRESHOLD` | 0.001 m | TCP position 수렴 threshold (1mm) |
| `IK_CONVERGE_MAX_LOOPS` | 100 | 최대 보정 루프 (5초) |
| **Phase 3 삽입** | | |
| `INSERT_VELOCITY` | 0.01 m/s | TCP 삽입 속도 (10mm/s) |
| `DT` | 0.05 s | 제어 루프 주기 (20Hz) |
| `MAX_LOOPS` | 2000 | 최대 반복 (100초) |
| **Phase 3 종료 판정** | | |
| `DEPTH_THRESHOLD_SFP` | 0.0 m | SFP 삽입 완료 최소 depth |
| `DEPTH_THRESHOLD_SC` | -0.0008 m | SC 삽입 완료 최소 depth |
| `FORCE_LOW_THRESHOLD` | 5.0 N | 삽입 완료 force 한계 |
| `FORCE_SLOPE_WINDOW` | 5 samples | force 기울기 계산 window (0.25초) |
| `FORCE_SLOPE_THRESHOLD` | -2.0 N/s | force 감소 기울기 threshold |
| `FORCE_STOP_THRESHOLD` | 20.0 N | 안전 정지 \|force\| 기준 |
| `FORCE_PENALTY_DURATION` | 1.5 s | 20N 초과 시 정지 대기 |
| **Torque Safety** | | |
| `EFFORT_LIMITS` | [150,150,150,28,28,28] Nm | UR5e 관절별 토크 한계 |
| `TORQUE_SAFETY_MARGIN` | 0.5 | 토크 한계의 50%를 threshold로 사용 |

---

### 1. 생성자 (`__init__`)

```
PilzPolicy(parent_node)
```

- `aic_model.Policy`를 상속. `parent_node`는 `aic_model` ROS 노드
- 내부 상태 초기화:
  - `_moveit`: MoveItPy 인스턴스 (lazy init, 첫 trial에서 초기화)
  - `_arm`: MoveItPy planning component ("manipulator" 그룹)
  - `_planning_scene_manager`: collision object 관리자
  - `_kdl_chain` / `_kdl_gravity_solver`: KDL dynamics 체인 (gravity torque 계산용)
  - `_cached_urdf`: `/robot_description` 토픽에서 읽은 URDF 문자열 캐시
- 디버그 로그 파일을 `./tmp/pilz_v6_YYYYMMDD_HHMMSS.log`에 생성

---

### 2. URDF 로딩 (`_get_robot_description`)

**읽는 토픽**: `/robot_description` (`std_msgs/String`, `TRANSIENT_LOCAL` QoS)

1. 이미 캐시된 URDF가 있으면 즉시 반환
2. `TRANSIENT_LOCAL` QoS로 `/robot_description` 토픽을 subscribe
3. 최대 5초 대기하며 URDF 문자열 수신
4. 수신 후 subscription 파괴
5. **mesh 경로 치환**: URDF 내 `/ws_aic/install/share/ur_description` 경로를 pixi 환경의 실제 `ur_description` 패키지 경로로 치환 (컨테이너/로컬 경로 차이 해결)
6. 결과를 `_cached_urdf`에 캐시하여 이후 trial에서 재사용

---

### 3. MoveItPy 초기화 (`_init_moveit`)

이미 초기화되어 있으면 스킵 (trial 간 재사용).

1. `_get_robot_description()`으로 URDF 획득
2. `my_policy/config/` 디렉토리에서 설정 파일 로드:
   - `ur5e.srdf`: SRDF (Semantic Robot Description, planning group 정의)
   - `kinematics.yaml`: KDL kinematics solver 설정
   - `pilz_cartesian_limits.yaml`: PILZ planner의 Cartesian 속도/가속도 한계
3. `config_dict` 구성:
   - `robot_description`: URDF 문자열
   - `robot_description_semantic`: SRDF 문자열
   - `robot_description_kinematics`: kinematics solver 파라미터
   - `planning_pipelines`: `pilz_industrial_motion_planner` 단일 파이프라인
   - `pilz_industrial_motion_planner`: CommandPlanner 플러그인 + request/response adapter 목록
4. `MoveItPy(node_name="my_policy_node", config_dict=...)` 생성 — 별도 ROS 노드로 MoveIt2 스택 초기화
5. `_arm = moveit.get_planning_component("manipulator")` — UR5e manipulator 그룹의 planning component 획득
6. `PlanningSceneManager` 인스턴스 생성 (parent_node와 tf_buffer 전달)

---

### 4. KDL Dynamics 체인 초기화 (`_init_kdl`)

URDF를 파싱하여 PyKDL 체인을 구축. gravity torque 계산에 사용.

1. `urdf_parser_py.urdf.URDF.from_xml_string()`으로 URDF 파싱
2. 6개 관절 순서대로 처리: `shoulder_pan → shoulder_lift → elbow → wrist_1 → wrist_2 → wrist_3`
3. **Tool chain 질량 합산**: `wrist_3_link` 이후의 모든 링크 (flange, tool0, cam_mount, ati, gripper, 카메라 3개)의 질량을 합산
   - URDF에 포함되지 않은 **케이블 무게 0.15kg**도 추가
   - 합산된 질량을 `wrist_3_link`에 합산하고, 무게중심(COM)을 가중 평균으로 재계산
   - tool chain COM은 wrist_3 기준 z=-0.1m로 근사
4. 각 관절에 대해 `PyKDL.Segment` 생성:
   - joint origin (xyz, rpy) → `PyKDL.Frame`
   - child link의 mass, COM, inertia → `PyKDL.RigidBodyInertia`
   - 모든 joint는 `RotZ` (z축 회전) 타입
5. `PyKDL.ChainDynParam(chain, gravity=(0,0,-9.81))` 생성 → 임의 관절 각도에서 gravity torque 계산 가능

---

### 5. 헬퍼 함수들

#### `_wait_for_tf(target_frame, source_frame, timeout_sec=10)`
- `tf_buffer.lookup_transform()`을 timeout까지 0.1초 간격으로 반복 시도
- 사용처: port/plug TF가 publish될 때까지 대기

#### `_compute_tcp_target(port_tf, plug_to_tcp_tf, z_offset)`
- **port TF** (world → port_frame)에서 port 위치와 방향 추출
- port의 z축(삽입 방향)을 따라 `z_offset`만큼 오프셋된 plug 목표 위치 계산
- **plug→TCP 변환** (plug_frame → gripper/tcp)을 적용하여 TCP world 목표 포즈 산출
  - TCP 위치 = plug 목표 위치 + R_port × plug→tcp translation
  - TCP 방향 = q_port × q_plug_tcp (쿼터니언 곱)

#### `_port_insert_direction(port_tf)`
- port 방향 쿼터니언 → 회전행렬의 z축 (3번째 열) = 삽입 방향 벡터

#### `_compute_gravity_torque(joint_positions)`
- KDL solver로 주어진 관절 각도에서의 gravity torque (6차원) 계산

#### `_check_trajectory_torque(points)`
- trajectory의 모든 waypoint에서 gravity torque 계산
- `EFFORT_LIMITS × TORQUE_SAFETY_MARGIN` 초과하는 waypoint 인덱스 목록 반환
- peak torque waypoint의 전 관절 torque를 로그에 출력

---

### 6. Planning (`_plan_only`, `_plan_and_execute`)

#### `_plan_only(target_pose, planner_id, velocity_scale)`
1. `_arm.set_start_state_to_current_state()` — 현재 관절 상태를 시작 상태로 설정
2. `_arm.set_goal_state(pose_stamped, pose_link="gripper/tcp")` — TCP 목표 포즈 설정
3. `PlanRequestParameters` 설정:
   - pipeline: `pilz_industrial_motion_planner`
   - planner_id: `"PTP"` 또는 `"LIN"` (PILZ planner의 두 가지 모드)
   - planning_time: 5초
   - velocity/acceleration scaling: `velocity_scale` (0.0~1.0)
   - planning_attempts: 3
4. `_arm.plan()` 호출 → 성공 시 trajectory 반환, 실패 시 None

#### `_plan_and_execute(target_pose, planner_id, velocity_scale, move_robot)`
- `_plan_only()` + `_execute_joint_trajectory()` 순차 실행

---

### 7. insert_cable — 메인 진입점

`aic_model`이 `/insert_cable` action 수신 시 호출. `Task` 메시지에서 cable/plug/port 정보를 받음.

#### 7-1. 초기화 단계

1. `_init_moveit()` 호출 (첫 trial에서만 실제 초기화, 이후 재사용)
2. TF 프레임명 구성:
   - `port_frame`: `"task_board/{target_module_name}/{port_name}_link"` (예: `task_board/nic_card_mount_0/sfp_port_0_link`)
   - `plug_frame`: `"{cable_name}/{plug_name}_link"` (예: `cable_0/sfp_tip_link`)
3. 두 프레임이 TF tree에 publish될 때까지 대기 (`_wait_for_tf`, 최대 10초)
4. **Planning Scene 등록** (`_planning_scene_manager.setup()`):
   - Enclosure collision: 메인 박스 + 기둥 4개 + 상단 벽 (world 고정, SDF 좌표 그대로)
   - Task Board collision: `task_board` TF에서 위치 읽어 보드(0.3×0.425×0.012m) + 상단 구조(0.14×0.087×0.005m) 등록
   - Mount collision: `nic_card_mount_0`, `sc_port_0` TF에서 위치 읽어 bounding box 등록
   - `/planning_scene` 토픽으로 `PlanningScene` (is_diff=True) publish
5. **Port TF 조회**: `world → port_frame` transform → port 위치/방향 획득
6. **Plug→TCP TF 조회**: `plug_frame → gripper/tcp` transform → plug에서 TCP까지의 상대 변환 (고정값, 그리퍼가 케이블을 잡고 있으므로)
7. Port 타입 판별: `task.port_name`에 `"sc_port"` 포함 여부로 SFP/SC 구분

#### 7-2. Phase 1: Torque-aware PTP Approach

**목적**: 현재 위치에서 port 위 접근 위치(SFP: 5cm, SC: 2cm)까지 PTP 이동.

`_phase1_torque_aware(tcp_approach, move_robot, get_observation)`:

1. `_init_kdl()` — KDL 체인 초기화 (첫 호출 시)
2. **직행 PTP plan**: `_plan_only(tcp_target, "PTP", velocity_scale=0.3)`
3. **Torque 검사**: `_check_trajectory_torque(points)`
   - 모든 waypoint에서 gravity torque가 `EFFORT_LIMITS × TORQUE_SAFETY_MARGIN` 이내인지 검사
4. **Case A: Torque-safe** → `_execute_waypoints(points)` 직접 실행
5. **Case B: Torque violation 발생** → 2-leg merged trajectory 생성:
   - 현재 TCP z좌표 조회 (`world → gripper/tcp` TF)
   - **Leg 1**: 현재 위치 → 중간점 (목표 XY, 현재 Z) — 같은 높이에서 XY 이동
   - **Leg 2**: 중간점 → 목표 — 하강
   - Leg 2 planning 시 `set_start_state`를 leg 1의 마지막 joint state로 설정
   - 두 trajectory를 시간 연속으로 merge (접합점 중복 제거, 시간 오프셋 누적)
   - merged trajectory를 `_execute_waypoints()`로 실행
6. **Fallback**: leg planning 실패 시 → 원래 trajectory를 `_execute_fine_interpolated()`로 실행 (8배 보간)

#### 7-2.5. Phase 1.5: IK 보정 (TCP 수렴)

**목적**: Phase 1 종료 후 실제 TCP 위치를 목표에 수렴시킴.

`_ik_converge(target_pose, get_observation, move_robot)`:

1. MoveItPy IK로 목표 pose → joint position 계산
2. `JointMotionUpdate` 발행
3. 실제 TCP 위치 측정 → 오차 계산
4. 오차 < `IK_CONVERGE_THRESHOLD` (1mm) 이면 수렴 완료
5. 최대 `IK_CONVERGE_MAX_LOOPS` (100회, 5초) 반복

#### 7-3. Phase 2: LIN Descent → PTP Fallback

**목적**: 접근 위치에서 삽입 직전 위치까지 직선(LIN) 하강.

1. TCP 목표 계산: `_compute_tcp_target(port_tf, plug_to_tcp_tf, Z_OFFSET_PREINSERT_*)`
2. `_plan_and_execute(tcp_preinsert, "LIN", velocity_scale=0.3)` 시도
   - LIN planner: Cartesian 직선 경로 생성 (PILZ 내부에서 IK 연속 해석)
3. **LIN 실패 시**: `_plan_and_execute(tcp_preinsert, "PTP", velocity_scale=0.1)` — PTP fallback
4. 둘 다 실패 시 → `return False` (trial 실패)

#### 7-4. Phase 3: Joint IK 삽입 + Force Slope 완료 판정

**목적**: port 방향으로 TCP를 증분 이동시키며 케이블을 삽입. depth + force 기울기 + force 크기로 완료/안전 정지 판정.

`_force_insert(port_tf, plug_to_tcp_tf, plug_frame, get_observation, move_robot, depth_threshold)`:

**초기화:**
1. port의 삽입 방향 벡터 (`port_z`) 및 위치 (`port_pos`) 계산
2. 현재 TCP 위치/방향 조회 (`world → gripper/tcp` TF)
3. 현재 관절 각도 조회 (`get_observation().joint_states.position[:6]`)
4. 초기 depth 계산: `dot(plug_pos - port_pos, port_z)` — port 좌표계 z축 투영

**제어 루프** (최대 2000회, 20Hz):

매 루프마다:

1. **관측 획득**: `get_observation()` → wrench (힘/토크), joint states
2. **Force 계산**:
   - `f_raw`: wrench force 벡터 (fx, fy, fz)
   - `f_insert = -dot(f_raw, port_z)` — 삽입 방향 투영 (양수=삽입, 음수=반발)
   - `f_abs = |f_raw|` — 전체 force 크기 (안전 정지용)
3. **Depth 계산**: `world → plug_frame` TF 조회 → `dot(plug_pos - port_pos, port_z)`
4. **Force 기울기 계산**: 최근 `FORCE_SLOPE_WINDOW` (5) 샘플의 선형 회귀 기울기 (N/s)

5. **종료 조건 1 — 삽입 완료** (3개 조건 AND, 즉시 종료):
   - `depth >= depth_threshold` (SFP: 0.0m, SC: -0.0008m)
   - `f_insert <= FORCE_LOW_THRESHOLD` (5.0N) — 삽입 저항 소멸
   - `f_slope < FORCE_SLOPE_THRESHOLD` (-2.0 N/s) — force가 감소 추세
   - → **insert_complete**로 즉시 종료

6. **종료 조건 2 — 안전 정지**:
   - `|force| > FORCE_STOP_THRESHOLD` (20N) 이 `FORCE_PENALTY_DURATION` (1.5초) 지속
   - → **force_stop**으로 종료

7. **TCP 증분 이동**:
   - `tcp_pos += port_z × INSERT_VELOCITY × DT` — 삽입 방향으로 0.5mm/step 이동 (10mm/s)
   - 새 TCP 위치로 `Pose` 생성 (방향은 Phase 2 종료 시의 TCP 방향 유지)

8. **MoveItPy IK 풀기**:
   - `planning_scene_monitor.read_only()` → `current_state.set_from_ik("manipulator", target_pose, "gripper/tcp")`
   - IK 성공: 결과 joint 값을 `last_joints`에 저장
   - IK 실패: TCP 이동 롤백

9. **Joint command 발행**:
   - `JointMotionUpdate` (MODE_POSITION, `EXEC_STIFFNESS`, `EXEC_DAMPING`)
   - `move_robot(joint_motion_update=ju)` → `/aic_controller/joint_commands`

10. **로그**: 매 10회마다 depth, f_insert, |f|, slope, raw force 출력

**루프 종료 후:**
1. 최종 depth, XY error 로그 출력 (안정화 없이 즉시 종료)

---

### 8. Trajectory 실행 방식 (Phase 1-2)

#### `_execute_joint_trajectory(trajectory)`
PILZ planner가 생성한 trajectory를 실행하되, 먼저 torque 안전 검사 수행.

1. `_init_kdl()` — KDL 초기화
2. trajectory에서 `JointTrajectoryPoint` 목록과 총 duration 추출
3. `_check_trajectory_torque(points)` — 전 waypoint gravity torque 검사
4. **Violation 있음** → `_execute_fine_interpolated(points)` (안전 모드)
5. **Violation 없음** → `_execute_waypoints(points)` (일반 모드)

#### `_execute_waypoints(points)` — 일반 실행
- trajectory의 각 waypoint를 **시간 동기화**하여 순차 발행
  - `time_from_start`를 기준으로 실제 경과 시간과 비교, 필요시 `sleep_for(wait)`
  - 각 waypoint를 `JointMotionUpdate` (MODE_POSITION, `EXEC_STIFFNESS`, `EXEC_DAMPING`) 메시지로 발행
  - `move_robot(joint_motion_update=ju)` → `/aic_controller/joint_commands`
- 매 10번째/첫/마지막 waypoint에서:
  - `get_observation()`으로 실제 joint position, wrench, effort 조회
  - joint error (목표-실제 차이), TCP 위치, effort peak 비율 로그 출력
- **안정화 0.5초**: trajectory 종료 후 마지막 waypoint를 0.05초 간격으로 계속 발행

#### `_execute_fine_interpolated(points)` — 안전 실행 (torque violation 대응)
- 원래 waypoint 간격을 **8배 세밀 보간** (linear interpolation)
  - 예: 39 waypoints → 305 interpolated waypoints
- 보간된 waypoint를 시간 동기화하여 순차 발행
- 관절이 더 작은 단위로 이동하므로 순간 토크 스파이크 완화
- **안정화 0.5초**: 동일

---

### 9. Planning Scene (planning_scene.py)

> **현재 상태: collision check 비활성화 **
> 추가해야 할 구조물이 남아있어 활성화 시 false positive 가능.
> `setup()`은 호출되지만 collision object를 등록하지 않고 즉시 반환.

`PlanningSceneManager.setup()` — trial 시작 시 1회 호출.
활성화 시 ground truth TF를 읽어 collision object를 `/planning_scene` 토픽으로 등록.

#### Task Board (TF 기반, `task_board` frame)
- `task_board` TF 조회 (최대 timeout_sec 대기)
- 전체 보드: 0.3×0.425×0.012m (z=0.006 오프셋)
- 상단 구조: 0.14×0.087×0.005m (x=-0.075, y=0.05, z=0.011 오프셋)
- parent pose + local offset 합성으로 world 좌표 계산

#### Mounts (TF 기반)
- `nic_card_mount_0` → 0.05×0.018×0.020m bounding box
- `sc_port_0` → 0.05×0.014×0.025m bounding box
- 해당 TF가 없는 마운트는 자동 스킵


---

### 10. 사용하는 ROS 토픽/TF 요약

| 방향 | 토픽/TF | 용도 |
|------|---------|------|
| **Subscribe** | `/robot_description` (String, TRANSIENT_LOCAL) | URDF 로드 → MoveItPy/KDL 초기화 |
| **TF Lookup** | `world → task_board/{module}/{port}_link` | port 위치/방향 |
| **TF Lookup** | `world → {cable}/{plug}_link` | plug 위치 (depth 계산) |
| **TF Lookup** | `{plug}_link → gripper/tcp` | plug-TCP 상대 변환 (목표 TCP 계산) |
| **TF Lookup** | `world → gripper/tcp` | 현재 TCP 위치 (Phase 1 중간점, 로그) |
| **TF Lookup** | `world → task_board` | planning scene: task board 위치 |
| **TF Lookup** | `world → nic_card_mount_0`, `sc_port_0` 등 | planning scene: mount 위치 |
| **Callback** | `get_observation()` | joint_states, wrist_wrench, controller_state |
| **Publish** | `move_robot(joint_motion_update=...)` → `/aic_controller/joint_commands` | JointMotionUpdate 명령 |
| **Publish** | `/planning_scene` (PlanningScene) | collision object 등록 |
| **Callback** | `send_feedback(string)` | InsertCable action feedback (디버그) |

---

### 11. 안정화 시간

각 Phase 종료 시 마지막 joint position을 0.05초 간격으로 반복 발행하는 안정화 구간:

| 구간 | 시간 | 상수 |
|------|------|------|
| Phase 1 종료 | 0.5초 | `SETTLE_DURATION` |
| Phase 1.5 | ~0.05초 | IK 1회 수렴 (보통 즉시) |
| Phase 2 종료 | 0.5초 | `SETTLE_DURATION` |
| Phase 3 종료 | 없음 | 종료 조건 충족 시 즉시 종료 |
| **합계** | **~1.05초** | |

---

### 12. 전체 실행 흐름 요약

```
aic_model 노드 시작
  └─ PilzPolicy.__init__()
       ├─ 내부 상태 초기화 (MoveIt/KDL은 lazy)
       └─ 디버그 로그 파일 생성

aic_engine이 /insert_cable action 호출
  └─ insert_cable(task, get_observation, move_robot, send_feedback)
       │
       ├─ [초기화]
       │   ├─ _init_moveit()
       │   │   ├─ /robot_description 토픽 subscribe → URDF 수신
       │   │   ├─ mesh 경로 치환
       │   │   ├─ config/*.yaml 로드 (SRDF, kinematics, cartesian_limits)
       │   │   ├─ MoveItPy 생성 (PILZ planner 등록)
       │   │   └─ PlanningSceneManager 생성
       │   ├─ TF 대기: port_frame, plug_frame
       │   ├─ planning_scene_manager.setup() (현재 비활성화)
       │   ├─ port TF 조회 → port 위치/방향
       │   ├─ plug→tcp TF 조회 → 상대 변환
       │   └─ port 타입 판별 (SFP / SC)
       │
       ├─ [Phase 1: Torque-aware PTP Approach]
       │   ├─ TCP 목표 = port 위치 + port_z × z_offset_approach
       │   ├─ _init_kdl() → KDL chain 구축
       │   ├─ PTP plan (velocity_scale=0.3)
       │   ├─ 전 waypoint gravity torque 검사
       │   ├─ Safe → _execute_waypoints()
       │   └─ Violation → 2-leg merged trajectory 또는 fine interpolation (8배)
       │
       ├─ [Phase 1.5: IK 보정]
       │   └─ _ik_converge() → 목표 TCP에 1mm 이내 수렴
       │
       ├─ [Phase 2: LIN Descent → PTP Fallback]
       │   ├─ LIN plan (velocity_scale=0.3) 시도
       │   └─ 실패 시 PTP (velocity_scale=0.1) fallback
       │
       └─ [Phase 3: Joint IK Insertion]
           ├─ 초기: TCP 위치, 관절 각도, 초기 depth 기록
           ├─ 루프 (max 2000회, 20Hz):
           │   ├─ observation → f_insert (port방향 투영), |f|, depth 계산
           │   ├─ force slope 계산 (5 sample window, 선형 회귀)
           │   ├─ 삽입 완료? depth≥threshold AND f_ins≤5N AND slope<-2N/s → 즉시 종료
           │   ├─ 안전 정지? |f|>20N → 1.5초 유지 시 종료
           │   ├─ TCP += port_z × 0.01 × 0.05 (0.5mm/step, 10mm/s)
           │   ├─ MoveItPy IK → joint 각도 계산
           │   └─ JointMotionUpdate 발행 (EXEC_STIFFNESS, EXEC_DAMPING)
           └─ 최종 depth, XY error 로그 (즉시 종료)
```
