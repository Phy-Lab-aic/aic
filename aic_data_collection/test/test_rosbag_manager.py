import pytest
import tempfile
import os

from aic_data_collection.rosbag_manager import RosbagManager, OBSERVATION_TOPICS


class TestObservationTopics:
    def test_contains_camera_topics(self):
        assert "/left_camera/image" in OBSERVATION_TOPICS
        assert "/center_camera/image" in OBSERVATION_TOPICS
        assert "/right_camera/image" in OBSERVATION_TOPICS

    def test_contains_sensor_topics(self):
        assert "/joint_states" in OBSERVATION_TOPICS
        assert "/fts_broadcaster/wrench" in OBSERVATION_TOPICS
        assert "/aic_controller/controller_state" in OBSERVATION_TOPICS

    def test_topic_count(self):
        assert len(OBSERVATION_TOPICS) == 9  # 3 images + 3 camera_info + 3 sensors


class TestRosbagManager:
    def test_build_record_command(self):
        mgr = RosbagManager(output_dir="/tmp/bags")
        cmd = mgr._build_record_command("episode_001")
        assert "ros2" in cmd[0]
        assert "bag" in cmd[1]
        assert "record" in cmd[2]
        assert "/left_camera/image" in cmd
        assert "--output" in cmd

    def test_bag_path(self):
        mgr = RosbagManager(output_dir="/tmp/bags")
        path = mgr._bag_path("episode_001")
        assert path == "/tmp/bags/episode_001"

    def test_failed_bag_path(self):
        mgr = RosbagManager(output_dir="/tmp/bags")
        path = mgr._failed_bag_path("episode_001")
        assert path == "/tmp/bags/failed/episode_001"
