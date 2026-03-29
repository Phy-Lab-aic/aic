"""Main orchestrator node for automated data collection."""

import threading
import time
from typing import Optional

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup

from aic_task_interfaces.action import InsertCable
from aic_task_interfaces.msg import Task
from lifecycle_msgs.srv import ChangeState
from lifecycle_msgs.msg import Transition
from sensor_msgs.msg import Image
from std_msgs.msg import String
import tf2_ros

from .completion_monitor import CompletionResult, check_tf_completion
from .homing_manager import HomingManager
from .rosbag_manager import RosbagManager
from .scene_manager import SceneManager
from .trial_config_provider import StaticTrialProvider


class AutoDataCollector(Node):
    """Orchestrates automated data collection across multiple episodes."""

    def __init__(self):
        super().__init__("auto_data_collector")

        # Declare parameters
        self.declare_parameter("config_file", "")
        self.declare_parameter("trial_mode", "static")
        self.declare_parameter("trials", [""])
        self.declare_parameter("target_episodes", 10)
        self.declare_parameter("max_attempts", 0)  # 0 = target × 3
        self.declare_parameter("task_timeout_sec", 180.0)
        self.declare_parameter("bag_output_dir", "bags")
        self.declare_parameter("completion_distance_threshold", 0.005)
        self.declare_parameter("completion_orientation_threshold", 0.1)

        # Read parameters
        config_file = self.get_parameter("config_file").get_parameter_value().string_value
        if not config_file:
            self.get_logger().fatal("config_file parameter is required")
            raise ValueError("config_file parameter is required")

        trial_names_param = self.get_parameter("trials").get_parameter_value().string_array_value
        trial_names = [t for t in trial_names_param if t] or None

        self._target_episodes = self.get_parameter("target_episodes").get_parameter_value().integer_value
        max_attempts = self.get_parameter("max_attempts").get_parameter_value().integer_value
        self._max_attempts = max_attempts if max_attempts > 0 else self._target_episodes * 3
        self._task_timeout = self.get_parameter("task_timeout_sec").get_parameter_value().double_value
        bag_dir = self.get_parameter("bag_output_dir").get_parameter_value().string_value
        self._dist_threshold = self.get_parameter("completion_distance_threshold").get_parameter_value().double_value
        self._orient_threshold = self.get_parameter("completion_orientation_threshold").get_parameter_value().double_value

        # Initialize components
        trial_mode = self.get_parameter("trial_mode").get_parameter_value().string_value
        if trial_mode == "dynamic":
            from .trial_config_provider import DynamicTrialProvider
            base_trial = trial_names[0] if trial_names else None
            if not base_trial:
                raise ValueError("dynamic mode requires at least one trial name as base_trial")
            self._trial_provider = DynamicTrialProvider(config_file, base_trial=base_trial)
        else:
            self._trial_provider = StaticTrialProvider(config_file, trials=trial_names)

        self._rosbag = RosbagManager(output_dir=bag_dir)
        self._scene = SceneManager(self)
        self._homing = HomingManager(self, self._trial_provider.home_joint_positions)

        # Camera dummy subscribers (activates lazy bridge for video topics)
        self._camera_subs = []
        for topic in ["/left_camera/image", "/center_camera/image", "/right_camera/image"]:
            sub = self.create_subscription(Image, topic, lambda msg: None, 1)
            self._camera_subs.append(sub)
        self.get_logger().info("Camera dummy subscribers created (lazy bridge activated)")

        # InsertCable action client
        self._cb_group = ReentrantCallbackGroup()
        self._insert_cable_client = ActionClient(
            self, InsertCable, "/insert_cable", callback_group=self._cb_group
        )

        # Completion monitoring state
        self._insertion_event_received = False
        self._insertion_event_sub = self.create_subscription(
            String, "/scoring/insertion_event", self._on_insertion_event, 10
        )

        # TF for completion check
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        # aic_model lifecycle client
        self._model_change_state = self.create_client(ChangeState, "/aic_model/change_state")

        # Stats
        self._successful = 0
        self._failed = 0
        self._fail_reasons: dict[str, int] = {}

    def _on_insertion_event(self, msg: String) -> None:
        self._insertion_event_received = True
        self.get_logger().info(f"Insertion event received: {msg.data}")

    def _activate_model(self) -> bool:
        """Configure and activate aic_model lifecycle node."""
        if not self._model_change_state.wait_for_service(timeout_sec=30.0):
            self.get_logger().error("aic_model lifecycle service not available")
            return False

        # Configure
        req = ChangeState.Request()
        req.transition = Transition(id=Transition.TRANSITION_CONFIGURE)
        future = self._model_change_state.call_async(req)
        self._poll_future(future, 30.0)
        if not future.done() or not future.result().success:
            self.get_logger().error("Failed to configure aic_model")
            return False

        # Activate
        req = ChangeState.Request()
        req.transition = Transition(id=Transition.TRANSITION_ACTIVATE)
        future = self._model_change_state.call_async(req)
        self._poll_future(future, 30.0)
        if not future.done() or not future.result().success:
            self.get_logger().error("Failed to activate aic_model")
            return False

        self.get_logger().info("aic_model activated")
        return True

    def _send_insert_cable(self, task_config: dict) -> Optional[bool]:
        """Send InsertCable action goal. Returns True=success, False=fail, None=timeout."""
        if not self._insert_cable_client.wait_for_action_server(timeout_sec=10.0):
            self.get_logger().error("InsertCable action server not available")
            return False

        goal = InsertCable.Goal()
        goal.task = Task()
        goal.task.id = task_config.get("cable_name", "task_1")
        goal.task.cable_type = task_config["cable_type"]
        goal.task.cable_name = task_config["cable_name"]
        goal.task.plug_type = task_config["plug_type"]
        goal.task.plug_name = task_config["plug_name"]
        goal.task.port_type = task_config["port_type"]
        goal.task.port_name = task_config["port_name"]
        goal.task.target_module_name = task_config["target_module_name"]
        goal.task.time_limit = int(self._task_timeout)

        send_goal_future = self._insert_cable_client.send_goal_async(goal)
        self._poll_future(send_goal_future, 10.0)
        if not send_goal_future.done():
            return None
        goal_handle = send_goal_future.result()
        if not goal_handle or not goal_handle.accepted:
            self.get_logger().error("InsertCable goal rejected")
            return False

        result_future = goal_handle.get_result_async()
        self._poll_future(result_future, self._task_timeout)
        if not result_future.done():
            self.get_logger().warn("InsertCable action timed out, cancelling")
            goal_handle.cancel_goal_async()
            return None
        result = result_future.result()
        return result.result.success if result else False

    def _check_completion(self, task_config: dict) -> CompletionResult:
        """Evaluate task completion using insertion_event + TF."""
        if not self._insertion_event_received:
            return CompletionResult.TIMEOUT

        # TF check
        plug_frame = f"{task_config['cable_name']}/{task_config['plug_name']}_link"
        port_frame = f"task_board/{task_config['target_module_name']}/{task_config['port_name']}_link"
        try:
            plug_tf = self._tf_buffer.lookup_transform("base_link", plug_frame, tf2_ros.Time())
            port_tf = self._tf_buffer.lookup_transform("base_link", port_frame, tf2_ros.Time())
            plug_pos = (plug_tf.transform.translation.x, plug_tf.transform.translation.y, plug_tf.transform.translation.z)
            port_pos = (port_tf.transform.translation.x, port_tf.transform.translation.y, port_tf.transform.translation.z)
            plug_quat = (plug_tf.transform.rotation.x, plug_tf.transform.rotation.y, plug_tf.transform.rotation.z, plug_tf.transform.rotation.w)
            port_quat = (port_tf.transform.rotation.x, port_tf.transform.rotation.y, port_tf.transform.rotation.z, port_tf.transform.rotation.w)

            if check_tf_completion(plug_pos, port_pos, plug_quat, port_quat,
                                   self._dist_threshold, self._orient_threshold):
                return CompletionResult.SUCCESS
            else:
                self.get_logger().warn("insertion_event received but TF check failed")
                return CompletionResult.PARTIAL
        except Exception as e:
            self.get_logger().warn(f"TF lookup failed: {e}, treating as PARTIAL")
            return CompletionResult.PARTIAL

    def _poll_future(self, future, timeout: float) -> None:
        """Poll a future until done or timeout (avoids executor deadlock)."""
        start = time.monotonic()
        while not future.done() and (time.monotonic() - start) < timeout:
            time.sleep(0.05)

    def run_collection(self) -> None:
        """Main collection loop."""
        self.get_logger().info(f"Starting collection: target={self._target_episodes}, max_attempts={self._max_attempts}")

        # Activate aic_model once
        if not self._activate_model():
            self.get_logger().fatal("Cannot activate aic_model, aborting")
            return

        attempt = 0
        while self._successful < self._target_episodes and attempt < self._max_attempts:
            attempt += 1
            trial = self._trial_provider.get_next_trial()
            trial_id = trial["trial_id"]
            episode_id = f"{trial_id}_ep{attempt:04d}"

            self.get_logger().info(f"\n{'='*50}")
            self.get_logger().info(f"Episode {attempt}/{self._max_attempts} ({self._successful}/{self._target_episodes} success) - {trial_id}")
            self.get_logger().info(f"{'='*50}")

            # Reset completion state
            self._insertion_event_received = False

            # 1. Spawn scene
            if not self._scene.spawn_scene(trial):
                self._record_failure("spawn_failed")
                continue

            # 2. Start recording
            self._rosbag.start(episode_id)

            # 3. Execute task (first task in trial)
            first_task_key = list(trial["tasks"].keys())[0]
            task_config = trial["tasks"][first_task_key]
            action_result = self._send_insert_cable(task_config)

            # 4. Check completion
            if action_result is None:
                completion = CompletionResult.TIMEOUT
            elif action_result is False:
                completion = CompletionResult.ACTION_FAILED
            else:
                completion = self._check_completion(task_config)

            # 5. Stop recording
            success = completion.is_success()
            bag_path = self._rosbag.stop(success=success)
            self.get_logger().info(f"Bag saved: {bag_path} (result: {completion.value})")

            # 6. Update stats
            if success:
                self._successful += 1
            else:
                self._record_failure(completion.value)

            # 7. Despawn + home
            self._scene.despawn_scene()
            if not self._homing.home_robot():
                self.get_logger().error("Homing failed!")

        self._print_summary()

    def _record_failure(self, reason: str) -> None:
        self._failed += 1
        self._fail_reasons[reason] = self._fail_reasons.get(reason, 0) + 1

    def _print_summary(self) -> None:
        total = self._successful + self._failed
        self.get_logger().info(f"\n{'='*50}")
        self.get_logger().info("=== Data Collection Summary ===")
        self.get_logger().info(f"Total attempts: {total}")
        target_msg = "target reached" if self._successful >= self._target_episodes else "target NOT reached"
        self.get_logger().info(f"Successful episodes: {self._successful} / {self._target_episodes} ({target_msg})")
        self.get_logger().info(f"Failed episodes: {self._failed}")
        for reason, count in self._fail_reasons.items():
            self.get_logger().info(f"  - {reason}: {count}")


def main(args=None):
    rclpy.init(args=args)
    node = AutoDataCollector()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        node.run_collection()
    finally:
        node.destroy_node()
        rclpy.shutdown()
