#include <gtest/gtest.h>
#include <fstream>
#include <cstdio>
#include <unistd.h>
#include "trial_config_provider.hpp"

static std::string write_sample_config() {
  const char* yaml = R"(
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
  char path[] = "/tmp/aic_test_config_XXXXXX.yaml";
  int fd = mkstemps(path, 5);
  write(fd, yaml, strlen(yaml));
  close(fd);
  return std::string(path);
}

class StaticTrialProviderTest : public ::testing::Test {
protected:
  void SetUp() override { config_path_ = write_sample_config(); }
  void TearDown() override { std::remove(config_path_.c_str()); }
  std::string config_path_;
};

TEST_F(StaticTrialProviderTest, LoadsAllTrials) {
  aic::StaticTrialProvider provider(config_path_);
  EXPECT_EQ(provider.trial_count(), 2u);
}

TEST_F(StaticTrialProviderTest, RoundRobinDefault) {
  aic::StaticTrialProvider provider(config_path_);
  auto t1 = provider.get_next_trial();
  EXPECT_EQ(t1["trial_id"].as<std::string>(), "trial_1");
  auto t2 = provider.get_next_trial();
  EXPECT_EQ(t2["trial_id"].as<std::string>(), "trial_2");
  auto t3 = provider.get_next_trial();
  EXPECT_EQ(t3["trial_id"].as<std::string>(), "trial_1");
}

TEST_F(StaticTrialProviderTest, SelectedTrials) {
  aic::StaticTrialProvider provider(config_path_, {"trial_2"});
  auto t1 = provider.get_next_trial();
  EXPECT_EQ(t1["trial_id"].as<std::string>(), "trial_2");
  auto t2 = provider.get_next_trial();
  EXPECT_EQ(t2["trial_id"].as<std::string>(), "trial_2");
}

TEST_F(StaticTrialProviderTest, TrialHasSceneAndTasks) {
  aic::StaticTrialProvider provider(config_path_);
  auto trial = provider.get_next_trial();
  EXPECT_TRUE(trial["scene"].IsDefined());
  EXPECT_TRUE(trial["tasks"].IsDefined());
  EXPECT_TRUE(trial["scene"]["cables"]["cable_0"].IsDefined());
}

TEST_F(StaticTrialProviderTest, HomeJointPositions) {
  aic::StaticTrialProvider provider(config_path_);
  auto home = provider.home_joint_positions();
  EXPECT_NEAR(home["shoulder_pan_joint"], -0.1597, 1e-4);
}

TEST_F(StaticTrialProviderTest, InvalidTrialNameThrows) {
  EXPECT_THROW(
    aic::StaticTrialProvider(config_path_, {"trial_99"}),
    std::runtime_error
  );
}
