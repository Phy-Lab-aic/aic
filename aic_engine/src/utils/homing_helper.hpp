#ifndef AIC_ENGINE_UTILS_HOMING_HELPER_HPP_
#define AIC_ENGINE_UTILS_HOMING_HELPER_HPP_

#include <map>
#include <string>
#include <vector>

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
  rclcpp::Client<controller_manager_msgs::srv::SwitchController>::SharedPtr switch_ctrl_client_;
  rclcpp::Client<aic_engine_interfaces::srv::ResetJoints>::SharedPtr reset_joints_client_;
  std::shared_ptr<aic_engine_interfaces::srv::ResetJoints::Request> reset_request_;
};

}  // namespace aic

#endif  // AIC_ENGINE_UTILS_HOMING_HELPER_HPP_
