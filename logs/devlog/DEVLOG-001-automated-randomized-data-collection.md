---
id: DEVLOG-001
title: Automated randomized data collection via ExecuteTrial service
task_type: feature
status: completed
complexity: high
user_validation: pending
created: 2026-03-29
duration_estimate: 4h
tags: [ros2, automated-collection, service, randomization, autopilot, validation, aic-engine, data-collection]
---

## 목표 (Goal)
- aic_engine에 `ExecuteTrial` ROS 2 서비스를 추가하여 런타임 trial injection 지원
- data_collection_node에서 랜덤 trial config 생성 → 서비스 호출 → rosbag 녹화 → N개 성공 에피소드 수집 자동화
- 3-stage pipeline (deep-interview → ralplan → autopilot) 으로 요구사항 정제 → 합의 계획 → 구현 → QA → 다중 리뷰

## 접근 과정 (Approach Log)

### 1차: Deep Interview → Spec 생성
- **방법**: Socratic 질문 6라운드로 모호한 아이디어를 정제 (ambiguity 100% → 12%)
- **결과**: 성공 — spec 문서 생성 (`deep-interview-auto-collection.md`)
- **핵심 결정**: 서비스 기반 (config 재생성 X), YAML string 전송, 성공 N개 기준 종료, 실패 bag 분리보관

### 2차: Ralplan 합의 계획
- **방법**: Planner → Architect → Critic 루프
- **결과**: 2회 반복 후 승인 (Architect 3 critical, Critic 1 critical + 3 major 발견 후 수정)
- **핵심 발견**: SingleThreadedExecutor 데드락, engine_state_ Error 오염, check_model() 재발견, double reset_after_trial

### 3차: Autopilot Phase 2-3 (구현 + QA)
- **방법**: cpp-pro/python-pro 에이전트 병렬 실행
- **결과**: 성공 — 빌드 8 packages, 0 errors
- **변경 범위**: .srv 1개 신규, .hpp/.cpp 수정, .py 수정, config/launch 수정

### 4차: Autopilot Phase 4 (Validation)
- **방법**: Architect + Security-reviewer + Code-reviewer 3개 에이전트 병렬
- **결과**: Architect APPROVED, Security/Code-reviewer REVISE → 8건 즉시 수정
- **발견 이슈 8건**:
  - [Critical] `activate_model_node()` 반환값 미확인 → `return activate_model_node()`
  - [High/Security] `cable_type` command injection → allowlist 검증
  - [High] `_successful_count` dead state → 제거
  - [High] bag 디렉토리 미생성 race → 2초 대기 로직
  - [Medium/Security] YAML::Load 무제한 → 64KB 제한
  - [Medium] float 동등비교 → sentinel 값 방식
  - [Medium] 변수명 `max_index` → `count`
  - [Low] 고정 trial ID → atomic counter

## 최종 해결 (Final Solution)
- C++ aic_engine: MultiThreadedExecutor + MutuallyExclusiveCallbackGroup, engine_state_ 격리, check_model() 가드
- Python data_collection_node: MultiThreadedExecutor + dedicated orchestration thread, deep-copy 기반 템플릿 랜덤화
- 빌드 검증 통과: 8 packages, 0 errors

## 교훈 (Lessons Learned)
- **SingleThreadedExecutor + 서비스 콜백 내 중첩 서비스 호출 = 데드락** — ROS 2에서 서비스 콜백이 무거운 작업을 할 때 반드시 MultiThreadedExecutor
- **engine_state_ 같은 공유 상태는 서비스 호출 간 오염됨** — 격리(save/restore) 패턴 필수
- **handle_trial()의 모든 exit path에서 reset 호출하는 경우, 외부에서 중복 호출하면 안 됨** — 코드 분석 선행 필수
- **popen() + string concatenation = command injection 위험** — 문자열 파라미터에 대해 allowlist 검증 또는 exec-family 사용
- **3-stage pipeline이 코드 품질에 유효** — deep-interview가 요구사항 모호성을 잡고, ralplan이 아키텍처 결함을 잡고, validation이 구현 결함을 잡음

## 변경 파일 (Changed Files)
- `aic_task_interfaces/srv/ExecuteTrial.srv` — NEW: 서비스 정의
- `aic_task_interfaces/CMakeLists.txt` — srv_files 추가
- `aic_engine/src/aic_engine.hpp` — ExecuteTrial 서비스, mutex, callback group 선언
- `aic_engine/src/aic_engine.cpp` — MultiThreadedExecutor, 서비스 콜백, parse_trial_from_yaml, check_model 가드, cable_type allowlist
- `aic_data_collection/data_collection_node.py` — 랜덤화, orchestration loop, failed bag 처리, metacard 확장
- `aic_data_collection/config/data_collection_config.yaml` — target_episodes, max_attempts, trial_timeout_sec
- `aic_data_collection/launch/data_collection.launch.py` — target_episodes, external_trial_mode 인자
