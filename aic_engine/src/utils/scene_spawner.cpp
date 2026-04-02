#include "utils/scene_spawner.hpp"

#include <cstdio>
#include <sstream>
#include <thread>

#include "ament_index_cpp/get_package_share_directory.hpp"

namespace aic {

SceneSpawner::SceneSpawner(rclcpp::Node* node, TfHelper& tf_helper)
    : node_(node), tf_helper_(tf_helper) {
  spawn_client_ = node_->create_client<simulation_interfaces::srv::SpawnEntity>(
      "/gz_server/spawn_entity");
  delete_client_ = node_->create_client<simulation_interfaces::srv::DeleteEntity>(
      "/gz_server/delete_entity");
  tare_ft_client_ = node_->create_client<std_srvs::srv::Trigger>(
      "/aic_controller/tare_force_torque_sensor");
  description_share_ = ament_index_cpp::get_package_share_directory("aic_description");
}

std::string SceneSpawner::process_xacro(
    const std::string& filepath,
    const std::map<std::string, std::string>& params) {
  std::string xacro_path = description_share_ + filepath;
  std::stringstream cmd;
  cmd << "xacro " << xacro_path;
  for (const auto& [k, v] : params) {
    cmd << " " << k << ":=" << v;
  }

  FILE* pipe = popen(cmd.str().c_str(), "r");
  if (!pipe) {
    RCLCPP_ERROR(node_->get_logger(), "Failed to execute xacro command");
    return "";
  }

  std::stringstream result;
  char buffer[256];
  while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
    result << buffer;
  }
  int ret = pclose(pipe);
  if (ret != 0) {
    RCLCPP_ERROR(node_->get_logger(), "xacro command failed with code %d", ret);
    return "";
  }
  return result.str();
}

std::map<std::string, std::string> SceneSpawner::build_task_board_xacro_params(
    const YAML::Node& tb_config, const YAML::Node& root_config) {
  std::map<std::string, std::string> params;

  double nic_min = -0.048, nic_max = 0.036;
  double sc_min = -0.055, sc_max = 0.055;
  double mount_min = -0.09625, mount_max = 0.09625;

  if (root_config["task_board_limits"]) {
    const auto& limits = root_config["task_board_limits"];
    if (limits["nic_rail"]) {
      nic_min = limits["nic_rail"]["min_translation"].as<double>();
      nic_max = limits["nic_rail"]["max_translation"].as<double>();
    }
    if (limits["sc_rail"]) {
      sc_min = limits["sc_rail"]["min_translation"].as<double>();
      sc_max = limits["sc_rail"]["max_translation"].as<double>();
    }
    if (limits["mount_rail"]) {
      mount_min = limits["mount_rail"]["min_translation"].as<double>();
      mount_max = limits["mount_rail"]["max_translation"].as<double>();
    }
  }

  // NIC rails 0-4
  for (int i = 0; i < 5; ++i) {
    std::string rail_key = "nic_rail_" + std::to_string(i);
    std::string mount_prefix = "nic_card_mount_" + std::to_string(i);
    if (tb_config[rail_key] && tb_config[rail_key]["entity_present"].as<bool>(false)) {
      params[mount_prefix + "_present"] = "true";
      if (tb_config[rail_key]["entity_pose"]) {
        const auto& pose = tb_config[rail_key]["entity_pose"];
        double trans = std::clamp(pose["translation"].as<double>(), nic_min, nic_max);
        params[mount_prefix + "_translation"] = std::to_string(trans);
        params[mount_prefix + "_roll"] = std::to_string(pose["roll"].as<double>(0.0));
        params[mount_prefix + "_pitch"] = std::to_string(pose["pitch"].as<double>(0.0));
        params[mount_prefix + "_yaw"] = std::to_string(pose["yaw"].as<double>(0.0));
      }
    } else {
      params[mount_prefix + "_present"] = "false";
    }
  }

  // SC rails 0-1
  for (int i = 0; i < 2; ++i) {
    std::string rail_key = "sc_rail_" + std::to_string(i);
    std::string port_prefix = "sc_port_" + std::to_string(i);
    if (tb_config[rail_key] && tb_config[rail_key]["entity_present"].as<bool>(false)) {
      params[port_prefix + "_present"] = "true";
      if (tb_config[rail_key]["entity_pose"]) {
        const auto& pose = tb_config[rail_key]["entity_pose"];
        double trans = std::clamp(pose["translation"].as<double>(), sc_min, sc_max);
        params[port_prefix + "_translation"] = std::to_string(trans);
        params[port_prefix + "_roll"] = std::to_string(pose["roll"].as<double>(0.0));
        params[port_prefix + "_pitch"] = std::to_string(pose["pitch"].as<double>(0.0));
        params[port_prefix + "_yaw"] = std::to_string(pose["yaw"].as<double>(0.0));
      }
    } else {
      params[port_prefix + "_present"] = "false";
    }
  }

  // Mount rails (lc, sfp, sc) 0-1
  for (const auto& rail_type : {"lc_mount", "sfp_mount", "sc_mount"}) {
    for (int i = 0; i < 2; ++i) {
      std::string rail_key = std::string(rail_type) + "_rail_" + std::to_string(i);
      if (tb_config[rail_key] && tb_config[rail_key]["entity_present"].as<bool>(false)) {
        params[rail_key + "_present"] = "true";
        if (tb_config[rail_key]["entity_pose"]) {
          const auto& pose = tb_config[rail_key]["entity_pose"];
          double trans = std::clamp(pose["translation"].as<double>(), mount_min, mount_max);
          params[rail_key + "_translation"] = std::to_string(trans);
          params[rail_key + "_roll"] = std::to_string(pose["roll"].as<double>(0.0));
          params[rail_key + "_pitch"] = std::to_string(pose["pitch"].as<double>(0.0));
          params[rail_key + "_yaw"] = std::to_string(pose["yaw"].as<double>(0.0));
        }
      } else {
        params[rail_key + "_present"] = "false";
      }
    }
  }

  return params;
}

