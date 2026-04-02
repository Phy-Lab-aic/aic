#ifndef AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_
#define AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_

#include <algorithm>
#include <cmath>
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

class SceneSpawner {
public:
  SceneSpawner(rclcpp::Node* node, TfHelper& tf_helper);

  bool spawn_entity(const std::string& name, const std::string& sdf_xml,
                    double x, double y, double z,
                    double roll, double pitch, double yaw);
  bool delete_entity(const std::string& name);
  void delete_all();
  bool spawn_scene(const YAML::Node& trial_config, const YAML::Node& root_config);
  void despawn_scene();

  const std::vector<std::string>& spawned_entities() const { return spawned_entities_; }

private:
  std::string process_xacro(const std::string& filepath,
                            const std::map<std::string, std::string>& params);
  std::map<std::string, std::string> build_task_board_xacro_params(
      const YAML::Node& tb_config, const YAML::Node& root_config);
  void tare_ft_sensor();

  template <typename FutureT>
  bool wait_for(const FutureT& future, double timeout_sec) const {
    auto start = std::chrono::steady_clock::now();
    while (future.wait_for(std::chrono::milliseconds(50)) != std::future_status::ready) {
      if (std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() > timeout_sec) {
        return false;
      }
    }
    return true;
  }

  rclcpp::Node* node_;
  TfHelper& tf_helper_;
  rclcpp::Client<simulation_interfaces::srv::SpawnEntity>::SharedPtr spawn_client_;
  rclcpp::Client<simulation_interfaces::srv::DeleteEntity>::SharedPtr delete_client_;
  rclcpp::Client<std_srvs::srv::Trigger>::SharedPtr tare_ft_client_;
  std::string description_share_;
  std::vector<std::string> spawned_entities_;
};

}  // namespace aic

#endif  // AIC_ENGINE_UTILS_SCENE_SPAWNER_HPP_
