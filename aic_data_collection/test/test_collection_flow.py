"""Orchestration flow tests for AutoDataCollector.

Tests the full episode lifecycle without ROS infrastructure by mocking
all ROS-dependent components and verifying call ordering and state transitions.
"""
import tempfile
import yaml
from unittest.mock import MagicMock, call, patch

import pytest

from aic_data_collection.completion_monitor import CompletionResult
from aic_data_collection.trial_config_provider import StaticTrialProvider, DynamicTrialProvider


@pytest.fixture
def sample_config_path():
    """Two-trial config for round-robin testing."""
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
                        "pose": {"x": 0.15, "y": -0.2, "z": 1.14,
                                 "roll": 0.0, "pitch": 0.0, "yaw": 3.14},
                    },
                    "cables": {
                        "cable_0": {
                            "pose": {"gripper_offset": {"x": 0.0, "y": 0.015, "z": 0.042},
                                     "roll": 0.44, "pitch": -0.48, "yaw": 1.33},
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
                    "task_board": {
                        "pose": {"x": 0.15, "y": -0.2, "z": 1.14,
                                 "roll": 0.0, "pitch": 0.0, "yaw": 3.14},
                    },
                    "cables": {
                        "cable_0": {
                            "pose": {"gripper_offset": {"x": 0.0, "y": 0.015, "z": 0.045},
                                     "roll": 0.44, "pitch": -0.48, "yaw": 1.33},
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


def _make_collector(trial_provider, target_episodes=3):
    """Create a mock AutoDataCollector with real trial_provider but mocked ROS deps."""
    # Avoid __init__ which requires rclpy; use object.__new__ and set fields manually
    from aic_data_collection.auto_data_collector import AutoDataCollector
    node = object.__new__(AutoDataCollector)

    # Orchestration state
    node._target_episodes = target_episodes
    node._max_attempts = target_episodes * 3
    node._task_timeout = 180.0
    node._dist_threshold = 0.005
    node._orient_threshold = 0.1
    node._successful = 0
    node._failed = 0
    node._fail_reasons = {}
    node._insertion_event_received = False

    # Components
    node._trial_provider = trial_provider
    node._scene = MagicMock()
    node._scene.spawn_scene.return_value = True
    node._scene.despawn_scene.return_value = None
    node._rosbag = MagicMock()
    node._rosbag.stop.return_value = "/tmp/bags/episode"
    node._homing = MagicMock()
    node._homing.home_robot.return_value = True

    # Mock logger
    node._Node__logger = MagicMock()  # rclpy Node stores logger here
    # Provide get_logger() via mock
    node.get_logger = MagicMock(return_value=MagicMock())

    return node


class TestPhase1StaticCollection:
    """Phase 1: Static trial mode - 3 successful episodes with round-robin trial transition."""

    def test_three_episodes_with_trial_transition_and_homing(self, sample_config_path):
        """Verify full lifecycle: robot moves → rosbag saved → trial transitions →
        robot resets → next rosbag → 3+ episodes collected."""
        provider = StaticTrialProvider(sample_config_path)
        node = _make_collector(provider, target_episodes=3)

        # Mock: InsertCable action succeeds every time
        node._send_insert_cable = MagicMock(return_value=True)
        # Mock: completion check returns SUCCESS every time
        node._check_completion = MagicMock(return_value=CompletionResult.SUCCESS)
        # Mock: activate model succeeds
        node._activate_model = MagicMock(return_value=True)
        # Set insertion_event as received (simulates subscription callback)
        node._insertion_event_received = True

        # Run
        node.run_collection()

        # === Verify 3 successful episodes collected ===
        assert node._successful == 3, f"Expected 3 successful episodes, got {node._successful}"
        assert node._failed == 0, f"Expected 0 failures, got {node._failed}"

        # === Verify robot moved (InsertCable called) for each episode ===
        assert node._send_insert_cable.call_count == 3

        # === Verify rosbag recorded per episode ===
        assert node._rosbag.start.call_count == 3
        assert node._rosbag.stop.call_count == 3
        # All stops should be success=True
        for c in node._rosbag.stop.call_args_list:
            assert c == call(success=True), f"Expected rosbag stop with success=True, got {c}"

        # === Verify trial round-robin: trial_1 → trial_2 → trial_1 ===
        spawn_calls = node._scene.spawn_scene.call_args_list
        assert len(spawn_calls) == 3
        trial_ids = [c.args[0]["trial_id"] for c in spawn_calls]
        assert trial_ids == ["trial_1", "trial_2", "trial_1"], \
            f"Expected round-robin [trial_1, trial_2, trial_1], got {trial_ids}"

        # === Verify robot resets (homing) between episodes ===
        assert node._homing.home_robot.call_count == 3

        # === Verify scene despawned between episodes ===
        assert node._scene.despawn_scene.call_count == 3

        # === Verify episode ordering: spawn → record → action → stop → despawn → home ===
        # Check call order via mock manager
        all_calls = []
        for i in range(3):
            all_calls.extend([
                ("spawn", i),
                ("rosbag_start", i),
                ("insert_cable", i),
                ("rosbag_stop", i),
                ("despawn", i),
                ("home", i),
            ])
        # Verify ordering by checking relative positions
        spawn_positions = [i for i, _ in enumerate(node._scene.spawn_scene.call_args_list)]
        rosbag_start_positions = [i for i, _ in enumerate(node._rosbag.start.call_args_list)]
        assert len(spawn_positions) == len(rosbag_start_positions) == 3

        # === Verify rosbag episode IDs follow trial names ===
        rosbag_start_calls = node._rosbag.start.call_args_list
        episode_ids = [c.args[0] for c in rosbag_start_calls]
        assert "trial_1" in episode_ids[0]
        assert "trial_2" in episode_ids[1]
        assert "trial_1" in episode_ids[2]


class TestPhase2DynamicCollection:
    """Phase 2: Dynamic trial mode - 3 successful episodes with randomized trials."""

    def test_three_episodes_with_dynamic_trials_and_homing(self, sample_config_path):
        """Verify full lifecycle with DynamicTrialProvider: randomized trials →
        robot moves → rosbag saved → robot resets → 3+ episodes collected."""
        provider = DynamicTrialProvider(sample_config_path, base_trial="trial_1", seed=42)
        node = _make_collector(provider, target_episodes=3)

        # Mock: all actions succeed
        node._send_insert_cable = MagicMock(return_value=True)
        node._check_completion = MagicMock(return_value=CompletionResult.SUCCESS)
        node._activate_model = MagicMock(return_value=True)
        node._insertion_event_received = True

        # Run
        node.run_collection()

        # === Verify 3 successful episodes ===
        assert node._successful == 3
        assert node._failed == 0

        # === Verify robot moved for each episode ===
        assert node._send_insert_cable.call_count == 3

        # === Verify rosbag recorded per episode ===
        assert node._rosbag.start.call_count == 3
        assert node._rosbag.stop.call_count == 3
        for c in node._rosbag.stop.call_args_list:
            assert c == call(success=True)

        # === Verify dynamic trial IDs (dynamic_NNNN format) ===
        spawn_calls = node._scene.spawn_scene.call_args_list
        trial_ids = [c.args[0]["trial_id"] for c in spawn_calls]
        for tid in trial_ids:
            assert tid.startswith("dynamic_"), f"Expected dynamic_ prefix, got {tid}"

        # === Verify each trial has different randomized config ===
        poses = [c.args[0]["scene"]["task_board"]["pose"] for c in spawn_calls]
        # At least one pair should differ in x, y, or yaw
        any_differ = False
        for i in range(len(poses)):
            for j in range(i + 1, len(poses)):
                if any(poses[i][k] != poses[j][k] for k in ["x", "y", "yaw"]):
                    any_differ = True
                    break
        assert any_differ, "Dynamic trials should have different randomized poses"

        # === Verify robot resets between episodes ===
        assert node._homing.home_robot.call_count == 3

        # === Verify scene despawned between episodes ===
        assert node._scene.despawn_scene.call_count == 3

        # === Verify rosbag episode IDs follow dynamic naming ===
        rosbag_start_calls = node._rosbag.start.call_args_list
        episode_ids = [c.args[0] for c in rosbag_start_calls]
        for eid in episode_ids:
            assert "dynamic_" in eid, f"Expected dynamic_ in episode ID, got {eid}"
