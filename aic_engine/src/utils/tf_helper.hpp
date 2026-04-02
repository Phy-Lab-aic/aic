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
