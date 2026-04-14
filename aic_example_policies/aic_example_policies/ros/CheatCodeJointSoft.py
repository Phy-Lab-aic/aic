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

"""Joint-space policy with very low insertion stiffness for physical compliance.

Phase 1 & 1.5 — JointMotionUpdate stiffness [150,150,150] (접근 정확도 유지)
Phase 2       — JointMotionUpdate stiffness [15,15,15] (매우 낮음)
  • 임피던스 컨트롤러가 물리적으로 순응 → 접촉 시 힘 자연 제한
  • 백오프 로직 제거: compliance 자체가 힘을 흡수하므로 불필요
  • 단순 하강(dist < 3mm 감지 또는 z_offset 한계까지)
  • 안전망: 20N 누적 0.8s 초과 시 중단
"""

import math

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
from tf2_ros import TransformException
from transforms3d._gohlketransforms import quaternion_multiply, quaternion_slerp
from transforms3d.quaternions import quat2mat

QuaternionTuple = tuple[float, float, float, float]

_BASE_FRAME  = "base_link"
_TCP_FRAME   = "gripper/tcp"
_TOOL0_FRAME = "tool0"

_D     = [0.1625, 0,       0,       0.1333,  0.0997, 0.0996]
_A     = [0,     -0.4250, -0.3922,  0,       0,      0     ]
_ALPHA = [math.pi/2, 0,   0,       math.pi/2, -math.pi/2, 0]
_RZ_PI = np.diag([-1.0, -1.0, 1.0, 1.0])


def _dh_matrix(a, d, alpha, theta):
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array([
        [ct, -st * ca,  st * sa, a * ct],
        [st,  ct * ca, -ct * sa, a * st],
        [0,   sa,       ca,      d     ],
        [0,   0,        0,       1     ],
    ])


def _ur5e_fk(q):
    T = np.eye(4)
    for i in range(6):
        T = T @ _dh_matrix(_A[i], _D[i], _ALPHA[i], q[i])
    return _RZ_PI @ T


def _ur5e_ik_solutions(T_tool0_in_dh):
    T   = T_tool0_in_dh
    d1  = _D[0]; d4 = _D[3]; d5 = _D[4]; d6 = _D[5]
    a1  = _A[1]; a2 = _A[2]
    solutions = []
    p05x = T[0, 3] - d6 * T[0, 2]
    p05y = T[1, 3] - d6 * T[1, 2]
    p05z = T[2, 3] - d6 * T[2, 2]
    r_xy = math.hypot(p05x, p05y)
    if r_xy < 1e-9:
        return solutions
    arg = d4 / r_xy
    if abs(arg) > 1.0:
        return solutions
    phi = math.atan2(p05y, p05x)
    psi = math.asin(arg)
    for t1 in [phi + psi, phi + math.pi - psi]:
        c1, s1 = math.cos(t1), math.sin(t1)
        cos_t5 = float(np.clip(s1 * T[0, 2] - c1 * T[1, 2], -1.0, 1.0))
        t5_abs = math.acos(cos_t5)
        for t5 in [t5_abs, -t5_abs]:
            s5 = math.sin(t5)
            if abs(s5) < 1e-6:
                t6 = 0.0
            else:
                cos6_s5 = s1 * T[0, 0] - c1 * T[1, 0]
                sin6_s5 = -(s1 * T[0, 1] - c1 * T[1, 1])
                t6 = math.atan2(sin6_s5, cos6_s5) if s5 > 0 else math.atan2(-sin6_s5, -cos6_s5)
            c5, c6, s6 = math.cos(t5), math.cos(t6), math.sin(t6)
            R01T = np.array([[c1, s1, 0.0], [0.0, 0.0, 1.0], [s1, -c1, 0.0]])
            R46  = np.array([[c5*c6, -c5*s6, -s5], [s5*c6, -s5*s6, c5], [-s6, -c6, 0.0]])
            R14  = R01T @ T[:3, :3] @ R46.T
            theta234 = math.atan2(R14[0, 2], -R14[1, 2])
            s234, c234 = math.sin(theta234), math.cos(theta234)
            x_wc = c1 * p05x + s1 * p05y
            y_wc = p05z - d1
            px23 = x_wc - d5 * s234
            py23 = y_wc + d5 * c234
            r2    = px23**2 + py23**2
            c3val = (r2 - a1**2 - a2**2) / (2.0 * a1 * a2)
            if abs(c3val) > 1.0:
                continue
            t3_abs = math.acos(float(np.clip(c3val, -1.0, 1.0)))
            for t3 in [t3_abs, -t3_abs]:
                c3, s3 = math.cos(t3), math.sin(t3)
                t2 = math.atan2(py23, px23) - math.atan2(a2*s3, a1 + a2*c3)
                t4 = theta234 - t2 - t3
                solutions.append(np.array([t1, t2, t3, t4, t5, t6]))
    return solutions


