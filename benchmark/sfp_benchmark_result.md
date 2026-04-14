# 실험 인덱스 — Policy 코드 매핑

## 전체 실험 결과 (SFP benchmark 20 configs)

| Run ID | Policy / 실험명 | 코드 | 주요 특징 | 평균 | 성공률 |
|--------|-----------------|------|-----------|------|--------|
| 20260414_175731 | **CheatCode** (baseline) | `aic_example_policies/ros/CheatCode.py` | 단순 하강, 기본 stiffness, PI windup=0.05 | 91.01 | 20/20 |
| 20260414_193607 | **AutoCode** (baseline) | `aic_example_policies/ros/AutoCode.py` | 준모님 코드: [20,20,150] stiffness, PI windup=0.08, 완료 시점 피드백이 없어서 시간 점수 감점 | 93.53 | **20/20** |
| 20260414_220340 | **OptimalPolicy 원본** | `benchmark_backup/20260414_220340_original.py` | auto code기반 추가: port 좌표계 정렬 + F/T feedback, DESCENT=0.0005 | **96.89** | **20/20** |
| 20260415_015930 | **2단계 descent + MIN75** | `benchmark_backup/20260415_015930_2stage_min75.py` | + 진입전 0.0005 / 진입후 0.002 | **97.34** | **20/20** |
| 20260415_021832 | **OptimalPolicyV1** (2단계 descent + MIN40) | `aic_example_policies/ros/OptimalPolicyV1.py` | + APPROACH_MIN_STEPS=40 | **97.47** | **20/20** |
| 20260415_030719 | **OptimalPolicyV2** (V1 + S-curve + 점진적 stiffness) | `aic_example_policies/ros/OptimalPolicyV2.py` | + S-curve approach + gradual stiffness 전환 | **97.47** | **20/20** |

## OptimalPolicyV1 vs V2 상세 비교

| 카테고리 | V1 (MIN40+2stage) | V2 (+ S-curve + gradual) | 차이 |
|----------|-------------------|--------------------------|------|
| **Duration** | 10.49 | 10.55 | +0.06 |
| **Smoothness** | **5.27** | 5.20 | -0.07 |
| **Efficiency** | 5.71 | 5.71 | 0.00 |
| **Total** | **97.47** | **97.47** | -0.001 |

V2는 S-curve(cosine ease-in-out)로 approach 가감속을 부드럽게 하고, stiffness를 z=-0.04~-0.02 구간에서 점진적으로 전환합니다. 하지만 full benchmark에서 **총점 차이 없음**. Smoothness가 -0.07 악화되고 Duration이 +0.06 개선되어 상쇄됩니다.

## 백업 파일 (research/benchmark_backup/)

| 파일명 | Run ID | 설명 |
|--------|--------|------|
| `20260414_220340_original.py` | 20260414_220340 | OptimalPolicy 원본 (DESCENT=0.0005, 96.89점) |
| `20260415_015930_2stage_min75.py` | 20260415_015930 | 2단계 descent + MIN75 (97.34점) |
| `20260415_021832_2stage_min40.py` | 20260415_021832 | OptimalPolicyV1 (97.47점, 현재 최고) |
| `20260415_030719_2stage_min40_scurve_gradual.py` | 20260415_030719 | OptimalPolicyV2 (97.47점, S-curve+gradual) |

---

## Benchmark 설정

### SFP Benchmark (20 configs)

**config 위치**: `benchmark/configs/sfp/benchmark_0000_sfp.yaml` ~ `benchmark_0019_sfp.yaml`

**구성**: config 1개 = trial 1개 (SFP 삽입 1회)

| 항목 | 값 |
|------|-----|
| cable_type | sfp_sc |
| plug_type / plug_name | sfp / sfp_tip |
| port_type / port_name | sfp / sfp_port_0 또는 sfp_port_1 |
| time_limit | 180초 |
| ground_truth | true (TF 제공) |

**target 분포** (5개 NIC card × 2 port = 10종, 각 2회):

| target_module | port | config 번호 |
|---------------|------|-------------|
| nic_card_mount_0 | sfp_port_0 | 0000, 0010 |
| nic_card_mount_0 | sfp_port_1 | 0001, 0011 |
| nic_card_mount_1 | sfp_port_0 | 0002, 0012 |
| nic_card_mount_1 | sfp_port_1 | 0003, 0013 |
| nic_card_mount_2 | sfp_port_0 | 0004, 0014 |
| nic_card_mount_2 | sfp_port_1 | 0005, 0015 |
| nic_card_mount_3 | sfp_port_0 | 0006, 0016 |
| nic_card_mount_3 | sfp_port_1 | 0007, 0017 |
| nic_card_mount_4 | sfp_port_0 | 0008, 0018 |
| nic_card_mount_4 | sfp_port_1 | 0009, 0019 |

**변수 요소** (config마다 다름):
- task board pose (x, y, z, yaw) — +-5cm, +-10 deg
- NIC card rail position/yaw — 각 rail에 NIC card 유무 및 위치 변동
- cable gripper offset (x, y, z, roll, pitch, yaw) — cable 잡는 자세 변동
- robot home joint positions — 시작 자세 변동

**고정 요소**:
- board z: 1.14m (고정)
- board roll/pitch: 0 (수평)

