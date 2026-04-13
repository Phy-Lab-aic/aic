# Config 생성 도구 — Design Document

> `gen_scene_config.py` 하나로 train/test 모드를 모두 지원합니다.

---

## 모드 비교

| 항목 | train | test |
|------|-------|------|
| trial 수/config | 1 | 3 (SFP×2 + SC×1) |
| 출력 구조 | `configs/train/sfp/`, `configs/train/sc/` 분리 | `configs/test/` 단일 |
| 파일명 | `config_sfp_XXXX.yaml`, `config_sc_XXXX.yaml` | `config_test_XXXX.yaml` |
| 용도 | VLA 학습 데이터 수집 | 평가 흐름 재현 (qualification 시뮬레이션) |

---

## 출력 구조

### train 모드

```
configs/train/
├── sfp/
│   ├── config_sfp_0000.yaml
│   ├── config_sfp_0001.yaml
│   ├── configs_log.xlsx
│   └── ...
└── sc/
    ├── config_sc_0000.yaml
    ├── config_sc_0001.yaml
    ├── configs_log.xlsx
    └── ...
```

### test 모드

```
configs/test/
├── config_test_0000.yaml    (trial_1=SFP, trial_2=SFP, trial_3=SC)
├── config_test_0001.yaml
├── configs_log.xlsx
└── ...
```

---

## 실행 방법

```bash
cd custom_tools
pixi install       # 최초 1회
pixi run gen-config
```

GUI 창에서:
1. **Mode** 선택: train (sfp/sc 분리) / test (3-trial)
2. **Number** 입력: SFP, SC 개수 각각 입력 (권장 비율 5:2, 예: SFP=50, SC=20)
3. **Generate** 클릭
4. 하단에 train/test 각각의 target/rail 분포 표시

기존 파일의 최대 번호를 자동 감지하여 이어서 생성합니다 (번호 충돌 없음).

`collect_training_data.sh --task-type sfp|sc|all`이 sfp/, sc/ 폴더를 기준으로 필터링합니다.

---

## 씬 구성

모든 config는 task 타입에 관계없이 **NIC card와 SC port를 모두 포함**하는 full scene을 생성합니다:

- **SFP task config**: NIC card (1~5개 랜덤) + SC port (1~2개 랜덤) + mount rail
- **SC task config**: SC port (타겟 포함 필수) + NIC card (1~5개 랜덤) + mount rail

모델이 모든 씬에서 전체 컴포넌트를 보도록 하여 시각적 다양성을 확보합니다.

---

## Task Target 분배

타겟은 **결정적 순환(deterministic cycling)**으로 할당되어 완벽하게 균등한 분포를 보장합니다:

- **SFP**: 10가지 조합 (5 rail x 2 port) 순환
  - `nic_card_mount_0/sfp_port_0`, `nic_card_mount_0/sfp_port_1`, ..., `nic_card_mount_4/sfp_port_1`
- **SC**: 2가지 타겟 순환
  - `sc_port_0`, `sc_port_1`

예시: SFP 100개 생성 시 → 10가지 타겟 각 정확히 10개.

**권장 비율**: SFP:SC = **5:2** (예: SFP=50, SC=20). 고유 타겟 수(SFP 10개, SC 2개)에 맞추기 위함.

---

## 랜덤화 분포

모든 연속 파라미터는 범위 내 **균등 분포(Uniform Distribution)**를 사용합니다.

| 파라미터 | 분포 | 범위 | 출처 |
|----------|------|------|------|
| NIC card translation | Uniform | [-0.0215, 0.0234] m | `task_board_limits.nic_rail` |
| NIC card yaw | Uniform | [-0.175, +0.175] rad (±10°) | `task_board_description.md` |
| SC port translation | Uniform | [-0.06, 0.055] m | `task_board_limits.sc_rail` |
| Gripper offset xyz | Uniform | nominal ± 0.002 m | `qualification_phase.md` |
| Gripper offset rpy | Uniform | nominal ± 0.04 rad | `qualification_phase.md` |
| NIC card 수 | Uniform 정수 | 1~5 | `qualification_phase.md` |
| SC port 존재 여부 | 독립 coin flip (최소 1개) | 0, 1 | `qualification_phase.md` |
| Target rail/port | **결정적 순환** (균등) | 위 참조 | 설계 결정 |

---

## 고정 항목

| 항목 | 값 | 고정 이유 |
|------|-----|----------|
| `scoring.topics` | sample 값 그대로 | 평가 인터페이스 불변 |
| `task_board_limits` | sample 값 그대로 | aic_engine 검증 범위, 수정 금지 |
| `robot.home_joint_positions` | sample 값 그대로 | 로봇 시작 자세 고정 |
| `task_board.pose` (SFP) | x=0.15, y=-0.2, z=1.14, yaw=π | 카메라 시야 안에 target 보장 |
| `task_board.pose` (SC) | x=0.17, y=0.0, z=1.14, yaw=3.0 | 동일 이유 |
| SC port yaw | 0.0 | `qualification_phase.md`에 SC orientation 랜덤화 명시 없음 |
| Mount rails | sample trial_1 패턴 | task 대상 아님, 고정 |
| `time_limit` | 180 | 모든 trial 동일 고정값 |

---

## 랜덤화 항목

### NIC Card (SFP trial)

