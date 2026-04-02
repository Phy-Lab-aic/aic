#include "auto_data_collector.hpp"

#include <chrono>
#include <iomanip>
#include <sstream>

#include "aic_task_interfaces/msg/task.hpp"
#include "lifecycle_msgs/msg/state.hpp"
#include "lifecycle_msgs/msg/transition.hpp"

namespace aic {

AutoDataCollector::AutoDataCollector()
    : rclcpp::Node("auto_data_collector") {
  // Declare parameters
  declare_parameter("config_file", std::string(""));
  declare_parameter("trial_mode", std::string("static"));
  declare_parameter("trials", std::vector<std::string>{""});
  declare_parameter("target_episodes", 10);
  declare_parameter("max_attempts", 0);
  declare_parameter("task_timeout_sec", 180.0);
  declare_parameter("bag_output_dir", std::string("bags"));
  declare_parameter("completion_distance_threshold", 0.005);
  declare_parameter("completion_orientation_threshold", 0.1);

  // Read parameters
  std::string config_file = get_parameter("config_file").as_string();
  if (config_file.empty()) {
    // Try alternate parameter name used by aic_engine
    declare_parameter("config_file_path", std::string(""));
    config_file = get_parameter("config_file_path").as_string();
  }
  if (config_file.empty()) {
    RCLCPP_FATAL(get_logger(), "config_file parameter is required");
    throw std::runtime_error("config_file parameter is required");
  }

  auto trial_names_param = get_parameter("trials").as_string_array();
  std::vector<std::string> trial_names;
  for (const auto& t : trial_names_param) {
    if (!t.empty()) trial_names.push_back(t);
  }

  target_episodes_ = get_parameter("target_episodes").as_int();
  int max_att = get_parameter("max_attempts").as_int();
  max_attempts_ = max_att > 0 ? max_att : target_episodes_ * 3;
  task_timeout_sec_ = get_parameter("task_timeout_sec").as_double();
  std::string bag_dir = get_parameter("bag_output_dir").as_string();
  dist_threshold_ = get_parameter("completion_distance_threshold").as_double();
  orient_threshold_ = get_parameter("completion_orientation_threshold").as_double();

  // Load root config for spawn_scene
  root_config_ = YAML::LoadFile(config_file);

  // Initialize trial provider
  std::string trial_mode = get_parameter("trial_mode").as_string();
  if (trial_mode == "dynamic") {
    trial_provider_ = std::make_unique<DynamicTrialProvider>(config_file, trial_names);
  } else {
    trial_provider_ = std::make_unique<StaticTrialProvider>(config_file, trial_names);
  }

  // Initialize components
  tf_helper_ = std::make_unique<TfHelper>(this);
  scene_spawner_ = std::make_unique<SceneSpawner>(this, *tf_helper_);
  homing_helper_ = std::make_unique<HomingHelper>(this, trial_provider_->home_joint_positions());
  rosbag_manager_ = std::make_unique<RosbagManager>(bag_dir);

  // Camera dummy subscribers (activates lazy bridge)
  for (const auto& topic : {"/left_camera/image", "/center_camera/image", "/right_camera/image"}) {
    auto sub = create_subscription<sensor_msgs::msg::Image>(
        topic, 1, [](const sensor_msgs::msg::Image::SharedPtr) {});
    camera_subs_.push_back(sub);
  }
  RCLCPP_INFO(get_logger(), "Camera dummy subscribers created (lazy bridge activated)");

  // InsertCable action client
  action_client_ = rclcpp_action::create_client<InsertCableAction>(this, "/insert_cable");

  // Insertion event subscription
  insertion_event_sub_ = create_subscription<std_msgs::msg::String>(
      "/scoring/insertion_event", 10,
      [this](const std_msgs::msg::String::SharedPtr msg) {
        insertion_event_received_ = true;
        RCLCPP_INFO(get_logger(), "Insertion event received: %s", msg->data.c_str());
      });

  // aic_model lifecycle clients
  model_get_state_ = create_client<lifecycle_msgs::srv::GetState>("/aic_model/get_state");
  model_change_state_ = create_client<lifecycle_msgs::srv::ChangeState>("/aic_model/change_state");
}

int AutoDataCollector::get_model_state() {
  if (!model_get_state_->wait_for_service(std::chrono::seconds(10))) {
    return -1;
  }
  auto req = std::make_shared<lifecycle_msgs::srv::GetState::Request>();
  auto future = model_get_state_->async_send_request(req);
  if (!poll_future(future, 10.0)) return -1;
  auto response = future.get();
  if (!response) return -1;
  return response->current_state.id;
}

bool AutoDataCollector::activate_model() {
  if (!model_change_state_->wait_for_service(std::chrono::seconds(30))) {
    RCLCPP_ERROR(get_logger(), "aic_model lifecycle service not available");
    return false;
  }

  int current_state = get_model_state();
  if (current_state == lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE) {
    RCLCPP_INFO(get_logger(), "aic_model already active");
    return true;
  }

  if (current_state == lifecycle_msgs::msg::State::PRIMARY_STATE_UNCONFIGURED ||
      current_state == lifecycle_msgs::msg::State::PRIMARY_STATE_UNKNOWN) {
    auto req = std::make_shared<lifecycle_msgs::srv::ChangeState::Request>();
    req->transition.id = lifecycle_msgs::msg::Transition::TRANSITION_CONFIGURE;
    auto future = model_change_state_->async_send_request(req);
    if (!poll_future(future, 30.0) || !future.get()->success) {
      RCLCPP_ERROR(get_logger(), "Failed to configure aic_model");
      return false;
    }
  }

  current_state = get_model_state();
  if (current_state == lifecycle_msgs::msg::State::PRIMARY_STATE_INACTIVE) {
    auto req = std::make_shared<lifecycle_msgs::srv::ChangeState::Request>();
    req->transition.id = lifecycle_msgs::msg::Transition::TRANSITION_ACTIVATE;
    auto future = model_change_state_->async_send_request(req);
    if (!poll_future(future, 30.0) || !future.get()->success) {
      RCLCPP_ERROR(get_logger(), "Failed to activate aic_model");
      return false;
    }
  }

  RCLCPP_INFO(get_logger(), "aic_model activated");
  return true;
}

std::optional<bool> AutoDataCollector::send_insert_cable(const YAML::Node& task_config) {
  if (!action_client_->wait_for_action_server(std::chrono::seconds(10))) {
    RCLCPP_ERROR(get_logger(), "InsertCable action server not available");
    return false;
  }

  auto goal = InsertCableAction::Goal();
  goal.task.id = task_config["cable_name"].as<std::string>("task_1");
  goal.task.cable_type = task_config["cable_type"].as<std::string>();
  goal.task.cable_name = task_config["cable_name"].as<std::string>();
  goal.task.plug_type = task_config["plug_type"].as<std::string>();
  goal.task.plug_name = task_config["plug_name"].as<std::string>();
  goal.task.port_type = task_config["port_type"].as<std::string>();
  goal.task.port_name = task_config["port_name"].as<std::string>();
  goal.task.target_module_name = task_config["target_module_name"].as<std::string>();
  goal.task.time_limit = static_cast<uint64_t>(task_timeout_sec_);

  auto send_goal_future = action_client_->async_send_goal(goal);
  if (!poll_future(send_goal_future, 10.0)) return std::nullopt;
  auto goal_handle = send_goal_future.get();
  if (!goal_handle) {
    RCLCPP_ERROR(get_logger(), "InsertCable goal rejected");
    return false;
  }

  auto result_future = action_client_->async_get_result(goal_handle);
  if (!poll_future(result_future, task_timeout_sec_)) {
    RCLCPP_WARN(get_logger(), "InsertCable action timed out, cancelling");
    action_client_->async_cancel_goal(goal_handle);
    return std::nullopt;
  }
  auto result = result_future.get();
  return result.result ? std::optional<bool>(result.result->success) : std::optional<bool>(false);
}

CompletionResult AutoDataCollector::check_completion(const YAML::Node& task_config) {
  if (!insertion_event_received_) {
    return CompletionResult::TIMEOUT;
  }

  std::string plug_frame = task_config["cable_name"].as<std::string>() + "/" +
                           task_config["plug_name"].as<std::string>() + "_link";
  std::string port_frame = "task_board/" +
                           task_config["target_module_name"].as<std::string>() + "/" +
                           task_config["port_name"].as<std::string>() + "_link";

  auto plug_tf = tf_helper_->lookup("base_link", plug_frame);
  auto port_tf = tf_helper_->lookup("base_link", port_frame);

  if (!plug_tf || !port_tf) {
    RCLCPP_WARN(get_logger(), "TF lookup failed, treating as PARTIAL");
    return CompletionResult::PARTIAL;
  }

  Eigen::Vector3d plug_pos(plug_tf->transform.translation.x,
                           plug_tf->transform.translation.y,
                           plug_tf->transform.translation.z);
  Eigen::Vector3d port_pos(port_tf->transform.translation.x,
                           port_tf->transform.translation.y,
                           port_tf->transform.translation.z);
  Eigen::Quaterniond plug_quat(plug_tf->transform.rotation.w,
                               plug_tf->transform.rotation.x,
                               plug_tf->transform.rotation.y,
                               plug_tf->transform.rotation.z);
  Eigen::Quaterniond port_quat(port_tf->transform.rotation.w,
                               port_tf->transform.rotation.x,
                               port_tf->transform.rotation.y,
                               port_tf->transform.rotation.z);

  if (check_tf_completion(plug_pos, port_pos, plug_quat, port_quat,
                          dist_threshold_, orient_threshold_)) {
    return CompletionResult::SUCCESS;
  }
  RCLCPP_WARN(get_logger(), "insertion_event received but TF check failed");
  return CompletionResult::PARTIAL;
}

void AutoDataCollector::record_failure(const std::string& reason) {
  failed_++;
  fail_reasons_[reason]++;
}

void AutoDataCollector::print_summary() {
  int total = successful_ + failed_;
  RCLCPP_INFO(get_logger(), "\n==================================================");
  RCLCPP_INFO(get_logger(), "=== Data Collection Summary ===");
  RCLCPP_INFO(get_logger(), "Total attempts: %d", total);
  std::string target_msg = successful_ >= target_episodes_ ? "target reached" : "target NOT reached";
  RCLCPP_INFO(get_logger(), "Successful episodes: %d / %d (%s)",
              successful_, target_episodes_, target_msg.c_str());
  RCLCPP_INFO(get_logger(), "Failed episodes: %d", failed_);
  for (const auto& [reason, count] : fail_reasons_) {
    RCLCPP_INFO(get_logger(), "  - %s: %d", reason.c_str(), count);
  }
}

void AutoDataCollector::run_collection() {
  RCLCPP_INFO(get_logger(), "Starting collection: target=%d, max_attempts=%d",
              target_episodes_, max_attempts_);

  if (!activate_model()) {
    RCLCPP_FATAL(get_logger(), "Cannot activate aic_model, aborting");
    return;
  }

  int attempt = 0;
  while (successful_ < target_episodes_ && attempt < max_attempts_) {
    attempt++;
    auto trial = trial_provider_->get_next_trial();
    std::string trial_id = trial["trial_id"].as<std::string>();

    auto now = std::chrono::system_clock::now();
    auto time_t_val = std::chrono::system_clock::to_time_t(now);
    struct tm tm_buf;
    localtime_r(&time_t_val, &tm_buf);
    std::ostringstream ts;
    ts << std::put_time(&tm_buf, "%Y%m%d_%H%M%S");
    std::string episode_id = trial_id + "_" + ts.str();

    RCLCPP_INFO(get_logger(), "\n==================================================");
    RCLCPP_INFO(get_logger(), "Episode %d/%d (%d/%d success) - %s",
                attempt, max_attempts_, successful_, target_episodes_, trial_id.c_str());

    // Reset completion state
    insertion_event_received_ = false;

    // 1. Spawn scene
    if (!scene_spawner_->spawn_scene(trial, root_config_)) {
      record_failure("spawn_failed");
      scene_spawner_->despawn_scene();
      homing_helper_->home_robot();
      continue;
    }

    // 2. Start recording
    rosbag_manager_->start_recording(episode_id);

    // 3. Execute task
    auto tasks = trial["tasks"];
    auto first_task_it = tasks.begin();
    auto task_config = first_task_it->second;
    auto action_result = send_insert_cable(task_config);

    // 4. Check completion
    CompletionResult completion;
    if (!action_result.has_value()) {
      completion = CompletionResult::TIMEOUT;
    } else if (!action_result.value()) {
      completion = CompletionResult::ACTION_FAILED;
    } else {
      completion = check_completion(task_config);
    }

    // 5. Stop recording
    bool success = is_success(completion);
    std::string bag_path = rosbag_manager_->stop_recording(success);
    RCLCPP_INFO(get_logger(), "Bag saved: %s (result: %d)", bag_path.c_str(),
                static_cast<int>(completion));

    // 6. Save metadata
    rosbag_manager_->save_metadata(episode_id, trial, success, bag_path);

    // Track episode
    episode_records_.push_back({episode_id, trial_id, success, bag_path});

    // 7. Update stats
    if (success) {
      successful_++;
    } else {
      std::string reason;
      switch (completion) {
        case CompletionResult::TIMEOUT: reason = "timeout"; break;
        case CompletionResult::ACTION_FAILED: reason = "action_failed"; break;
        default: reason = "unknown"; break;
      }
      record_failure(reason);
    }

    // 8. Despawn + home
    scene_spawner_->despawn_scene();
    if (!homing_helper_->home_robot()) {
      RCLCPP_ERROR(get_logger(), "Homing failed!");
    }
  }

  // Save manifest
  if (!episode_records_.empty()) {
    auto manifest_path = rosbag_manager_->save_manifest(episode_records_);
    RCLCPP_INFO(get_logger(), "Manifest saved: %s", manifest_path.c_str());
  }

  print_summary();
}

}  // namespace aic
