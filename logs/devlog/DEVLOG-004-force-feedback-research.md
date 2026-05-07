---
id: DEVLOG-004
title: Force feedback insertion research — wrist wrench sensor
task_type: feature
status: completed
complexity: high
user_validation: pending
created: 2026-04-05
duration_estimate: 2h
tags: [force-feedback, wrist-wrench, sensor, compliance, cable-filtering]
---

## 목표 (Goal)
- `get_observation().wrist_wrench` F/T 센서를 활용한 force-guided insertion 구현
- 70.29 -> 90+ 달성

## 사전 발견
- Observation 메시지에 `wrist_wrench` (WrenchStamped), 카메라 3대, joint_states, controller_state 포함
- 정책에서 `get_observation()` 한번도 호출한 적 없음 — 미활용 센서 데이터

## 접근 과정 (Approach Log)

### Iter 1: Force XY correction (gain=0.001, deadband=1N)
- **방법**: 삽입 시 wrist wrench의 Fx, Fy 읽어 반대 방향으로 XY 보정
- **결과**: 68.70 (분산 내). min score 42.3 (역대 최고)
- **원인**: 미세 효과. 케이블 필터링으로 접촉 정보가 감쇠

### Iter 2: Higher force gain (0.003, deadband=0.5N)
- **방법**: force gain 3배 증가, deadband 절반
- **결과**: 57.90 (악화)
- **원인**: 과보정으로 오버슈팅. 케이블 진동이 증폭

### Iter 3: Force Z descent control (Fz>8N threshold)
- **방법**: Fz 초과 시 하강 정지, compliance가 XY 보정할 시간 제공
- **결과**: 55.74 (대폭 악화, min=1.0)
- **원인**: 케이블 무게+마찰로 Fz가 상시 수 N. 임계값이 정상 하강도 차단

## 최종 해결 (Final Solution)
- Force feedback 전략 포기
- 순수 compliance (exp 15 코드) 유지: windup=0.08, stiffness=[20,20,150,50,50,50]@z<0.02
- 리더보드: 70.29 (변경 없음)

## 교훈 (Lessons Learned)
1. **Wrist wrench != plug tip force** — 플러그와 손목 사이의 유연 케이블이 저역통과 필터 역할. 접촉 정보가 왜곡/감쇠되어 도달
2. **Force gain은 극도로 보수적이어야** — 0.001은 중립적, 0.003은 이미 과보정. 케이블 동역학 증폭 위험
3. **Fz 임계값 방식은 비실용적** — 케이블 무게만으로 수 N 발생하여 접촉과 구분 불가
4. **직접 접촉 센서 필요** — Force-guided insertion은 플러그 끝에 F/T 센서가 있어야 효과적. 손목 센서로는 한계
5. **Passive compliance > Active force control** — 이 시스템에서는 능동적 힘 제어보다 수동적 compliance(낮은 stiffness)가 더 효과적

## 변경 파일 (Changed Files)
- 최종 변경 없음 (모든 실험 DISCARD, exp 15 코드 유지)
