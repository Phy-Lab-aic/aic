#include <gtest/gtest.h>
#include <cmath>
#include "completion_monitor.hpp"

using aic::CompletionResult;
using aic::check_tf_completion;

TEST(CheckTfCompletion, SuccessWithinThreshold) {
  Eigen::Vector3d plug_pos(0.1, 0.2, 0.3);
  Eigen::Vector3d port_pos(0.1, 0.2, 0.303);
  Eigen::Quaterniond plug_quat(1.0, 0.0, 0.0, 0.0);
  Eigen::Quaterniond port_quat(1.0, 0.0, 0.0, 0.0);
  EXPECT_TRUE(check_tf_completion(plug_pos, port_pos, plug_quat, port_quat, 0.005, 0.1));
}

TEST(CheckTfCompletion, FailDistanceTooLarge) {
  Eigen::Vector3d plug_pos(0.1, 0.2, 0.3);
  Eigen::Vector3d port_pos(0.1, 0.2, 0.31);
  Eigen::Quaterniond plug_quat(1.0, 0.0, 0.0, 0.0);
  Eigen::Quaterniond port_quat(1.0, 0.0, 0.0, 0.0);
  EXPECT_FALSE(check_tf_completion(plug_pos, port_pos, plug_quat, port_quat, 0.005, 0.1));
}

TEST(CheckTfCompletion, FailOrientationTooLarge) {
  Eigen::Vector3d plug_pos(0.1, 0.2, 0.3);
  Eigen::Vector3d port_pos(0.1, 0.2, 0.301);
  Eigen::Quaterniond plug_quat(1.0, 0.0, 0.0, 0.0);
  Eigen::Quaterniond port_quat(std::cos(0.1), 0.0, 0.0, std::sin(0.1));
  EXPECT_FALSE(check_tf_completion(plug_pos, port_pos, plug_quat, port_quat, 0.005, 0.1));
}

TEST(CompletionResult, SuccessIsSuccess) {
  EXPECT_TRUE(aic::is_success(CompletionResult::SUCCESS));
}

TEST(CompletionResult, PartialIsSuccess) {
  EXPECT_TRUE(aic::is_success(CompletionResult::PARTIAL));
}

TEST(CompletionResult, TimeoutIsNotSuccess) {
  EXPECT_FALSE(aic::is_success(CompletionResult::TIMEOUT));
}

TEST(CompletionResult, ActionFailedIsNotSuccess) {
  EXPECT_FALSE(aic::is_success(CompletionResult::ACTION_FAILED));
}
