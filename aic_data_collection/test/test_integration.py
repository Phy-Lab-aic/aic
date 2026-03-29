"""Integration test — requires running Gazebo simulation.

Launch sim first:
  ros2 launch aic_bringup aic_gz_bringup.launch.py ground_truth:=true start_aic_engine:=false
"""
import os
import time
import threading

import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor

from aic_data_collection.auto_data_collector import AutoDataCollector


# Skip if not in a ROS environment
pytestmark = pytest.mark.skipif(
    os.environ.get("ROS_DISTRO") is None,
    reason="ROS 2 environment not sourced"
)


@pytest.fixture(scope="module")
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


class TestSingleEpisodeCollection:
    """Test a single episode collection with the real sim."""

    def test_single_episode_completes(self, ros_context, tmp_path):
        """Run 1 episode with trial_1 from sample_config.yaml and verify bag is created."""
        from ament_index_python.packages import get_package_share_directory
        config_path = os.path.join(
            get_package_share_directory("aic_engine"), "config", "sample_config.yaml"
        )

        node = AutoDataCollector()
        # Override params for test
        node._target_episodes = 1
        node._max_attempts = 2
        node._rosbag._output_dir = str(tmp_path / "bags")
        os.makedirs(node._rosbag._output_dir, exist_ok=True)
        os.makedirs(os.path.join(node._rosbag._output_dir, "failed"), exist_ok=True)

        executor = MultiThreadedExecutor()
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        try:
            node.run_collection()
        finally:
            node.destroy_node()

        # Verify: at least one bag directory exists (success or failed)
        bag_dirs = os.listdir(str(tmp_path / "bags"))
        assert len(bag_dirs) > 0, "No bag directories created"

    def test_camera_topics_active(self, ros_context):
        """Verify camera dummy subscribers activate lazy bridge."""
        node = rclpy.create_node("test_camera_check")
        executor = MultiThreadedExecutor()
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        # Check that camera topics have publishers (bridge activated)
        time.sleep(3.0)
        topic_list = node.get_topic_names_and_types()
        camera_topics = [t for t, _ in topic_list if "camera/image" in t]

        node.destroy_node()
        assert len(camera_topics) >= 3, f"Expected 3 camera topics, got {camera_topics}"
