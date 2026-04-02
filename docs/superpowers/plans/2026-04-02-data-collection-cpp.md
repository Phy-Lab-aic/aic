# Data Collection C++ Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert aic_data_collection Python package to C++ within the aic_engine package, with shared utility extraction, full GTest coverage, and launch parameter engine selection.

**Architecture:** Extract reusable logic (spawn, homing, TF) from the existing 2017-line Engine monolith into shared utility classes. Build data-collection-specific components (TrialConfigProvider, CompletionMonitor, RosbagManager) as new C++ classes. Compose them in an AutoDataCollector ROS 2 node registered as a second executable in aic_engine. Add `engine_type` launch parameter to aic_gz_bringup.launch.py.

**Tech Stack:** C++17, ROS 2 (rclcpp, rclcpp_action, tf2_ros), yaml-cpp, nlohmann_json, Eigen3, GTest/GMock

---

## File Structure

```
aic_engine/
├── src/
│   ├── aic_engine.cpp/hpp                  # existing (refactored to delegate to utils)
│   ├── main.cpp                            # existing entry point
│   ├── auto_data_collector.hpp             # new orchestrator node
│   ├── auto_data_collector.cpp             # new orchestrator implementation
│   ├── auto_data_collector_main.cpp        # new entry point
│   ├── utils/
│   │   ├── scene_spawner.hpp               # extracted from Engine::spawn_entity + ready_simulator
│   │   ├── scene_spawner.cpp
│   │   ├── homing_helper.hpp               # extracted from Engine::home_robot
│   │   ├── homing_helper.cpp
│   │   ├── tf_helper.hpp                   # TF lookup utility
│   │   └── tf_helper.cpp
│   ├── completion_monitor.hpp              # TF proximity + insertion_event
│   ├── completion_monitor.cpp
│   ├── rosbag_manager.hpp                  # subprocess ros2 bag record
│   ├── rosbag_manager.cpp
│   ├── trial_config_provider.hpp           # Static + Dynamic providers
│   └── trial_config_provider.cpp
├── test/
│   ├── test_completion_monitor.cpp
│   ├── test_trial_config_provider.cpp
│   ├── test_dynamic_trial_provider.cpp
│   ├── test_rosbag_manager.cpp
│   └── test_collection_flow.cpp
├── CMakeLists.txt                          # updated
└── package.xml                             # updated
```

---

### Task 1: Update Build System (CMakeLists.txt + package.xml)

**Files:**
- Modify: `aic_engine/CMakeLists.txt`
- Modify: `aic_engine/package.xml`

- [ ] **Step 1: Add new dependencies to package.xml**

Add after the existing `<depend>yaml_cpp_vendor</depend>` line:

```xml
  <depend>std_msgs</depend>
  <depend>sensor_msgs</depend>

  <test_depend>ament_cmake_gtest</test_depend>
```

Note: Eigen3 is header-only and found via CMake, not rosdep. nlohmann_json likewise. std_msgs is for String subscription (insertion_event). sensor_msgs is for Image dummy subscriptions.

- [ ] **Step 2: Update CMakeLists.txt with new find_package, sources, and test targets**

Replace the entire CMakeLists.txt content with:

```cmake
cmake_minimum_required(VERSION 3.20)
project(aic_engine)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)

find_package(aic_scoring REQUIRED)
find_package(aic_control_interfaces REQUIRED)
find_package(aic_engine_interfaces REQUIRED)
find_package(aic_task_interfaces REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(controller_manager_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(lifecycle_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(simulation_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(trajectory_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(yaml_cpp_vendor REQUIRED)
find_package(yaml-cpp REQUIRED)
find_package(Eigen3 REQUIRED)
find_package(nlohmann_json REQUIRED)

# Shared utility library (used by both aic_engine and auto_data_collector)
add_library(aic_engine_utils STATIC
  src/utils/tf_helper.cpp
  src/utils/scene_spawner.cpp
  src/utils/homing_helper.cpp
)
target_include_directories(aic_engine_utils PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
)
target_link_libraries(aic_engine_utils
  ament_index_cpp::ament_index_cpp
  rclcpp::rclcpp
  tf2::tf2
  tf2_ros::tf2_ros
  yaml-cpp
  ${aic_engine_interfaces_TARGETS}
  ${controller_manager_msgs_TARGETS}
  ${geometry_msgs_TARGETS}
  ${simulation_interfaces_TARGETS}
  ${std_srvs_TARGETS}
)

# Data collection library (components specific to auto_data_collector)
add_library(aic_data_collection STATIC
  src/completion_monitor.cpp
  src/trial_config_provider.cpp
  src/rosbag_manager.cpp
)
target_include_directories(aic_data_collection PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
)
target_link_libraries(aic_data_collection
  aic_engine_utils
  Eigen3::Eigen
  nlohmann_json::nlohmann_json
  yaml-cpp
)

# Existing aic_engine executable
add_executable(aic_engine
  src/aic_engine.cpp
  src/main.cpp
)
target_link_libraries(aic_engine
  aic_engine_utils
  aic_scoring::aic_scoring
  ament_index_cpp::ament_index_cpp
  rclcpp::rclcpp
  rclcpp_action::rclcpp_action
  tf2::tf2
  tf2_ros::tf2_ros
  yaml-cpp
  ${aic_control_interfaces_TARGETS}
  ${aic_engine_interfaces_TARGETS}
  ${aic_task_interfaces_TARGETS}
  ${controller_manager_msgs_TARGETS}
  ${geometry_msgs_TARGETS}
  ${lifecycle_msgs_TARGETS}
  ${trajectory_msgs_TARGETS}
  ${simulation_interfaces_TARGETS}
  ${std_srvs_TARGETS}
  ${tf2_ros_TARGETS}
)

# New auto_data_collector executable
add_executable(auto_data_collector
  src/auto_data_collector.cpp
  src/auto_data_collector_main.cpp
)
target_link_libraries(auto_data_collector
  aic_engine_utils
  aic_data_collection
  rclcpp::rclcpp
  rclcpp_action::rclcpp_action
  yaml-cpp
  Eigen3::Eigen
  ${aic_task_interfaces_TARGETS}
  ${lifecycle_msgs_TARGETS}
  ${sensor_msgs_TARGETS}
  ${std_msgs_TARGETS}
)

install(
  TARGETS aic_engine auto_data_collector
  DESTINATION lib/${PROJECT_NAME}
)

# Install directories.
install(
  DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

# Tests
if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)

  ament_add_gtest(test_completion_monitor test/test_completion_monitor.cpp)
  target_link_libraries(test_completion_monitor aic_data_collection)

  ament_add_gtest(test_trial_config_provider test/test_trial_config_provider.cpp)
  target_link_libraries(test_trial_config_provider aic_data_collection)

  ament_add_gtest(test_dynamic_trial_provider test/test_dynamic_trial_provider.cpp)
  target_link_libraries(test_dynamic_trial_provider aic_data_collection)

  ament_add_gtest(test_rosbag_manager test/test_rosbag_manager.cpp)
  target_link_libraries(test_rosbag_manager aic_data_collection)

  # Collection flow test needs GMock for mocking ROS components
  ament_add_gtest(test_collection_flow test/test_collection_flow.cpp)
  target_link_libraries(test_collection_flow
    aic_data_collection
    aic_engine_utils
    rclcpp::rclcpp
    rclcpp_action::rclcpp_action
    ${aic_task_interfaces_TARGETS}
    ${lifecycle_msgs_TARGETS}
    ${std_msgs_TARGETS}
    ${sensor_msgs_TARGETS}
  )
endif()

ament_package()
```

- [ ] **Step 3: Create empty stub files so the build system can be validated**

Create minimal stubs for all new source files so the build graph is valid. Each `.cpp` file should be empty or have a single-line comment. Each `.hpp` should have an include guard and empty namespace. This lets us verify the CMake configuration before writing real code.

```cpp
// src/utils/tf_helper.hpp
#ifndef AIC_ENGINE_UTILS_TF_HELPER_HPP_
#define AIC_ENGINE_UTILS_TF_HELPER_HPP_
namespace aic { }
#endif

// src/utils/tf_helper.cpp
#include "utils/tf_helper.hpp"

// src/utils/scene_spawner.hpp
#ifndef AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_
#define AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_
namespace aic { }
#endif

// src/utils/scene_spawner.cpp
#include "utils/scene_spawner.hpp"

// src/utils/homing_helper.hpp
#ifndef AIC_ENGINE_UTILS_HOMING_HELPER_HPP_
#define AIC_ENGINE_UTILS_HOMING_HELPER_HPP_
namespace aic { }
#endif

// src/utils/homing_helper.cpp
#include "utils/homing_helper.hpp"

// src/completion_monitor.hpp
#ifndef AIC_ENGINE_COMPLETION_MONITOR_HPP_
#define AIC_ENGINE_COMPLETION_MONITOR_HPP_
namespace aic { }
#endif

// src/completion_monitor.cpp
#include "completion_monitor.hpp"

// src/trial_config_provider.hpp
#ifndef AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_
#define AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_
namespace aic { }
#endif

// src/trial_config_provider.cpp
#include "trial_config_provider.hpp"

// src/rosbag_manager.hpp
#ifndef AIC_ENGINE_ROSBAG_MANAGER_HPP_
#define AIC_ENGINE_ROSBAG_MANAGER_HPP_
namespace aic { }
#endif

// src/rosbag_manager.cpp
#include "rosbag_manager.hpp"

// src/auto_data_collector.hpp
#ifndef AIC_ENGINE_AUTO_DATA_COLLECTOR_HPP_
#define AIC_ENGINE_AUTO_DATA_COLLECTOR_HPP_
namespace aic { }
#endif

// src/auto_data_collector.cpp
#include "auto_data_collector.hpp"

// src/auto_data_collector_main.cpp
int main(int, char**) { return 0; }
```

