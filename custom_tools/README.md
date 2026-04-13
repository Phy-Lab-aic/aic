# Tools — AIC 학습 데이터 파이프라인

AIC 챌린지 정책 학습을 위한 데이터 수집 → 변환 → 업로드 E2E 파이프라인.

## 디렉토리 구조

```
custom_tools/
├── gen_training_configs/       # Config 생성기
│   ├── gen_scene_config.py           # train(1trial, sfp/sc분리) + test(3trial) 통합
│   ├── design.md                     # 설계 문서
│   └── configs/
│       ├── train/sfp/                # config_sfp_XXXX.yaml
│       ├── train/sc/                 # config_sc_XXXX.yaml
│       └── test/                     # config_test_XXXX.yaml
│
├── collect_training_data/      # 데이터 수집
│   ├── collect_training_data.sh      # 메인 수집 스크립트
│   ├── extract_metadata.py           # config → task_metadata.yaml
│   ├── merge_results.py              # 결과 summary 생성
│   ├── monitor_camera.py             # 카메라 모니터링 (cv2.imshow)
│   └── README.md                     # 상세 문서
│
├── rosbag-to-lerobot/          # MCAP → LeRobot v3 변환기 + HuggingFace 업로드
│   ├── src/main.py                   # 변환 + 업로드 진입점 (score 필터 + 자동 이동 포함)
│   ├── src/config.json               # 토픽 매핑, repo_id, min_score 설정
│   ├── pixi.toml                     # 변환기 pixi 환경
│   └── README.md                     # 변환기 상세 문서
│
├── curation-tools/             # (선택) LeRobot 데이터셋 시각화 + 품질 태깅
│
└── pixi.toml                   # tools pixi 환경 (config 생성용)
```

## 데이터 디렉토리 구조

```
~/aic_data/
├── raw/                # 수집 직후 데이터 (아직 변환 안 한 것)
├── done/               # 변환+업로드 완료 (자동 이동)
├── skipped/            # 90점 미만 (자동 이동)
└── lerobot/            # LeRobot 변환 결과
```

---

## E2E 파이프라인 전체 흐름

```
[1. Config 생성]  →  [2. 데이터 수집 → raw/]  →  [3. 변환 + 업로드]
                                                        ↓
                                              score >= 90 → done/
                                              score <  90 → skipped/
```

---

## Step 0. 사전 준비 (최초 1회)

### 0-1. rosbag-to-lerobot pixi 환경 설치

```bash
cd custom_tools/rosbag-to-lerobot
git submodule update --init --recursive lerobot
pixi install
```

### 0-2. HuggingFace 로그인 (토큰 영구 저장)

```bash
cd custom_tools/rosbag-to-lerobot
pixi run python3 -c "from huggingface_hub import login; login()"
```

### 0-3. config.json 설정

`rosbag-to-lerobot/src/config.json`:

```json
{
  "repo_id": "Phy-lab/jjhyeongg",
  "task": "aic_task",
  "robot": "ur5e",
  "fps": 20,
  "folders": "all",
  "min_score": 90.0,
  "move_after_convert": true,
  "camera_topic_map": { ... },
  "joint_names": [ ... ],
  "state_topic": "/joint_states",
  "action_topics_map": { "leader": "/joint_states" }
}
```

- `min_score`: 이 점수 미만 에피소드는 skipped/로 이동
- `move_after_convert`: 변환 완료 후 raw/ → done/ 자동 이동

---

## Step 1. Config 생성

```bash
cd custom_tools
pixi install        # 최초 1회
pixi run gen-config # GUI에서 mode/개수 선택
```

출력:
- `configs/train/sfp/config_sfp_0000.yaml` ~ `config_sfp_0499.yaml`
- `configs/train/sc/config_sc_0000.yaml` ~ `config_sc_0499.yaml`

---

## Step 2. 데이터 수집

```bash
cd custom_tools

# 주력 명령어: headless + 모니터링 + 전체 수집
./collect_training_data/collect_training_data.sh my_policy.PilzPolicy \
    --headless --monitor --task-type all \
    --start-idx 0 --end-idx 1000

# 이어하기 (중단 후 재실행 — progress.yaml 기반 자동 resume)
./collect_training_data/collect_training_data.sh my_policy.PilzPolicy \
    --headless --monitor
```

출력: `~/aic_data/raw/config_sfp_XXXX/` 또는 `~/aic_data/raw/config_sc_XXXX/`

---

## Step 3. LeRobot 변환 + HuggingFace 업로드

```bash
cd custom_tools/rosbag-to-lerobot
pixi run convert
```

이 한 줄로:
1. `~/aic_data/raw/`에서 모든 config 스캔
2. scoring.yaml 읽어서 **90점 미만 → `~/aic_data/skipped/`로 이동**
3. 90점 이상 에피소드 → LeRobot 변환 → `~/aic_data/lerobot/`
4. HuggingFace 자동 업로드
5. **변환 완료된 config → `~/aic_data/done/`로 이동**



---

## Step 4. 증분 수집 + 변환

추가 수집 → raw/에 새 데이터 쌓임 → 변환 실행하면 새 것만 처리.

```bash
# 1) 추가 수집
cd custom_tools
./collect_training_data/collect_training_data.sh my_policy.PilzPolicy \
    --headless --monitor

# 2) 변환 (raw/에 남아있는 새 데이터만 처리)
cd rosbag-to-lerobot
pixi run convert
```

`raw/`가 비면 모든 데이터가 처리 완료된 것.

---

## 빠른 참조

```bash
# Config 생성
cd custom_tools && pixi run gen-config

# 데이터 수집
./collect_training_data/collect_training_data.sh my_policy.PilzPolicy --headless --monitor

# 변환 + 업로드 (한 줄)
cd rosbag-to-lerobot && pixi run convert

# HF 로그인 확인
pixi run python3 -c "from huggingface_hub import HfApi; print(HfApi().whoami()['name'])"
```

---

## 주요 설정 파일

| 파일 | 역할 |
|------|------|
| `rosbag-to-lerobot/src/config.json` | 토픽 매핑, fps, repo_id, min_score |
| `rosbag-to-lerobot/pixi.toml` | 변환기 pixi 환경 |
| `~/.cache/huggingface/token` | HuggingFace 인증 토큰 |
| `~/aic_data/raw/progress.yaml` | 수집 resume 추적 |