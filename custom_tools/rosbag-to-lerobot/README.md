# jjhyeongg 수정사항

- `main.py`: `~/aic_data/raw/`에서 직접 수집 데이터를 읽도록 변경.
- `main.py`: score 필터링 내장 (`config.json`의 `min_score`). 미달 config → `~/aic_data/skipped/` 자동 이동.
- `main.py`: 변환 완료된 config → `~/aic_data/done/` 자동 이동 (`move_after_convert`).
- `main.py`: task_metadata.yaml에서 task instruction 자동 생성.
- `constants.py`: 기본 경로를 `~/aic_data/{raw,lerobot,done,skipped}`로 변경.
- `config.json`: `min_score`, `move_after_convert` 필드 추가.
- 아래 README 사용법도 위 변경에 맞춰 수정함.

---

# rosbag-to-lerobot

ROS2 rosbag (MCAP) files to [LeRobot](https://github.com/huggingface/lerobot) v3.0 dataset converter. No ROS2 installation required.

## Project Structure

```
rosbag-to-lerobot/
├── lerobot/                  # huggingface/lerobot (git submodule)
├── src/
│   ├── config.json           # Conversion configuration
│   ├── main.py               # CLI entry point
│   └── v3_conversion/
│       ├── constants.py      # Path constants (INPUT_PATH, OUTPUT_PATH)
│       ├── converter.py      # Main orchestrator
│       ├── mcap_reader.py    # MCAP frame extraction
│       ├── data_converter.py # Message-to-numpy conversion
│       ├── data_creator.py   # LeRobot dataset writer
│       ├── data_spec.py      # Rosbag config dataclass
│       └── hz_checker.py     # Frequency validation
└── pixi.toml                 # Pixi environment
```

## Setup

```bash
cd custom_tools/rosbag-to-lerobot
git submodule update --init --recursive lerobot
pixi install
```


## Data Layout (AIC 프로젝트)

변환기가 `~/aic_data/raw/`에서 직접 수집 데이터를 읽습니다.
별도 input 디렉토리 준비 불필요 — score 필터링, metacard 생성, done/skipped 이동을 자동 처리.

```
~/aic_data/
├── raw/                  # collect_training_data.sh 출력 (INPUT_PATH)
│   ├── config_sfp_0000/
│   │   ├── scoring.yaml
│   │   ├── task_metadata.yaml
│   │   └── engine_results/bag_trial_1_*/*.mcap
│   └── ...
├── done/                 # 변환 완료 후 자동 이동 (DONE_PATH)
├── skipped/              # min_score 미만 자동 이동 (SKIPPED_PATH)
└── lerobot/              # LeRobot 변환 결과 (OUTPUT_PATH)
```

## Configuration

Edit `src/config.json`:

```json
{
  "task": "aic_task",
  "repo_id": "Phy-lab/jjhyeongg",
  "robot": "ur5e",
  "fps": 20,
  "folders": "all",
  "min_score": 90.0,
  "move_after_convert": true,
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

| Field | Description |
|-------|-------------|
| `task` | Task/dataset name (output directory name) |
| `repo_id` | HuggingFace Hub repo (e.g. `org/name`). Set to push after conversion |
| `robot` | Robot type (e.g. `ur5e`) |
| `fps` | Target frames per second |
| `folders` | `"all"` to auto-detect from INPUT_PATH |
| `min_score` | Minimum trial score to convert (lower → skipped/) |
| `move_after_convert` | Move configs to done/skipped after conversion |
| `camera_topic_map` | Camera name to ROS topic mapping |
| `joint_names` | Ordered joint name list |
| `state_topic` | Observation joint states topic |
| `action_topics_map` | Leader source to ROS topic mapping |

## Run: Pixi (권장)

```bash
cd custom_tools/rosbag-to-lerobot
pixi run convert
```

이 한 줄로: raw/ 스캔 → score 필터 → LeRobot 변환 → HuggingFace 업로드 → done/skipped 이동.

## Environment Variables

Data paths are controlled by environment variables in `src/v3_conversion/constants.py`:

| Env var | Description | Default |
|---------|-------------|---------|
| `INPUT_PATH` | Raw data directory | `~/aic_data/raw` |
| `OUTPUT_PATH` | LeRobot output directory | `~/aic_data/lerobot` |
| `DONE_PATH` | Converted configs moved here | `~/aic_data/done` |
| `SKIPPED_PATH` | Low-score configs moved here | `~/aic_data/skipped` |

Override example:

```bash
INPUT_PATH=~/custom_raw OUTPUT_PATH=~/custom_output pixi run convert
```

