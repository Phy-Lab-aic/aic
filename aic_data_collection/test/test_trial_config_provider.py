import pytest
import tempfile
import yaml

from aic_data_collection.trial_config_provider import StaticTrialProvider


@pytest.fixture
def sample_config_path():
    """Create a minimal sample config YAML for testing."""
    config = {
        "trials": {
            "trial_1": {
                "scene": {
                    "task_board": {"pose": {"x": 0.15, "y": -0.2, "z": 1.14, "roll": 0.0, "pitch": 0.0, "yaw": 3.14}},
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
            "trial_2": {
                "scene": {
                    "task_board": {"pose": {"x": 0.15, "y": -0.2, "z": 1.14, "roll": 0.0, "pitch": 0.0, "yaw": 3.14}},
                    "cables": {
                        "cable_0": {
                            "pose": {"gripper_offset": {"x": 0.0, "y": 0.015, "z": 0.045}, "roll": 0.44, "pitch": -0.48, "yaw": 1.33},
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
                        "target_module_name": "nic_card_mount_1", "time_limit": 180,
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


class TestStaticTrialProvider:
    def test_loads_all_trials(self, sample_config_path):
        provider = StaticTrialProvider(sample_config_path)
        assert provider.trial_count == 2

    def test_round_robin_default(self, sample_config_path):
        provider = StaticTrialProvider(sample_config_path)
        first = provider.get_next_trial()
        assert first["trial_id"] == "trial_1"
        second = provider.get_next_trial()
        assert second["trial_id"] == "trial_2"
        third = provider.get_next_trial()
        assert third["trial_id"] == "trial_1"  # wraps around

    def test_selected_trials(self, sample_config_path):
        provider = StaticTrialProvider(sample_config_path, trials=["trial_2"])
        first = provider.get_next_trial()
        assert first["trial_id"] == "trial_2"
        second = provider.get_next_trial()
        assert second["trial_id"] == "trial_2"  # only trial_2

    def test_trial_has_scene_and_tasks(self, sample_config_path):
        provider = StaticTrialProvider(sample_config_path)
        trial = provider.get_next_trial()
        assert "scene" in trial
        assert "tasks" in trial
        assert "cable_0" in trial["scene"]["cables"]

    def test_home_joint_positions(self, sample_config_path):
        provider = StaticTrialProvider(sample_config_path)
        home = provider.home_joint_positions
        assert home["shoulder_pan_joint"] == pytest.approx(-0.1597)

    def test_invalid_trial_name_raises(self, sample_config_path):
        with pytest.raises(ValueError, match="not found"):
            StaticTrialProvider(sample_config_path, trials=["trial_99"])
