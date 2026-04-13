# AI for Industry Challenge Toolkit

[![build](https://github.com/intrinsic-dev/aic/actions/workflows/build.yml/badge.svg)](https://github.com/intrinsic-dev/aic/actions/workflows/build.yml)
[![style](https://github.com/intrinsic-dev/aic/actions/workflows/style.yml/badge.svg)](https://github.com/intrinsic-dev/aic/actions/workflows/style.yml)

![](../media/aic_banner.png)

The **AI for Industry Challenge** is an open competition for developers and roboticists aimed at solving some of the hardest, high-impact problems in robotics and manufacturing.

This repository contains the official toolkit to help participants start developing their solutions. For registration details, official rules, and FAQs, please visit the [AI for Industry Challenge event page](https://www.intrinsic.ai/events/ai-for-industry-challenge).

---

## Modifications

아래 항목이 추가/수정되었습니다.

### 추가된 패키지

| 패키지 | 설명 |
|--------|------|
| **`my_policy/`** | 커스텀 케이블 삽입 policy (PilzPolicy) — MoveIt2 PILZ planner + impedance control + force-based 완료 감지 |
| **`custom_tools/`** | 학습 데이터 수집 파이프라인 (config 생성, 자동 수집), 올려주신 레포기반으로 수정 (LeRobot 변환) |

### 수정된 파일

| 파일 | 변경 내용 |
|------|-----------|
| `pixi.toml` (root) | `my_policy` 의존성 추가, MoveIt2/PILZ/ur_description 등 runtime 의존성 추가 |
| `.gitignore` | `benchmark/`, `tmp/`, `*.log` 제외 추가 |
| `aic_scoring/` (`ScoringTier2.hh`, `ScoringTier2.cc`) | `record_all_topics` 기능 복원 — 카메라/관측/액션 토픽 기록 + zstd 압축 (로컬 데이터 수집 전용, 기본값 `false`) |
| `aic_engine/src/aic_engine.cpp` | `record_all_topics` 파라미터 선언 및 `SetRecordAllTopics()` 호출 복원 |

### 추가된 문서

| 파일 | 설명 |
|------|------|
| [`my_policy/README.md`](./my_policy/README.md) | PilzPolicy 방법론, 상세 동작 과정, 파라미터 정의 |
| [`custom_tools/README.md`](./custom_tools/README.md) | 데이터 수집 파이프라인 전체 가이드 |
| [`custom_tools/collect_training_data/README.md`](./custom_tools/collect_training_data/README.md) | 데이터 수집 스크립트 상세 |
| [`custom_tools/gen_training_configs/gen_config.md`](./custom_tools/gen_training_configs/gen_config.md) | 학습 Config 자동 생성 설계 |
| [`custom_tools/rosbag-to-lerobot/README.md`](./custom_tools/rosbag-to-lerobot/README.md) | LeRobot 변환 + HuggingFace 업로드 |
| [`custom_tools/curation-tools/README.md`](./custom_tools/curation-tools/README.md) | 데이터 품질 검수 도구 |
| [`custom_docs/logs/progress.md`](./custom_docs/logs/progress.md) | 개발 진행 로그 |
| [`custom_docs/guides/test_guide.md`](./custom_docs/guides/test_guide.md) | 테스트 실행 가이드 |

### Quick Start

```bash
# pixi 환경 설치
cd aic
pixi install

# 터미널 1: distrobox → 시뮬레이션 시작
export DBX_CONTAINER_MANAGER=docker
distrobox enter -r aic_eval -- /entrypoint.sh ground_truth:=true start_aic_engine:=true

# 터미널 2: policy 실행
pixi run ros2 run aic_model aic_model --ros-args -p use_sim_time:=true -p policy:=my_policy.PilzPolicy
```

---

## Toolkit Guide

Welcome to the AIC toolkit documentation. This guide walks you through the complete workflow for participating in the challenge — from understanding the requirements to submitting your solution.

Follow the sections below to navigate through each phase of the process.

1. **📖 Understand the Challenge**
   - Read the [Challenge Overview](./docs/overview.md) to understand the goals.
   - Review the [Qualification Phase](./docs/phases.md#qualification-phase-train-your-model) to understand what you'll be building.
   - Review the [Scoring Guide](./docs/scoring.md) to understand how you'll be scored.

2. **🔧 Set Up Your Environment**
   - Follow the [Getting Started](./docs/getting_started.md) guide to set up and validate your development environment.
   - Run the evaluation container and set up your local workspace with Pixi.

3. **💻 Develop Your Policy**
   - Explore the [Scene Description](./docs/scene_description.md) to learn how to customize and explore the environment.
   - Review [AIC Interfaces](./docs/aic_interfaces.md) to understand available interfaces to communicate with sensors and actuators.
   - Consult [AIC Controller](./docs/aic_controller.md) to learn about controlling the robot.
   - Consult the [Challenge Rules](./docs/challenge_rules.md) to ensure compliance.
   - Start with the [Policy Integration Guide](./docs/policy.md) to implement your solution.
   - See [Participant Utilities](./docs/participant_utilities.md) for a list of helpful tools.

4. **🧪 Test Your Solution**
   - Use the provided simulation environment to test your policy.
   - Run `aic_engine` with the `sample_config` in [`aic_engine/config/`](./aic_engine/config/) to test different scenarios. For more information on running the `aic_engine` with different configs, see the [aic_engine README file](./aic_engine/README.md).
   - Create your own test scenarios by following the configuration example in [`aic_engine/config/`](./aic_engine/config/) to run with `aic_engine`.
   - Refer to [Troubleshooting](./docs/troubleshooting.md) if you encounter issues.

5. **📦 Submit Your Entry**
   - Package your solution following the [Submission Guidelines](./docs/submission.md).
   - Test your container locally before submitting following [these instructions](./docs/submission.md#verify-locally).
   - Submit through the official portal following [these instructions](./docs/submission.md#2-upload-your-image-to-our-registry).

---

## Toolkit Architecture

![AIC Competition Components](../media/aic_competition_components.png)

The AI for Industry Challenge toolkit is divided into **two main components**:

### 1. Evaluation Component (Provided - Run by Organizers)

This component provides the complete evaluation infrastructure:
- **`aic_engine`** - Orchestrates trials and computes scores.
- **`aic_bringup`** - Launches simulation environment (Gazebo, robot, sensors).
- **`aic_controller`** - Low-level robot control with force management.
- **`aic_adapter`** - Sensor fusion and data synchronization.

**What you receive:** Standard ROS sensor topics providing camera images, joint states, force/torque measurements, and TF frames.

### 2. Participant Model Component (Your Implementation - What You Submit)

This is what you develop and submit:
- **A ROS 2 node** that follows the behavioral requirements defined in [Challenge Rules](./docs/challenge_rules.md).
- **Your custom logic** - Code to process sensor data and command the robot to insert cables.

**What you provide:** A container with a ROS 2 Lifecycle node named `aic_model` that responds to the `/insert_cable` action and outputs robot motion commands via standard ROS topics/services.

**Convenient Entry Point:** We provide an `aic_model` framework that handles all the ROS 2 boilerplate and lifecycle management. You simply implement a Python policy class that gets dynamically loaded at runtime. See the [Policy Integration Guide](./docs/policy.md) for details.

### Development and Submission Workflow

> [!IMPORTANT]
> **ROS 2 Distribution:** The official evaluation of all submissions will be conducted using **ROS 2 Kilted Kaiju**. If you choose to develop or test your policy using a different ROS 2 distribution (e.g., Humble or Jazzy), it is entirely your responsibility to ensure compatibility and support. Please note that **inter-distro communication is not guaranteed and not officially supported**.

**Development Options:**
- Develop inside a container (recommended - matches evaluation environment).
- OR develop in native Ubuntu 24.04 environment (requires all dependencies).

**Submission Requirements:**
- Package your solution using the provided `aic_model` Dockerfile.
- Submit your container - it must respond to standard ROS inputs and command the robot to insert cables.
- Your container interfaces with the evaluation component via ROS topics.

---
## Repository Structure

```
aic/
├── aic_adapter/          # Adapter for interfacing between model and controller
├── aic_assets/           # 3D models and simulation assets
├── aic_bringup/          # Launch files for starting the challenge environment
├── aic_controller/       # Robot controller implementation
├── aic_description/      # Robot and environment URDF/SDF descriptions
├── aic_engine/           # Trial orchestration and validation engine
├── aic_example_policies/ # Example policy implementations
├── aic_gazebo/           # Gazebo-specific plugins and configurations
├── aic_interfaces/       # ROS 2 message, service, and action definitions
├── aic_model/            # Template for participant policy implementation
├── aic_scoring/          # Scoring system implementation
├── aic_utils/            # Utility packages and tools
├── custom_docs/          # Team documentation (logs, guides, presentations)
├── custom_tools/         # Data collection pipeline tools
├── docker/               # Docker container definitions
├── docs/                 # Comprehensive documentation (upstream)
└── my_policy/            # Custom cable insertion policy (PilzPolicy)
```

---

## Key Packages for Participants

### `aic_model` - Convenient Policy Framework (Recommended)
This package provides a ready-to-use ROS 2 Lifecycle node that dynamically loads and executes your Python policy implementation. It handles all ROS 2 boilerplate, lifecycle management, and challenge rule compliance, allowing you to focus on implementing your policy logic.
- **Location**: `aic_model/`.
- **Documentation**: [Policy Integration Guide](./docs/policy.md).
- **Tutorial**: [Creating a New Policy Node](./docs/policy.md#tutorial-creating-a-new-policy-node).

> **Note:** While we recommend using this framework, you may implement your own ROS 2 node from scratch as long as it adheres to the [Challenge Rules](./docs/challenge_rules.md).

### `aic_interfaces` - Communication Protocols
Defines all ROS 2 messages, services, and actions used in the challenge.
- **Location**: `aic_interfaces/`.
- **Documentation**: [AIC Interfaces](./docs/aic_interfaces.md).

### `aic_example_policies` - Reference Implementations
Example policies demonstrating different approaches and techniques.
- **Location**: `aic_example_policies/`.
- **README**: [aic_example_policies/README.md](./aic_example_policies/README.md).

### `aic_bringup` - Launch the Environment
Launch files to start the simulation, robot, and scoring systems.
- **Location**: `aic_bringup/`.
- **README**: [aic_bringup/README.md](./aic_bringup/README.md).

### `aic_engine` - Trial Orchestrator
Manages trial execution, validates participant models, and collects scoring data.
- **Location**: `aic_engine/`.
- **README**: [aic_engine/README.md](./aic_engine/README.md).

---

## Additional Documentation

### Challenge Information

* **[Challenge Overview](./docs/overview.md):** High-level summary of the competition goals and structure.
* **[Competition Phases](./docs/phases.md):** Details on Qualification, Phase 1, and Phase 2.
* **[Qualification Phase](./docs/qualification_phase.md):** Detailed technical overview of the qualification phase trials and scoring.
* **[Challenge Rules](./docs/challenge_rules.md):** Required behavior for participant models.
* **[Scoring](./docs/scoring.md):** Metrics and methods used to evaluate performance.
* **[Scoring Test Examples](./docs/scoring_tests.md):** Reproducible examples exercising each scoring tier with exact commands.

### Technical Documentation

* **[Getting Started](./docs/getting_started.md):** How to set up your local development environment.
* **[Policy Integration](./docs/policy.md):** Guide to implementing your policy in the `aic_model` framework.
* **[AIC Interfaces](./docs/aic_interfaces.md):** ROS 2 topics, services, and actions available to your policy.
* **[AIC Controller](./docs/aic_controller.md):** Understanding the robot controller and motion commands.
* **[Scene Description](./docs/scene_description.md):** Technical details of the simulation environment.
* **[Task Board Description](./docs/task_board_description.md):** Physical layout and specifications of the task board.
* **[Troubleshooting](./docs/troubleshooting.md):** Common issues and debugging strategies.

### Reference Materials

* **[Glossary](./docs/glossary.md):** Terminology and definitions used throughout the AI for Industry Challenge

### Submission

* **[Submission Guidelines](./docs/submission.md):** How to package and submit your final model.

---


## Support and Resources

- **Discussions**: Engage in conversations and ask questions about the challenge on [Open Robotics Discourse](https://discourse.openrobotics.org/c/competitions/ai-for-industry-challenge/). The community is encouraged to participate in discussions and assist each other.
- **Issues**: Report any bugs or technical issues via [GitHub Issues](https://github.com/intrinsic-dev/aic/issues). Please refrain from using the Issue tracker for general questions about the challenge.
  - **Note:**: Review the list of [known issues](https://github.com/intrinsic-dev/aic/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22known%20issue%22) and [bugs](https://github.com/intrinsic-dev/aic/issues?q=is%3Aissue%20state%3Aopen%20label%3Abug) before opening a new ticket.
- **Event Page**: Visit the [AI for Industry Challenge](https://www.intrinsic.ai/events/ai-for-industry-challenge) for official updates.

---

## License

This project is licensed under the Apache License 2.0 - see the individual package files for details.
The [aic_isaac](./aic_utils/aic_isaac/) folder contains files licensed under BSD-3 - see [aic_isaac/LICENSE](./aic_utils/aic_isaac/LICENSE).