| 항목 | 범위 | 근거 문서 | 인용 |
|------|------|-----------|------|
| NIC card 수 | 1~5개 (비복원) | `qualification_phase.md` | *"One or more NIC_CARDs are mounted on randomly selected NIC_RAILs (there are 5 rails: nic_rail_0 through nic_rail_4)"* |
| rail 선택 (0~4) | 비복원 랜덤 | `qualification_phase.md` | 동일 |
| `entity_pose.translation` | [-0.0215, 0.0234] m | `sample_config.yaml` `task_board_limits.nic_rail` | `min_translation: -0.0215`, `max_translation: 0.0234` |
| `entity_pose.yaw` | [-0.175, +0.175] rad (±10°) | `task_board_description.md` | *"Card orientation limits: [-10, +10] degrees"* (Zone 1) |
| target `port_name` | sfp_port_0 / sfp_port_1 | `qualification_phase.md` | *"Insert … into either SFP_PORT_0 or SFP_PORT_1 … (the task config from aic_engine will specify which)"* |

### SC Port (SC trial)

| 항목 | 범위 | 근거 문서 | 인용 |
|------|------|-----------|------|
| SC port 수 | 1 or 2개 | `qualification_phase.md` | *"One or both SC ports are mounted on the task board"* |
| rail 선택 (0, 1) | 독립 on/off, 최소 1개 | 동일 | *"Only one SC port will be the target port"* |
| `entity_pose.translation` | [-0.06, 0.055] m | `task_board_description.md`<br>`sample_config.yaml` | `min_translation: -0.06`<br>`max_translation: 0.055`<br>*"each with a random translation along its rail"* |

### Gripper Offset (모든 trial)

| 항목 | 범위 | 근거 | 인용 |
|------|------|------|------|
| SFP xyz | nominal ± 0.002 m | `qualification_phase.md` | *"small deviations (~2mm, ~0.04 rad) in the relative grasp pose"* |
| SFP rpy | nominal ± 0.04 rad | 동일 | 동일 |
| SC xyz | nominal ± 0.002 m | 동일 | 동일 |
| SC rpy | nominal ± 0.04 rad | 동일 | 동일 |

Nominal 값:

| type | x | y | z | roll | pitch | yaw | 출처 |
|------|---|---|---|------|-------|-----|------|
| SFP | 0.0 | 0.015385 | 0.04245 | 0.4432 | -0.4838 | 1.3303 | `qualification_phase.md` + `sample_config.yaml` trial_1 |
| SC  | 0.0 | 0.015385 | 0.04045 | 0.4432 | -0.4838 | 1.3303 | `qualification_phase.md` + `sample_config.yaml` trial_3 |

---

## Entity Name / Target Module Name 매핑

| rail | `entity_name` (Gazebo) | `target_module_name` (Task.msg) |
|------|------------------------|----------------------------------|
| nic_rail_0 | `nic_card_0` | `nic_card_mount_0` |
| nic_rail_1 | `nic_card_1` | `nic_card_mount_1` |
| nic_rail_2 | `nic_card_2` | `nic_card_mount_2` |
| nic_rail_3 | `nic_card_3` | `nic_card_mount_3` |
| nic_rail_4 | `nic_card_4` | `nic_card_mount_4` |
| sc_rail_0  | `sc_mount_0` | `sc_port_0` |
| sc_rail_1  | `sc_mount_1` | `sc_port_1` |

> 근거: `sample_config.yaml` 패턴 + `aic_engine.cpp` 확인

---

## Excel 로그 구조

### train 모드

각 sfp/, sc/ 폴더에 독립 `configs_log.xlsx` 생성.
행 단위: 1행 = 1 config = 1 trial. 행 색상: SFP=파란색, SC=주황색.

### test 모드

단일 `configs_log.xlsx`.
행 단위: 1행 = 1 trial (config당 3행). 행 색상: trial_1=파란색, trial_2=초록색, trial_3=주황색.

### 공통 열

| 열 | 설명 |
|----|------|
| file | 생성된 yaml 파일명 |
| seed | 해당 실행의 랜덤 seed |
| trial | trial_1 / trial_2 / trial_3 (test만) |
| type | SFP / SC |
| n_nic | NIC card 수 (SFP만) |
| nic_rails | 배치된 NIC rail 번호 목록 (SFP만) |
| sc_rails | 배치된 SC rail 번호 목록 (SC만) |
| target_rail | 타겟 rail 번호 |
| port_name | 타겟 port 이름 |
| target_trans | 타겟 entity translation (m) |
| target_yaw | 타겟 entity yaw (rad, SC는 항상 0) |
| gripper_x/y/z | gripper offset 위치 (m) |
| gripper_roll/pitch/yaw | gripper offset 자세 (rad) |

---

## 현재 제한 사항

### Task Board 위치 랜덤화 미적용

현재 task board의 위치(pose)는 고정값 사용. 랜덤화하려면:
1. 목표 포트가 카메라 시야(FOV) 안에 있어야 함
2. 그리퍼에서 타겟 포트까지 거리가 수 cm 이내여야 함
3. 로봇의 관절 한계 내에서 도달 가능한 위치여야 함

→ 시뮬레이션 실측으로 유효 범위 결정 필요.

---

## 검증 체크리스트

1. **구조 검증**: 생성된 yaml top-level key가 `sample_config.yaml`과 동일한지 확인
2. **범위 검증**: 스크립트 내 `_assert_in_range()` 함수가 `task_board_limits` 위반 시 AssertionError 발생
3. **분포 검증**: 실행 후 GUI 통계에서 NIC rail 0~4, SC rail 0~1이 균등하게 분포하는지 확인
4. **타겟 균등 검증**: SFP 10가지 타겟, SC 2가지 타겟이 각각 동일 개수인지 확인
5. **씬 완성도 검증**: 모든 config에 NIC card와 SC port가 모두 포함되어 있는지 확인
6. **폴더 검증** (train만): sfp/ 폴더에 `config_sfp_*`, sc/ 폴더에 `config_sc_*`만 있는지 확인
7. **시뮬레이션 검증**: 생성된 config를 `aic_engine`에 전달하여 Gazebo 구동 테스트