def _best_ik(T_tcp_in_base, T_tool, q_ref):
    T_tool0    = T_tcp_in_base @ np.linalg.inv(T_tool)
    candidates = _ur5e_ik_solutions(_RZ_PI @ T_tool0)
    if not candidates:
        return None
    for q in candidates:
        q[:] = (q + math.pi) % (2 * math.pi) - math.pi
    return min(candidates, key=lambda q: float(np.sum((q - q_ref) ** 2)))


def _pose_to_matrix(pose):
    r = pose.orientation
    T = np.eye(4)
    T[:3, :3] = quat2mat([r.w, r.x, r.y, r.z])
    T[:3, 3]  = [pose.position.x, pose.position.y, pose.position.z]
    return T


def _tf_to_matrix(tf_stamped):
    t = tf_stamped.transform.translation
    r = tf_stamped.transform.rotation
    T = np.eye(4)
    T[:3, :3] = quat2mat([r.w, r.x, r.y, r.z])
    T[:3, 3]  = [t.x, t.y, t.z]
    return T


class CheatCodeJointSoft(Policy):
    """Joint IK throughout, very low insertion stiffness for physical compliance."""

    def __init__(self, parent_node):
        self._tip_x_error_integrator = 0.0
        self._tip_y_error_integrator = 0.0
        self._max_integrator_windup  = 0.05
        self._task   = None
        self._T_tool = None
        super().__init__(parent_node)

    def _wait_for_tf(self, target_frame, source_frame, timeout_sec=10.0):
        start   = self.time_now()
        timeout = Duration(seconds=timeout_sec)
        attempt = 0
        while (self.time_now() - start) < timeout:
            try:
                self._parent_node._tf_buffer.lookup_transform(target_frame, source_frame, Time())
                return True
            except TransformException:
                if attempt % 20 == 0:
                    self.get_logger().info(f"Waiting for '{source_frame}' -> '{target_frame}'")
                attempt += 1
                self.sleep_for(0.1)
        self.get_logger().error(f"Transform '{source_frame}' not available after {timeout_sec}s")
        return False

    def _cache_tool_transform(self):
        try:
            tf = self._parent_node._tf_buffer.lookup_transform(_TOOL0_FRAME, _TCP_FRAME, Time())
            self._T_tool = _tf_to_matrix(tf)
            return True
        except TransformException as ex:
            self.get_logger().error(f"Cannot cache tool transform: {ex}")
            return False

    def calc_gripper_pose(self, port_transform, slerp_fraction=1.0, position_fraction=1.0,
                          z_offset=0.1, reset_xy_integrator=False, freeze_xy_integrator=False):
        q_port = (port_transform.rotation.w, port_transform.rotation.x,
                  port_transform.rotation.y, port_transform.rotation.z)
        plug_tf = self._parent_node._tf_buffer.lookup_transform(
            _BASE_FRAME, f"{self._task.cable_name}/{self._task.plug_name}_link", Time())
        q_plug = (plug_tf.transform.rotation.w, plug_tf.transform.rotation.x,
                  plug_tf.transform.rotation.y, plug_tf.transform.rotation.z)
        q_diff = quaternion_multiply(q_port, (-q_plug[0], q_plug[1], q_plug[2], q_plug[3]))
        gripper_tf = self._parent_node._tf_buffer.lookup_transform(_BASE_FRAME, _TCP_FRAME, Time())
        q_gripper  = (gripper_tf.transform.rotation.w, gripper_tf.transform.rotation.x,
                      gripper_tf.transform.rotation.y, gripper_tf.transform.rotation.z)
        q_slerp = quaternion_slerp(q_gripper, quaternion_multiply(q_diff, q_gripper), slerp_fraction)
        gx = gripper_tf.transform.translation.x
        gy = gripper_tf.transform.translation.y
        gz = gripper_tf.transform.translation.z
        px = plug_tf.transform.translation.x
        py = plug_tf.transform.translation.y
        pz = plug_tf.transform.translation.z
        tip_x_err = port_transform.translation.x - px
        tip_y_err = port_transform.translation.y - py
        if reset_xy_integrator:
            self._tip_x_error_integrator = 0.0
            self._tip_y_error_integrator = 0.0
        elif not freeze_xy_integrator:
            self._tip_x_error_integrator = np.clip(
                self._tip_x_error_integrator + tip_x_err, -self._max_integrator_windup, self._max_integrator_windup)
            self._tip_y_error_integrator = np.clip(
                self._tip_y_error_integrator + tip_y_err, -self._max_integrator_windup, self._max_integrator_windup)
        i_gain = 0.15
        tx = port_transform.translation.x + i_gain * self._tip_x_error_integrator
        ty = port_transform.translation.y + i_gain * self._tip_y_error_integrator
        tz = port_transform.translation.z + z_offset + (gz - pz)
        blend = (
            position_fraction * tx + (1.0 - position_fraction) * gx,
            position_fraction * ty + (1.0 - position_fraction) * gy,
            position_fraction * tz + (1.0 - position_fraction) * gz,
        )
        return Pose(
            position=Point(x=blend[0], y=blend[1], z=blend[2]),
            orientation=Quaternion(w=q_slerp[0], x=q_slerp[1], y=q_slerp[2], z=q_slerp[3]),
        )

    def _send_joint_target(self, move_robot, jmu, target_pose, q):
        T_target = _pose_to_matrix(target_pose)
        q_next   = _best_ik(T_target, self._T_tool, q)
        if q_next is None:
            self.get_logger().warn("No IK solution — holding current q")
            q_next = q.copy()
        jmu.target_state.positions = list(q_next)
        try:
            move_robot(joint_motion_update=jmu)
        except Exception as ex:
            self.get_logger().info(f"move_robot exception: {ex}")
        return q_next

    def insert_cable(self, task, get_observation, move_robot, send_feedback):
        self.get_logger().info(f"CheatCodeJointSoft.insert_cable() task: {task}")
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
            self.get_logger().error(f"Could not look up port transform: {ex}")
            return False
        port_transform = port_tf_stamped.transform

        # --- Phase 1: 접근 — 충분한 stiffness로 정확한 호버 위치 (100 × 50ms) ---
        jmu = JointMotionUpdate(
            target_stiffness=[150.0, 150.0, 150.0, 50.0, 50.0, 50.0],
            target_damping=[35.0, 35.0, 35.0, 12.0, 12.0, 12.0],
            trajectory_generation_mode=TrajectoryGenerationMode(
                mode=TrajectoryGenerationMode.MODE_POSITION),
        )
        z_offset = 0.2
        for t in range(100):
            frac = t / 100.0
            try:
                q = self._send_joint_target(move_robot, jmu,
                    self.calc_gripper_pose(port_transform, slerp_fraction=frac,
                                           position_fraction=frac, z_offset=z_offset,
                                           reset_xy_integrator=True), q)
            except TransformException as ex:
                self.get_logger().warn(f"TF failed during approach: {ex}")
            self.sleep_for(0.05)

        # --- Phase 1.5: Hover — XY 정렬 (40 × 50ms) ---
        self.get_logger().info("Hovering for XY alignment...")
        for _ in range(40):
            try:
                q = self._send_joint_target(move_robot, jmu,
                    self.calc_gripper_pose(port_transform, z_offset=z_offset), q)
            except TransformException as ex:
                self.get_logger().warn(f"TF failed during hover: {ex}")
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

        # --- Phase 2: 매우 낮은 stiffness로 물리적 순응 삽입 ---
        # stiffness [15,15,15]: 관절 오차 0.1 rad당 ~1.5 N·m 토크
        # → 접촉 시 로봇이 물리적으로 순응, 20N 초과 힘 자연 억제
        # 백오프 없음: compliance가 힘을 흡수하므로 그냥 하강
        self.get_logger().info("Soft insertion (physical compliance, no backoff)...")
        jmu.target_stiffness = [15.0, 15.0, 15.0, 6.0, 6.0, 6.0]
        jmu.target_damping   = [5.0,  5.0,  5.0,  2.5, 2.5, 2.5]

        _INSERTED_DIST     = 0.003
        _PENALTY_FORCE_LVL = 20.0
        _PENALTY_BUDGET    = 0.8
        _DESCENT_STEP      = 0.0005
        _MAX_STEPS         = 500

        cumulative_penalty_time = 0.0

        for step in range(_MAX_STEPS):
            if z_offset < -0.06:
                self.get_logger().warn("z_offset safety limit reached.")
                break

            dist = None
            try:
                plug_tf_now = self._parent_node._tf_buffer.lookup_transform(
                    _BASE_FRAME, cable_tip_frame, Time())
                port_tf_now = self._parent_node._tf_buffer.lookup_transform(
                    _BASE_FRAME, port_frame, Time())
                dx = plug_tf_now.transform.translation.x - port_tf_now.transform.translation.x
                dy = plug_tf_now.transform.translation.y - port_tf_now.transform.translation.y
                dz = plug_tf_now.transform.translation.z - port_tf_now.transform.translation.z
                dist = math.sqrt(dx**2 + dy**2 + dz**2)
            except TransformException:
                pass

            if dist is not None and dist < _INSERTED_DIST:
                self.get_logger().info(f"Insertion detected! dist={dist*1000:.1f} mm")
                break

            obs = get_observation()
            f   = obs.wrist_wrench.wrench.force
            contact_force = math.sqrt(
                (f.x - tare_x)**2 + (f.y - tare_y)**2 + (f.z - tare_z)**2)

            # 안전망: 20N 이상이 0.8s 누적 시 중단
            if contact_force >= _PENALTY_FORCE_LVL:
                cumulative_penalty_time += 0.05
                if cumulative_penalty_time >= _PENALTY_BUDGET:
                    self.get_logger().warn(
                        f"Force budget reached ({cumulative_penalty_time:.2f}s) — stopping.")
                    break
            else:
                # 힘이 정상 범위면 누적 타이머 리셋 (일시적 스파이크는 무시)
                cumulative_penalty_time = max(0.0, cumulative_penalty_time - 0.025)

            # 단순 하강: compliance가 힘을 흡수하므로 백오프 불필요
            z_offset -= _DESCENT_STEP

            self.get_logger().info(
                f"z={z_offset:.4f}  dist={'N/A' if dist is None else f'{dist*1000:.1f}mm'}  "
                f"contact={contact_force:.1f}N  penalty_t={cumulative_penalty_time:.2f}s")

            try:
                q = self._send_joint_target(move_robot, jmu,
                    self.calc_gripper_pose(port_transform, z_offset=z_offset,
                                           freeze_xy_integrator=True), q)
            except TransformException as ex:
                self.get_logger().warn(f"TF failed during insertion: {ex}")
            self.sleep_for(0.05)

        self.get_logger().info("Waiting for connector to stabilize...")
        self.sleep_for(5.0)
        self.get_logger().info("CheatCodeJointSoft.insert_cable() exiting...")
        return True
