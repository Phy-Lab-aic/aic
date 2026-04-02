#include "utils/homing_helper.hpp"

#include <thread>

namespace aic {

HomingHelper::HomingHelper(
    rclcpp::Node* node,
    const std::map<std::string, double>& home_joint_positions)
    : node_(node) {
  switch_ctrl_client_ =
      node_->create_client<controller_manager_msgs::srv::SwitchController>(
          "/controller_manager/switch_controller");
  reset_joints_client_ =
      node_->create_client<aic_engine_interfaces::srv::ResetJoints>(
          "/scoring/reset_joints");

  // Pre-build reset request
  reset_request_ = std::make_shared<aic_engine_interfaces::srv::ResetJoints::Request>();
  for (const auto& [name, pos] : home_joint_positions) {
    reset_request_->joint_names.push_back(name);
    reset_request_->initial_positions.push_back(pos);
  }
}

bool HomingHelper::home_robot() {
  RCLCPP_INFO(node_->get_logger(), "Homing robot to initial positions...");

  // 1. Deactivate aic_controller
  if (!switch_controllers({}, {"aic_controller"})) {
    RCLCPP_ERROR(node_->get_logger(), "Failed to deactivate aic_controller");
    return false;
  }
  RCLCPP_INFO(node_->get_logger(), "aic_controller deactivated");

  // 2. Reset joints
  if (!reset_joints()) {
    RCLCPP_ERROR(node_->get_logger(), "Failed to reset joints");
    switch_controllers({"aic_controller"}, {});
    return false;
  }

  // 3. Wait for stabilization
  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  RCLCPP_INFO(node_->get_logger(), "Stabilization wait complete");

  // 4. Reactivate aic_controller
  if (!switch_controllers({"aic_controller"}, {})) {
    RCLCPP_ERROR(node_->get_logger(), "Failed to reactivate aic_controller");
    return false;
  }
  RCLCPP_INFO(node_->get_logger(), "Robot homed successfully");
  return true;
}

bool HomingHelper::switch_controllers(
    const std::vector<std::string>& activate,
    const std::vector<std::string>& deactivate) {
  if (!switch_ctrl_client_->wait_for_service(std::chrono::seconds(10))) {
    RCLCPP_ERROR(node_->get_logger(), "SwitchController service not available");
    return false;
  }

  auto request = std::make_shared<controller_manager_msgs::srv::SwitchController::Request>();
  request->activate_controllers = activate;
  request->deactivate_controllers = deactivate;
  request->strictness = controller_manager_msgs::srv::SwitchController::Request::STRICT;

  auto future = switch_ctrl_client_->async_send_request(request);
  if (!wait_for(future, 10.0)) {
    RCLCPP_ERROR(node_->get_logger(), "SwitchController timed out");
    return false;
  }
  auto response = future.get();
  return response && response->ok;
}

bool HomingHelper::reset_joints() {
  if (!reset_joints_client_->wait_for_service(std::chrono::seconds(10))) {
    RCLCPP_ERROR(node_->get_logger(), "ResetJoints service not available");
    return false;
  }

  auto future = reset_joints_client_->async_send_request(reset_request_);
  if (!wait_for(future, 10.0)) {
    RCLCPP_ERROR(node_->get_logger(), "ResetJoints timed out");
    return false;
  }
  auto response = future.get();
  return response && response->success;
}

}  // namespace aic
