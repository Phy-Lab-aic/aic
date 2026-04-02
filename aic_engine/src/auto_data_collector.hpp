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
  bool poll_future(const FutureT& future, double timeout_sec) {
    auto start = std::chrono::steady_clock::now();
    while (!future.valid() ||
           future.wait_for(std::chrono::milliseconds(50)) != std::future_status::ready) {
      if (std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() > timeout_sec) {
        return false;
      }
    }
    return true;
  }

  // Components
  std::unique_ptr<TrialConfigProvider> trial_provider_;
  std::unique_ptr<SceneSpawner> scene_spawner_;
  std::unique_ptr<HomingHelper> homing_helper_;
  std::unique_ptr<RosbagManager> rosbag_manager_;
  std::unique_ptr<TfHelper> tf_helper_;

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

  // Config (stored for spawn_scene root_config)
  YAML::Node root_config_;
};

}  // namespace aic

#endif  // AIC_ENGINE_AUTO_DATA_COLLECTOR_HPP_
