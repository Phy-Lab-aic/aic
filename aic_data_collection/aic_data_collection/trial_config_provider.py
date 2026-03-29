"""Trial configuration providers for data collection."""

import copy
import random
from typing import Optional

import yaml


class StaticTrialProvider:
    """Provides trial configs from a static YAML file in round-robin order."""

    def __init__(self, config_path: str, trials: Optional[list[str]] = None):
        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f)

        all_trials = self._config.get("trials", {})

        if trials is None:
            self._trial_names = list(all_trials.keys())
        else:
            for name in trials:
                if name not in all_trials:
                    raise ValueError(f"Trial '{name}' not found in config. Available: {list(all_trials.keys())}")
            self._trial_names = trials

        self._trials = {name: all_trials[name] for name in self._trial_names}
        self._index = 0

    @property
    def trial_count(self) -> int:
        return len(self._trial_names)

    @property
    def home_joint_positions(self) -> dict[str, float]:
        return self._config["robot"]["home_joint_positions"]

    def get_next_trial(self) -> dict:
        """Return the next trial config in round-robin order."""
        name = self._trial_names[self._index % len(self._trial_names)]
        trial = self._trials[name]
        self._index += 1
        return {
            "trial_id": name,
            "scene": trial["scene"],
            "tasks": trial["tasks"],
        }


class DynamicTrialProvider:
    """Generates randomized trial configs from a base template."""

    def __init__(self, config_path: str, base_trial: str, seed: int = None):
        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f)

        all_trials = self._config.get("trials", {})
        if base_trial not in all_trials:
            raise ValueError(f"Base trial '{base_trial}' not found. Available: {list(all_trials.keys())}")

        self._base_trial = all_trials[base_trial]
        self._limits = self._config.get("task_board_limits", {})
        self._rng = random.Random(seed)
        self._counter = 0

    @property
    def home_joint_positions(self) -> dict[str, float]:
        return self._config["robot"]["home_joint_positions"]

    def get_next_trial(self) -> dict:
        """Generate a randomized trial config from the base template."""
        self._counter += 1
        trial = copy.deepcopy(self._base_trial)
        tb = trial["scene"]["task_board"]

        # Randomize task_board pose slightly
        pose = tb["pose"]
        pose["x"] += self._rng.uniform(-0.03, 0.03)
        pose["y"] += self._rng.uniform(-0.03, 0.03)
        pose["yaw"] += self._rng.uniform(-0.3, 0.3)

        # Randomize rail translations within limits
        nic_limits = self._limits.get("nic_rail", {})
        nic_min = nic_limits.get("min_translation", -0.048)
        nic_max = nic_limits.get("max_translation", 0.036)
        for i in range(5):
            rail_key = f"nic_rail_{i}"
            if rail_key in tb and tb[rail_key].get("entity_present"):
                tb[rail_key]["entity_pose"]["translation"] = self._rng.uniform(nic_min, nic_max)

        sc_limits = self._limits.get("sc_rail", {})
        sc_min = sc_limits.get("min_translation", -0.06)
        sc_max = sc_limits.get("max_translation", 0.055)
        for i in range(2):
            rail_key = f"sc_rail_{i}"
            if rail_key in tb and tb[rail_key].get("entity_present"):
                tb[rail_key]["entity_pose"]["translation"] = self._rng.uniform(sc_min, sc_max)

        mount_limits = self._limits.get("mount_rail", {})
        mount_min = mount_limits.get("min_translation", -0.09425)
        mount_max = mount_limits.get("max_translation", 0.09425)
        for rail_type in ["lc_mount", "sfp_mount", "sc_mount"]:
            for i in range(2):
                rail_key = f"{rail_type}_rail_{i}"
                if rail_key in tb and tb[rail_key].get("entity_present"):
                    tb[rail_key]["entity_pose"]["translation"] = self._rng.uniform(mount_min, mount_max)

        return {
            "trial_id": f"dynamic_{self._counter:04d}",
            "scene": trial["scene"],
            "tasks": trial["tasks"],
        }
