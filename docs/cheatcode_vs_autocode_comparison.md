# CheatCode vs AutoCode 성능 비교 분석

> 작성일: 2026-04-13  
> 대상 파일:
> - `aic_example_policies/aic_example_policies/ros/CheatCode.py`
> - `aic_example_policies/aic_example_policies/ros/AutoCode.py`

---

## 1. 개요

두 정책 모두 **ground_truth TF**를 이용해 포트 위치와 플러그 위치를 읽고, PI 적분기를 통한 XY 보정을 가하면서 케이블을 삽입하는 방식이다. 핵심 알고리즘(`_wait_for_tf`, `calc_gripper_pose`, PI 제어기)은 **동일**하며, 차이는 `insert_cable()` 내의 **실행 전략(타이밍, 안정화 로직)**에 있다.

---

## 2. 공통 구조

```
[1] TF 대기        → 포트 및 플러그 프레임이 활성화될 때까지 대기 (최대 10초)
[2] 포트 TF 조회   → 삽입 목표 좌표 고정
[3] 접근 단계      → 현재 위치 → 포트 위 지점으로 보간 이동
[4] 하강 단계      → z_offset을 조금씩 줄이며 삽입
[5] 안정화 대기    → 커넥터가 정착될 때까지 대기
```

### 공통 파라미터

| 항목 | 값 |
|---|---|
| `z_offset` 초기값 | `0.2` m (포트 위 20 cm) |
| 삽입 종료 조건 | `z_offset < -0.015` |
| 하강 스텝 크기 | `0.0005` m/step |
| 루프 주기 | `0.05` s/step (20 Hz) |
| PI `i_gain` | `0.15` |
| `_max_integrator_windup` | `0.05` |
| 제어 방식 | Cartesian (`set_pose_target`) |
| 의존 정보 | ground_truth TF (`ground_truth:=true` 필수) |

---

## 3. 단계별 상세 비교

### 3-1. 접근 단계 (Approach Phase)

| 항목 | CheatCode | AutoCode |
|---|---|---|
| 루프 반복 수 | 100회 | 75회 |
| 소요 시간 | 100 × 0.05 = **5.00 초** | 75 × 0.05 = **3.75 초** |
| 보간 방식 | `t / 100.0` (0 → 1) | `t / 75.0` (0 → 1) |
| XY 적분기 | 접근 중 리셋 (`reset_xy_integrator=True`) | 동일 |
| 회전 보간 | SLERP 적용 | 동일 |

**분석:**  
AutoCode는 접근 단계를 1.25초 단축했다. 보간 비율 자체는 동일하게 0→1로 선형 증가하므로 운동 궤적의 형태는 같지만, 더 빠른 속도로 접근한다.  
이는 전체 실행 시간 단축에 기여하나, 관성/오버슈트 위험이 약간 높아질 수 있다.

---

### 3-2. 홀드 단계 (Hold Phase) — AutoCode 전용

| 항목 | CheatCode | AutoCode |
|---|---|---|
| 존재 여부 | **없음** | **있음** |
| 반복 수 | — | 20회 |
| 소요 시간 | — | 20 × 0.05 = **1.00 초** |
| 목적 | — | PI 컨트롤러 XY 오차 정착 |

**코드 (AutoCode 전용):**
```python
# Hold position above port for 1s to let PI controller settle XY
for _ in range(20):
    try:
        self.set_pose_target(
            move_robot=move_robot,
            pose=self.calc_gripper_pose(port_transform, z_offset=z_offset),
        )
    except TransformException as ex:
        self.get_logger().warn(f"TF lookup failed during hold: {ex}")
    self.sleep_for(0.05)
```

**분석:**  
접근 완료 후 포트 바로 위에서 1초 동안 정지하며 PI 적분기가 XY 오차를 누적·보정하도록 한다. CheatCode는 이 단계 없이 바로 하강하므로 초기 XY 정렬이 덜 된 상태로 삽입을 시작할 수 있다.

---

### 3-3. 하강 단계 (Descent Phase)

#### CheatCode — 단순 하강

```python
while True:
    if z_offset < -0.015:
        break
    z_offset -= 0.0005
    self.set_pose_target(move_robot=move_robot,
                         pose=self.calc_gripper_pose(port_transform, z_offset=z_offset))
    self.sleep_for(0.05)
```

#### AutoCode — 적응형 하강 (Adaptive Descent)

