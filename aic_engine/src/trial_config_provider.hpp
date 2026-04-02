#ifndef AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_
#define AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_

#include <iomanip>
#include <map>
#include <memory>
#include <optional>
#include <random>
#include <sstream>
#include <string>
#include <vector>

#include "yaml-cpp/yaml.h"

namespace aic {

class TrialConfigProvider {
public:
  virtual ~TrialConfigProvider() = default;
  virtual YAML::Node get_next_trial() = 0;
  virtual size_t trial_count() const = 0;
  virtual std::map<std::string, double> home_joint_positions() const = 0;
};

class StaticTrialProvider : public TrialConfigProvider {
public:
  explicit StaticTrialProvider(
      const std::string& config_path,
      const std::vector<std::string>& trials = {});

  YAML::Node get_next_trial() override;
  size_t trial_count() const override;
  std::map<std::string, double> home_joint_positions() const override;

private:
  YAML::Node config_;
  std::vector<std::string> trial_names_;
  std::map<std::string, YAML::Node> trials_;
  size_t index_ = 0;
};

class DynamicTrialProvider : public TrialConfigProvider {
public:
  explicit DynamicTrialProvider(
      const std::string& config_path,
      const std::vector<std::string>& base_trials = {},
      uint64_t seed = 0);

  YAML::Node get_next_trial() override;
  size_t trial_count() const override;
  std::map<std::string, double> home_joint_positions() const override;

private:
  double beta_sample(double low, double high);
  void randomize_cables(YAML::Node& scene);

  YAML::Node config_;
  std::vector<std::string> trial_names_;
  std::map<std::string, YAML::Node> base_trials_;
  YAML::Node limits_;
  std::mt19937_64 rng_;
  size_t index_ = 0;
  size_t counter_ = 0;
};

}  // namespace aic

#endif  // AIC_ENGINE_TRIAL_CONFIG_PROVIDER_HPP_
