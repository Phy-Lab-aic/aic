#include "rosbag_manager.hpp"

#include <chrono>
#include <csignal>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <sys/wait.h>
#include <unistd.h>

#include <nlohmann/json.hpp>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace aic {

const std::vector<std::string> OBSERVATION_TOPICS = {
    "/left_camera/image",
    "/center_camera/image",
    "/right_camera/image",
    "/left_camera/camera_info",
    "/center_camera/camera_info",
    "/right_camera/camera_info",
    "/fts_broadcaster/wrench",
    "/joint_states",
    "/aic_controller/controller_state",
};

static std::string now_iso8601() {
  auto now = std::chrono::system_clock::now();
  auto time_t_val = std::chrono::system_clock::to_time_t(now);
  struct tm tm_buf;
  gmtime_r(&time_t_val, &tm_buf);
  std::ostringstream oss;
  oss << std::put_time(&tm_buf, "%Y-%m-%dT%H:%M:%SZ");
  return oss.str();
}

RosbagManager::RosbagManager(const std::string& output_dir)
    : output_dir_(output_dir) {
  fs::create_directories(output_dir);
  fs::create_directories(fs::path(output_dir) / "failed");
}

std::string RosbagManager::bag_path(const std::string& episode_id) const {
  return (fs::path(output_dir_) / episode_id).string();
}

std::string RosbagManager::failed_bag_path(const std::string& episode_id) const {
  return (fs::path(output_dir_) / "failed" / episode_id).string();
}

std::vector<std::string> RosbagManager::build_record_command(
    const std::string& episode_id) const {
  std::vector<std::string> cmd = {"ros2", "bag", "record", "--output", bag_path(episode_id)};
  cmd.insert(cmd.end(), OBSERVATION_TOPICS.begin(), OBSERVATION_TOPICS.end());
  return cmd;
}

bool RosbagManager::start_recording(const std::string& episode_id) {
  if (recorder_pid_ > 0) return false;
  current_episode_ = episode_id;
  start_time_ = now_iso8601();

  auto cmd = build_record_command(episode_id);

  pid_t pid = fork();
  if (pid == 0) {
    std::vector<char*> argv;
    for (auto& s : cmd) argv.push_back(const_cast<char*>(s.c_str()));
    argv.push_back(nullptr);
    execvp(argv[0], argv.data());
    _exit(1);
  }
  recorder_pid_ = pid;
  return pid > 0;
}

std::string RosbagManager::stop_recording(bool success) {
  if (recorder_pid_ <= 0) return "";

  kill(recorder_pid_, SIGINT);
  int status;
  int waited = 0;
  while (waitpid(recorder_pid_, &status, WNOHANG) == 0 && waited < 50) {
    usleep(100000);
    waited++;
  }
  if (waited >= 50) {
    kill(recorder_pid_, SIGKILL);
    waitpid(recorder_pid_, &status, 0);
  }
  recorder_pid_ = -1;

  std::string path = bag_path(current_episode_);
  if (!success) {
    std::string fpath = failed_bag_path(current_episode_);
    if (fs::exists(path)) {
      fs::rename(path, fpath);
    }
    path = fpath;
  }

  current_episode_.clear();
  start_time_.clear();
  return path;
}

void RosbagManager::move_to_failed(const std::string& episode_id) {
  auto src = bag_path(episode_id);
  auto dst = failed_bag_path(episode_id);
  if (fs::exists(src)) {
    fs::rename(src, dst);
  }
}

std::string RosbagManager::save_metadata(
    const std::string& episode_id,
    const YAML::Node& trial,
    bool success,
    const std::string& bag_path_str,
    const std::string& start_time,
    const std::string& end_time) {
  YAML::Node metadata;
  metadata["episode_id"] = episode_id;
  metadata["trial_id"] = trial["trial_id"].as<std::string>("");
  metadata["base_trial"] = trial["base_trial"].as<std::string>(
      trial["trial_id"].as<std::string>(""));
  if (trial["seed"]) {
    metadata["seed"] = trial["seed"].as<uint64_t>();
  } else {
    metadata["seed"] = YAML::Null;
  }
  metadata["success"] = success;
  metadata["scene_config"] = trial["scene"] ? trial["scene"] : YAML::Node();
  metadata["tasks"] = trial["tasks"] ? trial["tasks"] : YAML::Node();
  metadata["timestamps"]["start"] = start_time.empty() ? start_time_ : start_time;
  metadata["timestamps"]["end"] = end_time.empty() ? now_iso8601() : end_time;
  metadata["bag_path"] = bag_path_str;

  fs::create_directories(bag_path_str);
  std::string metadata_path = (fs::path(bag_path_str) / "metadata.yaml").string();
  std::ofstream fout(metadata_path);
  fout << metadata;
  return metadata_path;
}

std::string RosbagManager::save_manifest(const std::vector<EpisodeRecord>& episodes) {
  int successful = 0;
  for (const auto& ep : episodes) {
    if (ep.success) successful++;
  }

  json manifest;
  manifest["total_episodes"] = static_cast<int>(episodes.size());
  manifest["successful"] = successful;
  manifest["failed"] = static_cast<int>(episodes.size()) - successful;
  manifest["episodes"] = json::array();
  for (const auto& ep : episodes) {
    manifest["episodes"].push_back({
      {"episode_id", ep.episode_id},
      {"trial_id", ep.trial_id},
      {"success", ep.success},
      {"bag_path", ep.bag_path},
    });
  }

  std::string path = (fs::path(output_dir_) / "manifest.json").string();
  std::ofstream fout(path);
  fout << manifest.dump(2);
  return path;
}

}  // namespace aic