Create empty test files too:
```cpp
// test/test_completion_monitor.cpp
#include <gtest/gtest.h>
TEST(Stub, Placeholder) { SUCCEED(); }

// test/test_trial_config_provider.cpp
#include <gtest/gtest.h>
TEST(Stub, Placeholder) { SUCCEED(); }

// test/test_dynamic_trial_provider.cpp
#include <gtest/gtest.h>
TEST(Stub, Placeholder) { SUCCEED(); }

// test/test_rosbag_manager.cpp
#include <gtest/gtest.h>
TEST(Stub, Placeholder) { SUCCEED(); }

// test/test_collection_flow.cpp
#include <gtest/gtest.h>
TEST(Stub, Placeholder) { SUCCEED(); }
```

- [ ] **Step 4: Verify build compiles**

Run:
```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON
```
Expected: Build succeeds with 0 errors.

- [ ] **Step 5: Verify tests run**

Run:
```bash
cd /home/weed/ws_aic && colcon test --packages-select aic_engine && colcon test-result --verbose
```
Expected: All 5 stub tests pass.

- [ ] **Step 6: Commit**

```bash
git add aic_engine/CMakeLists.txt aic_engine/package.xml aic_engine/src/ aic_engine/test/
git commit -m "build: add scaffolding for auto_data_collector C++ conversion"
```

---

### Task 2: CompletionMonitor (Pure Logic, No ROS Dependencies)

**Files:**
- Create: `aic_engine/src/completion_monitor.hpp`
- Create: `aic_engine/src/completion_monitor.cpp`
- Create: `aic_engine/test/test_completion_monitor.cpp`

This is the simplest component — pure math, no ROS. Port directly from `aic_data_collection/completion_monitor.py`.

- [ ] **Step 1: Write the failing tests**

Replace `test/test_completion_monitor.cpp`:

```cpp
#include <gtest/gtest.h>
#include <cmath>
#include "completion_monitor.hpp"

using aic::CompletionResult;
using aic::check_tf_completion;

// === check_tf_completion tests ===

TEST(CheckTfCompletion, SuccessWithinThreshold) {
  Eigen::Vector3d plug_pos(0.1, 0.2, 0.3);
  Eigen::Vector3d port_pos(0.1, 0.2, 0.303);  // 3mm away
  Eigen::Quaterniond plug_quat(1.0, 0.0, 0.0, 0.0);  // w,x,y,z
  Eigen::Quaterniond port_quat(1.0, 0.0, 0.0, 0.0);
  EXPECT_TRUE(check_tf_completion(plug_pos, port_pos, plug_quat, port_quat, 0.005, 0.1));
}

TEST(CheckTfCompletion, FailDistanceTooLarge) {
  Eigen::Vector3d plug_pos(0.1, 0.2, 0.3);
  Eigen::Vector3d port_pos(0.1, 0.2, 0.31);  // 10mm away
  Eigen::Quaterniond plug_quat(1.0, 0.0, 0.0, 0.0);
  Eigen::Quaterniond port_quat(1.0, 0.0, 0.0, 0.0);
  EXPECT_FALSE(check_tf_completion(plug_pos, port_pos, plug_quat, port_quat, 0.005, 0.1));
}

TEST(CheckTfCompletion, FailOrientationTooLarge) {
  Eigen::Vector3d plug_pos(0.1, 0.2, 0.3);
  Eigen::Vector3d port_pos(0.1, 0.2, 0.301);
  Eigen::Quaterniond plug_quat(1.0, 0.0, 0.0, 0.0);
  // ~0.2 rad rotation around z
  Eigen::Quaterniond port_quat(std::cos(0.1), 0.0, 0.0, std::sin(0.1));
  EXPECT_FALSE(check_tf_completion(plug_pos, port_pos, plug_quat, port_quat, 0.005, 0.1));
}

// === CompletionResult tests ===

TEST(CompletionResult, SuccessIsSuccess) {
  EXPECT_TRUE(is_success(CompletionResult::SUCCESS));
}

TEST(CompletionResult, PartialIsSuccess) {
  EXPECT_TRUE(is_success(CompletionResult::PARTIAL));
}

TEST(CompletionResult, TimeoutIsNotSuccess) {
  EXPECT_FALSE(is_success(CompletionResult::TIMEOUT));
}

TEST(CompletionResult, ActionFailedIsNotSuccess) {
  EXPECT_FALSE(is_success(CompletionResult::ACTION_FAILED));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON 2>&1 | tail -20`
Expected: Compile error — `check_tf_completion` and `CompletionResult` not defined.

- [ ] **Step 3: Implement completion_monitor.hpp**

Replace `src/completion_monitor.hpp`:

```cpp
#ifndef AIC_ENGINE_COMPLETION_MONITOR_HPP_
#define AIC_ENGINE_COMPLETION_MONITOR_HPP_

#include <Eigen/Geometry>

namespace aic {

enum class CompletionResult : uint8_t {
  SUCCESS = 0,
  PARTIAL,
  TIMEOUT,
  ACTION_FAILED
};

inline bool is_success(CompletionResult r) {
  return r == CompletionResult::SUCCESS || r == CompletionResult::PARTIAL;
}

/// Check if plug is within distance and orientation threshold of port.
/// @param plug_pos/port_pos  3D positions
/// @param plug_quat/port_quat  quaternions (Eigen convention: w,x,y,z)
/// @param distance_threshold  meters
/// @param orientation_threshold  radians
bool check_tf_completion(
    const Eigen::Vector3d& plug_pos,
    const Eigen::Vector3d& port_pos,
    const Eigen::Quaterniond& plug_quat,
    const Eigen::Quaterniond& port_quat,
    double distance_threshold = 0.005,
    double orientation_threshold = 0.1);

}  // namespace aic

#endif  // AIC_ENGINE_COMPLETION_MONITOR_HPP_
```

- [ ] **Step 4: Implement completion_monitor.cpp**

Replace `src/completion_monitor.cpp`:

```cpp
#include "completion_monitor.hpp"
#include <cmath>

namespace aic {

bool check_tf_completion(
    const Eigen::Vector3d& plug_pos,
    const Eigen::Vector3d& port_pos,
    const Eigen::Quaterniond& plug_quat,
    const Eigen::Quaterniond& port_quat,
    double distance_threshold,
    double orientation_threshold) {
  double distance = (plug_pos - port_pos).norm();
  if (distance > distance_threshold) {
    return false;
  }

  // Quaternion angle difference: angle = 2 * acos(|dot|)
  double dot = std::abs(plug_quat.dot(port_quat));
  dot = std::min(1.0, dot);
  double angle_diff = 2.0 * std::acos(dot);

  return angle_diff <= orientation_threshold;
}

}  // namespace aic
```

- [ ] **Step 5: Build and run tests**

Run:
```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select aic_engine --ctest-args -R test_completion_monitor && colcon test-result --verbose
```
Expected: All 7 CompletionMonitor tests pass.

- [ ] **Step 6: Commit**

```bash
git add aic_engine/src/completion_monitor.hpp aic_engine/src/completion_monitor.cpp aic_engine/test/test_completion_monitor.cpp
git commit -m "feat: add CompletionMonitor with TF proximity check (C++ port)"
```

---

### Task 3: TrialConfigProvider — StaticTrialProvider

**Files:**
- Create: `aic_engine/src/trial_config_provider.hpp`
- Create: `aic_engine/src/trial_config_provider.cpp`
- Create: `aic_engine/test/test_trial_config_provider.cpp`

Port from `aic_data_collection/trial_config_provider.py::StaticTrialProvider`.

- [ ] **Step 1: Write the failing tests**

Replace `test/test_trial_config_provider.cpp`:

```cpp
#include <gtest/gtest.h>
#include <fstream>
#include <cstdio>
#include "trial_config_provider.hpp"

// Helper: write a minimal YAML config to a temp file and return path
static std::string write_sample_config() {
  const char* yaml = R"(
trials:
  trial_1:
    scene:
      task_board:
        pose: {x: 0.15, y: -0.2, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.015, z: 0.042}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_0
        target_module_name: nic_card_mount_0
        time_limit: 180
  trial_2:
    scene:
      task_board:
        pose: {x: 0.15, y: -0.2, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.015, z: 0.045}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_0
        target_module_name: nic_card_mount_1
        time_limit: 180
robot:
  home_joint_positions:
    shoulder_pan_joint: -0.1597
    shoulder_lift_joint: -1.3542
    elbow_joint: -1.6648
    wrist_1_joint: -1.6933
    wrist_2_joint: 1.571
    wrist_3_joint: 1.411
)";
  char path[] = "/tmp/aic_test_config_XXXXXX.yaml";
  int fd = mkstemps(path, 5);
  write(fd, yaml, strlen(yaml));
  close(fd);
  return std::string(path);
}

class StaticTrialProviderTest : public ::testing::Test {
protected:
  void SetUp() override { config_path_ = write_sample_config(); }
  void TearDown() override { std::remove(config_path_.c_str()); }
  std::string config_path_;
};

TEST_F(StaticTrialProviderTest, LoadsAllTrials) {
  aic::StaticTrialProvider provider(config_path_);
  EXPECT_EQ(provider.trial_count(), 2u);
}

TEST_F(StaticTrialProviderTest, RoundRobinDefault) {
  aic::StaticTrialProvider provider(config_path_);
  auto t1 = provider.get_next_trial();
  EXPECT_EQ(t1["trial_id"].as<std::string>(), "trial_1");
  auto t2 = provider.get_next_trial();
  EXPECT_EQ(t2["trial_id"].as<std::string>(), "trial_2");
  auto t3 = provider.get_next_trial();
  EXPECT_EQ(t3["trial_id"].as<std::string>(), "trial_1");  // wraps
}

TEST_F(StaticTrialProviderTest, SelectedTrials) {
  aic::StaticTrialProvider provider(config_path_, {"trial_2"});
  auto t1 = provider.get_next_trial();
  EXPECT_EQ(t1["trial_id"].as<std::string>(), "trial_2");
  auto t2 = provider.get_next_trial();
  EXPECT_EQ(t2["trial_id"].as<std::string>(), "trial_2");
}

TEST_F(StaticTrialProviderTest, TrialHasSceneAndTasks) {
  aic::StaticTrialProvider provider(config_path_);
  auto trial = provider.get_next_trial();
  EXPECT_TRUE(trial["scene"].IsDefined());
  EXPECT_TRUE(trial["tasks"].IsDefined());
  EXPECT_TRUE(trial["scene"]["cables"]["cable_0"].IsDefined());
}

TEST_F(StaticTrialProviderTest, HomeJointPositions) {
  aic::StaticTrialProvider provider(config_path_);
  auto home = provider.home_joint_positions();
  EXPECT_NEAR(home["shoulder_pan_joint"], -0.1597, 1e-4);
}

TEST_F(StaticTrialProviderTest, InvalidTrialNameThrows) {
  EXPECT_THROW(
    aic::StaticTrialProvider(config_path_, {"trial_99"}),
    std::runtime_error
  );
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON 2>&1 | tail -20`
Expected: Compile error — `StaticTrialProvider` not defined.

