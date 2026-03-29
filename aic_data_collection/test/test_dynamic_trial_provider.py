import pytest
import tempfile
import yaml

from aic_data_collection.trial_config_provider import DynamicTrialProvider


@pytest.fixture
def sample_config_path():
    """Config with task_board_limits for randomization."""
    config = {
        "task_board_limits": {
            "nic_rail": {"min_translation": -0.048, "max_translation": 0.036},
            "sc_rail": {"min_translation": -0.06, "max_translation": 0.055},
            "mount_rail": {"min_translation": -0.09425, "max_translation": 0.09425},
        },
        "trials": {
            "trial_1": {
                "scene": {
                    "task_board": {
                        "pose": {"x": 0.15, "y": -0.2, "z": 1.14, "roll": 0.0, "pitch": 0.0, "yaw": 3.14},
                        "nic_rail_0": {"entity_present": True, "entity_name": "nic_card_0",
                                       "entity_pose": {"translation": 0.02, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
                    },
                    "cables": {
                        "cable_0": {
                            "pose": {"gripper_offset": {"x": 0.0, "y": 0.015, "z": 0.042}, "roll": 0.44, "pitch": -0.48, "yaw": 1.33},
                            "attach_cable_to_gripper": True,
                            "cable_type": "sfp_sc_cable",
                        }
                    },
                },
                "tasks": {
                    "task_1": {
                        "cable_type": "sfp_sc", "cable_name": "cable_0",
                        "plug_type": "sfp", "plug_name": "sfp_tip",
                        "port_type": "sfp", "port_name": "sfp_port_0",
                        "target_module_name": "nic_card_mount_0", "time_limit": 180,
                    }
                },
            },
        },
        "robot": {
            "home_joint_positions": {
                "shoulder_pan_joint": -0.1597,
                "shoulder_lift_joint": -1.3542,
                "elbow_joint": -1.6648,
                "wrist_1_joint": -1.6933,
                "wrist_2_joint": 1.5710,
                "wrist_3_joint": 1.4110,
            }
        },
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        return f.name


class TestDynamicTrialProvider:
    def test_generates_randomized_trial(self, sample_config_path):
        provider = DynamicTrialProvider(sample_config_path, base_trial="trial_1")
        trial = provider.get_next_trial()
        assert "trial_id" in trial
        assert "scene" in trial
        assert trial["trial_id"].startswith("dynamic_")

    def test_randomized_trials_differ(self, sample_config_path):
        provider = DynamicTrialProvider(sample_config_path, base_trial="trial_1", seed=42)
        t1 = provider.get_next_trial()
        t2 = provider.get_next_trial()
        # Task board pose should differ between randomized trials
        pose1 = t1["scene"]["task_board"]["pose"]
        pose2 = t2["scene"]["task_board"]["pose"]
        differs = any(pose1[k] != pose2[k] for k in ["x", "y", "yaw"])
        assert differs, "Randomized trials should have different poses"

    def test_rail_translations_within_limits(self, sample_config_path):
        provider = DynamicTrialProvider(sample_config_path, base_trial="trial_1", seed=123)
        for _ in range(20):
            trial = provider.get_next_trial()
            tb = trial["scene"]["task_board"]
            for key in tb:
                if key.startswith("nic_rail_") and tb[key].get("entity_present"):
                    trans = tb[key]["entity_pose"]["translation"]
                    assert -0.048 <= trans <= 0.036, f"NIC rail translation {trans} out of limits"
