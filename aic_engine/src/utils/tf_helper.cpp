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