- [ ] **Step 3: Implement trial_config_provider.hpp**

Replace `src/trial_config_provider.hpp`:

```cpp
#ifndef AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_
#define AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_

#include <map>
#include <memory>
#include <optional>
#include <random>
#include <string>
#include <vector>

#include "yaml-cpp/yaml.h"

namespace aic {

/// Abstract base for trial providers.
class TrialConfigProvider {
public:
  virtual ~TrialConfigProvider() = default;
  virtual YAML::Node get_next_trial() = 0;
  virtual size_t trial_count() const = 0;
  virtual std::map<std::string, double> home_joint_positions() const = 0;
};

/// Provides trial configs from a static YAML file in round-robin order.
class StaticTrialProvider : public TrialConfigProvider {
public:
  /// @param config_path Path to YAML config file.
  /// @param trials Optional list of trial names to filter. Empty = all.
  explicit StaticTrialProvider(
      const std::string& config_path,
      const std::vector<std::string>& trials = {});

  YAML::Node get_next_trial() override;
  size_t trial_count() const override;
  std::map<std::string, double> home_joint_positions() const override;

private:
  YAML::Node config_;
  std::vector<std::string> trial_names_;
  std::map<std::string, YAML::Node> trials_;
  size_t index_ = 0;
};

/// Generates randomized trial configs from base templates.
/// Supports round-robin base trial selection, edge-biased beta(0.5,0.5) rail
/// sampling, cable gripper_offset perturbation, and per-episode seed recording.
class DynamicTrialProvider : public TrialConfigProvider {
public:
  /// @param config_path Path to YAML config file.
  /// @param base_trials List of base trial names. Empty = all.
  /// @param seed Optional RNG seed (0 = random).
  explicit DynamicTrialProvider(
      const std::string& config_path,
      const std::vector<std::string>& base_trials = {},
      uint64_t seed = 0);

  YAML::Node get_next_trial() override;
  size_t trial_count() const override;
  std::map<std::string, double> home_joint_positions() const override;

private:
  double beta_sample(double low, double high);
  void randomize_cables(YAML::Node& scene);

  YAML::Node config_;
  std::vector<std::string> trial_names_;
  std::map<std::string, YAML::Node> base_trials_;
  YAML::Node limits_;
  std::mt19937_64 rng_;
  size_t index_ = 0;
  size_t counter_ = 0;
};

}  // namespace aic

#endif  // AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_
```

- [ ] **Step 4: Implement trial_config_provider.cpp (StaticTrialProvider only)**

Replace `src/trial_config_provider.cpp`:

```cpp
#include "trial_config_provider.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace aic {

// ===========================================================================
// StaticTrialProvider
// ===========================================================================

StaticTrialProvider::StaticTrialProvider(
    const std::string& config_path,
    const std::vector<std::string>& trials) {
  config_ = YAML::LoadFile(config_path);
  auto all_trials = config_["trials"];

  if (trials.empty()) {
    for (auto it = all_trials.begin(); it != all_trials.end(); ++it) {
      trial_names_.push_back(it->first.as<std::string>());
    }
  } else {
    for (const auto& name : trials) {
      if (!all_trials[name]) {
        std::ostringstream oss;
        oss << "Trial '" << name << "' not found in config. Available:";
        for (auto it = all_trials.begin(); it != all_trials.end(); ++it) {
          oss << " " << it->first.as<std::string>();
        }
        throw std::runtime_error(oss.str());
      }
      trial_names_.push_back(name);
    }
  }

  for (const auto& name : trial_names_) {
    trials_[name] = all_trials[name];
  }
}

YAML::Node StaticTrialProvider::get_next_trial() {
  const auto& name = trial_names_[index_ % trial_names_.size()];
  index_++;
  YAML::Node result;
  result["trial_id"] = name;
  result["scene"] = trials_[name]["scene"];
  result["tasks"] = trials_[name]["tasks"];
  return result;
}

size_t StaticTrialProvider::trial_count() const {
  return trial_names_.size();
}

std::map<std::string, double> StaticTrialProvider::home_joint_positions() const {
  std::map<std::string, double> positions;
  const auto& joints = config_["robot"]["home_joint_positions"];
  for (auto it = joints.begin(); it != joints.end(); ++it) {
    positions[it->first.as<std::string>()] = it->second.as<double>();
  }
  return positions;
}

// ===========================================================================
// DynamicTrialProvider (stub — implemented in Task 4)
// ===========================================================================

DynamicTrialProvider::DynamicTrialProvider(
    const std::string& /*config_path*/,
    const std::vector<std::string>& /*base_trials*/,
    uint64_t /*seed*/) {}

YAML::Node DynamicTrialProvider::get_next_trial() { return {}; }
size_t DynamicTrialProvider::trial_count() const { return 0; }
std::map<std::string, double> DynamicTrialProvider::home_joint_positions() const { return {}; }
double DynamicTrialProvider::beta_sample(double, double) { return 0.0; }
void DynamicTrialProvider::randomize_cables(YAML::Node&) {}

}  // namespace aic
```

- [ ] **Step 5: Build and run tests**

Run:
```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select aic_engine --ctest-args -R test_trial_config_provider && colcon test-result --verbose
```
Expected: All 6 StaticTrialProvider tests pass.

- [ ] **Step 6: Commit**

```bash
git add aic_engine/src/trial_config_provider.hpp aic_engine/src/trial_config_provider.cpp aic_engine/test/test_trial_config_provider.cpp
git commit -m "feat: add StaticTrialProvider with round-robin and filtering (C++ port)"
```

---

### Task 4: TrialConfigProvider — DynamicTrialProvider

**Files:**
- Modify: `aic_engine/src/trial_config_provider.cpp`
- Create: `aic_engine/test/test_dynamic_trial_provider.cpp`

Port from `aic_data_collection/trial_config_provider.py::DynamicTrialProvider`.

- [ ] **Step 1: Write the failing tests**

Replace `test/test_dynamic_trial_provider.cpp`:

