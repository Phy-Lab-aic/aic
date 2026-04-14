#
#  Copyright (C) 2026 Intrinsic Innovation LLC
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

"""Joint-space version of CheatCode using analytical UR5e IK.

TF에서 target TCP pose를 읽은 뒤, UR5e 해석적 IK (8-solution closed-form)로
즉시 정확한 joint angle을 계산하여 JointMotionUpdate로 전송.

Jacobian 반복 수렴 없음 → singularity/damping/oscillation 문제 해소.
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

# ---------------------------------------------------------------------------
# TF frame names
# ---------------------------------------------------------------------------
_BASE_FRAME  = "base_link"
_TCP_FRAME   = "gripper/tcp"
_TOOL0_FRAME = "tool0"

# ---------------------------------------------------------------------------
# UR5e DH parameters (standard DH convention)
# ---------------------------------------------------------------------------
_D     = [0.1625, 0,       0,       0.1333,  0.0997, 0.0996]
_A     = [0,     -0.4250, -0.3922,  0,       0,      0     ]
_ALPHA = [math.pi/2, 0,   0,       math.pi/2, -math.pi/2, 0]

# Robot is mounted at yaw = π on the table, so DH base frame = Rz(π) @ ROS base_link.
# _RZ_PI converts between the two: T_dh = _RZ_PI @ T_ros, T_ros = _RZ_PI @ T_dh.
_RZ_PI = np.diag([-1.0, -1.0, 1.0, 1.0])


# ---------------------------------------------------------------------------
# Forward kinematics (for verification / logging)
# ---------------------------------------------------------------------------

def _dh_matrix(a: float, d: float, alpha: float, theta: float) -> np.ndarray:
    """Standard DH transform T_{i-1,i}."""
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array([
        [ct, -st * ca,  st * sa, a * ct],
        [st,  ct * ca, -ct * sa, a * st],
        [0,   sa,       ca,      d     ],
        [0,   0,        0,       1     ],
    ])


def _ur5e_fk(q: np.ndarray) -> np.ndarray:
    """FK: returns 4×4 pose of tool0 in base_link frame."""
    T = np.eye(4)
    for i in range(6):
        T = T @ _dh_matrix(_A[i], _D[i], _ALPHA[i], q[i])
    return _RZ_PI @ T


# ---------------------------------------------------------------------------
# Analytical UR5e IK  (8 closed-form solutions)
# ---------------------------------------------------------------------------

def _ur5e_ik_solutions(T_tool0_in_dh: np.ndarray) -> list[np.ndarray]:
    """Compute up to 8 analytical IK solutions.

    Args:
        T_tool0_in_dh: 4×4 target pose of tool0 in the DH base frame
                       (= _RZ_PI @ T_tool0_in_ros_base_link)
    Returns:
        List of valid joint-angle arrays (each shape (6,)).
        May have fewer than 8 entries near singularities or at workspace limits.
    """
    T   = T_tool0_in_dh
    d1  = _D[0];  d4  = _D[3];  d5  = _D[4];  d6  = _D[5]
    a1  = _A[1];  a2  = _A[2]          # both negative: −0.425, −0.3922

    solutions: list[np.ndarray] = []

    # -- Wrist centre (frame-5 origin) in DH base frame --
    # T56 is a pure Rz(θ6) + translation [0,0,d6], so z-axis of frame 6 = z-axis of frame 5.
    # p05 = p06 − d6 * z6
    p05x = T[0, 3] - d6 * T[0, 2]
    p05y = T[1, 3] - d6 * T[1, 2]
    p05z = T[2, 3] - d6 * T[2, 2]

    # ---- θ1: 2 solutions ------------------------------------------------
    # Derived from: sin(θ1)*p05x − cos(θ1)*p05y = d4
    r_xy = math.hypot(p05x, p05y)
    if r_xy < 1e-9:
        return solutions                  # wrist centre on Z-axis: degenerate
    arg = d4 / r_xy
    if abs(arg) > 1.0:
        return solutions                  # outside workspace
    phi = math.atan2(p05y, p05x)
    psi = math.asin(arg)
    theta1_list = [phi + psi, phi + math.pi - psi]

    for t1 in theta1_list:
        c1, s1 = math.cos(t1), math.sin(t1)

        # ---- θ5: 2 solutions --------------------------------------------
        # Derived from the z-component of z6-axis in frame 1:
        #   (z6_in_frame1)[2] = s1*T[0,2] − c1*T[1,2] = cos(θ5)
        cos_t5 = s1 * T[0, 2] - c1 * T[1, 2]
        cos_t5 = float(np.clip(cos_t5, -1.0, 1.0))
        t5_abs = math.acos(cos_t5)

        for t5 in [t5_abs, -t5_abs]:
            s5 = math.sin(t5)

            # ---- θ6 ----------------------------------------------------
            if abs(s5) < 1e-6:
                # Wrist singularity (θ5 ≈ 0 or π): θ6 is arbitrary.
                t6 = 0.0
            else:
                # sin(θ5)*cos(θ6) = s1*T[0,0] − c1*T[1,0]
                # sin(θ5)*sin(θ6) = −(s1*T[0,1] − c1*T[1,1])
                cos6_s5 = s1 * T[0, 0] - c1 * T[1, 0]
                sin6_s5 = -(s1 * T[0, 1] - c1 * T[1, 1])
                # atan2(y/s5, x/s5) — same ratio regardless of sign(s5)
                if s5 > 0:
                    t6 = math.atan2(sin6_s5, cos6_s5)
                else:
                    t6 = math.atan2(-sin6_s5, -cos6_s5)

            c5, c6, s6 = math.cos(t5), math.cos(t6), math.sin(t6)

            # ---- θ2, θ3, θ4 --------------------------------------------
            # Compute R14 = R01^T @ R06 @ R46^T
            #   R01^T = [[c1,s1,0],[0,0,1],[s1,−c1,0]]
            R01T = np.array([[c1, s1, 0.0],
                             [0.0, 0.0, 1.0],
                             [s1, -c1, 0.0]])

            # R46 = R45 @ R56 (computed analytically):
            R46 = np.array([
                [ c5 * c6, -c5 * s6, -s5],
                [ s5 * c6, -s5 * s6,  c5],
                [-s6,      -c6,       0.0],
            ])
            R14 = R01T @ T[:3, :3] @ R46.T

            # θ234 from z-column of R14: R14[:,2] = [sin(θ234), −cos(θ234), 0]
            theta234 = math.atan2(R14[0, 2], -R14[1, 2])
            s234 = math.sin(theta234)
            c234 = math.cos(theta234)

            # Wrist centre in frame 1
            x_wc = c1 * p05x + s1 * p05y
            y_wc = p05z - d1

            # Remove d5 contribution to get the 2-link-arm target
            px23 = x_wc - d5 * s234
            py23 = y_wc + d5 * c234

            # 2-link arm IK (link lengths a1, a2 — both negative)
            r2    = px23 ** 2 + py23 ** 2
            c3val = (r2 - a1 ** 2 - a2 ** 2) / (2.0 * a1 * a2)
            if abs(c3val) > 1.0:
                continue
            t3_abs = math.acos(float(np.clip(c3val, -1.0, 1.0)))

            for t3 in [t3_abs, -t3_abs]:
                c3, s3 = math.cos(t3), math.sin(t3)
                denom  = a1 + a2 * c3
                numer  = a2 * s3
                t2 = math.atan2(py23, px23) - math.atan2(numer, denom)
                t4 = theta234 - t2 - t3
                solutions.append(np.array([t1, t2, t3, t4, t5, t6]))

    return solutions


def _best_ik(T_tcp_in_base: np.ndarray, T_tool: np.ndarray,
             q_ref: np.ndarray) -> np.ndarray | None:
    """Return the IK solution closest to q_ref, or None if no solution."""
    # 1. Target for tool0 (remove gripper offset)
    T_tool0 = T_tcp_in_base @ np.linalg.inv(T_tool)

    # 2. Convert to DH base frame
    T_dh = _RZ_PI @ T_tool0

    # 3. Compute all solutions
    candidates = _ur5e_ik_solutions(T_dh)
    if not candidates:
        return None

    # 4. Normalise to [−π, π] and pick closest to q_ref
    for q in candidates:
        q[:] = (q + math.pi) % (2 * math.pi) - math.pi

    return min(candidates, key=lambda q: float(np.sum((q - q_ref) ** 2)))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _pose_to_matrix(pose: Pose) -> np.ndarray:
    r = pose.orientation
    T = np.eye(4)
    T[:3, :3] = quat2mat([r.w, r.x, r.y, r.z])
    T[:3, 3]  = [pose.position.x, pose.position.y, pose.position.z]
    return T


def _tf_to_matrix(tf_stamped) -> np.ndarray:
    t = tf_stamped.transform.translation
    r = tf_stamped.transform.rotation
    T = np.eye(4)
    T[:3, :3] = quat2mat([r.w, r.x, r.y, r.z])
    T[:3, 3]  = [t.x, t.y, t.z]
    return T


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class CheatCodeJoint(Policy):
    def __init__(self, parent_node):
        self._tip_x_error_integrator = 0.0
        self._tip_y_error_integrator = 0.0
        self._max_integrator_windup  = 0.05
        self._task    = None
        self._T_tool  = None   # cached transform: tool0 → gripper/tcp
        super().__init__(parent_node)

    # ------------------------------------------------------------------
    # TF helpers
    # ------------------------------------------------------------------

    def _wait_for_tf(
        self, target_frame: str, source_frame: str, timeout_sec: float = 10.0
    ) -> bool:
        start   = self.time_now()
        timeout = Duration(seconds=timeout_sec)
        attempt = 0
        while (self.time_now() - start) < timeout:
            try:
                self._parent_node._tf_buffer.lookup_transform(
                    target_frame, source_frame, Time()
                )
                return True
            except TransformException:
                if attempt % 20 == 0:
                    self.get_logger().info(
                        f"Waiting for '{source_frame}' -> '{target_frame}'"
                        " -- are you running eval with `ground_truth:=true`?"
                    )
                attempt += 1
                self.sleep_for(0.1)
        self.get_logger().error(
            f"Transform '{source_frame}' not available after {timeout_sec}s"
        )
        return False

    def _cache_tool_transform(self) -> bool:
        """Cache the fixed transform from tool0 to gripper/tcp."""
        try:
            tf = self._parent_node._tf_buffer.lookup_transform(
                _TOOL0_FRAME, _TCP_FRAME, Time()
            )
            self._T_tool = _tf_to_matrix(tf)
            self.get_logger().info(
                f"Cached tool transform (tool0→tcp): "
                f"t=[{self._T_tool[0,3]:.4f}, {self._T_tool[1,3]:.4f}, {self._T_tool[2,3]:.4f}]"
            )
            return True
        except TransformException as ex:
            self.get_logger().error(f"Cannot cache tool transform: {ex}")
            return False

    # ------------------------------------------------------------------
    # Cartesian target computation (identical to CheatCode)
    # ------------------------------------------------------------------

    def calc_gripper_pose(
        self,
        port_transform: Transform,
        slerp_fraction:    float = 1.0,
        position_fraction: float = 1.0,
        z_offset:          float = 0.1,
        reset_xy_integrator: bool = False,
        freeze_xy_integrator: bool = False,
    ) -> Pose:
        """Find the gripper pose that results in plug alignment."""
        q_port = (
            port_transform.rotation.w,
            port_transform.rotation.x,
            port_transform.rotation.y,
            port_transform.rotation.z,
        )

        plug_tf = self._parent_node._tf_buffer.lookup_transform(
            _BASE_FRAME,
            f"{self._task.cable_name}/{self._task.plug_name}_link",
            Time(),
        )
        q_plug = (
            plug_tf.transform.rotation.w,
            plug_tf.transform.rotation.x,
            plug_tf.transform.rotation.y,
            plug_tf.transform.rotation.z,
        )
        q_diff = quaternion_multiply(q_port, (-q_plug[0], q_plug[1], q_plug[2], q_plug[3]))

        gripper_tf = self._parent_node._tf_buffer.lookup_transform(
            _BASE_FRAME, _TCP_FRAME, Time()
        )
        q_gripper = (
            gripper_tf.transform.rotation.w,
            gripper_tf.transform.rotation.x,
            gripper_tf.transform.rotation.y,
            gripper_tf.transform.rotation.z,
        )
        q_gripper_slerp = quaternion_slerp(
            q_gripper, quaternion_multiply(q_diff, q_gripper), slerp_fraction
        )

        gripper_xyz = (
            gripper_tf.transform.translation.x,
            gripper_tf.transform.translation.y,
            gripper_tf.transform.translation.z,
        )
        port_xy  = (port_transform.translation.x, port_transform.translation.y)
        plug_xyz = (
            plug_tf.transform.translation.x,
            plug_tf.transform.translation.y,
            plug_tf.transform.translation.z,
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
        elif not freeze_xy_integrator:
            self._tip_x_error_integrator = np.clip(
                self._tip_x_error_integrator + tip_x_error,
                -self._max_integrator_windup, self._max_integrator_windup,
            )
            self._tip_y_error_integrator = np.clip(
                self._tip_y_error_integrator + tip_y_error,
                -self._max_integrator_windup, self._max_integrator_windup,
            )

        self.get_logger().info(
            f"pfrac: {position_fraction:.3f}  xy_err: {tip_x_error:.3f} {tip_y_error:.3f}"
            f"  integ: {self._tip_x_error_integrator:.3f} {self._tip_y_error_integrator:.3f}"
        )

        i_gain   = 0.15
        target_x = port_xy[0] + i_gain * self._tip_x_error_integrator
        target_y = port_xy[1] + i_gain * self._tip_y_error_integrator
        target_z = port_transform.translation.z + z_offset + plug_tip_gripper_offset[2]

        blend = (
            position_fraction * target_x + (1.0 - position_fraction) * gripper_xyz[0],
            position_fraction * target_y + (1.0 - position_fraction) * gripper_xyz[1],
            position_fraction * target_z + (1.0 - position_fraction) * gripper_xyz[2],
        )

        return Pose(
            position=Point(x=blend[0], y=blend[1], z=blend[2]),
            orientation=Quaternion(
                w=q_gripper_slerp[0],
                x=q_gripper_slerp[1],
                y=q_gripper_slerp[2],
                z=q_gripper_slerp[3],
            ),
        )

    # ------------------------------------------------------------------
    # Joint-space motion helper
    # ------------------------------------------------------------------

    def _send_joint_target(
        self,
        move_robot: MoveRobotCallback,
        jmu: JointMotionUpdate,
        target_pose: Pose,
        q: np.ndarray,
    ) -> np.ndarray:
        """Compute analytical IK for target_pose → publish JointMotionUpdate.

        Returns q_next (use as q on the next call).
        """
        T_target = _pose_to_matrix(target_pose)
        q_next   = _best_ik(T_target, self._T_tool, q)

        if q_next is None:
            self.get_logger().warn("No IK solution found — holding current q")
            q_next = q.copy()
        else:
            delta = np.degrees(np.max(np.abs(q_next - q)))
            self.get_logger().debug(f"IK Δq_max: {delta:.2f}°")

        jmu.target_state.positions = list(q_next)
        try:
            move_robot(joint_motion_update=jmu)
        except Exception as ex:
            self.get_logger().info(f"move_robot exception: {ex}")

        return q_next

    # ------------------------------------------------------------------
    # Main task entry point
    # ------------------------------------------------------------------

    def insert_cable(
        self,
        task: Task,
        get_observation: GetObservationCallback,
        move_robot: MoveRobotCallback,
        send_feedback: SendFeedbackCallback,
    ):
        self.get_logger().info(f"CheatCodeJoint.insert_cable() task: {task}")
        self._task = task

        port_frame      = f"task_board/{task.target_module_name}/{task.port_name}_link"
        cable_tip_frame = f"{task.cable_name}/{task.plug_name}_link"

        # Wait for ground-truth TF frames
        for frame in [port_frame, cable_tip_frame, _TOOL0_FRAME, _TCP_FRAME]:
            if not self._wait_for_tf(_BASE_FRAME, frame):
                return False

        # Cache the fixed tool transform (tool0 → gripper/tcp)
        if not self._cache_tool_transform():
            return False

        # Log FK at home to verify kinematics are consistent
        obs = get_observation()
        q   = np.array(obs.joint_states.position[:6], dtype=float)
        T_fk = _ur5e_fk(q)
        try:
            tcp_tf = self._parent_node._tf_buffer.lookup_transform(
                _BASE_FRAME, _TCP_FRAME, Time()
            )
            p_tf = np.array([tcp_tf.transform.translation.x,
                             tcp_tf.transform.translation.y,
                             tcp_tf.transform.translation.z])
            # FK gives tool0 pose; TCP = tool0 + T_tool
            T_tcp_fk = T_fk @ self._T_tool
            err = np.linalg.norm(T_tcp_fk[:3, 3] - p_tf)
            self.get_logger().info(f"FK vs TF position error: {err*1000:.1f} mm")
        except TransformException:
            pass

        try:
            port_tf_stamped = self._parent_node._tf_buffer.lookup_transform(
                _BASE_FRAME, port_frame, Time()
            )
        except TransformException as ex:
            self.get_logger().error(f"Could not look up port transform: {ex}")
            return False
        port_transform = port_tf_stamped.transform

        jmu = JointMotionUpdate(
            target_stiffness=[200.0, 200.0, 200.0, 100.0, 100.0, 100.0],
            target_damping=[40.0, 40.0, 40.0, 15.0, 15.0, 15.0],
            trajectory_generation_mode=TrajectoryGenerationMode(
                mode=TrajectoryGenerationMode.MODE_POSITION
            ),
        )

        z_offset = 0.2

        # Phase 1: smoothly approach above the port (100 × 50 ms = 5 s)
        for t in range(100):
            frac = t / 100.0
            try:
                obs = get_observation()
                q = self._send_joint_target(
                    move_robot, jmu,
                    self.calc_gripper_pose(
                        port_transform,
                        slerp_fraction=frac,
                        position_fraction=frac,
                        z_offset=z_offset,
                        reset_xy_integrator=True,
                    ),
                    q,
                )
            except TransformException as ex:
                self.get_logger().warn(f"TF lookup failed during approach: {ex}")
            self.sleep_for(0.05)

        # Phase 1.5: Hover and let the X/Y integrator correct the offset (40 × 50 ms = 2 s)
        self.get_logger().info("Hovering to correct X/Y alignment before insertion...")
        for t in range(40):
            try:
                obs = get_observation()
                q = self._send_joint_target(
                    move_robot, jmu,
                    self.calc_gripper_pose(
                        port_transform,
                        z_offset=z_offset,
                        reset_xy_integrator=False,  # 적분기를 켜서 X, Y 오차를 수정합니다!
                    ),
                    q,
                )
            except TransformException as ex:
                self.get_logger().warn(f"TF lookup failed during hover: {ex}")
            self.sleep_for(0.05)

        # FT Tare: hover 직후, 소켓 미접촉 상태에서 기준값 측정 (케이블+그리퍼 무게 제거)
        self.get_logger().info("Measuring FT baseline (tare)...")
        tare_x = tare_y = tare_z = 0.0
        n_tare = 10
        for _ in range(n_tare):
            obs = get_observation()
            tare_x += obs.wrist_wrench.wrench.force.x
            tare_y += obs.wrist_wrench.wrench.force.y
            tare_z += obs.wrist_wrench.wrench.force.z
            self.sleep_for(0.05)
        tare_x /= n_tare
        tare_y /= n_tare
        tare_z /= n_tare
        self.get_logger().info(
            f"FT tare: [{tare_x:.1f}, {tare_y:.1f}, {tare_z:.1f}] N "
            f"(mag={math.sqrt(tare_x**2+tare_y**2+tare_z**2):.1f} N)"
        )

        # Phase 2: compliance-first insertion
        # commit mode 제거 — 항상 FT 피드백으로 하강 제어.
        # 스티프니스를 낮춰 임피던스 컨트롤러가 자연스럽게 힘을 제한하도록 함.
        jmu.target_stiffness = [50.0, 50.0, 50.0, 20.0, 20.0, 20.0]
        jmu.target_damping   = [15.0, 15.0, 15.0,  8.0,  8.0,  8.0]

        # 2단계 제어:
        #   dist > 40mm  → 포트에서 멀리 떨어진 구간, FT 무시하고 하강
        #   dist ≤ 40mm  → FT 기반 제어 (contact_force ≥ 12N 시 백오프)
        #   dist < 3mm   → 삽입 완료 감지, break
        # 추가: 20N 이상 힘이 0.8s 누적되면 패널티 직전에 중단
        _NEAR_PORT_DIST     = 0.04   # m: FT 제어 시작 거리 (was 0.03)
        _INSERTED_DIST      = 0.003  # m: 삽입 완료 판단 거리
        _CONTACT_THRESH     = 12.0   # N: 백오프 기준 (20N 패널티보다 일찍 반응)
        _PENALTY_FORCE_LVL  = 20.0   # N: 스코어링 패널티 기준
        _PENALTY_BUDGET     = 0.8    # s: 누적 패널티 허용 시간 (1.0s 기준 마진)
        _PENALTY_WINDOW     = 0.4    # s: 연속 접촉 후 백오프 (was 0.6)
        _DESCENT_STEP       = 0.0005 # m: 하강 보폭
        _BACKOFF_STEP       = 0.0015 # m: 백오프 보폭 (비율 3:1, was 6:1)
        _MAX_INSERTION_STEPS = 500

        above_thresh_time = 0.0
        cumulative_penalty_time = 0.0
        insertion_steps = 0

        while True:
            insertion_steps += 1
            if insertion_steps > _MAX_INSERTION_STEPS:
                self.get_logger().warn("Insertion timeout reached.")
                break

            if z_offset < -0.06:
                self.get_logger().warn("z_offset safety limit reached.")
                break

            # --- TF 거리 계산 ---
            dist = None
            try:
                plug_tf_now = self._parent_node._tf_buffer.lookup_transform(
                    _BASE_FRAME, cable_tip_frame, Time()
                )
                port_tf_now = self._parent_node._tf_buffer.lookup_transform(
                    _BASE_FRAME, port_frame, Time()
                )
                dx = plug_tf_now.transform.translation.x - port_tf_now.transform.translation.x
                dy = plug_tf_now.transform.translation.y - port_tf_now.transform.translation.y
                dz = plug_tf_now.transform.translation.z - port_tf_now.transform.translation.z
                dist = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
            except TransformException:
                pass

            # --- 삽입 완료 감지 ---
            if dist is not None and dist < _INSERTED_DIST:
                self.get_logger().info(f"Insertion detected! dist={dist*1000:.1f} mm")
                break

            # --- 힘 측정 + 기록 (항상) ---
            obs = get_observation()
            f = obs.wrist_wrench.wrench.force
            contact_force = math.sqrt(
                (f.x - tare_x) ** 2 + (f.y - tare_y) ** 2 + (f.z - tare_z) ** 2
            )

            # --- 패널티 누적 시간 추적: 0.8s 이상이면 중단하여 -12 패널티 회피 ---
            if contact_force >= _PENALTY_FORCE_LVL:
                cumulative_penalty_time += 0.05
                if cumulative_penalty_time >= _PENALTY_BUDGET:
                    self.get_logger().warn(
                        f"Force penalty budget reached ({cumulative_penalty_time:.2f}s) — stopping."
                    )
                    break

            # --- 하강 판단 ---
            if dist is None or dist > _NEAR_PORT_DIST:
                # 포트에서 멀리 → 그냥 하강
                z_offset -= _DESCENT_STEP
                above_thresh_time = 0.0
                self.get_logger().info(
                    f"z={z_offset:.4f}  dist={'N/A' if dist is None else f'{dist*1000:.1f}mm'}  far→descend"
                )
            else:
                # 포트 근접 → FT 기반 제어 (commit mode 없음)
                if contact_force >= _CONTACT_THRESH:
                    above_thresh_time += 0.05
                    if above_thresh_time >= _PENALTY_WINDOW:
                        z_offset = min(z_offset + _BACKOFF_STEP, 0.2)
                        above_thresh_time = 0.0
                        self.get_logger().warn(
                            f"Contact sustained — backing off z={z_offset:.4f}"
                        )
                else:
                    above_thresh_time = 0.0
                    z_offset -= _DESCENT_STEP

                self.get_logger().info(
                    f"z={z_offset:.4f}  dist={dist*1000:.1f}mm  "
                    f"contact={contact_force:.1f}N  t_high={above_thresh_time:.2f}s  "
                    f"penalty_t={cumulative_penalty_time:.2f}s"
                )

            try:
                q = self._send_joint_target(
                    move_robot, jmu,
                    self.calc_gripper_pose(
                        port_transform,
                        z_offset=z_offset,
                        freeze_xy_integrator=True,
                    ),
                    q,
                )
            except TransformException as ex:
                self.get_logger().warn(f"TF lookup failed during insertion: {ex}")
            self.sleep_for(0.05)

        self.get_logger().info("Waiting for connector to stabilize...")
        self.sleep_for(5.0)
        self.get_logger().info("CheatCodeJoint.insert_cable() exiting...")
        return True
