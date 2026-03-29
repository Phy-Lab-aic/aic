"""Rosbag recording manager using subprocess."""

import os
import signal
import shutil
import subprocess
import time
from typing import Optional


OBSERVATION_TOPICS = [
    "/left_camera/image",
    "/center_camera/image",
    "/right_camera/image",
    "/left_camera/camera_info",
    "/center_camera/camera_info",
    "/right_camera/camera_info",
    "/fts_broadcaster/wrench",
    "/joint_states",
    "/aic_controller/controller_state",
]


class RosbagManager:
    """Manages rosbag recording via subprocess."""

    def __init__(self, output_dir: str = "bags"):
        self._output_dir = output_dir
        self._process: Optional[subprocess.Popen] = None
        self._current_episode: Optional[str] = None
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "failed"), exist_ok=True)

    def _bag_path(self, episode_id: str) -> str:
        return os.path.join(self._output_dir, episode_id)

    def _failed_bag_path(self, episode_id: str) -> str:
        return os.path.join(self._output_dir, "failed", episode_id)

    def _build_record_command(self, episode_id: str) -> list[str]:
        cmd = ["ros2", "bag", "record", "--output", self._bag_path(episode_id)]
        cmd.extend(OBSERVATION_TOPICS)
        return cmd

    def start(self, episode_id: str) -> None:
        """Start recording a new episode."""
        if self._process is not None:
            raise RuntimeError("Recording already in progress")
        self._current_episode = episode_id
        cmd = self._build_record_command(episode_id)
        self._process = subprocess.Popen(cmd, shell=False)

    def stop(self, success: bool = True) -> str:
        """Stop recording. Returns the final bag path."""
        if self._process is None or self._current_episode is None:
            raise RuntimeError("No recording in progress")

        # SIGINT for graceful shutdown
        self._process.send_signal(signal.SIGINT)
        try:
            self._process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

        bag_path = self._bag_path(self._current_episode)

        if not success:
            failed_path = self._failed_bag_path(self._current_episode)
            if os.path.exists(bag_path):
                shutil.move(bag_path, failed_path)
            bag_path = failed_path

        self._process = None
        self._current_episode = None
        return bag_path