```python
baseline_err = max(abs(self._tip_x_error_integrator),
                   abs(self._tip_y_error_integrator))
descent_step = 0
while True:
    if z_offset < -0.015:
        break
    z_offset -= 0.0005
    descent_step += 1
    self.set_pose_target(...)
    self.sleep_for(0.05)

    # 80 스텝(~4초)마다 정렬 상태 점검
    if descent_step % 80 == 0:
        current_err = max(abs(self._tip_x_error_integrator),
                          abs(self._tip_y_error_integrator))
        if current_err > baseline_err * 1.3:
            # 10 스텝(0.5초) 재정렬 대기
            for _ in range(10):
                self.set_pose_target(...)
                self.sleep_for(0.05)
            baseline_err = max(...)  # baseline 갱신
```

| 항목 | CheatCode | AutoCode |
|---|---|---|
| 기본 하강 로직 | 동일 | 동일 |
| 정렬 모니터링 | **없음** | **있음** (80스텝마다) |
| 재정렬 pause | **없음** | 오차 30% 초과 시 0.5초 대기 |
| Baseline 갱신 | — | 재정렬 후 baseline 업데이트 |
| 총 하강 스텝 (정상) | ≈ 430 스텝 | ≈ 430 스텝 (재정렬 없을 때) |
| 정상 시 하강 소요 시간 | ≈ 21.5 초 | ≈ 21.5 초 |
| 재정렬 발생 시 추가 시간 | — | 최대 n × 0.5초 추가 |

**하강 단계 총 스텝 계산:**
```
z_offset: 0.2 → -0.015
총 변화량: 0.215 m
스텝당 변화: 0.0005 m
총 스텝 수: 0.215 / 0.0005 = 430 스텝
소요 시간: 430 × 0.05 = 21.5 초
```

**분석:**  
AutoCode의 adaptive pause는 삽입 중 플러그가 벽에 닿거나 마찰로 인해 XY 정렬이 틀어질 때 자동으로 재정렬을 시도한다. 이는 삽입 실패율을 낮출 것으로 기대되나, 재정렬이 자주 발생하면 전체 실행 시간이 길어진다. 임계값 `1.3× baseline`은 다소 관대하여 소폭의 오차 증가에는 반응하지 않는다.

---

### 3-4. 안정화 대기 (Stabilization Wait)

| 항목 | CheatCode | AutoCode |
|---|---|---|
| 대기 시간 | **5.0 초** | **2.0 초** |
| 감소량 | — | **3.0 초 단축** |

**분석:**  
AutoCode는 삽입 후 안정화 대기를 절반 이하로 줄였다. hold phase + adaptive descent로 삽입 품질이 높아진다고 가정하면, 더 짧은 안정화 대기도 충분하다고 판단한 것으로 보인다. 반대로 삽입이 불안정했을 경우에는 오히려 위험할 수 있다.

---

## 4. 전체 실행 시간 비교

### CheatCode (정상 케이스)

| 단계 | 시간 |
|---|---|
| TF 대기 | 가변 (보통 수 초 이내) |
| 접근 | 5.00 초 |
| 홀드 | 없음 |
| 하강 | ≈ 21.50 초 |
| 안정화 | 5.00 초 |
| **합계 (TF 제외)** | **≈ 31.50 초** |

### AutoCode (정상 케이스, 재정렬 없음)

| 단계 | 시간 |
|---|---|
| TF 대기 | 가변 |
| 접근 | 3.75 초 |
| 홀드 | 1.00 초 |
| 하강 | ≈ 21.50 초 |
| 안정화 | 2.00 초 |
| **합계 (TF 제외)** | **≈ 28.25 초** |

### AutoCode (재정렬 발생 케이스)

80 스텝마다 점검이 이루어지므로, 430 스텝 하강 시 최대 `430 / 80 ≈ 5`회 점검 발생.  
5회 모두 재정렬 발생 시: `5 × 0.5 = 2.5초` 추가 → **≈ 30.75 초**

**→ 재정렬이 없으면 AutoCode가 약 3.25초 빠르고, 최악의 경우에도 CheatCode보다 느리지 않다.**

---

## 5. 알고리즘 설계 철학 비교

| 관점 | CheatCode | AutoCode |
|---|---|---|
| 설계 방향 | 단순·직관적 | 적응형·강인성 중심 |
| 접근 속도 | 느림 (5초) | 빠름 (3.75초) |
| 삽입 전 정렬 | 없음 | 1초 홀드로 정착 |
| 삽입 중 피드백 | 없음 | 주기적 오차 점검 |
| 안정화 의존도 | 높음 (5초 대기) | 낮음 (2초 대기) |
| 코드 복잡도 | 낮음 | 중간 |
| 예측 가능성 | 높음 (고정 타이밍) | 중간 (조건부 지연) |
| 실패 대응 | 없음 | 재정렬 시도 |

