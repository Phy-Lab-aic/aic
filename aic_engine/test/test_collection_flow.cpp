#include <gtest/gtest.h>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <unistd.h>
#include <nlohmann/json.hpp>
#include "trial_config_provider.hpp"
#include "completion_monitor.hpp"
#include "rosbag_manager.hpp"

namespace fs = std::filesystem;
using json = nlohmann::json;

static std::string write_flow_config() {
  const char* yaml = R"(
task_board_limits:
  nic_rail: {min_translation: -0.048, max_translation: 0.036}
  sc_rail: {min_translation: -0.06, max_translation: 0.055}
  mount_rail: {min_translation: -0.09425, max_translation: 0.09425}
trials:
  trial_1:
    scene:
      task_board:
        pose: {x: 0.15, y: -0.2, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.015, z: 0.042}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_0
        target_module_name: nic_card_mount_0
        time_limit: 180
  trial_2:
    scene:
      task_board:
        pose: {x: 0.15, y: -0.2, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.015, z: 0.045}
            roll: 0.44
            pitch: -0.48
            yaw: 1.33
          attach_cable_to_gripper: true
          cable_type: sfp_sc_cable
    tasks:
      task_1:
        cable_type: sfp_sc
        cable_name: cable_0
        plug_type: sfp
        plug_name: sfp_tip
        port_type: sfp
        port_name: sfp_port_0
        target_module_name: nic_card_mount_1
        time_limit: 180
robot:
  home_joint_positions:
    shoulder_pan_joint: -0.1597
    shoulder_lift_joint: -1.3542
    elbow_joint: -1.6648
    wrist_1_joint: -1.6933
    wrist_2_joint: 1.571
    wrist_3_joint: 1.411
)";
  char path[] = "/tmp/aic_flow_config_XXXXXX.yaml";
  int fd = mkstemps(path, 5);
  write(fd, yaml, strlen(yaml));
  close(fd);
  return std::string(path);
}

TEST(CollectionFlow, StaticModeRoundRobinTrialTransition) {
  auto config_path = write_flow_config();
  aic::StaticTrialProvider provider(config_path);

  int target_episodes = 3;
  std::vector<std::string> trial_ids;

  for (int i = 0; i < target_episodes; ++i) {
    auto trial = provider.get_next_trial();
    trial_ids.push_back(trial["trial_id"].as<std::string>());
  }

  ASSERT_EQ(trial_ids.size(), 3u);
  EXPECT_EQ(trial_ids[0], "trial_1");
  EXPECT_EQ(trial_ids[1], "trial_2");
  EXPECT_EQ(trial_ids[2], "trial_1");

  std::remove(config_path.c_str());
}

TEST(CollectionFlow, DynamicModeRandomizedTrials) {
  auto config_path = write_flow_config();
  aic::DynamicTrialProvider provider(config_path, {"trial_1"}, 42);

  int target_episodes = 3;
  std::vector<YAML::Node> trials;

  for (int i = 0; i < target_episodes; ++i) {
    trials.push_back(provider.get_next_trial());
  }

  for (const auto& trial : trials) {
    auto tid = trial["trial_id"].as<std::string>();
    EXPECT_TRUE(tid.find("dynamic_") == 0) << "Got: " << tid;
    EXPECT_EQ(trial["base_trial"].as<std::string>(), "trial_1");
  }

  bool any_differ = false;
  for (size_t i = 0; i < trials.size(); ++i) {
    for (size_t j = i + 1; j < trials.size(); ++j) {
      auto p1 = trials[i]["scene"]["task_board"]["pose"];
      auto p2 = trials[j]["scene"]["task_board"]["pose"];
      if (p1["x"].as<double>() != p2["x"].as<double>() ||
          p1["y"].as<double>() != p2["y"].as<double>() ||
          p1["yaw"].as<double>() != p2["yaw"].as<double>()) {
        any_differ = true;
      }
    }
  }
  EXPECT_TRUE(any_differ);

  std::remove(config_path.c_str());
}

TEST(CollectionFlow, ManifestTrackingWithMixedResults) {
  auto tmpdir = fs::temp_directory_path() / ("aic_flow_test_" + std::to_string(getpid()));
  fs::create_directories(tmpdir);

  aic::RosbagManager mgr(tmpdir.string());
  std::vector<aic::EpisodeRecord> records = {
    {"trial_1_ep001", "trial_1", true, (tmpdir / "trial_1_ep001").string()},
    {"trial_2_ep002", "trial_2", false, (tmpdir / "failed" / "trial_2_ep002").string()},
    {"trial_1_ep003", "trial_1", true, (tmpdir / "trial_1_ep003").string()},
  };

  auto manifest_path = mgr.save_manifest(records);
  std::ifstream f(manifest_path);
  auto data = json::parse(f);
  EXPECT_EQ(data["total_episodes"], 3);
  EXPECT_EQ(data["successful"], 2);
  EXPECT_EQ(data["failed"], 1);

  EXPECT_TRUE(aic::is_success(aic::CompletionResult::SUCCESS));
  EXPECT_TRUE(aic::is_success(aic::CompletionResult::PARTIAL));
  EXPECT_FALSE(aic::is_success(aic::CompletionResult::TIMEOUT));

  fs::remove_all(tmpdir);
}
