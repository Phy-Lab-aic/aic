#ifndef AIC_ENGINE_COMPLETION_MONITOR_HPP_
#define AIC_ENGINE_COMPLETION_MONITOR_HPP_

#include <Eigen/Geometry>

namespace aic {

enum class CompletionResult : uint8_t {
  SUCCESS = 0,
  PARTIAL,
  TIMEOUT,
  ACTION_FAILED
};

inline bool is_success(CompletionResult r) {
  return r == CompletionResult::SUCCESS || r == CompletionResult::PARTIAL;
}

bool check_tf_completion(
    const Eigen::Vector3d& plug_pos,
    const Eigen::Vector3d& port_pos,
    const Eigen::Quaterniond& plug_quat,
    const Eigen::Quaterniond& port_quat,
    double distance_threshold = 0.005,
    double orientation_threshold = 0.1);

}  // namespace aic

#endif  // AIC_ENGINE_COMPLETION_MONITOR_HPP_
