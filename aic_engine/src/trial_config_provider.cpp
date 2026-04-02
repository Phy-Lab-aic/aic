#include "trial_config_provider.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <stdexcept>

namespace aic {

// ===========================================================================
// StaticTrialProvider
// ===========================================================================

StaticTrialProvider::StaticTrialProvider(
    const std::string& config_path,
    const std::vector<std::string>& trials) {
  config_ = YAML::LoadFile(config_path);
  auto all_trials = config_["trials"];

  if (trials.empty()) {
    for (auto it = all_trials.begin(); it != all_trials.end(); ++it) {
      trial_names_.push_back(it->first.as<std::string>());
    }
  } else {
    for (const auto& name : trials) {
      if (!all_trials[name]) {
        std::ostringstream oss;
        oss << "Trial '" << name << "' not found in config. Available:";
        for (auto it = all_trials.begin(); it != all_trials.end(); ++it) {
          oss << " " << it->first.as<std::string>();
        }
        throw std::runtime_error(oss.str());
      }
      trial_names_.push_back(name);
    }
  }

  for (const auto& name : trial_names_) {
    trials_[name] = all_trials[name];
  }
}

YAML::Node StaticTrialProvider::get_next_trial() {
  const auto& name = trial_names_[index_ % trial_names_.size()];
  index_++;
  YAML::Node result;
  result["trial_id"] = name;
  result["scene"] = trials_[name]["scene"];
  result["tasks"] = trials_[name]["tasks"];
  return result;
}

size_t StaticTrialProvider::trial_count() const {
  return trial_names_.size();
}

std::map<std::string, double> StaticTrialProvider::home_joint_positions() const {
  std::map<std::string, double> positions;
  const auto& joints = config_["robot"]["home_joint_positions"];
  for (auto it = joints.begin(); it != joints.end(); ++it) {
    positions[it->first.as<std::string>()] = it->second.as<double>();
  }
  return positions;
}

// ===========================================================================
// DynamicTrialProvider
// ===========================================================================

DynamicTrialProvider::DynamicTrialProvider(
    const std::string& config_path,
    const std::vector<std::string>& base_trials,
    uint64_t seed) {
  config_ = YAML::LoadFile(config_path);
  auto all_trials = config_["trials"];
  limits_ = config_["task_board_limits"];

  std::vector<std::string> selected = base_trials;
  if (selected.empty()) {
    for (auto it = all_trials.begin(); it != all_trials.end(); ++it) {
      selected.push_back(it->first.as<std::string>());
    }
  }

  for (const auto& name : selected) {
    if (!all_trials[name]) {
      throw std::runtime_error("Base trial '" + name + "' not found.");
    }
    trial_names_.push_back(name);
    base_trials_[name] = YAML::Clone(all_trials[name]);
  }

  if (seed == 0) {
    std::random_device rd;
    rng_.seed(rd());
  } else {
    rng_.seed(seed);
  }
}

double DynamicTrialProvider::beta_sample(double low, double high) {
  std::gamma_distribution<double> gamma(0.5, 1.0);
  double x = gamma(rng_);
  double y = gamma(rng_);
  double u = x / (x + y);
  return low + u * (high - low);
}

void DynamicTrialProvider::randomize_cables(YAML::Node& scene) {
  if (!scene["cables"]) return;
  auto cables = scene["cables"];
  std::uniform_real_distribution<double> perturb(-0.002, 0.002);
  for (auto it = cables.begin(); it != cables.end(); ++it) {
    auto offset = it->second["pose"]["gripper_offset"];
    if (!offset) continue;
    for (const auto& axis : {"x", "y", "z"}) {
      if (offset[axis]) {
        offset[axis] = offset[axis].as<double>() + perturb(rng_);
      }
    }
  }
}

YAML::Node DynamicTrialProvider::get_next_trial() {
  std::uniform_int_distribution<uint64_t> seed_dist;
  uint64_t episode_seed = seed_dist(rng_);
  counter_++;

  const auto& base_name = trial_names_[index_ % trial_names_.size()];
  index_++;
  YAML::Node trial = YAML::Clone(base_trials_[base_name]);

  auto tb = trial["scene"]["task_board"];

  std::uniform_real_distribution<double> xy_perturb(-0.03, 0.03);
  std::uniform_real_distribution<double> yaw_perturb(-0.3, 0.3);
  tb["pose"]["x"] = tb["pose"]["x"].as<double>() + xy_perturb(rng_);
  tb["pose"]["y"] = tb["pose"]["y"].as<double>() + xy_perturb(rng_);
  tb["pose"]["yaw"] = tb["pose"]["yaw"].as<double>() + yaw_perturb(rng_);

  double nic_min = limits_["nic_rail"] ? limits_["nic_rail"]["min_translation"].as<double>(-0.048) : -0.048;
  double nic_max = limits_["nic_rail"] ? limits_["nic_rail"]["max_translation"].as<double>(0.036) : 0.036;
  for (int i = 0; i < 5; ++i) {
    std::string key = "nic_rail_" + std::to_string(i);
    if (tb[key] && tb[key]["entity_present"].as<bool>(false)) {
      tb[key]["entity_pose"]["translation"] = beta_sample(nic_min, nic_max);
    }
  }

  double sc_min = limits_["sc_rail"] ? limits_["sc_rail"]["min_translation"].as<double>(-0.06) : -0.06;
  double sc_max = limits_["sc_rail"] ? limits_["sc_rail"]["max_translation"].as<double>(0.055) : 0.055;
  for (int i = 0; i < 2; ++i) {
    std::string key = "sc_rail_" + std::to_string(i);
    if (tb[key] && tb[key]["entity_present"].as<bool>(false)) {
      tb[key]["entity_pose"]["translation"] = beta_sample(sc_min, sc_max);
    }
  }

  double mount_min = limits_["mount_rail"] ? limits_["mount_rail"]["min_translation"].as<double>(-0.09425) : -0.09425;
  double mount_max = limits_["mount_rail"] ? limits_["mount_rail"]["max_translation"].as<double>(0.09425) : 0.09425;
  for (const auto& rail_type : {"lc_mount", "sfp_mount", "sc_mount"}) {
    for (int i = 0; i < 2; ++i) {
      std::string key = std::string(rail_type) + "_rail_" + std::to_string(i);
      if (tb[key] && tb[key]["entity_present"].as<bool>(false)) {
        tb[key]["entity_pose"]["translation"] = beta_sample(mount_min, mount_max);
      }
    }
  }

  auto scene = trial["scene"];
  randomize_cables(scene);

  std::ostringstream tid;
  tid << "dynamic_" << std::setfill('0') << std::setw(4) << counter_;

  YAML::Node result;
  result["trial_id"] = tid.str();
  result["base_trial"] = base_name;
  result["seed"] = episode_seed;
  result["scene"] = trial["scene"];
  result["tasks"] = trial["tasks"];
  return result;
}

size_t DynamicTrialProvider::trial_count() const {
  return trial_names_.size();
}

std::map<std::string, double> DynamicTrialProvider::home_joint_positions() const {
  std::map<std::string, double> positions;
  const auto& joints = config_["robot"]["home_joint_positions"];
  for (auto it = joints.begin(); it != joints.end(); ++it) {
    positions[it->first.as<std::string>()] = it->second.as<double>();
  }
  return positions;
}

}  // namespace aic
