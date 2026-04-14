#!/usr/bin/env python3
"""카메라 토픽 구독 + cv2.imshow 실시간 뷰어.
별도 프로세스로 실행하여 실험 중 시각적 모니터링.

Usage:
  cd /home/jjhyeongg/0_Project/intrinsic_challenge/ws_aic/src/aic
  RMW_IMPLEMENTATION=rmw_zenoh_cpp pixi run python research/scripts/camera_viewer.py
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import cv2
import numpy as np


class CameraViewer(Node):
    def __init__(self):
        super().__init__("camera_viewer")
        self.sub = self.create_subscription(
            Image, "/center_camera/image_raw", self.callback, 1)
        self.get_logger().info("Subscribed to /center_camera/image_raw")

    def callback(self, msg: Image):
        # ROS Image → numpy
        if msg.encoding == "rgb8":
            img = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                msg.height, msg.width, 3)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        elif msg.encoding == "bgr8":
            img = np.frombuffer(msg.data, dtype=np.uint8).reshape(
                msg.height, msg.width, 3)
        else:
            self.get_logger().warn(f"Unknown encoding: {msg.encoding}")
            return

        # 크기 조정 (표시용)
        h, w = img.shape[:2]
        scale = min(640 / w, 480 / h)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
        cv2.imshow("AIC Camera", img)
        cv2.waitKey(1)


def main():
    rclpy.init()
    node = CameraViewer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
