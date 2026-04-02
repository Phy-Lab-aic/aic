#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <nlohmann/json.hpp>
#include "rosbag_manager.hpp"
#include "yaml-cpp/yaml.h"

namespace fs = std::filesystem;
using json = nlohmann::json;

TEST(ObservationTopics, ContainsCameraTopics) {
  auto& topics = aic::OBSERVATION_TOPICS;
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/left_camera/image"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/center_camera/image"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/right_camera/image"), topics.end());
}

TEST(ObservationTopics, ContainsSensorTopics) {
  auto& topics = aic::OBSERVATION_TOPICS;
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/joint_states"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/fts_broadcaster/wrench"), topics.end());
  EXPECT_NE(std::find(topics.begin(), topics.end(), "/aic_controller/controller_state"), topics.end());
}

TEST(ObservationTopics, TopicCount) {
  EXPECT_EQ(aic::OBSERVATION_TOPICS.size(), 9u);
}

class RosbagManagerTest : public ::testing::Test {
protected:
  void SetUp() override {
    tmpdir_ = fs::temp_directory_path() / ("aic_bag_test_" + std::to_string(getpid()));
    fs::create_directories(tmpdir_);
  }
  void TearDown() override { fs::remove_all(tmpdir_); }
  fs::path tmpdir_;
};

TEST_F(RosbagManagerTest, BagPath) {
  aic::RosbagManager mgr(tmpdir_.string());
  EXPECT_EQ(mgr.bag_path("episode_001"), (tmpdir_ / "episode_001").string());
}

TEST_F(RosbagManagerTest, FailedBagPath) {
  aic::RosbagManager mgr(tmpdir_.string());
  EXPECT_EQ(mgr.failed_bag_path("episode_001"), (tmpdir_ / "failed" / "episode_001").string());
}

TEST_F(RosbagManagerTest, BuildRecordCommand) {
  aic::RosbagManager mgr(tmpdir_.string());
  auto cmd = mgr.build_record_command("episode_001");
  EXPECT_EQ(cmd[0], "ros2");
  EXPECT_EQ(cmd[1], "bag");
  EXPECT_EQ(cmd[2], "record");
  EXPECT_NE(std::find(cmd.begin(), cmd.end(), "/left_camera/image"), cmd.end());
  EXPECT_NE(std::find(cmd.begin(), cmd.end(), "--output"), cmd.end());
}

TEST_F(RosbagManagerTest, SaveMetadataWritesYaml) {
  aic::RosbagManager mgr(tmpdir_.string());
  fs::path ep_dir = tmpdir_ / "trial_1_ep0001";
  fs::create_directories(ep_dir);

  YAML::Node trial;
  trial["trial_id"] = "trial_1";
  trial["base_trial"] = "trial_1";
  trial["seed"] = static_cast<uint64_t>(12345678);
  trial["scene"]["task_board"]["pose"]["x"] = 0.15;
  trial["tasks"]["task_1"]["cable_name"] = "cable_a";

  auto path = mgr.save_metadata("trial_1_ep0001", trial, true, ep_dir.string(),
                                "2026-04-01T04:30:00Z", "2026-04-01T04:33:00Z");
  EXPECT_TRUE(fs::exists(path));

  auto data = YAML::LoadFile(path);
  EXPECT_EQ(data["episode_id"].as<std::string>(), "trial_1_ep0001");
  EXPECT_EQ(data["trial_id"].as<std::string>(), "trial_1");
  EXPECT_EQ(data["base_trial"].as<std::string>(), "trial_1");
  EXPECT_EQ(data["seed"].as<uint64_t>(), 12345678u);
  EXPECT_TRUE(data["success"].as<bool>());
  EXPECT_EQ(data["timestamps"]["start"].as<std::string>(), "2026-04-01T04:30:00Z");
  EXPECT_EQ(data["timestamps"]["end"].as<std::string>(), "2026-04-01T04:33:00Z");
  EXPECT_TRUE(data["scene_config"].IsDefined());
  EXPECT_TRUE(data["tasks"].IsDefined());
}

TEST_F(RosbagManagerTest, SaveMetadataSuccessFalse) {
  aic::RosbagManager mgr(tmpdir_.string());
  fs::path ep_dir = tmpdir_ / "failed" / "trial_1_ep0002";
  fs::create_directories(ep_dir);

  YAML::Node trial;
  trial["trial_id"] = "trial_1";
  auto path = mgr.save_metadata("trial_1_ep0002", trial, false, ep_dir.string());
  auto data = YAML::LoadFile(path);
  EXPECT_FALSE(data["success"].as<bool>());
}

TEST_F(RosbagManagerTest, SaveManifestWritesJson) {
  aic::RosbagManager mgr(tmpdir_.string());
  std::vector<aic::EpisodeRecord> episodes = {
    {"t1_ep0001", "t1", true, "/bags/t1_ep0001"},
    {"t1_ep0002", "t1", false, "/bags/failed/t1_ep0002"},
    {"t1_ep0003", "t1", true, "/bags/t1_ep0003"},
  };
  auto path = mgr.save_manifest(episodes);
  EXPECT_TRUE(fs::exists(path));

  std::ifstream f(path);
  auto data = json::parse(f);
  EXPECT_EQ(data["total_episodes"], 3);
  EXPECT_EQ(data["successful"], 2);
  EXPECT_EQ(data["failed"], 1);
  EXPECT_EQ(data["episodes"].size(), 3u);
}

TEST_F(RosbagManagerTest, ManifestEpisodeFields) {
  aic::RosbagManager mgr(tmpdir_.string());
  std::vector<aic::EpisodeRecord> episodes = {
    {"t1_ep0001", "t1", true, "/bags/t1_ep0001"},
  };
  mgr.save_manifest(episodes);
  std::ifstream f((tmpdir_ / "manifest.json").string());
  auto data = json::parse(f);
  auto ep = data["episodes"][0];
  EXPECT_EQ(ep["episode_id"], "t1_ep0001");
  EXPECT_EQ(ep["trial_id"], "t1");
  EXPECT_TRUE(ep["success"].get<bool>());
  EXPECT_EQ(ep["bag_path"], "/bags/t1_ep0001");
}

TEST_F(RosbagManagerTest, EmptyManifest) {
  aic::RosbagManager mgr(tmpdir_.string());
  mgr.save_manifest({});
  std::ifstream f((tmpdir_ / "manifest.json").string());
  auto data = json::parse(f);
  EXPECT_EQ(data["total_episodes"], 0);
  EXPECT_EQ(data["successful"], 0);
  EXPECT_EQ(data["episodes"].size(), 0u);
}
