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

"""AutoCodeTrial3: AutoCode + PilzPolicy 결합 정책 (Trial 3, SC 커넥터).

Phase 1   — Cartesian 접근 (AutoCode): slerp + position_fraction 보간, PI 적분기 초기화
Phase 1.5 — XY 안정화 (AutoCode PI 적분기): tip_x/y_error_integrator로 XY 오차 수렴
Phase 2   — FT Tare (CheatCodeHybrid): baseline force 측정
Phase 3   — 포트 Z축 삽입 (PilzPolicy 알고리즘, 해석적 IK):
              - port_z = R_port[:, 2] 방향으로 TCP 증분
              - 해석적 UR5e IK → JointMotionUpdate
              - 완료 판정: depth >= threshold AND f_insert <= 5N AND slope < -2 N/s
              - 안전 정지: |force| > 20N for > 1.5s
              - 백오프: contact > 16N for > 0.3s → 8mm 후퇴
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
from geometry_msgs.msg import Point, Pose, Quaternion
from rclpy.duration import Duration
from rclpy.time import Time
from tf2_ros import TransformException
from transforms3d._gohlketransforms import quaternion_multiply, quaternion_slerp
from transforms3d.quaternions import mat2quat, quat2mat

# ── UR5e DH 파라미터 ──────────────────────────────────────────────────
_D     = [0.1625, 0,       0,       0.1333,  0.0997, 0.0996]
_A     = [0,     -0.4250, -0.3922,  0,       0,      0     ]
_ALPHA = [math.pi/2, 0,   0,       math.pi/2, -math.pi/2, 0]
_RZ_PI = np.diag([-1.0, -1.0, 1.0, 1.0])

_BASE_FRAME  = "base_link"
_TCP_FRAME   = "gripper/tcp"
_TOOL0_FRAME = "tool0"

# ── 접근 파라미터 ────────────────────────────────────────────────────
Z_OFFSET_HOVER   = 0.2    # Phase 1 호버 높이 (m)
APPROACH_STEPS   = 75     # Phase 1 스텝 수 (× 50ms = 3.75s)
STABILIZE_STEPS  = 20     # Phase 1.5 스텝 수 (× 50ms = 1.0s)
I_GAIN           = 0.15   # PI 적분기 gain
MAX_INTEGRATOR   = 0.05   # 적분기 windup 한계 (m)

# ── 관절 강성 (Phase 1) ───────────────────────────────────────────────
JSTIFF = [200.0, 200.0, 200.0, 100.0, 100.0, 100.0]
JDAMP  = [40.0,  40.0,  40.0,  15.0,  15.0,  15.0]

# ── 삽입 제어 ────────────────────────────────────────────────────────
INSERT_VELOCITY  = 0.01   # TCP 삽입 속도 (m/s)
DT               = 0.05   # 제어 주기 (s)
MAX_LOOPS        = 2000   # 최대 루프 (× 0.05s = 100s)

# ── 삽입 완료 판정 (PilzPolicy) ──────────────────────────────────────
DEPTH_THRESHOLD_SC  = -0.0008  # SC 완료 depth (m, port 표면보다 0.8mm 위)
FORCE_LOW_THRESH    = 5.0      # 완료 판정 최대 force (N)
FORCE_SLOPE_WIN     = 5        # slope 계산 window (샘플 수)
FORCE_SLOPE_THRESH  = -2.0     # slope threshold (N/s), 이 이하면 감소 중

# ── 안전 / 백오프 파라미터 ───────────────────────────────────────────
FORCE_STOP_THRESH   = 20.0     # 안전 정지 force (N)
FORCE_STOP_DUR      = 1.5      # 안전 정지 판정 시간 (s)
CONTACT_THRESH      = 16.0     # 백오프 시작 force (N)
CONTACT_WINDOW      = 0.3      # 백오프 판정 시간 (s)
BACKOFF_DIST        = 0.008    # 백오프 거리 (m)


# ══════════════════════════════════════════════════════════════════════
# UR5e 해석적 IK / FK (from CheatCodeHybrid)
# ══════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════
# Policy
# ══════════════════════════════════════════════════════════════════════

class AutoCodeTrial3(Policy):
    """AutoCode PI 적분기 + PilzPolicy 포트축 삽입 + 해석적 IK."""

    def __init__(self, parent_node):
        self._tip_x_error_integrator = 0.0
        self._tip_y_error_integrator = 0.0
        self._task = None
        self._T_tool = None
        super().__init__(parent_node)

    # ── TF 헬퍼 ──────────────────────────────────────────────────────

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

    # ── calc_gripper_pose: AutoCode PI 적분기 포함 ────────────────────

    def calc_gripper_pose(
        self,
        port_transform,
        slerp_fraction: float = 1.0,
        position_fraction: float = 1.0,
        z_offset: float = Z_OFFSET_HOVER,
        reset_xy_integrator: bool = False,
    ) -> Pose:
        """포트 정렬을 위한 gripper 목표 pose 계산 (AutoCode PI 적분기 포함)."""
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
        q_plug_inv = (-q_plug[0], q_plug[1], q_plug[2], q_plug[3])
        q_diff = quaternion_multiply(q_port, q_plug_inv)

        gripper_tf = self._parent_node._tf_buffer.lookup_transform(
            _BASE_FRAME, _TCP_FRAME, Time())
        q_gripper = (
            gripper_tf.transform.rotation.w,
            gripper_tf.transform.rotation.x,
            gripper_tf.transform.rotation.y,
            gripper_tf.transform.rotation.z,
        )
        q_gripper_target = quaternion_multiply(q_diff, q_gripper)
        q_slerp = quaternion_slerp(q_gripper, q_gripper_target, slerp_fraction)

        gripper_xyz = (
            gripper_tf.transform.translation.x,
            gripper_tf.transform.translation.y,
            gripper_tf.transform.translation.z,
        )
        port_xy = (port_transform.translation.x, port_transform.translation.y)
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
        else:
            self._tip_x_error_integrator = np.clip(
                self._tip_x_error_integrator + tip_x_error,
                -MAX_INTEGRATOR, MAX_INTEGRATOR,
            )
            self._tip_y_error_integrator = np.clip(
                self._tip_y_error_integrator + tip_y_error,
                -MAX_INTEGRATOR, MAX_INTEGRATOR,
            )

        self.get_logger().info(
            f"pfrac:{position_fraction:.3f} xy_err:[{tip_x_error:.4f},{tip_y_error:.4f}] "
            f"intg:[{self._tip_x_error_integrator:.4f},{self._tip_y_error_integrator:.4f}]"
        )

        target_x = port_xy[0] + I_GAIN * self._tip_x_error_integrator
        target_y = port_xy[1] + I_GAIN * self._tip_y_error_integrator
        target_z = port_transform.translation.z + z_offset - plug_tip_gripper_offset[2]

        blend_xyz = (
            position_fraction * target_x + (1.0 - position_fraction) * gripper_xyz[0],
            position_fraction * target_y + (1.0 - position_fraction) * gripper_xyz[1],
            position_fraction * target_z + (1.0 - position_fraction) * gripper_xyz[2],
        )

        return Pose(
            position=Point(x=blend_xyz[0], y=blend_xyz[1], z=blend_xyz[2]),
            orientation=Quaternion(
                w=q_slerp[0], x=q_slerp[1], y=q_slerp[2], z=q_slerp[3]),
        )

    # ── Joint IK 명령 헬퍼 ────────────────────────────────────────────

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

    # ── 메인 ─────────────────────────────────────────────────────────

    def insert_cable(
        self,
        task: Task,
        get_observation: GetObservationCallback,
        move_robot: MoveRobotCallback,
        send_feedback: SendFeedbackCallback,
    ) -> bool:
        self.get_logger().info(f"AutoCodeTrial3.insert_cable() task: {task}")
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

        # port Z축 계산 (PilzPolicy: 삽입 방향)
        pr = port_transform.rotation
        R_port = quat2mat([pr.w, pr.x, pr.y, pr.z])
        port_z = R_port[:, 2]
        port_pos = np.array([
            port_transform.translation.x,
            port_transform.translation.y,
            port_transform.translation.z,
        ])
        self.get_logger().info(f"port_z axis: {port_z}")

        # ── Phase 1: Cartesian 접근 (AutoCode) ──────────────────────
        send_feedback("Phase 1: Cartesian approach")
        self.get_logger().info("Phase 1: Cartesian approach (slerp + position_fraction)...")
        jmu = JointMotionUpdate(
            target_stiffness=JSTIFF,
            target_damping=JDAMP,
            trajectory_generation_mode=TrajectoryGenerationMode(
                mode=TrajectoryGenerationMode.MODE_POSITION),
        )
        for t in range(APPROACH_STEPS):
            frac = t / float(APPROACH_STEPS)
            try:
                target_pose = self.calc_gripper_pose(
                    port_transform,
                    slerp_fraction=frac,
                    position_fraction=frac,
                    z_offset=Z_OFFSET_HOVER,
                    reset_xy_integrator=True,
                )
                q = self._send_joint_target(move_robot, jmu, target_pose, q)
            except Exception as ex:
                self.get_logger().warn(f"Phase 1 error: {ex}")
            self.sleep_for(DT)

        # ── Phase 1.5: XY 안정화 (AutoCode PI 적분기) ───────────────
        send_feedback("Phase 1.5: XY stabilization")
        self.get_logger().info("Phase 1.5: XY stabilization (PI integrator)...")
        for _ in range(STABILIZE_STEPS):
            try:
                target_pose = self.calc_gripper_pose(
                    port_transform, z_offset=Z_OFFSET_HOVER)
                q = self._send_joint_target(move_robot, jmu, target_pose, q)
            except Exception as ex:
                self.get_logger().warn(f"Phase 1.5 error: {ex}")
            self.sleep_for(DT)

        # ── Phase 2: FT Tare (CheatCodeHybrid) ──────────────────────
        send_feedback("Phase 2: FT tare")
        self.get_logger().info("Phase 2: FT tare...")
        tare_x = tare_y = tare_z = 0.0
        for _ in range(10):
            obs = get_observation()
            tare_x += obs.wrist_wrench.wrench.force.x
            tare_y += obs.wrist_wrench.wrench.force.y
            tare_z += obs.wrist_wrench.wrench.force.z
            self.sleep_for(DT)
        tare_x /= 10; tare_y /= 10; tare_z /= 10
        self.get_logger().info(
            f"FT tare: [{tare_x:.2f}, {tare_y:.2f}, {tare_z:.2f}] N")
        tare = np.array([tare_x, tare_y, tare_z])

        # ── Phase 3: 포트 Z축 삽입 (PilzPolicy 알고리즘) ────────────
        send_feedback("Phase 3: port-axis insertion")
        self.get_logger().info("Phase 3: port-axis insertion...")

        # 현재 TCP 위치를 삽입 시작점으로
        try:
            tcp_tf = self._parent_node._tf_buffer.lookup_transform(
                _BASE_FRAME, _TCP_FRAME, Time())
            tcp_pos = np.array([
                tcp_tf.transform.translation.x,
                tcp_tf.transform.translation.y,
                tcp_tf.transform.translation.z,
            ])
            tcp_ori = tcp_tf.transform.rotation
        except TransformException as ex:
            self.get_logger().error(f"TCP TF failed at Phase 3 start: {ex}")
            return False

        obs = get_observation()
        q = np.array(obs.joint_states.position[:6], dtype=float)

        # 삽입 Phase JMU (Cartesian stiffness로 compliant하게)
        jmu_insert = JointMotionUpdate(
            target_stiffness=[50.0, 50.0, 50.0, 30.0, 30.0, 50.0],
            target_damping=[35.0, 35.0, 35.0, 15.0, 15.0, 25.0],
            trajectory_generation_mode=TrajectoryGenerationMode(
                mode=TrajectoryGenerationMode.MODE_POSITION),
        )

        exit_reason      = "timeout"
        f_insert_history = []
        excessive_start  = None   # 20N 초과 시작 시각 (sim time, nanosec)
        contact_time     = 0.0    # 16N 이상 누적 시간 (s)
        ik_fails         = 0

        for lc in range(1, MAX_LOOPS + 1):
            obs = get_observation()
            if obs is None:
                self.sleep_for(DT)
                continue

            # 힘 계산 (tare 제거)
            f_raw = np.array([
                obs.wrist_wrench.wrench.force.x - tare_x,
                obs.wrist_wrench.wrench.force.y - tare_y,
                obs.wrist_wrench.wrench.force.z - tare_z,
            ])
            # 삽입 방향 투영 force (port_z 방향, 양수=삽입방향 반발)
            f_insert = float(np.dot(f_raw, port_z))
            f_abs    = float(np.linalg.norm(f_raw))

            # depth 계산 (PilzPolicy)
            depth = None
            try:
                plug_tf = self._parent_node._tf_buffer.lookup_transform(
                    _BASE_FRAME, cable_tip_frame, Time())
                plug_pos = np.array([
                    plug_tf.transform.translation.x,
                    plug_tf.transform.translation.y,
                    plug_tf.transform.translation.z,
                ])
                depth = float(np.dot(plug_pos - port_pos, port_z))
            except TransformException:
                pass

            # force 이력 + slope 계산 (PilzPolicy)
            f_insert_history.append(f_insert)
            if len(f_insert_history) > FORCE_SLOPE_WIN:
                f_insert_history.pop(0)

            f_slope = 0.0
            if len(f_insert_history) >= FORCE_SLOPE_WIN:
                y = np.array(f_insert_history)
                x = np.arange(len(y)) * DT
                denom = len(y) * np.dot(x, x) - x.sum() ** 2
                if abs(denom) > 1e-9:
                    f_slope = float(
                        (len(y) * np.dot(x, y) - x.sum() * y.sum()) / denom)

            if lc % 10 == 0 or lc == 1:
                ds = f"{depth:.5f}" if depth is not None else "N/A"
                self.get_logger().info(
                    f"P3[{lc:4d}] depth={ds}m f_ins={f_insert:.2f}N "
                    f"|f|={f_abs:.2f}N slope={f_slope:.2f}N/s")

            # 삽입 완료 판정 (PilzPolicy)
            depth_ok = depth is not None and depth >= DEPTH_THRESHOLD_SC
            if depth_ok and f_insert <= FORCE_LOW_THRESH and f_slope < FORCE_SLOPE_THRESH:
                exit_reason = (
                    f"insert_complete: depth={depth:.5f}m "
                    f"f_ins={f_insert:.2f}N slope={f_slope:.2f}N/s"
                )
                self.get_logger().info(f"Phase 3 EXIT [{exit_reason}]")
                break

            # 안전 정지: |force| > 20N for > 1.5s (PilzPolicy)
            now_ns = self.time_now().nanoseconds
            if f_abs > FORCE_STOP_THRESH:
                if excessive_start is None:
                    excessive_start = now_ns
                    self.get_logger().warn(
                        f"P3: |force| {f_abs:.1f}N > {FORCE_STOP_THRESH}N")
                elif (now_ns - excessive_start) * 1e-9 > FORCE_STOP_DUR:
                    exit_reason = (
                        f"force_stop: |f|={f_abs:.1f}N for "
                        f"{(now_ns - excessive_start)*1e-9:.2f}s")
                    self.get_logger().warn(f"Phase 3 EXIT [{exit_reason}]")
                    break
            else:
                excessive_start = None

            # 백오프: contact > 16N for > 0.3s (CheatCodeHybrid)
            if f_insert >= CONTACT_THRESH:
                contact_time += DT
                if contact_time >= CONTACT_WINDOW:
                    tcp_pos -= port_z * BACKOFF_DIST
                    contact_time = 0.0
                    self.get_logger().warn(
                        f"P3: contact backoff {BACKOFF_DIST*1000:.0f}mm")
            else:
                contact_time = max(0.0, contact_time - DT * 0.5)

            # TCP 증분 + 해석적 IK (PilzPolicy 방향, CheatCodeHybrid IK)
            prev_tcp = tcp_pos.copy()
            tcp_pos = tcp_pos + port_z * INSERT_VELOCITY * DT

            target_pose = Pose(
                position=Point(
                    x=float(tcp_pos[0]),
                    y=float(tcp_pos[1]),
                    z=float(tcp_pos[2]),
                ),
                orientation=Quaternion(
                    w=tcp_ori.w, x=tcp_ori.x, y=tcp_ori.y, z=tcp_ori.z),
            )

            q_next = _best_ik(_pose_to_matrix(target_pose), self._T_tool, q)
            if q_next is None:
                ik_fails += 1
                tcp_pos = prev_tcp
                if ik_fails % 20 == 1:
                    self.get_logger().warn(f"P3: IK failed x{ik_fails}")
            else:
                q = q_next
                ik_fails = 0

            jmu_insert.target_state.positions = list(q)
            try:
                move_robot(joint_motion_update=jmu_insert)
            except Exception as ex:
                self.get_logger().warn(f"P3 move_robot error: {ex}")
            self.sleep_for(DT)
        else:
            exit_reason = f"max_loops={MAX_LOOPS}"
            self.get_logger().warn(f"Phase 3 EXIT [{exit_reason}]")

        self.get_logger().info("Waiting for connector to stabilize...")
        self.sleep_for(2.0)
        self.get_logger().info(f"AutoCodeTrial3.insert_cable() done. [{exit_reason}]")
        return True