void SceneSpawner::tare_ft_sensor() {
  if (!tare_ft_client_->wait_for_service(std::chrono::seconds(5))) {
    RCLCPP_WARN(node_->get_logger(), "Tare FT service not available, skipping");
    return;
  }
  auto req = std::make_shared<std_srvs::srv::Trigger::Request>();
  auto future = tare_ft_client_->async_send_request(req);
  wait_for(future, 10.0);
}

bool SceneSpawner::spawn_entity(
    const std::string& name, const std::string& sdf_xml,
    double x, double y, double z,
    double roll, double pitch, double yaw) {
  auto request = std::make_shared<simulation_interfaces::srv::SpawnEntity::Request>();
  request->name = name;
  request->resource_string = sdf_xml;
  request->uri = "";
  request->allow_renaming = false;
  request->entity_namespace = "";
  request->initial_pose.header.frame_id = "world";
  request->initial_pose.pose.position.x = x;
  request->initial_pose.pose.position.y = y;
  request->initial_pose.pose.position.z = z;

  double cy = std::cos(yaw * 0.5), sy = std::sin(yaw * 0.5);
  double cp = std::cos(pitch * 0.5), sp = std::sin(pitch * 0.5);
  double cr = std::cos(roll * 0.5), sr = std::sin(roll * 0.5);
  request->initial_pose.pose.orientation.w = cr * cp * cy + sr * sp * sy;
  request->initial_pose.pose.orientation.x = sr * cp * cy - cr * sp * sy;
  request->initial_pose.pose.orientation.y = cr * sp * cy + sr * cp * sy;
  request->initial_pose.pose.orientation.z = cr * cp * sy - sr * sp * cy;

  auto future = spawn_client_->async_send_request(request);
  if (!wait_for(future, 30.0)) {
    RCLCPP_ERROR(node_->get_logger(), "Spawn '%s' timed out", name.c_str());
    return false;
  }
  auto response = future.get();
  if (!response || response->result.result != 1) {
    RCLCPP_ERROR(node_->get_logger(), "Spawn '%s' failed", name.c_str());
    return false;
  }
  spawned_entities_.push_back(name);
  RCLCPP_INFO(node_->get_logger(), "Spawned '%s'", name.c_str());
  return true;
}