```cpp
#include <gtest/gtest.h>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <set>
#include <unistd.h>
#include "trial_config_provider.hpp"

static std::string write_dynamic_config() {
  const char* yaml = R"(
task_board_limits:
  nic_rail: {min_translation: -0.048, max_translation: 0.036}
  sc_rail: {min_translation: -0.06, max_translation: 0.055}
  mount_rail: {min_translation: -0.09425, max_translation: 0.09425}
trials:
  trial_1:
    scene:
      task_board:
        pose: {x: 0.15, y: -0.2, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
        nic_rail_0:
          entity_present: true
          entity_name: nic_card_0
          entity_pose: {translation: 0.02, roll: 0.0, pitch: 0.0, yaw: 0.0}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.015, z: 0.042}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_0
        target_module_name: nic_card_mount_0
        time_limit: 180
  trial_2:
    scene:
      task_board:
        pose: {x: 0.16, y: -0.21, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
        nic_rail_0:
          entity_present: true
          entity_name: nic_card_0
          entity_pose: {translation: 0.01, roll: 0.0, pitch: 0.0, yaw: 0.0}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.016, z: 0.045}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_1
        target_module_name: nic_card_mount_1
        time_limit: 180
robot:
  home_joint_positions:
    shoulder_pan_joint: -0.1597
    shoulder_lift_joint: -1.3542
    elbow_joint: -1.6648
    wrist_1_joint: -1.6933
    wrist_2_joint: 1.571
    wrist_3_joint: 1.411
)";
  char path[] = "/tmp/aic_dyn_config_XXXXXX.yaml";
  int fd = mkstemps(path, 5);
  write(fd, yaml, strlen(yaml));
  close(fd);
  return std::string(path);
}

class DynamicTrialProviderTest : public ::testing::Test {
protected:
  void SetUp() override { config_path_ = write_dynamic_config(); }
  void TearDown() override { std::remove(config_path_.c_str()); }
  std::string config_path_;
};

TEST_F(DynamicTrialProviderTest, GeneratesRandomizedTrial) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  auto trial = provider.get_next_trial();
  auto tid = trial["trial_id"].as<std::string>();
  EXPECT_TRUE(tid.find("dynamic_") == 0) << "Got: " << tid;
  EXPECT_TRUE(trial["scene"].IsDefined());
}

TEST_F(DynamicTrialProviderTest, RandomizedTrialsDiffer) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  auto t1 = provider.get_next_trial();
  auto t2 = provider.get_next_trial();
  auto p1 = t1["scene"]["task_board"]["pose"];
  auto p2 = t2["scene"]["task_board"]["pose"];
  bool differs = (p1["x"].as<double>() != p2["x"].as<double>()) ||
                 (p1["y"].as<double>() != p2["y"].as<double>()) ||
                 (p1["yaw"].as<double>() != p2["yaw"].as<double>());
  EXPECT_TRUE(differs);
}

TEST_F(DynamicTrialProviderTest, RailTranslationsWithinLimits) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 123);
  for (int i = 0; i < 20; ++i) {
    auto trial = provider.get_next_trial();
    auto tb = trial["scene"]["task_board"];
    if (tb["nic_rail_0"] && tb["nic_rail_0"]["entity_present"].as<bool>()) {
      double trans = tb["nic_rail_0"]["entity_pose"]["translation"].as<double>();
      EXPECT_GE(trans, -0.048) << "Iteration " << i;
      EXPECT_LE(trans, 0.036) << "Iteration " << i;
    }
  }
}

TEST_F(DynamicTrialProviderTest, MultiTrialRoundRobin) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1", "trial_2"}, 42);
  EXPECT_EQ(provider.trial_count(), 2u);
  auto t1 = provider.get_next_trial();
  auto t2 = provider.get_next_trial();
  auto t3 = provider.get_next_trial();
  EXPECT_EQ(t1["base_trial"].as<std::string>(), "trial_1");
  EXPECT_EQ(t2["base_trial"].as<std::string>(), "trial_2");
  EXPECT_EQ(t3["base_trial"].as<std::string>(), "trial_1");
}

TEST_F(DynamicTrialProviderTest, EmptyBaseTrialsUsesAll) {
  aic::DynamicTrialProvider provider(config_path_, {}, 42);
  EXPECT_EQ(provider.trial_count(), 2u);
}

TEST_F(DynamicTrialProviderTest, SeedRecordedInTrial) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  auto trial = provider.get_next_trial();
  EXPECT_TRUE(trial["seed"].IsDefined());
  EXPECT_TRUE(trial["seed"].as<uint64_t>() > 0);
}

TEST_F(DynamicTrialProviderTest, SeedsDifferPerEpisode) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  std::set<uint64_t> seeds;
  for (int i = 0; i < 10; ++i) {
    auto trial = provider.get_next_trial();
    seeds.insert(trial["seed"].as<uint64_t>());
  }
  EXPECT_EQ(seeds.size(), 10u);
}

TEST_F(DynamicTrialProviderTest, CableGripperOffsetRandomized) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  bool any_changed = false;
  for (int i = 0; i < 5; ++i) {
    auto trial = provider.get_next_trial();
    auto offset = trial["scene"]["cables"]["cable_0"]["pose"]["gripper_offset"];
    double ox = offset["x"].as<double>();
    double oy = offset["y"].as<double>();
    double oz = offset["z"].as<double>();
    EXPECT_NEAR(ox, 0.0, 0.002 + 1e-9);
    EXPECT_NEAR(oy, 0.015, 0.002 + 1e-9);
    EXPECT_NEAR(oz, 0.042, 0.002 + 1e-9);
    if (ox != 0.0 || oy != 0.015 || oz != 0.042) any_changed = true;
  }
  EXPECT_TRUE(any_changed);
}

TEST_F(DynamicTrialProviderTest, EdgeBiasedSamplingCoversRange) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  std::vector<double> translations;
  for (int i = 0; i < 200; ++i) {
    auto trial = provider.get_next_trial();
    auto tb = trial["scene"]["task_board"];
    if (tb["nic_rail_0"] && tb["nic_rail_0"]["entity_present"].as<bool>()) {
      translations.push_back(tb["nic_rail_0"]["entity_pose"]["translation"].as<double>());
    }
  }
  ASSERT_FALSE(translations.empty());
  double nic_min = -0.048, nic_max = 0.036;
  double range = nic_max - nic_min;
  int near_min = 0, near_max = 0;
  for (double t : translations) {
    if (t < nic_min + 0.2 * range) near_min++;
    if (t > nic_max - 0.2 * range) near_max++;
  }
  EXPECT_GT(near_min, 20) << "Expected >20 near-min samples, got " << near_min;
  EXPECT_GT(near_max, 20) << "Expected >20 near-max samples, got " << near_max;
}

TEST_F(DynamicTrialProviderTest, InvalidBaseTrialThrows) {
  EXPECT_THROW(
    aic::DynamicTrialProvider(config_path_, {"nonexistent"}, 42),
    std::runtime_error
  );
}
```

- [ ] **Step 2: Implement DynamicTrialProvider in trial_config_provider.cpp**

Replace the DynamicTrialProvider stub section in `src/trial_config_provider.cpp`:

```cpp
// ===========================================================================
// DynamicTrialProvider
// ===========================================================================

DynamicTrialProvider::DynamicTrialProvider(
    const std::string& config_path,
    const std::vector<std::string>& base_trials,
    uint64_t seed) {
  config_ = YAML::LoadFile(config_path);
  auto all_trials = config_["trials"];
  limits_ = config_["task_board_limits"];

  std::vector<std::string> selected = base_trials;
  if (selected.empty()) {
    for (auto it = all_trials.begin(); it != all_trials.end(); ++it) {
      selected.push_back(it->first.as<std::string>());
    }
  }

  for (const auto& name : selected) {
    if (!all_trials[name]) {
      throw std::runtime_error("Base trial '" + name + "' not found.");
    }
    trial_names_.push_back(name);
    base_trials_[name] = YAML::Clone(all_trials[name]);
  }

  if (seed == 0) {
    std::random_device rd;
    rng_.seed(rd());
  } else {
    rng_.seed(seed);
  }
}

double DynamicTrialProvider::beta_sample(double low, double high) {
  // Beta(0.5, 0.5) via gamma distribution: X ~ Gamma(0.5,1), Y ~ Gamma(0.5,1)
  // then X/(X+Y) ~ Beta(0.5, 0.5)
  std::gamma_distribution<double> gamma(0.5, 1.0);
  double x = gamma(rng_);
  double y = gamma(rng_);
  double u = x / (x + y);
  return low + u * (high - low);
}

void DynamicTrialProvider::randomize_cables(YAML::Node& scene) {
  if (!scene["cables"]) return;
  auto cables = scene["cables"];
  std::uniform_real_distribution<double> perturb(-0.002, 0.002);
  for (auto it = cables.begin(); it != cables.end(); ++it) {
    auto offset = it->second["pose"]["gripper_offset"];
    if (!offset) continue;
    for (const auto& axis : {"x", "y", "z"}) {
      if (offset[axis]) {
        offset[axis] = offset[axis].as<double>() + perturb(rng_);
      }
    }
  }
}

YAML::Node DynamicTrialProvider::get_next_trial() {
  // Capture per-episode seed before any RNG calls
  std::uniform_int_distribution<uint64_t> seed_dist;
  uint64_t episode_seed = seed_dist(rng_);
  counter_++;

  // Round-robin base trial selection
  const auto& base_name = trial_names_[index_ % trial_names_.size()];
  index_++;
  YAML::Node trial = YAML::Clone(base_trials_[base_name]);

  auto tb = trial["scene"]["task_board"];

  // Randomize task_board pose slightly
  std::uniform_real_distribution<double> xy_perturb(-0.03, 0.03);
  std::uniform_real_distribution<double> yaw_perturb(-0.3, 0.3);
  tb["pose"]["x"] = tb["pose"]["x"].as<double>() + xy_perturb(rng_);
  tb["pose"]["y"] = tb["pose"]["y"].as<double>() + xy_perturb(rng_);
  tb["pose"]["yaw"] = tb["pose"]["yaw"].as<double>() + yaw_perturb(rng_);

  // Randomize NIC rails
  double nic_min = limits_["nic_rail"] ? limits_["nic_rail"]["min_translation"].as<double>(-0.048) : -0.048;
  double nic_max = limits_["nic_rail"] ? limits_["nic_rail"]["max_translation"].as<double>(0.036) : 0.036;
  for (int i = 0; i < 5; ++i) {
    std::string key = "nic_rail_" + std::to_string(i);
    if (tb[key] && tb[key]["entity_present"].as<bool>(false)) {
      tb[key]["entity_pose"]["translation"] = beta_sample(nic_min, nic_max);
    }
  }

  // Randomize SC rails
  double sc_min = limits_["sc_rail"] ? limits_["sc_rail"]["min_translation"].as<double>(-0.06) : -0.06;
  double sc_max = limits_["sc_rail"] ? limits_["sc_rail"]["max_translation"].as<double>(0.055) : 0.055;
  for (int i = 0; i < 2; ++i) {
    std::string key = "sc_rail_" + std::to_string(i);
    if (tb[key] && tb[key]["entity_present"].as<bool>(false)) {
      tb[key]["entity_pose"]["translation"] = beta_sample(sc_min, sc_max);
    }
  }

  // Randomize mount rails
  double mount_min = limits_["mount_rail"] ? limits_["mount_rail"]["min_translation"].as<double>(-0.09425) : -0.09425;
  double mount_max = limits_["mount_rail"] ? limits_["mount_rail"]["max_translation"].as<double>(0.09425) : 0.09425;
  for (const auto& rail_type : {"lc_mount", "sfp_mount", "sc_mount"}) {
    for (int i = 0; i < 2; ++i) {
      std::string key = std::string(rail_type) + "_rail_" + std::to_string(i);
      if (tb[key] && tb[key]["entity_present"].as<bool>(false)) {
        tb[key]["entity_pose"]["translation"] = beta_sample(mount_min, mount_max);
      }
    }
  }

  // Randomize cable gripper offsets
  randomize_cables(trial["scene"]);

  // Build result
  std::ostringstream tid;
  tid << "dynamic_" << std::setfill('0') << std::setw(4) << counter_;

  YAML::Node result;
  result["trial_id"] = tid.str();
  result["base_trial"] = base_name;
  result["seed"] = episode_seed;
  result["scene"] = trial["scene"];
  result["tasks"] = trial["tasks"];
  return result;
}

size_t DynamicTrialProvider::trial_count() const {
  return trial_names_.size();
}

std::map<std::string, double> DynamicTrialProvider::home_joint_positions() const {
  std::map<std::string, double> positions;
  const auto& joints = config_["robot"]["home_joint_positions"];
  for (auto it = joints.begin(); it != joints.end(); ++it) {
    positions[it->first.as<std::string>()] = it->second.as<double>();
  }
  return positions;
}
```

