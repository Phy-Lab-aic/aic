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

  double dot = std::abs(plug_quat.dot(port_quat));
  dot = std::min(1.0, dot);
  double angle_diff = 2.0 * std::acos(dot);

  return angle_diff <= orientation_threshold;
}

}  // namespace aic
