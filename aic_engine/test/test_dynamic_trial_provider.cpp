#include <gtest/gtest.h>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <set>
#include <unistd.h>
#include "trial_config_provider.hpp"

static std::string write_dynamic_config() {
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
        nic_rail_0:
          entity_present: true
          entity_name: nic_card_0
          entity_pose: {translation: 0.02, roll: 0.0, pitch: 0.0, yaw: 0.0}
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
        pose: {x: 0.16, y: -0.21, z: 1.14, roll: 0.0, pitch: 0.0, yaw: 3.14}
        nic_rail_0:
          entity_present: true
          entity_name: nic_card_0
          entity_pose: {translation: 0.01, roll: 0.0, pitch: 0.0, yaw: 0.0}
      cables:
        cable_0:
          pose:
            gripper_offset: {x: 0.0, y: 0.016, z: 0.045}
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
        port_name: sfp_port_1
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
  char path[] = "/tmp/aic_dyn_config_XXXXXX.yaml";
  int fd = mkstemps(path, 5);
  write(fd, yaml, strlen(yaml));
  close(fd);
  return std::string(path);
}

class DynamicTrialProviderTest : public ::testing::Test {
protected:
  void SetUp() override { config_path_ = write_dynamic_config(); }
  void TearDown() override { std::remove(config_path_.c_str()); }
  std::string config_path_;
};

TEST_F(DynamicTrialProviderTest, GeneratesRandomizedTrial) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  auto trial = provider.get_next_trial();
  auto tid = trial["trial_id"].as<std::string>();
  EXPECT_TRUE(tid.find("dynamic_") == 0) << "Got: " << tid;
  EXPECT_TRUE(trial["scene"].IsDefined());
}

TEST_F(DynamicTrialProviderTest, RandomizedTrialsDiffer) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  auto t1 = provider.get_next_trial();
  auto t2 = provider.get_next_trial();
  auto p1 = t1["scene"]["task_board"]["pose"];
  auto p2 = t2["scene"]["task_board"]["pose"];
  bool differs = (p1["x"].as<double>() != p2["x"].as<double>()) ||
                 (p1["y"].as<double>() != p2["y"].as<double>()) ||
                 (p1["yaw"].as<double>() != p2["yaw"].as<double>());
  EXPECT_TRUE(differs);
}

TEST_F(DynamicTrialProviderTest, RailTranslationsWithinLimits) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 123);
  for (int i = 0; i < 20; ++i) {
    auto trial = provider.get_next_trial();
    auto tb = trial["scene"]["task_board"];
    if (tb["nic_rail_0"] && tb["nic_rail_0"]["entity_present"].as<bool>()) {
      double trans = tb["nic_rail_0"]["entity_pose"]["translation"].as<double>();
      EXPECT_GE(trans, -0.048) << "Iteration " << i;
      EXPECT_LE(trans, 0.036) << "Iteration " << i;
    }
  }
}

TEST_F(DynamicTrialProviderTest, MultiTrialRoundRobin) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1", "trial_2"}, 42);
  EXPECT_EQ(provider.trial_count(), 2u);
  auto t1 = provider.get_next_trial();
  auto t2 = provider.get_next_trial();
  auto t3 = provider.get_next_trial();
  EXPECT_EQ(t1["base_trial"].as<std::string>(), "trial_1");
  EXPECT_EQ(t2["base_trial"].as<std::string>(), "trial_2");
  EXPECT_EQ(t3["base_trial"].as<std::string>(), "trial_1");
}

TEST_F(DynamicTrialProviderTest, EmptyBaseTrialsUsesAll) {
  aic::DynamicTrialProvider provider(config_path_, {}, 42);
  EXPECT_EQ(provider.trial_count(), 2u);
}

TEST_F(DynamicTrialProviderTest, SeedRecordedInTrial) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  auto trial = provider.get_next_trial();
  EXPECT_TRUE(trial["seed"].IsDefined());
  EXPECT_TRUE(trial["seed"].as<uint64_t>() > 0);
}

TEST_F(DynamicTrialProviderTest, SeedsDifferPerEpisode) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  std::set<uint64_t> seeds;
  for (int i = 0; i < 10; ++i) {
    auto trial = provider.get_next_trial();
    seeds.insert(trial["seed"].as<uint64_t>());
  }
  EXPECT_EQ(seeds.size(), 10u);
}

TEST_F(DynamicTrialProviderTest, CableGripperOffsetRandomized) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  bool any_changed = false;
  for (int i = 0; i < 5; ++i) {
    auto trial = provider.get_next_trial();
    auto offset = trial["scene"]["cables"]["cable_0"]["pose"]["gripper_offset"];
    double ox = offset["x"].as<double>();
    double oy = offset["y"].as<double>();
    double oz = offset["z"].as<double>();
    EXPECT_NEAR(ox, 0.0, 0.002 + 1e-9);
    EXPECT_NEAR(oy, 0.015, 0.002 + 1e-9);
    EXPECT_NEAR(oz, 0.042, 0.002 + 1e-9);
    if (ox != 0.0 || oy != 0.015 || oz != 0.042) any_changed = true;
  }
  EXPECT_TRUE(any_changed);
}

TEST_F(DynamicTrialProviderTest, EdgeBiasedSamplingCoversRange) {
  aic::DynamicTrialProvider provider(config_path_, {"trial_1"}, 42);
  std::vector<double> translations;
  for (int i = 0; i < 200; ++i) {
    auto trial = provider.get_next_trial();
    auto tb = trial["scene"]["task_board"];
    if (tb["nic_rail_0"] && tb["nic_rail_0"]["entity_present"].as<bool>()) {
      translations.push_back(tb["nic_rail_0"]["entity_pose"]["translation"].as<double>());
    }
  }
  ASSERT_FALSE(translations.empty());
  double nic_min = -0.048, nic_max = 0.036;
  double range = nic_max - nic_min;
  int near_min = 0, near_max = 0;
  for (double t : translations) {
    if (t < nic_min + 0.2 * range) near_min++;
    if (t > nic_max - 0.2 * range) near_max++;
  }
  EXPECT_GT(near_min, 20) << "Expected >20 near-min samples, got " << near_min;
  EXPECT_GT(near_max, 20) << "Expected >20 near-max samples, got " << near_max;
}

TEST_F(DynamicTrialProviderTest, InvalidBaseTrialThrows) {
  EXPECT_THROW(
    aic::DynamicTrialProvider(config_path_, {"nonexistent"}, 42),
    std::runtime_error
  );
}