- [ ] **Step 3: Build and run tests**

Run:
```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select aic_engine --ctest-args -R test_dynamic_trial_provider && colcon test-result --verbose
```
Expected: All 11 DynamicTrialProvider tests pass.

- [ ] **Step 4: Commit**

```bash
git add aic_engine/src/trial_config_provider.cpp aic_engine/test/test_dynamic_trial_provider.cpp
git commit -m "feat: add DynamicTrialProvider with beta sampling and per-episode seeds"
```

---

### Task 5: RosbagManager

**Files:**
- Create: `aic_engine/src/rosbag_manager.hpp`
- Create: `aic_engine/src/rosbag_manager.cpp`
- Create: `aic_engine/test/test_rosbag_manager.cpp`

Port from `aic_data_collection/rosbag_manager.py`. The subprocess recording (start/stop) is hard to unit-test, so tests focus on path construction, metadata YAML, and manifest JSON — matching Python test coverage.

- [ ] **Step 1: Write the failing tests**

Replace `test/test_rosbag_manager.cpp`:

```cpp
#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <nlohmann/json.hpp>
#include "rosbag_manager.hpp"
#include "yaml-cpp/yaml.h"

namespace fs = std::filesystem;
using json = nlohmann::json;

// === Observation Topics ===

TEST(ObservationTopics, ContainsCameraTopics) {
  auto& topics = aic::OBSERVATION_TOPICS;
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/left_camera/image"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/center_camera/image"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/right_camera/image"), topics.end());
}

TEST(ObservationTopics, ContainsSensorTopics) {
  auto& topics = aic::OBSERVATION_TOPICS;
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/joint_states"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/fts_broadcaster/wrench"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/aic_controller/controller_state"), topics.end());
}

TEST(ObservationTopics, TopicCount) {
  EXPECT_EQ(aic::OBSERVATION_TOPICS.size(), 9u);
}

// === RosbagManager path helpers ===

class RosbagManagerTest : public ::testing::Test {
protected:
  void SetUp() override {
    tmpdir_ = fs::temp_directory_path() / ("aic_bag_test_" + std::to_string(getpid()));
    fs::create_directories(tmpdir_);
  }
  void TearDown() override { fs::remove_all(tmpdir_); }
  fs::path tmpdir_;
};

TEST_F(RosbagManagerTest, BagPath) {
  aic::RosbagManager mgr(tmpdir_.string());
  EXPECT_EQ(mgr.bag_path("episode_001"), (tmpdir_ / "episode_001").string());
}

TEST_F(RosbagManagerTest, FailedBagPath) {
  aic::RosbagManager mgr(tmpdir_.string());
  EXPECT_EQ(mgr.failed_bag_path("episode_001"), (tmpdir_ / "failed" / "episode_001").string());
}

TEST_F(RosbagManagerTest, BuildRecordCommand) {
  aic::RosbagManager mgr(tmpdir_.string());
  auto cmd = mgr.build_record_command("episode_001");
  EXPECT_EQ(cmd[0], "ros2");
  EXPECT_EQ(cmd[1], "bag");
  EXPECT_EQ(cmd[2], "record");
  EXPECT_NE(std::find(cmd.begin(), cmd.end(), "/left_camera/image"), cmd.end());
  EXPECT_NE(std::find(cmd.begin(), cmd.end(), "--output"), cmd.end());
}

// === Metadata ===

TEST_F(RosbagManagerTest, SaveMetadataWritesYaml) {
  aic::RosbagManager mgr(tmpdir_.string());
  fs::path ep_dir = tmpdir_ / "trial_1_ep0001";
  fs::create_directories(ep_dir);

  YAML::Node trial;
  trial["trial_id"] = "trial_1";
  trial["base_trial"] = "trial_1";
  trial["seed"] = 12345678;
  trial["scene"]["task_board"]["pose"]["x"] = 0.15;
  trial["tasks"]["task_1"]["cable_name"] = "cable_a";

  auto path = mgr.save_metadata("trial_1_ep0001", trial, true, ep_dir.string(),
                                "2026-04-01T04:30:00Z", "2026-04-01T04:33:00Z");
  EXPECT_TRUE(fs::exists(path));

  auto data = YAML::LoadFile(path);
  EXPECT_EQ(data["episode_id"].as<std::string>(), "trial_1_ep0001");
  EXPECT_EQ(data["trial_id"].as<std::string>(), "trial_1");
  EXPECT_EQ(data["base_trial"].as<std::string>(), "trial_1");
  EXPECT_EQ(data["seed"].as<int>(), 12345678);
  EXPECT_TRUE(data["success"].as<bool>());
  EXPECT_EQ(data["timestamps"]["start"].as<std::string>(), "2026-04-01T04:30:00Z");
  EXPECT_EQ(data["timestamps"]["end"].as<std::string>(), "2026-04-01T04:33:00Z");
  EXPECT_TRUE(data["scene_config"].IsDefined());
  EXPECT_TRUE(data["tasks"].IsDefined());
}

TEST_F(RosbagManagerTest, SaveMetadataSuccessFalse) {
  aic::RosbagManager mgr(tmpdir_.string());
  fs::path ep_dir = tmpdir_ / "failed" / "trial_1_ep0002";
  fs::create_directories(ep_dir);

  YAML::Node trial;
  trial["trial_id"] = "trial_1";
  auto path = mgr.save_metadata("trial_1_ep0002", trial, false, ep_dir.string());
  auto data = YAML::LoadFile(path);
  EXPECT_FALSE(data["success"].as<bool>());
}

// === Manifest ===

TEST_F(RosbagManagerTest, SaveManifestWritesJson) {
  aic::RosbagManager mgr(tmpdir_.string());
  std::vector<aic::EpisodeRecord> episodes = {
    {"t1_ep0001", "t1", true, "/bags/t1_ep0001"},
    {"t1_ep0002", "t1", false, "/bags/failed/t1_ep0002"},
    {"t1_ep0003", "t1", true, "/bags/t1_ep0003"},
  };
  auto path = mgr.save_manifest(episodes);
  EXPECT_TRUE(fs::exists(path));

  std::ifstream f(path);
  auto data = json::parse(f);
  EXPECT_EQ(data["total_episodes"], 3);
  EXPECT_EQ(data["successful"], 2);
  EXPECT_EQ(data["failed"], 1);
  EXPECT_EQ(data["episodes"].size(), 3u);
}

TEST_F(RosbagManagerTest, ManifestEpisodeFields) {
  aic::RosbagManager mgr(tmpdir_.string());
  std::vector<aic::EpisodeRecord> episodes = {
    {"t1_ep0001", "t1", true, "/bags/t1_ep0001"},
  };
  mgr.save_manifest(episodes);
  std::ifstream f((tmpdir_ / "manifest.json").string());
  auto data = json::parse(f);
  auto ep = data["episodes"][0];
  EXPECT_EQ(ep["episode_id"], "t1_ep0001");
  EXPECT_EQ(ep["trial_id"], "t1");
  EXPECT_TRUE(ep["success"].get<bool>());
  EXPECT_EQ(ep["bag_path"], "/bags/t1_ep0001");
}

TEST_F(RosbagManagerTest, EmptyManifest) {
  aic::RosbagManager mgr(tmpdir_.string());
  mgr.save_manifest({});
  std::ifstream f((tmpdir_ / "manifest.json").string());
  auto data = json::parse(f);
  EXPECT_EQ(data["total_episodes"], 0);
  EXPECT_EQ(data["successful"], 0);
  EXPECT_EQ(data["episodes"].size(), 0u);
}
```

- [ ] **Step 2: Implement rosbag_manager.hpp**

Replace `src/rosbag_manager.hpp`:

```cpp
#ifndef AIC_ENGINE_ROSBAG_MANAGER_HPP_
#define AIC_ENGINE_ROSBAG_MANAGER_HPP_

#include <string>
#include <vector>
#include <sys/types.h>
#include "yaml-cpp/yaml.h"

namespace aic {

struct EpisodeRecord {
  std::string episode_id;
  std::string trial_id;
  bool success;
  std::string bag_path;
};

extern const std::vector<std::string> OBSERVATION_TOPICS;

class RosbagManager {
public:
  explicit RosbagManager(const std::string& output_dir);

  std::string bag_path(const std::string& episode_id) const;
  std::string failed_bag_path(const std::string& episode_id) const;
  std::vector<std::string> build_record_command(const std::string& episode_id) const;

  bool start_recording(const std::string& episode_id);
  std::string stop_recording(bool success);
  void move_to_failed(const std::string& episode_id);

  std::string save_metadata(
      const std::string& episode_id,
      const YAML::Node& trial,
      bool success,
      const std::string& bag_path,
      const std::string& start_time = "",
      const std::string& end_time = "");

  std::string save_manifest(const std::vector<EpisodeRecord>& episodes);

private:
  std::string output_dir_;
  pid_t recorder_pid_ = -1;
  std::string current_episode_;
  std::string start_time_;
};

}  // namespace aic

#endif  // AIC_ENGINE_ROSBAG_MANAGER_HPP_
```

- [ ] **Step 3: Implement rosbag_manager.cpp**

Replace `src/rosbag_manager.cpp`:

```cpp
#include "rosbag_manager.hpp"

#include <chrono>
#include <csignal>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <sys/wait.h>
#include <unistd.h>

#include <nlohmann/json.hpp>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace aic {

const std::vector<std::string> OBSERVATION_TOPICS = {
    "/left_camera/image",
    "/center_camera/image",
    "/right_camera/image",
    "/left_camera/camera_info",
    "/center_camera/camera_info",
    "/right_camera/camera_info",
    "/fts_broadcaster/wrench",
    "/joint_states",
    "/aic_controller/controller_state",
};

static std::string now_iso8601() {
  auto now = std::chrono::system_clock::now();
  auto time_t = std::chrono::system_clock::to_time_t(now);
  std::ostringstream oss;
  oss << std::put_time(std::gmtime(&time_t), "%Y-%m-%dT%H:%M:%SZ");
  return oss.str();
}

RosbagManager::RosbagManager(const std::string& output_dir)
    : output_dir_(output_dir) {
  fs::create_directories(output_dir);
  fs::create_directories(fs::path(output_dir) / "failed");
}

std::string RosbagManager::bag_path(const std::string& episode_id) const {
  return (fs::path(output_dir_) / episode_id).string();
}

std::string RosbagManager::failed_bag_path(const std::string& episode_id) const {
  return (fs::path(output_dir_) / "failed" / episode_id).string();
}

std::vector<std::string> RosbagManager::build_record_command(
    const std::string& episode_id) const {
  std::vector<std::string> cmd = {"ros2", "bag", "record", "--output", bag_path(episode_id)};
  cmd.insert(cmd.end(), OBSERVATION_TOPICS.begin(), OBSERVATION_TOPICS.end());
  return cmd;
}

bool RosbagManager::start_recording(const std::string& episode_id) {
  if (recorder_pid_ > 0) return false;
  current_episode_ = episode_id;
  start_time_ = now_iso8601();

  auto cmd = build_record_command(episode_id);

  pid_t pid = fork();
  if (pid == 0) {
    // Child: exec ros2 bag record
    std::vector<char*> argv;
    for (auto& s : cmd) argv.push_back(const_cast<char*>(s.c_str()));
    argv.push_back(nullptr);
    execvp(argv[0], argv.data());
    _exit(1);
  }
  recorder_pid_ = pid;
  return pid > 0;
}

std::string RosbagManager::stop_recording(bool success) {
  if (recorder_pid_ <= 0) return "";

  kill(recorder_pid_, SIGINT);
  int status;
  int waited = 0;
  while (waitpid(recorder_pid_, &status, WNOHANG) == 0 && waited < 50) {
    usleep(100000);  // 100ms
    waited++;
  }
  if (waited >= 50) {
    kill(recorder_pid_, SIGKILL);
    waitpid(recorder_pid_, &status, 0);
  }
  recorder_pid_ = -1;

  std::string path = bag_path(current_episode_);
  if (!success) {
    std::string fpath = failed_bag_path(current_episode_);
    if (fs::exists(path)) {
      fs::rename(path, fpath);
    }
    path = fpath;
  }

  current_episode_.clear();
  start_time_.clear();
  return path;
}

void RosbagManager::move_to_failed(const std::string& episode_id) {
  auto src = bag_path(episode_id);
  auto dst = failed_bag_path(episode_id);
  if (fs::exists(src)) {
    fs::rename(src, dst);
  }
}

std::string RosbagManager::save_metadata(
    const std::string& episode_id,
    const YAML::Node& trial,
    bool success,
    const std::string& bag_path_str,
    const std::string& start_time,
    const std::string& end_time) {
  YAML::Node metadata;
  metadata["episode_id"] = episode_id;
  metadata["trial_id"] = trial["trial_id"].as<std::string>("");
  metadata["base_trial"] = trial["base_trial"].as<std::string>(
      trial["trial_id"].as<std::string>(""));
  if (trial["seed"]) {
    metadata["seed"] = trial["seed"].as<uint64_t>();
  } else {
    metadata["seed"] = YAML::Null;
  }
  metadata["success"] = success;
  metadata["scene_config"] = trial["scene"] ? trial["scene"] : YAML::Node();
  metadata["tasks"] = trial["tasks"] ? trial["tasks"] : YAML::Node();
  metadata["timestamps"]["start"] = start_time.empty() ? start_time_ : start_time;
  metadata["timestamps"]["end"] = end_time.empty() ? now_iso8601() : end_time;
  metadata["bag_path"] = bag_path_str;

  fs::create_directories(bag_path_str);
  std::string metadata_path = (fs::path(bag_path_str) / "metadata.yaml").string();
  std::ofstream fout(metadata_path);
  fout << metadata;
  return metadata_path;
}

std::string RosbagManager::save_manifest(const std::vector<EpisodeRecord>& episodes) {
  int successful = 0;
  for (const auto& ep : episodes) {
    if (ep.success) successful++;
  }

  json manifest;
  manifest["total_episodes"] = static_cast<int>(episodes.size());
  manifest["successful"] = successful;
  manifest["failed"] = static_cast<int>(episodes.size()) - successful;
  manifest["episodes"] = json::array();
  for (const auto& ep : episodes) {
    manifest["episodes"].push_back({
      {"episode_id", ep.episode_id},
      {"trial_id", ep.trial_id},
      {"success", ep.success},
      {"bag_path", ep.bag_path},
    });
  }

  std::string path = (fs::path(output_dir_) / "manifest.json").string();
  std::ofstream fout(path);
  fout << manifest.dump(2);
  return path;
}

}  // namespace aic
```

- [ ] **Step 4: Build and run tests**

Run:
```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select aic_engine --ctest-args -R test_rosbag_manager && colcon test-result --verbose
```
Expected: All RosbagManager tests pass.

- [ ] **Step 5: Commit**

```bash
git add aic_engine/src/rosbag_manager.hpp aic_engine/src/rosbag_manager.cpp aic_engine/test/test_rosbag_manager.cpp
git commit -m "feat: add RosbagManager with subprocess recording, metadata, and manifest"
```

---

### Task 6: TfHelper Utility

**Files:**
- Create: `aic_engine/src/utils/tf_helper.hpp`
- Create: `aic_engine/src/utils/tf_helper.cpp`

Simple wrapper — no dedicated test (tested via integration). Extracted from Engine's TF setup.

- [ ] **Step 1: Implement tf_helper.hpp**

```cpp
#ifndef AIC_ENGINE_UTILS_TF_HELPER_HPP_
#define AIC_ENGINE_UTILS_TF_HELPER_HPP_

#include <memory>
#include <optional>
#include <string>

#include "geometry_msgs/msg/transform_stamped.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2_ros/buffer.h"
#include "tf2_ros/transform_listener.h"

namespace aic {

class TfHelper {
public:
  explicit TfHelper(rclcpp::Node* node);

  std::optional<geometry_msgs::msg::TransformStamped>
  lookup(const std::string& target_frame,
         const std::string& source_frame,
         rclcpp::Duration timeout = rclcpp::Duration(1, 0));

  tf2_ros::Buffer& buffer() { return *tf_buffer_; }

private:
  std::shared_ptr<tf2_ros::Buffer> tf_buffer_;
  std::shared_ptr<tf2_ros::TransformListener> tf_listener_;
};

}  // namespace aic

#endif  // AIC_ENGINE_UTILS_TF_HELPER_HPP_
```

- [ ] **Step 2: Implement tf_helper.cpp**

```cpp
#include "utils/tf_helper.hpp"
#include "tf2/exceptions.hpp"

namespace aic {

TfHelper::TfHelper(rclcpp::Node* node)
    : tf_buffer_(std::make_shared<tf2_ros::Buffer>(node->get_clock())),
      tf_listener_(std::make_shared<tf2_ros::TransformListener>(*tf_buffer_)) {}

std::optional<geometry_msgs::msg::TransformStamped>
TfHelper::lookup(const std::string& target_frame,
                 const std::string& source_frame,
                 rclcpp::Duration timeout) {
  try {
    std::string warning;
    if (!tf_buffer_->canTransform(target_frame, source_frame,
                                   tf2::TimePointZero,
                                   tf2::durationFromSec(timeout.seconds()),
                                   &warning)) {
      return std::nullopt;
    }
    return tf_buffer_->lookupTransform(target_frame, source_frame,
                                        tf2::TimePointZero);
  } catch (const tf2::TransformException&) {
    return std::nullopt;
  }
}

}  // namespace aic
```

- [ ] **Step 3: Verify build**

Run: `cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add aic_engine/src/utils/tf_helper.hpp aic_engine/src/utils/tf_helper.cpp
git commit -m "feat: add TfHelper utility for transform lookups"
```

---

### Task 7: SceneSpawner Utility

**Files:**
- Create: `aic_engine/src/utils/scene_spawner.hpp`
- Create: `aic_engine/src/utils/scene_spawner.cpp`

Extracted from Engine's `spawn_entity()`, `ready_simulator()`, `reset_simulator()`. The spawning logic closely mirrors the Python SceneManager.

- [ ] **Step 1: Implement scene_spawner.hpp**

