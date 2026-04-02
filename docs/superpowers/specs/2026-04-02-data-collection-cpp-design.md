# aic_data_collection C++ Conversion Design

## Overview

Convert `aic_data_collection` Python package to C++ and integrate it into the `aic_engine` package as a separate executable (`auto_data_collector`). Add an `engine_type` launch parameter to `aic_gz_bringup.launch.py` so users can switch between `aic_engine` and `auto_data_collector` at launch time.

## Goals

1. C++ `auto_data_collector` executable in `aic_engine` package
2. Reuse existing Engine functionality via extracted shared utilities
3. Full GTest coverage matching existing Python test suite
4. Launch parameter `engine_type` to select engine at runtime

## Architecture

```
aic_engine (package)
├── executables
│   ├── aic_engine              (existing, unchanged behavior)
│   └── auto_data_collector     (new)
│
├── shared utils (extracted from Engine, used by both)
│   ├── SceneSpawner            - Gazebo spawn/despawn, xacro processing
│   ├── HomingHelper            - controller switch + joint reset
│   └── TfHelper                - TF lookup utility
│
├── data collection components (new)
│   ├── TrialConfigProvider     - Static/Dynamic trial loading
│   ├── CompletionMonitor       - TF proximity + insertion_event check
│   └── RosbagManager           - subprocess-based ros2 bag record
│
└── launch integration
    └── engine_type parameter in aic_gz_bringup.launch.py
```

### Principle

- Engine existing behavior stays 100% intact (utility extraction only, no logic changes)
- AutoDataCollector is an independent ROS node (separate process from Engine)
- Launch file `engine_type` parameter determines which executable to start

## Shared Utilities

### SceneSpawner

Extracted from Engine's `spawn_entity()`, `delete_entity()`, xacro processing, and rail clamping logic.

```cpp
class SceneSpawner {
public:
  SceneSpawner(rclcpp::Node* node);

  bool spawn_entity(const std::string& name, const std::string& filepath,
                    double x, double y, double z,
                    double roll, double pitch, double yaw,
                    std::vector<std::string>& spawned_entities);
  bool delete_entity(const std::string& name);
  void delete_all(std::vector<std::string>& spawned_entities);

  bool spawn_scene(const YAML::Node& scene_config,
                   std::vector<std::string>& spawned_entities);

private:
  std::string process_xacro(const std::string& filepath,
                            const std::map<std::string, std::string>& params);
  rclcpp::Client<SpawnEntitySrv>::SharedPtr spawn_client_;
  rclcpp::Client<DeleteEntitySrv>::SharedPtr delete_client_;
  rclcpp::Client<TriggerSrv>::SharedPtr tare_ft_client_;
};
```

### HomingHelper

Extracted from Engine's `home_robot()`.

```cpp
class HomingHelper {
public:
  HomingHelper(rclcpp::Node* node, const YAML::Node& robot_config);
  bool home_robot();

private:
  rclcpp::Client<SwitchControllerSrv>::SharedPtr switch_ctrl_client_;
  rclcpp::Client<ResetJointsSrv>::SharedPtr reset_joints_client_;
  ResetJointsSrv::Request::SharedPtr reset_request_;
};
```

### TfHelper

TF lookup utility.

```cpp
class TfHelper {
public:
  TfHelper(rclcpp::Node* node);
  std::optional<geometry_msgs::msg::TransformStamped>
    lookup(const std::string& target, const std::string& source,
           rclcpp::Duration timeout = rclcpp::Duration(1, 0));

private:
  std::shared_ptr<tf2_ros::Buffer> tf_buffer_;
  std::shared_ptr<tf2_ros::TransformListener> tf_listener_;
};
```

### Engine Refactoring

Engine class replaces inline spawn/homing/TF logic with calls to these utilities. Behavior remains identical. Engine instantiates SceneSpawner, HomingHelper, TfHelper in its constructor and delegates to them.

## Data Collection Components

### TrialConfigProvider

```cpp
class TrialConfigProvider {
public:
  virtual ~TrialConfigProvider() = default;
  virtual YAML::Node get_next_trial() = 0;
  virtual size_t trial_count() const = 0;
  virtual std::vector<double> home_joint_positions() const = 0;
};

class StaticTrialProvider : public TrialConfigProvider {
  // Round-robin, deterministic, optional trial name filtering
};

class DynamicTrialProvider : public TrialConfigProvider {
  // Randomized variants per episode
  // Edge-biased beta(0.5, 0.5) distribution for rail translations
  // Uniform +/-0.002 for gripper_offset perturbation
  // std::mt19937 with seed tracking per episode
};
```

### CompletionMonitor

```cpp
class CompletionMonitor {
public:
  enum class Result { SUCCESS, PARTIAL, TIMEOUT, ACTION_FAILED };

  CompletionMonitor(rclcpp::Node* node, TfHelper& tf_helper);

  void on_insertion_event(const std_msgs::msg::String::SharedPtr msg);
  bool has_insertion_event() const;
  void reset();

  static bool check_tf_completion(
    const Eigen::Vector3d& plug_pos, const Eigen::Vector3d& port_pos,
    const Eigen::Quaterniond& plug_quat, const Eigen::Quaterniond& port_quat,
    double distance_threshold = 0.005,
    double orientation_threshold = 0.1);
};
```

### RosbagManager

