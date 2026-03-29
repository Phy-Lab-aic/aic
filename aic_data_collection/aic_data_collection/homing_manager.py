"""Robot homing via controller switching + joint reset."""

import time

from aic_engine_interfaces.srv import ResetJoints
from controller_manager_msgs.srv import SwitchController
from rclpy.node import Node


class HomingManager:
    """Homes the robot to initial joint positions between episodes."""

    def __init__(self, node: Node, home_joint_positions: dict[str, float]):
        self._node = node
        self._logger = node.get_logger()
        self._home_positions = home_joint_positions

        self._switch_controller_client = node.create_client(
            SwitchController, "/controller_manager/switch_controller"
        )
        self._reset_joints_client = node.create_client(
            ResetJoints, "/scoring/reset_joints"
        )

    def home_robot(self) -> bool:
        """Home robot: deactivate controller -> reset joints -> activate controller."""
        # 1. Deactivate aic_controller
        if not self._switch_controllers(deactivate=["aic_controller"]):
            self._logger.error("Failed to deactivate aic_controller")
            return False
        self._logger.info("aic_controller deactivated")

        # 2. Reset joints to home position
        if not self._reset_joints():
            self._logger.error("Failed to reset joints, attempting fallback")
            self._switch_controllers(activate=["aic_controller"])
            return False

        # 3. Reactivate aic_controller
        if not self._switch_controllers(activate=["aic_controller"]):
            self._logger.error("Failed to reactivate aic_controller")
            return False
        self._logger.info("Robot homed successfully")
        return True

    def _switch_controllers(
        self,
        activate: list[str] = None,
        deactivate: list[str] = None,
    ) -> bool:
        """Switch controllers via controller_manager service."""
        if not self._switch_controller_client.wait_for_service(timeout_sec=10.0):
            self._logger.error("SwitchController service not available")
            return False

        req = SwitchController.Request()
        req.activate_controllers = activate or []
        req.deactivate_controllers = deactivate or []
        req.strictness = SwitchController.Request.BEST_EFFORT

        future = self._switch_controller_client.call_async(req)
        start = time.monotonic()
        while not future.done() and (time.monotonic() - start) < 10.0:
            time.sleep(0.05)
        if not future.done():
            return False
        result = future.result()
        return result is not None and result.ok

    def _reset_joints(self) -> bool:
        """Call /scoring/reset_joints to teleport joints to home position."""
        if not self._reset_joints_client.wait_for_service(timeout_sec=10.0):
            self._logger.error("ResetJoints service not available")
            return False

        req = ResetJoints.Request()
        req.joint_names = list(self._home_positions.keys())
        req.initial_positions = list(self._home_positions.values())

        future = self._reset_joints_client.call_async(req)
        start = time.monotonic()
        while not future.done() and (time.monotonic() - start) < 10.0:
            time.sleep(0.05)
        if not future.done():
            return False
        result = future.result()
        return result is not None and result.success