```cpp
#ifndef AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_
#define AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_

#include <map>
#include <string>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "simulation_interfaces/srv/delete_entity.hpp"
#include "simulation_interfaces/srv/spawn_entity.hpp"
#include "std_srvs/srv/trigger.hpp"
#include "utils/tf_helper.hpp"
#include "yaml-cpp/yaml.h"

namespace aic {

using DeleteEntitySrv = simulation_interfaces::srv::DeleteEntity;
using SpawnEntitySrv = simulation_interfaces::srv::SpawnEntity;
using TriggerSrv = std_srvs::srv::Trigger;

class SceneSpawner {
public:
  SceneSpawner(rclcpp::Node* node, TfHelper& tf_helper);

  /// Spawn a single entity via Gazebo service.
  bool spawn_entity(const std::string& name, const std::string& sdf_xml,
                    double x, double y, double z,
                    double roll, double pitch, double yaw);

  /// Delete a single entity.
  bool delete_entity(const std::string& name);

  /// Delete all tracked spawned entities.
  void delete_all();

  /// Spawn entire scene (task_board + cables) from trial config.
  /// Config is a YAML node with "scene" key containing "task_board" and "cables".
  bool spawn_scene(const YAML::Node& trial_config, const YAML::Node& root_config);

  /// Despawn all entities and wait.
  void despawn_scene();

  /// Get list of currently spawned entity names.
  const std::vector<std::string>& spawned_entities() const { return spawned_entities_; }

private:
  std::string process_xacro(const std::string& filepath,
                            const std::map<std::string, std::string>& params);
  std::map<std::string, std::string> build_task_board_xacro_params(
      const YAML::Node& tb_config, const YAML::Node& root_config);
  void tare_ft_sensor();

  template <typename FutureT>
  bool wait_for(const FutureT& future, double timeout_sec) const;

  rclcpp::Node* node_;
  TfHelper& tf_helper_;
  rclcpp::Client<SpawnEntitySrv>::SharedPtr spawn_client_;
  rclcpp::Client<DeleteEntitySrv>::SharedPtr delete_client_;
  rclcpp::Client<TriggerSrv>::SharedPtr tare_ft_client_;
  std::string description_share_;
  std::vector<std::string> spawned_entities_;
};

}  // namespace aic

#endif  // AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_
```

- [ ] **Step 2: Implement scene_spawner.cpp**

Implement the full scene spawner with xacro processing, RPY-to-quaternion conversion, rail parameter building (NIC 0-4, SC 0-1, mount rails), FT taring, and cable spawning with gripper offset. Port from both `aic_engine.cpp:spawn_entity()` (lines 1763-1992) and `scene_manager.py:spawn_scene()`.

The key methods:
- `process_xacro()`: runs `xacro` subprocess, reads stdout
- `build_task_board_xacro_params()`: builds NIC rail, SC rail, mount rail params with clamping from `task_board_limits`
- `spawn_entity()`: builds SpawnEntity request with RPY→quaternion, sends service call
- `spawn_scene()`: spawns task_board via xacro, tares FT, gets gripper TF, spawns cables with offset
- `delete_entity()` / `delete_all()` / `despawn_scene()`: cleanup

This is a large file (~300 lines). The implementation follows the exact same logic as Engine's `ready_simulator()` and `spawn_entity()` methods, plus Python SceneManager patterns. Implement with polling-based service calls (`wait_for` template) matching the Engine pattern.

- [ ] **Step 3: Verify build**

Run: `cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add aic_engine/src/utils/scene_spawner.hpp aic_engine/src/utils/scene_spawner.cpp
git commit -m "feat: add SceneSpawner utility extracted from Engine spawn logic"
```

---

### Task 8: HomingHelper Utility

**Files:**
- Create: `aic_engine/src/utils/homing_helper.hpp`
- Create: `aic_engine/src/utils/homing_helper.cpp`

Extracted from Engine's `home_robot()` (lines 1651-1711).

- [ ] **Step 1: Implement homing_helper.hpp**

```cpp
#ifndef AIC_ENGINE_UTILS_HOMING_HELPER_HPP_
#define AIC_ENGINE_UTILS_HOMING_HELPER_HPP_

#include <map>
#include <string>

#include "aic_engine_interfaces/srv/reset_joints.hpp"
#include "controller_manager_msgs/srv/switch_controller.hpp"
#include "rclcpp/rclcpp.hpp"

namespace aic {

class HomingHelper {
public:
  HomingHelper(rclcpp::Node* node,
               const std::map<std::string, double>& home_joint_positions);

  bool home_robot();

private:
  bool switch_controllers(const std::vector<std::string>& activate,
                          const std::vector<std::string>& deactivate);
  bool reset_joints();

  template <typename FutureT>
  bool wait_for(const FutureT& future, double timeout_sec) const;

  rclcpp::Node* node_;
  rclcpp::Client<controller_manager_msgs::srv::SwitchController>::SharedPtr switch_ctrl_client_;
  rclcpp::Client<aic_engine_interfaces::srv::ResetJoints>::SharedPtr reset_joints_client_;
  std::shared_ptr<aic_engine_interfaces::srv::ResetJoints::Request> reset_request_;
};

}  // namespace aic

#endif  // AIC_ENGINE_UTILS_HOMING_HELPER_HPP_
```

- [ ] **Step 2: Implement homing_helper.cpp**

Port Engine's `home_robot()` logic:
1. Deactivate aic_controller via SwitchController service
2. Reset joints via ResetJoints service (pre-built request from home positions)
3. Sleep 0.5s for stabilization
4. Reactivate aic_controller

Use polling-based `wait_for` template (same as SceneSpawner).

- [ ] **Step 3: Verify build**

Run: `cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add aic_engine/src/utils/homing_helper.hpp aic_engine/src/utils/homing_helper.cpp
git commit -m "feat: add HomingHelper utility extracted from Engine homing logic"
```

---

### Task 9: AutoDataCollector Node

**Files:**
- Create: `aic_engine/src/auto_data_collector.hpp`
- Create: `aic_engine/src/auto_data_collector.cpp`
- Create: `aic_engine/src/auto_data_collector_main.cpp`

Main orchestrator node composing all components. Port from `auto_data_collector.py`.

- [ ] **Step 1: Implement auto_data_collector.hpp**

```cpp
#ifndef AIC_ENGINE_AUTO_DATA_COLLECTOR_HPP_
#define AIC_ENGINE_AUTO_DATA_COLLECTOR_HPP_

#include <map>
#include <memory>
#include <string>
#include <vector>

#include "aic_task_interfaces/action/insert_cable.hpp"
#include "completion_monitor.hpp"
#include "lifecycle_msgs/srv/change_state.hpp"
#include "lifecycle_msgs/srv/get_state.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"
#include "rosbag_manager.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "std_msgs/msg/string.hpp"
#include "trial_config_provider.hpp"
#include "utils/homing_helper.hpp"
#include "utils/scene_spawner.hpp"
#include "utils/tf_helper.hpp"

namespace aic {

class AutoDataCollector : public rclcpp::Node {
public:
  AutoDataCollector();
  void run_collection();

private:
  using InsertCableAction = aic_task_interfaces::action::InsertCable;

  bool activate_model();
  int get_model_state();
  std::optional<bool> send_insert_cable(const YAML::Node& task_config);
  CompletionResult check_completion(const YAML::Node& task_config);
  void record_failure(const std::string& reason);
  void print_summary();

  template <typename FutureT>
  bool poll_future(const FutureT& future, double timeout_sec);

  // Components
  std::unique_ptr<TrialConfigProvider> trial_provider_;
  std::unique_ptr<SceneSpawner> scene_spawner_;
  std::unique_ptr<HomingHelper> homing_helper_;
  std::unique_ptr<RosbagManager> rosbag_manager_;
  TfHelper tf_helper_;

  // ROS interfaces
  rclcpp_action::Client<InsertCableAction>::SharedPtr action_client_;
  rclcpp::Client<lifecycle_msgs::srv::GetState>::SharedPtr model_get_state_;
  rclcpp::Client<lifecycle_msgs::srv::ChangeState>::SharedPtr model_change_state_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr insertion_event_sub_;
  std::vector<rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr> camera_subs_;

  // State
  bool insertion_event_received_ = false;
  int target_episodes_;
  int max_attempts_;
  double task_timeout_sec_;
  double dist_threshold_;
  double orient_threshold_;
  int successful_ = 0;
  int failed_ = 0;
  std::map<std::string, int> fail_reasons_;
  std::vector<EpisodeRecord> episode_records_;
};

}  // namespace aic

#endif  // AIC_ENGINE_AUTO_DATA_COLLECTOR_HPP_
```

- [ ] **Step 2: Implement auto_data_collector.cpp**

Port the full Python `AutoDataCollector` class:
- Constructor: declare parameters, create TrialConfigProvider (static/dynamic), create SceneSpawner, HomingHelper, RosbagManager, TfHelper. Create InsertCable action client, insertion_event subscription, lifecycle clients, camera dummy subs.
- `run_collection()`: main loop — activate model, iterate episodes (get trial, spawn, record, action, check completion, stop, metadata, despawn, home, stats), save manifest, print summary.
- `activate_model()`: check state, configure if unconfigured, activate if inactive.
- `send_insert_cable()`: send goal, wait for result with timeout, cancel on timeout.
- `check_completion()`: check insertion_event + TF proximity.
- `poll_future()`: polling wait (50ms sleep loop).

- [ ] **Step 3: Implement auto_data_collector_main.cpp**

```cpp
#include <cstdlib>
#include <thread>

#include "auto_data_collector.hpp"
#include "rclcpp/rclcpp.hpp"

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);

  auto node = std::make_shared<aic::AutoDataCollector>();

  // Spin in background thread
  std::thread spin_thread([&node]() {
    rclcpp::executors::MultiThreadedExecutor executor;
    executor.add_node(node);
    executor.spin();
  });

  node->run_collection();

  rclcpp::shutdown();
  if (spin_thread.joinable()) {
    spin_thread.join();
  }
  return EXIT_SUCCESS;
}
```

- [ ] **Step 4: Verify build**

Run: `cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON`
Expected: Both `aic_engine` and `auto_data_collector` executables build.

- [ ] **Step 5: Commit**

```bash
git add aic_engine/src/auto_data_collector.hpp aic_engine/src/auto_data_collector.cpp aic_engine/src/auto_data_collector_main.cpp
git commit -m "feat: add AutoDataCollector C++ orchestrator node"
```

---

### Task 10: Collection Flow Integration Test

**Files:**
- Create: `aic_engine/test/test_collection_flow.cpp`

Port from `test_collection_flow.py`. Tests the AutoDataCollector orchestration with mocked components.

- [ ] **Step 1: Write the integration test**

Replace `test/test_collection_flow.cpp`. This test:
- Creates a StaticTrialProvider with real config
- Creates AutoDataCollector with mocked spawn/homing/rosbag (via dependency injection or by testing the TrialConfigProvider + CompletionMonitor flow separately)
- Verifies episode lifecycle ordering and trial round-robin