```cpp
class RosbagManager {
public:
  RosbagManager(const std::string& output_dir);

  bool start_recording(const std::string& episode_id,
                       const std::vector<std::string>& topics);
  bool stop_recording();
  void move_to_failed(const std::string& episode_id);

  void save_metadata(const std::string& episode_id,
                     const YAML::Node& metadata);
  void save_manifest(const std::vector<EpisodeRecord>& episodes);

private:
  pid_t recorder_pid_ = -1;
  std::string output_dir_;
};
```

### AutoDataCollector (Main Node)

```cpp
class AutoDataCollector : public rclcpp::Node {
public:
  AutoDataCollector();
  void run_collection();

private:
  std::unique_ptr<TrialConfigProvider> trial_provider_;
  std::unique_ptr<SceneSpawner> scene_spawner_;
  std::unique_ptr<HomingHelper> homing_helper_;
  std::unique_ptr<CompletionMonitor> completion_monitor_;
  std::unique_ptr<RosbagManager> rosbag_manager_;
  TfHelper tf_helper_;

  rclcpp_action::Client<InsertCableAction>::SharedPtr action_client_;
  rclcpp::Client<GetState>::SharedPtr model_get_state_;
  rclcpp::Client<ChangeState>::SharedPtr model_change_state_;

  int target_episodes_, max_attempts_;
  double task_timeout_sec_;
};
```

**Execution flow**: get_trial -> spawn -> record -> action -> monitor -> stop -> metadata -> despawn -> home -> repeat

## Launch Integration

### engine_type parameter in aic_gz_bringup.launch.py

```python
DeclareLaunchArgument('engine_type', default_value='aic_engine',
                      choices=['aic_engine', 'auto_data_collector'],
                      description='Which engine executable to launch')

Node(
    package='aic_engine',
    executable=LaunchConfiguration('engine_type'),
    parameters=[...],
    condition=IfCondition(LaunchConfiguration('start_aic_engine'))
)
```

### Parameters

**auto_data_collector only:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `trial_mode` | `"static"` | static or dynamic |
| `target_episodes` | `10` | Successful episodes to collect |
| `max_attempts` | `0` (=3x target) | Maximum attempts |
| `bag_output_dir` | `"bags"` | Rosbag output path |
| `task_timeout_sec` | `180.0` | Task timeout |
| `trials` | `[]` | Trial name filter |

**Shared:**

| Parameter | Description |
|-----------|-------------|
| `config_file` | Trial config YAML path |
| `use_sim_time` | Use simulation time |

### Usage

```bash
# Default engine
ros2 launch aic_bringup aic_gz_bringup.launch.py config_file:=config.yaml

# Data collector
ros2 launch aic_bringup aic_gz_bringup.launch.py \
  engine_type:=auto_data_collector \
  config_file:=config.yaml \
  target_episodes:=50 \
  trial_mode:=dynamic
```

## Testing

### Unit Tests (GTest + GMock)

| Test File | Target | Coverage |
|-----------|--------|----------|
| `test_trial_config_provider.cpp` | StaticTrialProvider | round-robin order, trial filtering, home positions |
| `test_dynamic_trial_provider.cpp` | DynamicTrialProvider | randomization range, beta distribution, seed uniqueness, gripper offset perturbation |
| `test_completion_monitor.cpp` | CompletionMonitor | distance/orientation thresholds, boundary values, Result enum |
| `test_rosbag_manager.cpp` | RosbagManager | bag path construction, metadata YAML, manifest JSON, failed directory move |

### Integration Tests (launch_testing + GTest)

| Test File | Target | Coverage |
|-----------|--------|----------|
| `test_collection_flow.cpp` | AutoDataCollector | Episode lifecycle (spawn -> record -> action -> stop -> despawn -> home), static/dynamic mode transition |

### Mock Strategy

Components with ROS dependencies (SceneSpawner, HomingHelper) use interfaces for mock injection:

```cpp
class ISceneSpawner {
public:
  virtual ~ISceneSpawner() = default;
  virtual bool spawn_scene(const YAML::Node& config,
                           std::vector<std::string>& entities) = 0;
  virtual void delete_all(std::vector<std::string>& entities) = 0;
};
```

Pure logic components (TrialConfigProvider, CompletionMonitor) are tested directly without mocks.

## File Layout

```
aic_engine/
├── src/
│   ├── aic_engine.cpp/hpp              # existing (refactored to use utils)
│   ├── main.cpp                        # existing entry point
│   ├── auto_data_collector.cpp/hpp     # new orchestrator node
│   ├── auto_data_collector_main.cpp    # new entry point
│   ├── utils/
│   │   ├── scene_spawner.cpp/hpp
│   │   ├── homing_helper.cpp/hpp
│   │   └── tf_helper.cpp/hpp
│   ├── rosbag_manager.cpp/hpp
│   ├── trial_config_provider.cpp/hpp
│   └── completion_monitor.cpp/hpp
├── test/
│   ├── test_trial_config_provider.cpp
│   ├── test_dynamic_trial_provider.cpp
│   ├── test_completion_monitor.cpp
│   ├── test_rosbag_manager.cpp
│   └── test_collection_flow.cpp
├── CMakeLists.txt                      # updated with new targets
└── package.xml                         # updated with new deps (Eigen3, nlohmann_json)
```

## Dependencies Added

- `Eigen3` - vector/quaternion math for CompletionMonitor
- `nlohmann_json` - manifest JSON writing
- `yaml-cpp` - already present, used for metadata

## Out of Scope

- Python `aic_data_collection` package removal (kept for reference)
- aic_engine scoring integration in data collector (uses separate rosbag approach)
- Multi-robot parallel collection
