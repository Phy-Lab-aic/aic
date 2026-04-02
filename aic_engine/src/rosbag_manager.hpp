#ifndef AIC_ENGINE_ROSBAG_MANAGER_HPP_
#define AIC_ENGINE_ROSBAG_MANAGER_HPP_

#include <string>
#include <vector>
#include <sys/types.h>
#include "yaml-cpp/yaml.h"

namespace aic {

struct EpisodeRecord {
  std::string episode_id;
  std::string trial_id;
  bool success;
  std::string bag_path;
};

extern const std::vector<std::string> OBSERVATION_TOPICS;

class RosbagManager {
public:
  explicit RosbagManager(const std::string& output_dir);

  std::string bag_path(const std::string& episode_id) const;
  std::string failed_bag_path(const std::string& episode_id) const;
  std::vector<std::string> build_record_command(const std::string& episode_id) const;

  bool start_recording(const std::string& episode_id);
  std::string stop_recording(bool success);
  void move_to_failed(const std::string& episode_id);

  std::string save_metadata(
      const std::string& episode_id,
      const YAML::Node& trial,
      bool success,
      const std::string& bag_path_str,
      const std::string& start_time = "",
      const std::string& end_time = "");

  std::string save_manifest(const std::vector<EpisodeRecord>& episodes);

private:
  std::string output_dir_;
  pid_t recorder_pid_ = -1;
  std::string current_episode_;
  std::string start_time_;
};

}  // namespace aic

#endif  // AIC_ENGINE_ROSBAG_MANAGER_HPP_