---

## 6. 예상 성능 차이

### 성공률
- **AutoCode 우위 예상**: 홀드 단계에서 XY 오차를 줄이고, 하강 중 정렬 이탈 시 자동 보정하므로 성공률이 더 높을 것으로 기대된다.
- CheatCode는 XY가 정렬되지 않은 채 하강을 시작할 수 있어 포트 가장자리에 걸릴 위험이 있다.

### 실행 시간
- **AutoCode 우위**: 정상 케이스에서 약 3.25초 단축. 경쟁 환경에서 유리.
- 다만 재정렬이 빈번히 발생하면 시간 이점이 감소한다.

### 안정성
- **비슷하거나 AutoCode 우위**: 두 정책 모두 ground_truth TF에 의존하므로 TF가 없는 환경에서는 모두 실패한다.
- AutoCode의 adaptive pause는 예외적 상황에서 추가 견고성을 제공한다.

### 잠재적 위험
- **AutoCode**: 빠른 접근 + 짧은 안정화 → 시뮬레이터의 물리 엔진이 느릴 때 불안정해질 수 있다.
- **CheatCode**: 느리지만 안정적. 물리 오버슈트에 덜 민감.

---

## 7. 코드 diff 요약

```diff
 class CheatCode(Policy):          |  class AutoCode(Policy):
     ...                           |      ...
 
-    # 5초 접근                    |  -    # 3.75초 접근
-    for t in range(0, 100):       |  +    for t in range(0, 75):
-        interp_fraction = t/100.0 |  +        interp_fraction = t/75.0
 
                                   |  +    # 1초 홀드 (AutoCode 전용)
                                   |  +    for _ in range(20):
                                   |  +        self.set_pose_target(...)
                                   |  +        self.sleep_for(0.05)
 
     # 하강                        |      # 하강 (기본은 동일)
     while True:                   |  +    baseline_err = max(...)
         ...                       |  +    descent_step = 0
         z_offset -= 0.0005        |      while True:
         self.set_pose_target(...) |          ...
         self.sleep_for(0.05)      |  +        descent_step += 1
                                   |  +        if descent_step % 80 == 0:
                                   |  +            # 정렬 점검 및 재정렬
 
-    self.sleep_for(5.0)           |  +    self.sleep_for(2.0)
```

---

## 8. 벤치마크 실험 설계 제안

두 정책을 공정하게 비교하려면 아래 조건을 통제해야 한다:

| 항목 | 권장 조건 |
|---|---|
| 커넥터 종류 | LC, SFP, SC 각각 N회씩 |
| 실험 반복 수 | 각 조건당 최소 5회 이상 |
| 측정 지표 | 성공률, 평균 소요 시간, 삽입 점수 |
| 환경 | 동일 시뮬레이터 시드, `ground_truth:=true` |
| 시작 자세 | 동일한 초기 관절 각도 |
| 로그 | `z_offset`, XY 오차 integrator 값 기록 |

**측정할 핵심 지표:**
1. **성공률** (%) — 삽입 완료 여부
2. **평균 실행 시간** (초) — TF 대기 포함/제외 분리
3. **삽입 점수** — `aic_scoring`이 제공하는 점수
4. **재정렬 횟수** (AutoCode) — adaptive pause가 얼마나 자주 발동하는지
5. **최종 XY 오차 integrator 값** — 삽입 직전 정렬 품질

---

## 9. 결론

| 항목 | 승자 |
|---|---|
| 코드 단순성 | CheatCode |
| 예상 성공률 | AutoCode |
| 실행 속도 | AutoCode |
| 삽입 정밀도 | AutoCode |
| 환경 변화 대응 | AutoCode |
| 예측 가능한 타이밍 | CheatCode |

**AutoCode는 CheatCode의 모든 핵심 로직을 유지하면서 세 가지 개선을 추가했다:**
1. 빠른 접근 (5초 → 3.75초)
2. 삽입 전 1초 정렬 안정화
3. 하강 중 적응형 재정렬

이론적으로는 AutoCode가 더 나은 성능을 보여야 하며, 실제 벤치마크를 통해 이를 검증하는 것이 권장된다.
