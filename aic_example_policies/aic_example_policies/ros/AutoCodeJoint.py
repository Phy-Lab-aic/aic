# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""AutoCodeJoint: Joint IK approach + Cartesian insertion with XY integrator.

Phase 1 — JointMotionUpdate (IK):
  calc_gripper_pose()로 hover 목표 계산, analytical IK로 joint 목표 변환.
  /autocode_joint/joint_target (sensor_msgs/JointState) 토픽이 발행 중이면
  그 값을 우선 사용하고, 없으면 내부 IK 폴백.

Phase 2 — MotionUpdate (Cartesian + wrench feedback):
  XY integrator(AutoCode)로 동적 XY 보정 유지.
  접촉 감지(>16N, 0.3s) 시 8mm 백오프.
  패널티 누적(20N 초과 0.8s) 시 중단.
"""

import math
import threading

import numpy as np

from aic_control_interfaces.msg import JointMotionUpdate, TrajectoryGenerationMode
from aic_model.policy import (
    GetObservationCallback,
    MoveRobotCallback,
    Policy,
    SendFeedbackCallback,
)
from aic_task_interfaces.msg import Task
from geometry_msgs.msg import Point, Pose, Quaternion, Transform
from rclpy.duration import Duration
from rclpy.time import Time
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from tf2_ros import TransformException
from transforms3d._gohlketransforms import quaternion_multiply, quaternion_slerp
from transforms3d.quaternions import mat2quat, quat2mat

JOINT_TARGET_TOPIC = "/autocode_joint/joint_target"

_BASE_FRAME  = "base_link"
_TCP_FRAME   = "gripper/tcp"
_TOOL0_FRAME = "tool0"

# UR5e DH parameters
_D     = [0.1625, 0,       0,       0.1333,  0.0997, 0.0996]
_A     = [0,     -0.4250, -0.3922,  0,       0,      0     ]
_ALPHA = [math.pi/2, 0,   0,       math.pi/2, -math.pi/2, 0]
_RZ_PI = np.diag([-1.0, -1.0, 1.0, 1.0])


# ---------------------------------------------------------------------------
# FK / IK
# ---------------------------------------------------------------------------

def _ur5e_ik_solutions(T_tool0_in_dh):
    T = T_tool0_in_dh
    d1, d4, d5, d6 = _D[0], _D[3], _D[4], _D[5]
    a1, a2 = _A[1], _A[2]
    solutions = []
    p05x = T[0, 3] - d6 * T[0, 2]
    p05y = T[1, 3] - d6 * T[1, 2]
    p05z = T[2, 3] - d6 * T[2, 2]
    r_xy = math.hypot(p05x, p05y)
    if r_xy < 1e-9 or abs(d4 / r_xy) > 1.0:
        return solutions
    phi = math.atan2(p05y, p05x)
    psi = math.asin(d4 / r_xy)
    for t1 in [phi + psi, phi + math.pi - psi]:
        c1, s1 = math.cos(t1), math.sin(t1)
        cos_t5 = float(np.clip(s1 * T[0, 2] - c1 * T[1, 2], -1.0, 1.0))
        for t5 in [math.acos(cos_t5), -math.acos(cos_t5)]:
            s5 = math.sin(t5)
            if abs(s5) < 1e-6:
                t6 = 0.0
            else:
                n = -(s1 * T[0, 1] - c1 * T[1, 1])
                m = s1 * T[0, 0] - c1 * T[1, 0]
                t6 = math.atan2(n, m) if s5 > 0 else math.atan2(-n, -m)
            c5, c6, s6 = math.cos(t5), math.cos(t6), math.sin(t6)
            R01T = np.array([[c1, s1, 0.0], [0.0, 0.0, 1.0], [s1, -c1, 0.0]])
            R46  = np.array([[c5*c6, -c5*s6, -s5], [s5*c6, -s5*s6, c5], [-s6, -c6, 0.0]])
            R14  = R01T @ T[:3, :3] @ R46.T
            th234 = math.atan2(R14[0, 2], -R14[1, 2])
            s234, c234 = math.sin(th234), math.cos(th234)
            x_wc = c1 * p05x + s1 * p05y
            y_wc = p05z - d1
            px23 = x_wc - d5 * s234
            py23 = y_wc + d5 * c234
            c3val = (px23**2 + py23**2 - a1**2 - a2**2) / (2.0 * a1 * a2)
            if abs(c3val) > 1.0:
                continue
            for t3 in [math.acos(float(np.clip(c3val, -1.0, 1.0))),
                       -math.acos(float(np.clip(c3val, -1.0, 1.0)))]:
                c3, s3 = math.cos(t3), math.sin(t3)
                t2 = math.atan2(py23, px23) - math.atan2(a2 * s3, a1 + a2 * c3)
                solutions.append(np.array([t1, t2, t3, th234 - t2 - t3, t5, t6]))
    return solutions


def _tf_to_matrix(tf_stamped):
    t = tf_stamped.transform.translation
    r = tf_stamped.transform.rotation
    T = np.eye(4)
    T[:3, :3] = quat2mat([r.w, r.x, r.y, r.z])
    T[:3, 3]  = [t.x, t.y, t.z]
    return T


def _pose_to_matrix(pose):
    r = pose.orientation
    T = np.eye(4)
    T[:3, :3] = quat2mat([r.w, r.x, r.y, r.z])
    T[:3, 3]  = [pose.position.x, pose.position.y, pose.position.z]
    return T


def _best_ik(T_tcp_in_base, T_tool, q_ref):
    T_tool0 = T_tcp_in_base @ np.linalg.inv(T_tool)
    cands = _ur5e_ik_solutions(_RZ_PI @ T_tool0)
    if not cands:
        return None
    for q in cands:
        q[:] = (q + math.pi) % (2 * math.pi) - math.pi
    return min(cands, key=lambda q: float(np.sum((q - q_ref) ** 2)))


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class AutoCodeJoint(Policy):
    """Joint IK approach + Cartesian insertion with XY integrator.

    Phase 1에서 /autocode_joint/joint_target 토픽이 있으면 그 값을 우선 사용.
    토픽 없으면 내부 IK로 폴백 — 단독 실행 시에도 정상 동작.
    """

    def __init__(self, parent_node):
        self._task = None
        self._T_tool = None
        self._tip_x_error_integrator = 0.0
        self._tip_y_error_integrator = 0.0
        self._max_integrator_windup  = 0.05
        self._latest_joint_target: np.ndarray | None = None
        self._joint_target_lock = threading.Lock()
        self._insertion_detected = False
        super().__init__(parent_node)
        self._joint_sub = self._parent_node.create_subscription(
            JointState,
            JOINT_TARGET_TOPIC,
            self._joint_target_callback,
            10,
        )
        self._insertion_sub = self._parent_node.create_subscription(
            String,
            "/scoring/insertion_event",
            lambda msg: setattr(self, "_insertion_detected", True),
            10,
        )
        self.get_logger().info(
            f"AutoCodeJoint: subscribed to '{JOINT_TARGET_TOPIC}' (optional)")

    def _joint_target_callback(self, msg: JointState) -> None:
        if len(msg.position) < 6:
            return
        with self._joint_target_lock:
            self._latest_joint_target = np.array(msg.position[:6], dtype=float)

    def _get_joint_target(self) -> np.ndarray | None:
        with self._joint_target_lock:
            return self._latest_joint_target.copy() \
                if self._latest_joint_target is not None else None

    # ------------------------------------------------------------------
    # TF helpers
    # ------------------------------------------------------------------

    def _wait_for_tf(self, target_frame, source_frame, timeout_sec=10.0):
        start, timeout, attempt = self.time_now(), Duration(seconds=timeout_sec), 0
        while (self.time_now() - start) < timeout:
            try:
                self._parent_node._tf_buffer.lookup_transform(target_frame, source_frame, Time())
                return True
            except TransformException:
                if attempt % 20 == 0:
                    self.get_logger().info(f"Waiting for TF: '{source_frame}' → '{target_frame}'")
                attempt += 1
                self.sleep_for(0.1)
        self.get_logger().error(f"TF '{source_frame}' not available after {timeout_sec}s")
        return False

    def _cache_tool_transform(self):
        try:
            tf = self._parent_node._tf_buffer.lookup_transform(_TOOL0_FRAME, _TCP_FRAME, Time())
            self._T_tool = _tf_to_matrix(tf)
            return True
        except TransformException as ex:
            self.get_logger().error(f"Cannot cache tool transform: {ex}")
            return False

    # ------------------------------------------------------------------
    # calc_gripper_pose (XY integrator 포함)
    # ------------------------------------------------------------------

    def calc_gripper_pose(
        self,
        port_transform: Transform,
        slerp_fraction: float = 1.0,
        position_fraction: float = 1.0,
        z_offset: float = 0.1,
        reset_xy_integrator: bool = False,
    ) -> Pose:
        """Find the gripper pose that results in plug alignment."""
        q_port = (
            port_transform.rotation.w,
            port_transform.rotation.x,
            port_transform.rotation.y,
            port_transform.rotation.z,
        )
        plug_tf_stamped = self._parent_node._tf_buffer.lookup_transform(
            "base_link",
            f"{self._task.cable_name}/{self._task.plug_name}_link",
            Time(),
        )
        q_plug = (
            plug_tf_stamped.transform.rotation.w,
            plug_tf_stamped.transform.rotation.x,
            plug_tf_stamped.transform.rotation.y,
            plug_tf_stamped.transform.rotation.z,
        )
        q_plug_inv = (-q_plug[0], q_plug[1], q_plug[2], q_plug[3])
        q_diff = quaternion_multiply(q_port, q_plug_inv)

        gripper_tf_stamped = self._parent_node._tf_buffer.lookup_transform(
            "base_link", "gripper/tcp", Time()
        )
        q_gripper = (
            gripper_tf_stamped.transform.rotation.w,
            gripper_tf_stamped.transform.rotation.x,
            gripper_tf_stamped.transform.rotation.y,
            gripper_tf_stamped.transform.rotation.z,
        )
        q_gripper_target = quaternion_multiply(q_diff, q_gripper)
        q_gripper_slerp  = quaternion_slerp(q_gripper, q_gripper_target, slerp_fraction)

        gripper_xyz = (
            gripper_tf_stamped.transform.translation.x,
            gripper_tf_stamped.transform.translation.y,
            gripper_tf_stamped.transform.translation.z,
        )
        port_xy = (port_transform.translation.x, port_transform.translation.y)
        plug_xyz = (
            plug_tf_stamped.transform.translation.x,
            plug_tf_stamped.transform.translation.y,
            plug_tf_stamped.transform.translation.z,
        )
        plug_tip_gripper_offset = (
            gripper_xyz[0] - plug_xyz[0],
            gripper_xyz[1] - plug_xyz[1],
            gripper_xyz[2] - plug_xyz[2],
        )

        tip_x_error = port_xy[0] - plug_xyz[0]
        tip_y_error = port_xy[1] - plug_xyz[1]

        if reset_xy_integrator:
            self._tip_x_error_integrator = 0.0
            self._tip_y_error_integrator = 0.0
        else:
            self._tip_x_error_integrator = np.clip(
                self._tip_x_error_integrator + tip_x_error,
                -self._max_integrator_windup,
                self._max_integrator_windup,
            )
            self._tip_y_error_integrator = np.clip(
                self._tip_y_error_integrator + tip_y_error,
                -self._max_integrator_windup,
                self._max_integrator_windup,
            )

        i_gain = 0.15
        target_x = port_xy[0] + i_gain * self._tip_x_error_integrator
        target_y = port_xy[1] + i_gain * self._tip_y_error_integrator
        target_z = port_transform.translation.z + z_offset - plug_tip_gripper_offset[2]

        blend_xyz = (
            position_fraction * target_x + (1.0 - position_fraction) * gripper_xyz[0],
            position_fraction * target_y + (1.0 - position_fraction) * gripper_xyz[1],
            position_fraction * target_z + (1.0 - position_fraction) * gripper_xyz[2],
        )

        return Pose(
            position=Point(x=blend_xyz[0], y=blend_xyz[1], z=blend_xyz[2]),
            orientation=Quaternion(
                w=q_gripper_slerp[0],
                x=q_gripper_slerp[1],
                y=q_gripper_slerp[2],
                z=q_gripper_slerp[3],
            ),
        )

    # ------------------------------------------------------------------
    # Joint motion helper
    # ------------------------------------------------------------------

    def _send_joint_target(self, move_robot, jmu, target_pose, q):
        q_next = _best_ik(_pose_to_matrix(target_pose), self._T_tool, q)
        if q_next is None:
            self.get_logger().warn("No IK solution — holding current q")
            q_next = q.copy()
        jmu.target_state.positions = list(q_next)
        try:
            move_robot(joint_motion_update=jmu)
        except Exception as ex:
            self.get_logger().info(f"move_robot exception: {ex}")
        return q_next

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def insert_cable(self, task, get_observation, move_robot, send_feedback):
        self.get_logger().info(f"AutoCodeJoint.insert_cable() task: {task}")
        self._task = task

        port_frame      = f"task_board/{task.target_module_name}/{task.port_name}_link"
        cable_tip_frame = f"{task.cable_name}/{task.plug_name}_link"

        for frame in [port_frame, cable_tip_frame, _TOOL0_FRAME, _TCP_FRAME]:
            if not self._wait_for_tf(_BASE_FRAME, frame):
                return False
        if not self._cache_tool_transform():
            return False

        obs = get_observation()
        q   = np.array(obs.joint_states.position[:6], dtype=float)

        try:
            port_tf_stamped = self._parent_node._tf_buffer.lookup_transform(
                _BASE_FRAME, port_frame, Time())
        except TransformException as ex:
            self.get_logger().error(f"Port TF lookup failed: {ex}")
            return False
        port_transform = port_tf_stamped.transform

        # --- Phase 1: Joint approach ---
        # 토픽 값이 있으면 우선 사용, 없으면 내부 IK
        # Joint 접근 중엔 인테그레이터 누적 불필요 — reset_xy_integrator=True 유지
        jmu = JointMotionUpdate(
            target_stiffness=[200.0, 200.0, 200.0, 100.0, 100.0, 100.0],
            target_damping=[40.0, 40.0, 40.0, 15.0, 15.0, 15.0],
            trajectory_generation_mode=TrajectoryGenerationMode(
                mode=TrajectoryGenerationMode.MODE_POSITION),
        )
        self.get_logger().info("Phase 1: Joint approach...")
        for t in range(50):
            frac = t / 50.0
            q_topic = self._get_joint_target()
            if q_topic is not None:
                jmu.target_state.positions = list(q_topic)
                try:
                    move_robot(joint_motion_update=jmu)
                    q = q_topic
                except Exception as ex:
                    self.get_logger().info(f"move_robot exception: {ex}")
            else:
                try:
                    target_pose = self.calc_gripper_pose(
                        port_transform,
                        slerp_fraction=frac,
                        position_fraction=frac,
                        z_offset=0.15,
                        reset_xy_integrator=True,  # Joint 접근 중엔 항상 리셋
                    )
                    q = self._send_joint_target(move_robot, jmu, target_pose, q)
                except Exception as ex:
                    self.get_logger().warn(f"Phase 1 error: {ex}")
            self.sleep_for(0.05)

        # --- FT tare ---
        self.get_logger().info("FT tare...")
        tare_x = tare_y = tare_z = 0.0
        for _ in range(10):
            obs = get_observation()
            tare_x += obs.wrist_wrench.wrench.force.x
            tare_y += obs.wrist_wrench.wrench.force.y
            tare_z += obs.wrist_wrench.wrench.force.z
            self.sleep_for(0.05)
        tare_x /= 10; tare_y /= 10; tare_z /= 10
        self.get_logger().info(
            f"FT tare: [{tare_x:.1f}, {tare_y:.1f}, {tare_z:.1f}] N")

        # --- XY 인테그레이터 워밍업 홀드 (AutoCode 패턴) ---
        self.get_logger().info("XY integrator warm-up hold (1s)...")
        for _ in range(20):
            try:
                self.set_pose_target(
                    move_robot=move_robot,
                    pose=self.calc_gripper_pose(port_transform, z_offset=0.15),
                )
            except TransformException as ex:
                self.get_logger().warn(f"TF failed during hold: {ex}")
            self.sleep_for(0.05)

        # --- Phase 2: Cartesian 삽입 + wrench feedback + XY integrator ---
        self.get_logger().info("Phase 2: Cartesian insertion...")

        _INSERTED_DIST     = 0.003
        _PENALTY_FORCE_LVL = 20.0
        _PENALTY_BUDGET    = 0.8
        _CONTACT_THRESH    = 16.0
        _PENALTY_WINDOW    = 0.3
        _DESCENT_STEP_FAR  = 0.001   # 20mm/s (원거리도 안정적 하강)
        _DESCENT_STEP_NEAR = 0.001   # 20mm/s (근접: 백오프 로직이 보호)
        _BACKOFF_STEP      = 0.008
        _MAX_STEPS         = 500
        _NEAR_DIST         = 0.06    # 60mm 이내부터 정밀 제어 (smoothness 향상)

        z_offset                = 0.15
        above_thresh_time       = 0.0
        cumulative_penalty_time = 0.0
        self._insertion_detected = False
        baseline_align_err = max(abs(self._tip_x_error_integrator),
                                 abs(self._tip_y_error_integrator))
        descent_step = 0

        for step in range(_MAX_STEPS):
            if z_offset < -0.015:
                self.get_logger().warn("z_offset safety limit reached.")
                break

            # 삽입 완료: /scoring/insertion_event 토픽 또는 TF dist 둘 다 감지
            dist = None
            try:
                plug_tf = self._parent_node._tf_buffer.lookup_transform(
                    _BASE_FRAME, cable_tip_frame, Time())
                port_tf_now = self._parent_node._tf_buffer.lookup_transform(
                    _BASE_FRAME, port_frame, Time())
                dx = plug_tf.transform.translation.x - port_tf_now.transform.translation.x
                dy = plug_tf.transform.translation.y - port_tf_now.transform.translation.y
                dz = plug_tf.transform.translation.z - port_tf_now.transform.translation.z
                dist = math.sqrt(dx**2 + dy**2 + dz**2)
            except TransformException:
                pass

            if self._insertion_detected:
                self.get_logger().info("Insertion event received — done!")
                break
            if dist is not None and dist < _INSERTED_DIST:
                self.get_logger().info(f"Insertion detected via TF! dist={dist*1000:.1f} mm")
                break

            # 힘 측정
            obs = get_observation()
            f   = obs.wrist_wrench.wrench.force
            contact_force = math.sqrt(
                (f.x - tare_x)**2 + (f.y - tare_y)**2 + (f.z - tare_z)**2)

            # 패널티 누적 추적
            if contact_force >= _PENALTY_FORCE_LVL:
                cumulative_penalty_time += 0.05
                if cumulative_penalty_time >= _PENALTY_BUDGET:
                    self.get_logger().warn(
                        f"Force budget reached ({cumulative_penalty_time:.2f}s) — stopping.")
                    break
            else:
                cumulative_penalty_time = max(0.0, cumulative_penalty_time - 0.02)

            # 하강 판단
            if dist is None or dist > _NEAR_DIST:
                z_offset -= _DESCENT_STEP_FAR
                above_thresh_time = 0.0
            else:
                # 근접: FT 기반 정밀 제어
                if contact_force >= _CONTACT_THRESH:
                    above_thresh_time += 0.05
                    if above_thresh_time >= _PENALTY_WINDOW:
                        z_offset = min(z_offset + _BACKOFF_STEP, 0.15)
                        above_thresh_time = 0.0
                        self.get_logger().warn(f"Contact — backoff z={z_offset:.4f}")
                else:
                    above_thresh_time = 0.0
                    z_offset -= _DESCENT_STEP_NEAR

            self.get_logger().info(
                f"step={step} z={z_offset:.4f}  "
                f"dist={'N/A' if dist is None else f'{dist*1000:.1f}mm'}  "
                f"contact={contact_force:.1f}N  penalty_t={cumulative_penalty_time:.2f}s")

            # Cartesian 목표 (XY integrator 포함)
            try:
                self.set_pose_target(
                    move_robot=move_robot,
                    pose=self.calc_gripper_pose(port_transform, z_offset=z_offset),
                    stiffness=[50.0, 50.0, 90.0, 30.0, 30.0, 50.0],
                    damping=[35.0, 35.0, 50.0, 15.0, 15.0, 25.0],
                )
            except TransformException as ex:
                self.get_logger().warn(f"TF failed during insertion: {ex}")
            self.sleep_for(0.05)
            descent_step += 1

            # 80스텝마다 정렬 상태 확인, 열화 시 재정렬 홀드 (AutoCode 패턴)
            if descent_step % 80 == 0:
                current_align_err = max(abs(self._tip_x_error_integrator),
                                        abs(self._tip_y_error_integrator))
                if current_align_err > baseline_align_err * 1.3:
                    self.get_logger().info(
                        f"Alignment degraded ({current_align_err:.4f} > {baseline_align_err:.4f}), re-aligning...")
                    for _ in range(10):
                        try:
                            self.set_pose_target(
                                move_robot=move_robot,
                                pose=self.calc_gripper_pose(port_transform, z_offset=z_offset),
                                stiffness=[50.0, 50.0, 90.0, 30.0, 30.0, 50.0],
                                damping=[35.0, 35.0, 50.0, 15.0, 15.0, 25.0],
                            )
                        except TransformException:
                            pass
                        self.sleep_for(0.05)
                    baseline_align_err = max(abs(self._tip_x_error_integrator),
                                             abs(self._tip_y_error_integrator))

        self.get_logger().info("AutoCodeJoint.insert_cable() done.")
        return True
