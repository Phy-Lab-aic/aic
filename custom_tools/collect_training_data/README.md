# Training Data Collection Pipeline

AIC 챌린지 정책(policy) 학습을 위한 E2E 데이터 수집 파이프라인.
`custom_tools/gen_training_configs/configs/train/` 하위 config들을 순차 실행하며, 모든 토픽 데이터 + 점수 + task 메타데이터를 수집한다.

## 구성 파일

| 파일 | 설명 |
|------|------|
| `collect_training_data.sh` | 메인 데이터 수집 스크립트 |
| `extract_metadata.py` | config YAML → task_metadata.yaml 변환 |
| `merge_results.py` | 전체 결과 summary.csv / summary.yaml 생성 |
| `monitor_camera.py` | 카메라 실시간 모니터링 (cv2.imshow) |
| `prepare_for_lerobot.py` | [DEPRECATED] 변환기가 raw/에서 직접 처리 |

## 사전 요구사항

- `aic_eval` distrobox/docker 컨테이너 실행 중
- pixi 환경 설정 완료
- 정책 패키지 빌드 완료 (또는 `--skip-build` 미사용 시 자동 빌드)

---

## Quick Start: 전체 파이프라인

### Step 1. Config 생성

```bash
cd custom_tools
pixi run gen-config   # GUI에서 mode/개수 선택
```

### Step 2. 데이터 수집

```bash
# 주력 명령어
./collect_training_data/collect_training_data.sh my_policy.PilzPolicy \
    --headless --monitor --task-type all \
    --start-idx 0 --end-idx 1000
```

출력: `~/aic_data/raw/config_sfp_XXXX/` 또는 `~/aic_data/raw/config_sc_XXXX/`

### Step 3. LeRobot 변환 + 업로드

```bash
cd rosbag-to-lerobot
pixi run convert
```

자동으로: raw/ 스캔 → 90점 미만은 skipped/ → 변환 → 업로드 → done/로 이동

### Step 4. 증분 수집 + 변환

```bash
# 추가 수집 (resume 자동)
./collect_training_data/collect_training_data.sh my_policy.PilzPolicy \
    --headless --monitor

# 변환 (raw/에 남아있는 새 데이터만 처리)
cd rosbag-to-lerobot && pixi run convert
```

---

## 데이터 수집 상세

### CLI 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--headless` | off | GUI 없이 실행 |
| `--monitor` | off | 카메라 피드 cv2.imshow 표시 (headless 확인용) |
| `--task-type <sfp\|sc\|all>` | `all` | config 타입 필터 (sfp/, sc/ 폴더 기반) |
| `--start-idx <N>` | `0` | 시작 config 인덱스 |
| `--end-idx <N>` | `999` | 종료 config 인덱스 |
| `--data-dir <path>` | `~/aic_data/raw` | 출력 디렉토리 |
| `--no-ground-truth` | on | ground truth TF 비활성화 (기본: 활성화) |
| `--skip-build` | off | pixi 빌드 스킵 |
| `--max-retries <N>` | `3` | config당 최대 재시도 횟수 |

### 사용 예시

```bash
# SFP만 10개 수집
./collect_training_data.sh my_policy.PilzPolicy \
    --headless --task-type sfp --start-idx 0 --end-idx 9

# 이어하기 (progress.yaml 기반 자동 resume)
./collect_training_data.sh my_policy.PilzPolicy --headless --monitor
```

### 카메라 모니터링

`--monitor` 옵션 또는 단독 실행:

```bash
# 단독: center 카메라만
pixi run python3 monitor_camera.py

# 단독: 모든 카메라 (3개 창)
pixi run python3 monitor_camera.py --all
```

---

## 데이터 기록 방식

### 기록 토픽

> `aic_engine` 내부 `record_all_topics` 파라미터로 기록. `collect_training_data.sh`에서 자동으로 `-p record_all_topics:=true`를 전달하여 활성화됨.