bool SceneSpawner::delete_entity(const std::string& name) {
  auto request = std::make_shared<simulation_interfaces::srv::DeleteEntity::Request>();
  request->entity = name;
  auto future = delete_client_->async_send_request(request);
  if (!wait_for(future, 10.0)) {
    RCLCPP_ERROR(node_->get_logger(), "Delete '%s' timed out", name.c_str());
    return false;
  }
  auto response = future.get();
  if (!response || response->result.result != 1) {
    RCLCPP_ERROR(node_->get_logger(), "Delete '%s' failed", name.c_str());
    return false;
  }
  RCLCPP_INFO(node_->get_logger(), "Deleted '%s'", name.c_str());
  return true;
}

void SceneSpawner::delete_all() {
  for (const auto& name : spawned_entities_) {
    delete_entity(name);
  }
  spawned_entities_.clear();
}

bool SceneSpawner::spawn_scene(const YAML::Node& trial_config, const YAML::Node& root_config) {
  if (!spawn_client_->wait_for_service(std::chrono::seconds(30))) {
    RCLCPP_ERROR(node_->get_logger(), "Spawn service not available");
    return false;
  }

  const auto& scene = trial_config["scene"];
  const auto& tb = scene["task_board"];

  // 1. Spawn task board
  auto tb_params = build_task_board_xacro_params(tb, root_config);
  auto tb_sdf = process_xacro("/urdf/task_board.urdf.xacro", tb_params);
  if (tb_sdf.empty()) return false;
  if (!spawn_entity("task_board", tb_sdf,
                    tb["pose"]["x"].as<double>(), tb["pose"]["y"].as<double>(),
                    tb["pose"]["z"].as<double>(), tb["pose"]["roll"].as<double>(),
                    tb["pose"]["pitch"].as<double>(), tb["pose"]["yaw"].as<double>())) {
    return false;
  }

  // 2. Tare FT sensor
  tare_ft_sensor();

  // 3. Spawn cables
  auto gripper_tf = tf_helper_.lookup("world", "gripper/tcp");
  if (!gripper_tf) {
    RCLCPP_ERROR(node_->get_logger(), "Cannot get gripper transform");
    return false;
  }

  const auto& cables = scene["cables"];
  for (auto it = cables.begin(); it != cables.end(); ++it) {
    const std::string cable_id = it->first.as<std::string>();
    const auto& cable_cfg = it->second;

    std::map<std::string, std::string> cable_params = {
      {"attach_cable_to_gripper", cable_cfg["attach_cable_to_gripper"].as<bool>() ? "true" : "false"},
      {"cable_type", cable_cfg["cable_type"].as<std::string>()},
    };
    auto cable_sdf = process_xacro("/urdf/cable.sdf.xacro", cable_params);
    if (cable_sdf.empty()) return false;

    const auto& offset = cable_cfg["pose"]["gripper_offset"];
    if (!spawn_entity(cable_id, cable_sdf,
                      gripper_tf->transform.translation.x + offset["x"].as<double>(),
                      gripper_tf->transform.translation.y + offset["y"].as<double>(),
                      gripper_tf->transform.translation.z + offset["z"].as<double>(),
                      cable_cfg["pose"]["roll"].as<double>(),
                      cable_cfg["pose"]["pitch"].as<double>(),
                      cable_cfg["pose"]["yaw"].as<double>())) {
      return false;
    }
  }

  // 4. Wait for joints to settle
  std::this_thread::sleep_for(std::chrono::seconds(2));
  RCLCPP_INFO(node_->get_logger(), "Scene spawned successfully");
  return true;
}

void SceneSpawner::despawn_scene() {
  delete_all();
  std::this_thread::sleep_for(std::chrono::seconds(1));
}

}  // namespace aic
