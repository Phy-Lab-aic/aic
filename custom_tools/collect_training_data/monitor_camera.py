#!/usr/bin/env python3
"""
monitor_camera.py

Headless 데이터 수집 중 카메라 이미지를 실시간 모니터링하는 도구.
ROS2 토픽을 구독하여 cv2.imshow로 표시한다.

Usage:
    # 기본 (center 카메라)
    python3 monitor_camera.py

    # 특정 카메라
    python3 monitor_camera.py --topic /left_camera/image

    # 모든 카메라
    python3 monitor_camera.py --all

종료: 'q' 키 또는 Ctrl+C
"""

from __future__ import annotations

import argparse
import sys

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image


CAMERA_TOPICS = {
    "left":   "/left_camera/image",
    "center": "/center_camera/image",
    "right":  "/right_camera/image",
}


class CameraMonitor(Node):
    def __init__(self, topics: list[str]):
        super().__init__("camera_monitor")

        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self._windows: dict[str, np.ndarray | None] = {}
        for topic in topics:
            name = topic.split("/")[1] if "/" in topic else topic
            self._windows[name] = None
            self.create_subscription(
                Image, topic,
                lambda msg, n=name: self._on_image(msg, n),
                qos,
            )
            self.get_logger().info(f"Subscribing to {topic} -> window '{name}'")

    def _on_image(self, msg: Image, window_name: str) -> None:
        try:
            # Convert ROS Image to OpenCV
            if msg.encoding in ("rgb8", "RGB8"):
                img = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    msg.height, msg.width, 3
                )
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif msg.encoding in ("bgr8", "BGR8"):
                img = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    msg.height, msg.width, 3
                )
            elif msg.encoding in ("mono8",):
                img = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    msg.height, msg.width
                )
            else:
                # Fallback: try as 3-channel
                img = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                    msg.height, msg.width, -1
                )
                if img.shape[2] == 3:
                    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            self._windows[window_name] = img
        except Exception as e:
            self.get_logger().warn(f"Failed to decode image: {e}")

    def show(self) -> bool:
        """Display current frames. Returns False if user pressed 'q'."""
        for name, img in self._windows.items():
            if img is not None:
                cv2.imshow(name, img)

        key = cv2.waitKey(1) & 0xFF
        return key != ord("q")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor camera during headless collection")
    parser.add_argument("--topic", type=str, default=None,
                        help="Single camera topic to monitor (default: /center_camera/image)")
    parser.add_argument("--all", action="store_true",
                        help="Monitor all 3 cameras")
    args = parser.parse_args()

    if args.all:
        topics = list(CAMERA_TOPICS.values())
    elif args.topic:
        topics = [args.topic]
    else:
        topics = [CAMERA_TOPICS["center"]]

    rclpy.init()
    node = CameraMonitor(topics)

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.03)
            if not node.show():
                break
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