| 구분 | 토픽 |
|------|------|
| scoring (기본) | `/joint_states`, `/tf`, `/tf_static`, `/scoring/tf` |
| scoring (기본) | `/fts_broadcaster/wrench`, `/aic_controller/controller_state` |
| scoring (기본) | `/aic_controller/pose_commands`, `/aic_controller/joint_commands` |
| scoring (기본) | `/scoring/insertion_event`, `/aic/gazebo/contacts/off_limit` |
| 학습용 (추가) | `/observations`, `/left_camera/image`, `/center_camera/image`, `/right_camera/image` |
| 학습용 (추가) | `/left_camera/camera_info`, `/center_camera/camera_info`, `/right_camera/camera_info` |

---

## LeRobot 변환

변환기가 `~/aic_data/raw/`에서 직접 읽고, score 필터링 + done/skipped 이동을 자동 수행합니다.

```bash
cd custom_tools/rosbag-to-lerobot
pixi run convert
```

### 변환 흐름

```
~/aic_data/raw/config_sfp_0000/  ──(score >= 90)──→  변환  →  ~/aic_data/done/config_sfp_0000/
~/aic_data/raw/config_sc_0001/   ──(score < 90)───→          ~/aic_data/skipped/config_sc_0001/
```

### config.json 설정 (rosbag-to-lerobot/src/config.json)

```json
{
  "task": "aic_task",
  "repo_id": "psedulab/aic_task",
  "robot": "ur5e",
  "fps": 20,
  "folders": "all",
  "camera_topic_map": {
    "cam_left": "/left_camera/image",
    "cam_center": "/center_camera/image",
    "cam_right": "/right_camera/image"
  },
  "joint_names": [
    "shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
    "wrist_1_joint", "wrist_2_joint", "wrist_3_joint",
    "gripper/left_finger_joint"
  ],
  "state_topic": "/joint_states",
  "action_topics_map": { "leader": "/joint_states" }
}
```

- `state_topic`: 관측(observation) = 현재 관절 위치
- `action_topics_map.leader`: 행동(action) = 관절 궤적 (다음 관절 위치 예측)

---

## 출력 디렉토리 구조

```
~/aic_data/raw/                     # 수집 직후 (변환 전)
├── config_sfp_0000/                # SFP
│   ├── config.yaml                 # 원본 config 복사
│   ├── task_metadata.yaml          # 파싱된 task 정보
│   ├── scoring.yaml                # 점수 결과
│   └── engine_results/             # aic_engine 출력
│       ├── bag_trial_1_*/
│       └── scoring.yaml
├── config_0001/                    # SC (홀수)
│   └── ...
├── progress.yaml                   # resume 추적
├── collection.log                  # 실행 로그
├── summary.csv                     # 결과 요약 (trial 단위)
├── summary.yaml                    # 결과 통계
└── logs/

~/aic_data/done/                    # 변환+업로드 완료 (자동 이동)
~/aic_data/skipped/                 # 90점 미만 (자동 이동)
~/aic_data/lerobot/                 # LeRobot 변환 결과
```

## Resume 동작

`progress.yaml`에 완료/실패 상태가 기록된다. 동일 명령 재실행 시 완료된 config는 skip.

```yaml
config_sfp_0000: completed  # score=94.0335 time=2026-04-08T12:34:56
config_0001: completed  # score=38.1200 time=2026-04-08T12:42:10
config_0002: failed  # time=2026-04-08T12:50:30
```

실패한 config를 재시도: `progress.yaml`에서 해당 줄 삭제.

---

## 디스크 / 시간 추정

| 항목 | 추정값 |
|------|--------|
| Engine bag (전체 토픽, zstd) | config당 ~1-3 GB |
| 전체 2000 configs | ~2-6 TB |
| Config당 소요 시간 | ~7분 |
| 전체 2000 configs | ~233시간 (~10일) |
