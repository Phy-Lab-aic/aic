"""Scene management: spawn/despawn entities via Gazebo services."""

import math
import subprocess
import time
from typing import Optional

from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from simulation_interfaces.srv import SpawnEntity, DeleteEntity
from std_srvs.srv import Trigger
import tf2_ros


class SceneManager:
    """Manages scene entities (task_board, cables) via Gazebo services."""

    def __init__(self, node: Node):
        self._node = node
        self._logger = node.get_logger()
        self._spawned_entities: list[str] = []

        self._spawn_client = node.create_client(SpawnEntity, "/gz_server/spawn_entity")
        self._delete_client = node.create_client(DeleteEntity, "/gz_server/delete_entity")
        self._tare_ft_client = node.create_client(Trigger, "/aic_controller/tare_force_torque_sensor")

        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, node)

        self._description_share = get_package_share_directory("aic_description")

    def _wait_for_services(self, timeout_sec: float = 30.0) -> bool:
        """Wait for required Gazebo services to become available."""
        for client in [self._spawn_client, self._delete_client]:
            if not client.wait_for_service(timeout_sec=timeout_sec):
                self._logger.error(f"Service {client.srv_name} not available")
                return False
        return True

    def _process_xacro(self, filepath: str, params: dict[str, str] = None) -> Optional[str]:
        """Run xacro to produce SDF/URDF string."""
        xacro_path = self._description_share + filepath
        cmd = ["xacro", xacro_path]
        if params:
            for k, v in params.items():
                cmd.append(f"{k}:={v}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                self._logger.error(f"xacro failed: {result.stderr}")
                return None
            return result.stdout
        except subprocess.TimeoutExpired:
            self._logger.error("xacro timed out")
            return None

    def _spawn_entity(self, name: str, sdf_xml: str, x: float, y: float, z: float,
                      roll: float, pitch: float, yaw: float) -> bool:
        """Spawn a single entity in Gazebo."""
        req = SpawnEntity.Request()
        req.name = name
        req.xml = sdf_xml
        req.initial_pose.position.x = x
        req.initial_pose.position.y = y
        req.initial_pose.position.z = z
        # Convert RPY to quaternion for initial_pose.orientation
        cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
        cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
        cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
        req.initial_pose.orientation.w = cr * cp * cy + sr * sp * sy
        req.initial_pose.orientation.x = sr * cp * cy - cr * sp * sy
        req.initial_pose.orientation.y = cr * sp * cy + sr * cp * sy
        req.initial_pose.orientation.z = cr * cp * sy - sr * sp * cy

        future = self._spawn_client.call_async(req)
        # Poll-based wait (avoids executor threading issues per devlog lesson #5)
        timeout = 30.0
        start = time.monotonic()
        while not future.done() and (time.monotonic() - start) < timeout:
            time.sleep(0.05)
        if not future.done():
            self._logger.error(f"Spawn '{name}' timed out")
            return False
        result = future.result()
        if not result or result.result.result != 1:  # RESULT_OK = 1
            self._logger.error(f"Spawn '{name}' failed: {getattr(result, 'result', 'unknown')}")
            return False
        self._spawned_entities.append(name)
        self._logger.info(f"Spawned '{name}'")
        return True

    def _delete_entity(self, name: str) -> bool:
        """Delete a single entity from Gazebo."""
        req = DeleteEntity.Request()
        req.entity = name
        future = self._delete_client.call_async(req)
        timeout = 10.0
        start = time.monotonic()
        while not future.done() and (time.monotonic() - start) < timeout:
            time.sleep(0.05)
        if not future.done():
            self._logger.error(f"Delete '{name}' timed out")
            return False
        result = future.result()
        if not result or result.result.result != 1:
            self._logger.error(f"Delete '{name}' failed")
            return False
        self._logger.info(f"Deleted '{name}'")
        return True

    def spawn_scene(self, trial_config: dict) -> bool:
        """Spawn task_board and cable(s) for a trial.

        Replicates aic_engine::ready_simulator() logic.
        """
        if not self._wait_for_services():
            return False

        scene = trial_config["scene"]

        # 1. Spawn task board with xacro params
        tb = scene["task_board"]
        tb_params = self._build_task_board_xacro_params(tb, trial_config)
        tb_sdf = self._process_xacro("/urdf/task_board.urdf.xacro", tb_params)
        if not tb_sdf:
            return False
        if not self._spawn_entity("task_board",
                                  tb_sdf,
                                  tb["pose"]["x"], tb["pose"]["y"], tb["pose"]["z"],
                                  tb["pose"]["roll"], tb["pose"]["pitch"], tb["pose"]["yaw"]):
            return False

        # 2. Tare FT sensor
        self._tare_ft_sensor()

        # 3. Spawn cables
        cables = scene.get("cables", {})
        gripper_tf = self._get_gripper_transform()
        if gripper_tf is None:
            self._logger.error("Cannot get gripper transform")
            return False

        for cable_id, cable_cfg in cables.items():
            cable_params = {
                "attach_cable_to_gripper": str(cable_cfg["attach_cable_to_gripper"]).lower(),
                "cable_type": cable_cfg["cable_type"],
            }
            cable_sdf = self._process_xacro("/urdf/cable.sdf.xacro", cable_params)
            if not cable_sdf:
                return False
            offset = cable_cfg["pose"]["gripper_offset"]
            if not self._spawn_entity(
                cable_id, cable_sdf,
                gripper_tf.translation.x + offset["x"],
                gripper_tf.translation.y + offset["y"],
                gripper_tf.translation.z + offset["z"],
                cable_cfg["pose"]["roll"],
                cable_cfg["pose"]["pitch"],
                cable_cfg["pose"]["yaw"],
            ):
                return False

        # 4. Wait for joints to settle
        time.sleep(2.0)
        self._logger.info("Scene spawned successfully")
        return True

    def despawn_scene(self) -> None:
        """Delete all spawned entities."""
        for name in list(self._spawned_entities):
            self._delete_entity(name)
        self._spawned_entities.clear()

    def _build_task_board_xacro_params(self, tb_config: dict, trial_config: dict) -> dict[str, str]:
        """Build xacro params for task_board from config (NIC rails, SC rails, mounts)."""
        params = {}
        # NIC rails 0-4
        for i in range(5):
            rail_key = f"nic_rail_{i}"
            mount_prefix = f"nic_card_mount_{i}"
            rail = tb_config.get(rail_key, {})
            if rail.get("entity_present", False):
                params[f"{mount_prefix}_present"] = "true"
                pose = rail.get("entity_pose", {})
                params[f"{mount_prefix}_translation"] = str(pose.get("translation", 0.0))
                params[f"{mount_prefix}_roll"] = str(pose.get("roll", 0.0))
                params[f"{mount_prefix}_pitch"] = str(pose.get("pitch", 0.0))
                params[f"{mount_prefix}_yaw"] = str(pose.get("yaw", 0.0))
            else:
                params[f"{mount_prefix}_present"] = "false"

        # SC rails 0-1
        for i in range(2):
            rail_key = f"sc_rail_{i}"
            rail = tb_config.get(rail_key, {})
            if rail.get("entity_present", False):
                params[f"sc_port_{i}_present"] = "true"
                pose = rail.get("entity_pose", {})
                params[f"sc_port_{i}_translation"] = str(pose.get("translation", 0.0))
                params[f"sc_port_{i}_roll"] = str(pose.get("roll", 0.0))
                params[f"sc_port_{i}_pitch"] = str(pose.get("pitch", 0.0))
                params[f"sc_port_{i}_yaw"] = str(pose.get("yaw", 0.0))
            else:
                params[f"sc_port_{i}_present"] = "false"

        # Mount rails (lc, sfp, sc) 0-1
        for rail_type in ["lc_mount", "sfp_mount", "sc_mount"]:
            for i in range(2):
                rail_key = f"{rail_type}_rail_{i}"
                rail = tb_config.get(rail_key, {})
                if rail.get("entity_present", False):
                    params[f"{rail_type}_{i}_present"] = "true"
                    pose = rail.get("entity_pose", {})
                    params[f"{rail_type}_{i}_translation"] = str(pose.get("translation", 0.0))
                    params[f"{rail_type}_{i}_roll"] = str(pose.get("roll", 0.0))
                    params[f"{rail_type}_{i}_pitch"] = str(pose.get("pitch", 0.0))
                    params[f"{rail_type}_{i}_yaw"] = str(pose.get("yaw", 0.0))
                else:
                    params[f"{rail_type}_{i}_present"] = "false"

        return params

    def _tare_ft_sensor(self) -> None:
        """Tare the force-torque sensor."""
        if not self._tare_ft_client.wait_for_service(timeout_sec=5.0):
            self._logger.warn("Tare FT service not available, skipping")
            return
        req = Trigger.Request()
        future = self._tare_ft_client.call_async(req)
        start = time.monotonic()
        while not future.done() and (time.monotonic() - start) < 10.0:
            time.sleep(0.05)

    def _get_gripper_transform(self) -> Optional[TransformStamped]:
        """Get current gripper pose from TF."""
        try:
            tf = self._tf_buffer.lookup_transform("world", "gripper/tcp", time=tf2_ros.Time())
            return tf.transform
        except Exception as e:
            self._logger.error(f"TF lookup failed: {e}")
            return None
