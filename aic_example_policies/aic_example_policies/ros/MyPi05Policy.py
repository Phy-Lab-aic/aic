#
#  Copyright (C) 2026
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#

"""π0.5 inference policy for AIC cable-insertion task — ROS adapter.

This file is the thin ROS layer:
    /observations msg → numpy/torch  →  Pi05InferenceCore (lerobot PI05Policy)
                                       ↓
                               6D arm joint targets
                                       ↓
                               JointMotionUpdate  →  /aic_controller/joint_commands

All non-ROS inference logic lives in ``pi05_inference.py`` so it can be
unit-tested without rclpy / aic_interfaces. See ``tests/test_pi05_inference.py``.

Loading layout (env var PI05_CKPT, default /models/pi05_ur5e_lerobot):
    <PI05_CKPT>/
      ├── model.safetensors      # produced by Phase 3.7 conversion
      ├── config.json
      └── norm_stats/

Backend stack: option C (RLinf train ↔ lerobot deploy), see
project_pi05_stack_decision.md.
"""

from __future__ import annotations

import os
import time
from typing import List

# Disable HF telemetry / opt-in HF transfer for faster cold start.
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

import numpy as np
import torch
from rclpy.node import Node

from aic_control_interfaces.msg import JointMotionUpdate, TrajectoryGenerationMode
from aic_model.policy import (
    GetObservationCallback,
    MoveRobotCallback,
    Policy,
    SendFeedbackCallback,
)
from aic_model_interfaces.msg import Observation
from aic_task_interfaces.msg import Task
from trajectory_msgs.msg import JointTrajectoryPoint

from aic_example_policies.ros.pi05_inference import (
    CONTROL_DT_S,
    Pi05InferenceCore,
    TRAINING_JOINT_ORDER,
    build_prompt,
    joint_dict_to_state,
    numpy_image_to_chw,
)

# Joint-mode impedance gains. Matches sample_config.yaml + RLinf_Report2 §7.2.
_TARGET_STIFFNESS: List[float] = [100.0, 100.0, 100.0, 50.0, 50.0, 50.0]
_TARGET_DAMPING: List[float] = [40.0, 40.0, 40.0, 15.0, 15.0, 15.0]


class MyPi05Policy(Policy):
    def __init__(self, parent_node: Node):
        super().__init__(parent_node)

        # CUDA threading hardening — aic_model uses MultiThreadedExecutor and
        # ROS callbacks may interleave with GPU forward. Pi05InferenceCore
        # holds its own lock for the actual inference call.
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)

        ckpt_dir = os.environ.get("PI05_CKPT", "/models/pi05_ur5e_lerobot")
        self.get_logger().info(f"MyPi05Policy: loading PI05 from {ckpt_dir}")

        self._inference = Pi05InferenceCore.from_pretrained(ckpt_dir)

        self.get_logger().info(
            f"MyPi05Policy: loaded on {self._inference.device}"
        )

    # ------------------------------------------------------------------ #
    # ROS msg ↔ numpy adapters
    # ------------------------------------------------------------------ #

    @staticmethod
    def _ros_image_array(raw_img) -> np.ndarray:
        """Decode sensor_msgs/Image (rgb8) into a uint8 (H, W, 3) array.

        encoding=rgb8 confirmed via basler_camera_macro.xacro:99
        ``<format>R8G8B8</format>`` and the absence of any cvtColor in
        existing AIC policies (RunACT.py).
        """
        h, w = raw_img.height, raw_img.width
        return np.frombuffer(raw_img.data, dtype=np.uint8).reshape(h, w, 3)

    def _extract_state(self, joint_states) -> np.ndarray:
        """sensor_msgs/JointState → 7D training-ordered state vector."""
        name_to_pos = dict(zip(joint_states.name, joint_states.position))
        try:
            return joint_dict_to_state(name_to_pos, TRAINING_JOINT_ORDER)
        except KeyError as exc:
            self.get_logger().error(f"MyPi05Policy: {exc}")
            raise

    def _build_joint_motion_update(
        self, abs_joint_targets: np.ndarray
    ) -> JointMotionUpdate:
        """Pack 6 absolute joint targets into a JointMotionUpdate.

        action[6] (gripper) is intentionally dropped — insertion keeps grip
        closed (B3 decision, project_inference_deployment.md).
        """
        target = JointTrajectoryPoint()
        target.positions = [float(x) for x in abs_joint_targets[:6]]

        msg = JointMotionUpdate()
        msg.target_state = target
        msg.target_stiffness = list(_TARGET_STIFFNESS)
        msg.target_damping = list(_TARGET_DAMPING)
        msg.target_feedforward_torque = []
        msg.trajectory_generation_mode = TrajectoryGenerationMode(
            mode=TrajectoryGenerationMode.MODE_POSITION
        )
        return msg

    # ------------------------------------------------------------------ #
    # Main entry
    # ------------------------------------------------------------------ #

    def insert_cable(
        self,
        task: Task,
        get_observation: GetObservationCallback,
        move_robot: MoveRobotCallback,
        send_feedback: SendFeedbackCallback,
    ) -> bool:
        prompt = build_prompt(task.plug_type, task.port_name, task.target_module_name)
        self.get_logger().info(f"MyPi05Policy.insert_cable() — {prompt}")

        # Warm-up: dummy forward absorbs the 500-1000ms cold start (vision
        # encoder JIT + flow 10-step denoise) before the first real tick.
        # Without this the first chunk is published 0.5-1s late, eating into
        # the trial timeout. See pi05_inference.Pi05InferenceCore.warm_up().
        warm_start = time.monotonic()
        self._inference.warm_up()
        self.get_logger().info(
            f"MyPi05Policy: warm-up took {time.monotonic() - warm_start:.2f}s"
        )

        time_limit_s = float(task.time_limit) if task.time_limit > 0 else 180.0
        deadline = time.monotonic() + time_limit_s

        loop_idx = 0
        while time.monotonic() < deadline:
            loop_start = time.monotonic()

            obs_msg = get_observation()
            if obs_msg is None:
                self.sleep_for(CONTROL_DT_S)
                continue

            # ROS msg → numpy
            state = self._extract_state(obs_msg.joint_states)
            img_center = self._ros_image_array(obs_msg.center_image)
            img_left = self._ros_image_array(obs_msg.left_image)
            img_right = self._ros_image_array(obs_msg.right_image)

            # numpy → batch → action
            arm_action = self._inference.infer_arm(
                img_center=img_center,
                img_left=img_left,
                img_right=img_right,
                state=state,
                prompt=prompt,
            )

            # action → ROS msg
            jmu = self._build_joint_motion_update(arm_action)
            move_robot(joint_motion_update=jmu)

            send_feedback("running")

            elapsed = time.monotonic() - loop_start
            sleep_remaining = max(0.0, CONTROL_DT_S - elapsed)
            if sleep_remaining > 0:
                self.sleep_for(sleep_remaining)

            loop_idx += 1
            if loop_idx % 100 == 0:
                self.get_logger().info(
                    f"MyPi05Policy: loop {loop_idx}, "
                    f"remaining {deadline - time.monotonic():.1f}s"
                )

        self.get_logger().info("MyPi05Policy.insert_cable() exiting (time limit).")
        return True