Since AutoDataCollector's ROS dependencies are hard to mock in C++ without a full DI framework, the integration test validates the TrialConfigProvider integration and state tracking:

```cpp
#include <gtest/gtest.h>
#include <cstdio>
#include <fstream>
#include <unistd.h>
#include "trial_config_provider.hpp"
#include "completion_monitor.hpp"
#include "rosbag_manager.hpp"

// Test the collection flow components work together correctly.
// This mirrors test_collection_flow.py but tests component interaction
// rather than the full AutoDataCollector node (which requires ROS).

static std::string write_flow_config() {
  const char* yaml = R"(
task_board_limits:
  nic_rail: {min_translation: -0.048, max_translation: 0.036}
  sc_rail: {min_translation: -0.06, max_translation: 0.055}
  mount_rail: {min_translation: -0.09425, max_translation: 0.09425}
trials:
  trial_1:
    scene:
      task_board:
        pose: {x: 0.15, y: -0.2, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.015, z: 0.042}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_0
        target_module_name: nic_card_mount_0
        time_limit: 180
  trial_2:
    scene:
      task_board:
        pose: {x: 0.15, y: -0.2, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.015, z: 0.045}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_0
        target_module_name: nic_card_mount_1
        time_limit: 180
robot:
  home_joint_positions:
    shoulder_pan_joint: -0.1597
    shoulder_lift_joint: -1.3542
    elbow_joint: -1.6648
    wrist_1_joint: -1.6933
    wrist_2_joint: 1.571
    wrist_3_joint: 1.411
)";
  char path[] = "/tmp/aic_flow_config_XXXXXX.yaml";
  int fd = mkstemps(path, 5);
  write(fd, yaml, strlen(yaml));
  close(fd);
  return std::string(path);
}

// Phase 1: Static trial mode - verify round-robin and episode tracking
TEST(CollectionFlow, StaticModeRoundRobinTrialTransition) {
  auto config_path = write_flow_config();
  aic::StaticTrialProvider provider(config_path);

  int target_episodes = 3;
  std::vector<std::string> trial_ids;

  for (int i = 0; i < target_episodes; ++i) {
    auto trial = provider.get_next_trial();
    trial_ids.push_back(trial["trial_id"].as<std::string>());
  }

  // Verify round-robin: trial_1 -> trial_2 -> trial_1
  ASSERT_EQ(trial_ids.size(), 3u);
  EXPECT_EQ(trial_ids[0], "trial_1");
  EXPECT_EQ(trial_ids[1], "trial_2");
  EXPECT_EQ(trial_ids[2], "trial_1");

  std::remove(config_path.c_str());
}

// Phase 2: Dynamic trial mode - verify randomized trials with base_trial tracking
TEST(CollectionFlow, DynamicModeRandomizedTrials) {
  auto config_path = write_flow_config();
  aic::DynamicTrialProvider provider(config_path, {"trial_1"}, 42);

  int target_episodes = 3;
  std::vector<YAML::Node> trials;

  for (int i = 0; i < target_episodes; ++i) {
    trials.push_back(provider.get_next_trial());
  }

  // Verify dynamic IDs
  for (const auto& trial : trials) {
    auto tid = trial["trial_id"].as<std::string>();
    EXPECT_TRUE(tid.find("dynamic_") == 0) << "Got: " << tid;
    EXPECT_EQ(trial["base_trial"].as<std::string>(), "trial_1");
  }

  // Verify poses differ between episodes
  bool any_differ = false;
  for (size_t i = 0; i < trials.size(); ++i) {
    for (size_t j = i + 1; j < trials.size(); ++j) {
      auto p1 = trials[i]["scene"]["task_board"]["pose"];
      auto p2 = trials[j]["scene"]["task_board"]["pose"];
      if (p1["x"].as<double>() != p2["x"].as<double>() ||
          p1["y"].as<double>() != p2["y"].as<double>() ||
          p1["yaw"].as<double>() != p2["yaw"].as<double>()) {
        any_differ = true;
      }
    }
  }
  EXPECT_TRUE(any_differ);

  std::remove(config_path.c_str());
}

// Verify manifest generation with episode records
TEST(CollectionFlow, ManifestTrackingWithMixedResults) {
  auto tmpdir = std::filesystem::temp_directory_path() / "aic_flow_test";
  std::filesystem::create_directories(tmpdir);

  aic::RosbagManager mgr(tmpdir.string());
  std::vector<aic::EpisodeRecord> records = {
    {"trial_1_ep001", "trial_1", true, (tmpdir / "trial_1_ep001").string()},
    {"trial_2_ep002", "trial_2", false, (tmpdir / "failed" / "trial_2_ep002").string()},
    {"trial_1_ep003", "trial_1", true, (tmpdir / "trial_1_ep003").string()},
  };

  auto manifest_path = mgr.save_manifest(records);
  std::ifstream f(manifest_path);
  auto data = nlohmann::json::parse(f);
  EXPECT_EQ(data["total_episodes"], 3);
  EXPECT_EQ(data["successful"], 2);
  EXPECT_EQ(data["failed"], 1);

  // Verify completion result logic
  EXPECT_TRUE(aic::is_success(aic::CompletionResult::SUCCESS));
  EXPECT_TRUE(aic::is_success(aic::CompletionResult::PARTIAL));
  EXPECT_FALSE(aic::is_success(aic::CompletionResult::TIMEOUT));

  std::filesystem::remove_all(tmpdir);
}
```

- [ ] **Step 2: Build and run tests**

Run:
```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select aic_engine --ctest-args -R test_collection_flow && colcon test-result --verbose
```
Expected: All collection flow tests pass.

- [ ] **Step 3: Commit**

```bash
git add aic_engine/test/test_collection_flow.cpp
git commit -m "test: add collection flow integration tests for C++ data collector"
```

---

### Task 11: Launch File Integration

**Files:**
- Modify: `aic_bringup/launch/aic_gz_bringup.launch.py`

Add `engine_type` parameter to select between `aic_engine` and `auto_data_collector`.

- [ ] **Step 1: Add engine_type LaunchArgument**

In `aic_gz_bringup.launch.py`, add a new `DeclareLaunchArgument` for `engine_type` near the other launch arguments:

```python
DeclareLaunchArgument(
    'engine_type',
    default_value='aic_engine',
    choices=['aic_engine', 'auto_data_collector'],
    description='Which engine executable to launch (aic_engine or auto_data_collector)',
),
```

Also add data-collection-specific arguments:

```python
DeclareLaunchArgument('trial_mode', default_value='static',
                      description='Trial mode: static or dynamic'),
DeclareLaunchArgument('target_episodes', default_value='10',
                      description='Number of successful episodes to collect'),
DeclareLaunchArgument('max_attempts', default_value='0',
                      description='Max attempts (0 = 3x target_episodes)'),
DeclareLaunchArgument('bag_output_dir', default_value='bags',
                      description='Output directory for rosbag recordings'),
DeclareLaunchArgument('task_timeout_sec', default_value='180.0',
                      description='Task execution timeout in seconds'),
DeclareLaunchArgument('trials', default_value="['']",
                      description='Trial names to collect (empty = all)'),
```

- [ ] **Step 2: Replace the aic_engine Node with engine_type-driven Node**

Find the existing `aic_engine` Node declaration in the launch file and replace it with:

```python
Node(
    package='aic_engine',
    executable=LaunchConfiguration('engine_type'),
    name=LaunchConfiguration('engine_type'),
    parameters=[
        {'config_file_path': LaunchConfiguration('config_file_path')},
        {'use_sim_time': True},
        # auto_data_collector specific (ignored by aic_engine)
        {'trial_mode': LaunchConfiguration('trial_mode')},
        {'target_episodes': LaunchConfiguration('target_episodes')},
        {'max_attempts': LaunchConfiguration('max_attempts')},
        {'bag_output_dir': LaunchConfiguration('bag_output_dir')},
        {'task_timeout_sec': LaunchConfiguration('task_timeout_sec')},
        {'trials': LaunchConfiguration('trials')},
    ],
    condition=IfCondition(LaunchConfiguration('start_aic_engine')),
    on_exit=shutdown_event_handler,
),
```

Note: The auto_data_collector-specific parameters are harmless when passed to aic_engine (undeclared params are ignored with default NodeOptions).

- [ ] **Step 3: Verify launch file loads**

Run:
```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_bringup aic_engine && ros2 launch aic_bringup aic_gz_bringup.launch.py --show-args 2>&1 | grep engine_type
```
Expected: Shows `engine_type` argument with choices `[aic_engine, auto_data_collector]`.

- [ ] **Step 4: Commit**

```bash
git add aic_bringup/launch/aic_gz_bringup.launch.py
git commit -m "feat: add engine_type launch parameter for engine/data-collector selection"
```

---

### Task 12: Run Full Test Suite and Final Verification

- [ ] **Step 1: Build everything**

```bash
cd /home/weed/ws_aic && colcon build --packages-select aic_engine --cmake-args -DBUILD_TESTING=ON
```
Expected: 0 errors, 0 warnings (or only pre-existing warnings).

- [ ] **Step 2: Run all tests**

```bash
cd /home/weed/ws_aic && colcon test --packages-select aic_engine && colcon test-result --verbose
```
Expected: All 5 test executables pass (test_completion_monitor, test_trial_config_provider, test_dynamic_trial_provider, test_rosbag_manager, test_collection_flow).

- [ ] **Step 3: Verify executables exist**

```bash
ls -la /home/weed/ws_aic/install/aic_engine/lib/aic_engine/
```
Expected: Both `aic_engine` and `auto_data_collector` executables present.

- [ ] **Step 4: Final commit with all files**

```bash
git add -A aic_engine/
git status
git commit -m "feat: complete C++ auto_data_collector with tests and launch integration"
```
