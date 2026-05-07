---
id: DEVLOG-003
title: AutoCode Phase 2 — advanced insertion strategies
task_type: feature
status: completed
complexity: high
user_validation: pending
created: 2026-04-05
duration_estimate: 4h
tags: [autocode, phase2, feedforward-force, spiral, compliance, damping, disk-full]
---

## 목표 (Goal)
- Phase 1 best (70.29) 위에 추가 개선하여 90점+ 달성 시도
- 6가지 전략을 유망도 순으로 실험

## 접근 과정 (Approach Log)

### P2 Exp 1: Feedforward downward force (-5N)
- **방법**: MotionUpdate를 직접 구성하여 삽입 시 Z방향 -5N 하방 힘 인가
- **결과**: 54.93 (대참패)
- **원인**: Force가 trajectory를 불안정하게 만들고 (tier2: 13.16), 플러그를 장애물에 밀어붙임

### P2 Exp 2: Compliance + tiny spiral (2mm)
- **방법**: z<0.02에서 compliance + 2mm 반경 spiral search
- **결과**: 60.86 (악화)
- **원인**: descent_step 카운터가 spiral phase 시작 시 이미 360이라 radius 즉시 max. 진동이 삽입 방해

### P2 Exp 3: Compliance hold at z=0.02 (2s)
- **방법**: Port 바로 위에서 compliance 상태로 2초 hold 후 삽입
- **결과**: 61.76 (duration만 증가)
- **원인**: Hold가 삽입을 돕지 않고 시간만 소모. Tier2 15.53으로 하락

### P2 Exp 4: Connector type별 stiffness (SC=10, SFP=20)
- **방법**: task.plug_type으로 SC/SFP 분기, SC에 더 낮은 stiffness
- **결과**: 67.01 (분산 내)
- **원인**: Connector 차이보다 시뮬레이션 분산이 더 큼. 유의미한 효과 없음

### P2 Exp 5: Lower damping (50->20)
- **방법**: 삽입 시 XY damping 감소
- **결과**: FAIL (ENOSPC — 디스크 공간 부족)
- **원인**: 벤치마크 로그/bag 파일 누적으로 디스크 풀. AutoCode.py 소스 파일 1줄로 손상

## 최종 해결 (Final Solution)
- Phase 2에서 70.29를 넘는 개선 없음
- **순수 compliance (Exp 15 설정)이 최적** — 그 위에 어떤 변경도 역효과
- install 복사본에서 소스 복원 완료

## 교훈 (Lessons Learned)
1. **순수 compliance가 local optimum** — force, spiral, hold, damping, connector 분기 등 모두 나빠짐
2. **디스크 관리 필수** — 장기 autocode 세션에서 벤치마크 로그(bag 파일)가 디스크를 채움
3. **ENOSPC는 파일 손상을 유발** — Write 도중 디스크 풀 발생 시 파일이 잘림
4. **Shell 불안정 전파** — 디스크 풀 시 bash 세션 전체가 exit code 1 반환
5. **Git commit이 안전망** — 소스가 손상되어도 commit된 버전에서 복원 가능
6. **Spiral 카운터 주의** — 전역 카운터를 spiral phase에 재사용하면 의도와 다르게 동작

## 변경 파일 (Changed Files)
- `AutoCode.py` — 손상 후 복원, 최종 상태는 exp 15 코드 (commit 037948d)
- `.gitignore` — logs/ 추가
