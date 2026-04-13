# 테스트 가이드

## 사전 준비

### 1. pixi 환경 확인
```bash
cd aic
pixi install  # 이미 완료된 경우 생략
```

### 2. 시뮬레이션 시작 (터미널 1)
```bash
cd aic
/entrypoint.sh ground_truth:=true start_aic_engine:=true
```
> `ground_truth:=true` 필수 — TF 기반 정렬에 필요

### 3. 시뮬레이션 준비 확인
Gazebo GUI가 뜨고 로봇이 보이면 준비 완료. TF가 publish되려면 수 초 대기.

---

## Policy 테스트 (터미널 2)

### PilzPolicy (torque-aware cable insertion policy)
```bash
pixi run ros2 run aic_model aic_model --ros-args -p use_sim_time:=true -p policy:=my_policy.PilzPolicy
```
**확인 포인트**:
- Phase 1 (PTP): port 앞 접근 위치 도달 (torque-aware execution)
- Phase 2 (LIN → PTP fallback): port 입구까지 직선 이동
- Phase 3: Joint IK 삽입 + depth+force 완료 판정
- 삽입 완료: `insert_complete` 또는 안전 정지: `force_stop` 로그

---

## 평가 실행 (scoring 포함)

### 기본 평가
```bash
pixi run ros2 launch aic_bringup aic_gz_bringup.launch.py ground_truth:=true
# 다른 터미널에서:
pixi run ros2 run aic_model aic_model --ros-args -p use_sim_time:=true -p policy:=my_policy.PilzPolicy
```

### 특정 config로 평가
```bash
pixi run ros2 launch aic_bringup aic_gz_bringup.launch.py \
  ground_truth:=true \
  sample_config:=path/to/config.yaml
```

---

## 로그 확인


## 비교 테스트 체크리스트

| Policy | Trial 1 (SFP) | Trial 2 (SFP) | Trial 3 (SC) | 비고 |
|--------|---------------|---------------|--------------|------|
| PilzPolicy | | | | torque-aware, Phase 3: Joint IK |

> **Note**: 이전 버전 (v1~v5)은 `src/backup/` 폴더에 백업되어 있습니다.

---

## 주의사항

1. **use_sim_time**: `--ros-args -p use_sim_time:=true` 필수.
2. **pixi run 필수**: 직접 `ros2 run`이 아닌 `pixi run ros2 run`으로 실행해야 pixi 환경이 적용됨.
3. **시뮬레이션 재시작**: policy 변경 시 aic_model만 재시작하면 됨. 시뮬레이션(bringup)은 유지 가능.
4. **pixi reinstall**: my_policy 코드 수정 후에는 `pixi reinstall ros-kilted-my-policy` 필요.
