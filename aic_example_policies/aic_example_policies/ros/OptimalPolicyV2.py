"""
OptimalPolicy: AutoCode closed-loop 제어 + F/T feedback 최적화.

- AutoCode의 연속 set_pose_target + PI integrator (smoothness 보장)
- F/T baseline 보상 + EMA filtering (정확한 접촉력 측정)
- Adaptive stiffness (삽입 구간에서 XY 유연)
- Force safety (20N penalty 방지)
- Stall detection + 후퇴 (stuck 방지)
- Depth 기반 삽입 완료 판정
- 전체 MotionUpdate(Cartesian) 통일 (VLA 데이터 action space 일관성)
"""

import numpy as np
import datetime
from pathlib import Path

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

# ══════════════════════════════════════════════════════════════════════
# 상수
# ══════════════════════════════════════════════════════════════════════

# ── Approach ──────────────────────────────────────────────────────────
APPROACH_Z_OFFSET = -0.08         # port z축 방향 접근 offset (m, 음수=삽입 반대방향) [확정]
APPROACH_VELOCITY = 0.05          # approach 이동 속도 (m/s)
APPROACH_MIN_STEPS = 40           # 최소 approach 스텝 (2초, 정렬은 Phase3에서)
DT = 0.05                         # 제어 주기 (초, 20Hz)

# ── Descent + Insertion ───────────────────────────────────────────────
DESCENT_STEP_SLOW = 0.0005        # 진입 전 하강 (0.5mm/step, 원본 속도 — 정렬 안정성)
DESCENT_STEP_FAST = 0.002         # 진입 후 빠른 하강 (2mm/step)
DESCENT_STEP_MIN = 0.0001         # force-adaptive 최소 step (0.1mm)
ENTRY_DEPTH = -0.035              # 이 depth 이상이면 진입 완료로 판단
INSERT_Z_LIMIT = 0.02             # 최대 삽입 깊이 z_offset (m, port z축 양수 = 삽입 진행)

# ── Stiffness ─────────────────────────────────────────────────────────
STIFFNESS_DEFAULT = [90.0, 90.0, 90.0, 50.0, 50.0, 50.0]  # [확정] 원래값, 안정적
STIFFNESS_INSERT  = [20.0, 20.0, 150.0, 50.0, 50.0, 50.0]  # XY 유연, Z pushing
STIFFNESS_TRANSITION_Z = -0.02    # 이 z_offset 이상이면 insertion stiffness (port 앞 2cm)

# ── PI Controller (AutoCode 기반) ──────────────────────────────────────
PI_I_GAIN = 0.15
PI_WINDUP_MAX = 0.08              # CheatCode 기반, 더 보수적

# ── F/T Feedback ──────────────────────────────────────────────────────
FORCE_ALPHA = 0.3                 # EMA filter alpha
FORCE_SAFETY_THRESHOLD = 18.0     # 안전 후퇴 threshold (N), 20N penalty 전 마진
FORCE_SAFETY_DURATION = 0.5       # 안전 후퇴 지속 시간 (초)
FORCE_SAFETY_RETRACT = 0.001      # 안전 후퇴 거리 (m)

# ── Stall Detection ──────────────────────────────────────────────────
STALL_WINDOW = 50                 # stall 감지 window (50 × 0.05s = 2.5초)
STALL_DEPTH_THRESHOLD = 0.0005    # depth 변화 threshold (m)
STALL_FORCE_MIN = 3.0             # stall 판정 최소 force (N)
STALL_RETRACT = 0.002             # stall 시 후퇴 거리 (m)
STALL_MAX_RETRIES = 10

# ── Alignment Check ───────────────────────────────────────────────────
ALIGN_CHECK_INTERVAL = 80         # 정렬 확인 간격 (스텝)
ALIGN_DEGRADE_RATIO = 1.3         # 오차 악화 판정 비율
ALIGN_HOLD_STEPS = 10             # 재정렬 대기 (10 × 0.05s = 0.5초)

# ── Depth Thresholds ──────────────────────────────────────────────────
DEPTH_THRESHOLD_SFP = 0.0         # SFP: depth > 0.0 → 만점
DEPTH_THRESHOLD_SC = -0.0008      # SC: depth > -0.0008 → 만점

# ── Stabilize ─────────────────────────────────────────────────────────
STABILIZE_DURATION = 1.0          # 최종 안정화 (초) [확정]


def _quat_to_matrix(x, y, z, w):
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
        [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)],
    ])


class OptimalPolicyV2(Policy):
    """AutoCode closed-loop + F/T feedback 최적화 policy."""

    def __init__(self, parent_node):
        self._tip_x_error_integrator = 0.0
        self._tip_y_error_integrator = 0.0
        self._task = None

        # F/T filter state
        self._f_filtered = np.zeros(3)
        self._t_filtered = np.zeros(3)
        self._f_baseline = np.zeros(3)
        self._t_baseline = np.zeros(3)

        super().__init__(parent_node)

        # 디버그 로그
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path.cwd() / "tmp"
        log_dir.mkdir(exist_ok=True)
        self._log_path = log_dir / f"optimal_policy_{ts}.log"
        self._log_file = open(self._log_path, "w")
        self.get_logger().info(f"Debug log: {self._log_path}")

    def _log(self, msg: str):
        self.get_logger().info(msg)
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_file.write(f"[{ts}] {msg}\n")
        self._log_file.flush()

    # ══════════════════════════════════════════════════════════════════
    # TF 헬퍼
    # ══════════════════════════════════════════════════════════════════

    def _wait_for_tf(self, target_frame, source_frame, timeout_sec=10.0):
        start = self.time_now()
        while (self.time_now() - start) < Duration(seconds=timeout_sec):
            try:
                self._parent_node._tf_buffer.lookup_transform(
                    target_frame, source_frame, Time())
                return True
            except TransformException:
                self.sleep_for(0.1)
        self.get_logger().error(
            f"TF '{source_frame}' not available after {timeout_sec}s")
        return False

    # ══════════════════════════════════════════════════════════════════
    # AutoCode calc_gripper_pose (PI integrator 포함)
    # ══════════════════════════════════════════════════════════════════

    def calc_gripper_pose(self, port_transform: Transform,
                          slerp_fraction: float = 1.0,
                          position_fraction: float = 1.0,
                          z_offset: float = 0.1,
                          reset_xy_integrator: bool = False) -> Pose:
        q_port = (
            port_transform.rotation.w,
            port_transform.rotation.x,
            port_transform.rotation.y,
            port_transform.rotation.z,
        )
        plug_tf = self._parent_node._tf_buffer.lookup_transform(
            "base_link",
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
            "base_link", "gripper/tcp", Time())
        q_gripper = (
            gripper_tf.transform.rotation.w,
            gripper_tf.transform.rotation.x,
            gripper_tf.transform.rotation.y,
            gripper_tf.transform.rotation.z,
        )
        q_target = quaternion_multiply(q_diff, q_gripper)
        q_slerp = quaternion_slerp(q_gripper, q_target, slerp_fraction)

        gripper_xyz = (
            gripper_tf.transform.translation.x,
            gripper_tf.transform.translation.y,
            gripper_tf.transform.translation.z,
        )
        plug_xyz = (
            plug_tf.transform.translation.x,
            plug_tf.transform.translation.y,
            plug_tf.transform.translation.z,
        )
        plug_tip_offset = np.array([
            gripper_xyz[0] - plug_xyz[0],
            gripper_xyz[1] - plug_xyz[1],
            gripper_xyz[2] - plug_xyz[2],
        ])

        # port 로컬 좌표계 (base_link에서 표현)
        pr = port_transform.rotation
        R_port = _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)
        port_x_axis = R_port[:, 0]  # port 로컬 x축
        port_y_axis = R_port[:, 1]  # port 로컬 y축
        port_z_axis = R_port[:, 2]  # port 삽입 방향

        port_pos = np.array([port_transform.translation.x,
                             port_transform.translation.y,
                             port_transform.translation.z])
        plug_pos = np.array(plug_xyz)

        # plug tip → port 오차를 port 로컬 좌표계로 투영
        error_vec = port_pos - plug_pos
        tip_x_error = float(np.dot(error_vec, port_x_axis))  # port x축 방향 오차
        tip_y_error = float(np.dot(error_vec, port_y_axis))  # port y축 방향 오차

        if reset_xy_integrator:
            self._tip_x_error_integrator = 0.0
            self._tip_y_error_integrator = 0.0
        else:
            self._tip_x_error_integrator = np.clip(
                self._tip_x_error_integrator + tip_x_error,
                -PI_WINDUP_MAX, PI_WINDUP_MAX)
            self._tip_y_error_integrator = np.clip(
                self._tip_y_error_integrator + tip_y_error,
                -PI_WINDUP_MAX, PI_WINDUP_MAX)

        # plug tip 목표 위치 (port 좌표계 기준)
        #   = port 원점
        #   + port z축 × z_offset (삽입 방향 offset)
        #   + port x축 × PI 보정 (port 로컬 x 오차 보정)
        #   + port y축 × PI 보정 (port 로컬 y 오차 보정)
        desired_plug_pos = (port_pos
                            + port_z_axis * z_offset
                            + port_x_axis * PI_I_GAIN * self._tip_x_error_integrator
                            + port_y_axis * PI_I_GAIN * self._tip_y_error_integrator)

        # gripper target = desired plug tip + (gripper - plug tip) offset
        target_pos = desired_plug_pos + plug_tip_offset

        blend_xyz = (
            position_fraction * target_pos[0] + (1.0 - position_fraction) * gripper_xyz[0],
            position_fraction * target_pos[1] + (1.0 - position_fraction) * gripper_xyz[1],
            position_fraction * target_pos[2] + (1.0 - position_fraction) * gripper_xyz[2],
        )

        return Pose(
            position=Point(x=blend_xyz[0], y=blend_xyz[1], z=blend_xyz[2]),
            orientation=Quaternion(w=q_slerp[0], x=q_slerp[1],
                                   y=q_slerp[2], z=q_slerp[3]),
        )

    # ══════════════════════════════════════════════════════════════════
    # F/T 헬퍼
    # ══════════════════════════════════════════════════════════════════

    def _read_wrench(self, obs):
        """F/T 읽기 + baseline 보상 + EMA filtering."""
        f_raw = np.array([obs.wrist_wrench.wrench.force.x,
                          obs.wrist_wrench.wrench.force.y,
                          obs.wrist_wrench.wrench.force.z]) - self._f_baseline
        t_raw = np.array([obs.wrist_wrench.wrench.torque.x,
                          obs.wrist_wrench.wrench.torque.y,
                          obs.wrist_wrench.wrench.torque.z]) - self._t_baseline
        self._f_filtered = FORCE_ALPHA * f_raw + (1 - FORCE_ALPHA) * self._f_filtered
        self._t_filtered = FORCE_ALPHA * t_raw + (1 - FORCE_ALPHA) * self._t_filtered
        return self._f_filtered.copy(), self._t_filtered.copy()

    def _calibrate_wrench_baseline(self, get_observation, n=10):
        """현재 자세에서 F/T baseline 측정."""
        f_sum, t_sum, count = np.zeros(3), np.zeros(3), 0
        for _ in range(n):
            obs = get_observation()
            if obs:
                f_sum += np.array([obs.wrist_wrench.wrench.force.x,
                                   obs.wrist_wrench.wrench.force.y,
                                   obs.wrist_wrench.wrench.force.z])
                t_sum += np.array([obs.wrist_wrench.wrench.torque.x,
                                   obs.wrist_wrench.wrench.torque.y,
                                   obs.wrist_wrench.wrench.torque.z])
                count += 1
            self.sleep_for(0.02)
        if count > 0:
            self._f_baseline = f_sum / count
            self._t_baseline = t_sum / count
            self._f_filtered = np.zeros(3)
            self._t_filtered = np.zeros(3)
        self._log(f"  F/T baseline: force=({self._f_baseline[0]:.1f}, "
                  f"{self._f_baseline[1]:.1f}, {self._f_baseline[2]:.1f})N")

    # ══════════════════════════════════════════════════════════════════
    # Depth 계산
    # ══════════════════════════════════════════════════════════════════

    def _compute_depth(self, port_transform: Transform, plug_frame: str):
        """plug tip의 port z축 방향 depth 계산. 양수 = 삽입 진행."""
        try:
            pf = self._parent_node._tf_buffer.lookup_transform(
                "base_link", plug_frame, Time())
            pp = np.array([pf.transform.translation.x,
                           pf.transform.translation.y,
                           pf.transform.translation.z])
            port_pos = np.array([port_transform.translation.x,
                                 port_transform.translation.y,
                                 port_transform.translation.z])
            pr = port_transform.rotation
            port_z = _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)[:, 2]
            return float(np.dot(pp - port_pos, port_z))
        except TransformException:
            return None

    # ══════════════════════════════════════════════════════════════════
    # insert_cable — 메인 루프
    # ══════════════════════════════════════════════════════════════════

    def insert_cable(self, task: Task, get_observation: GetObservationCallback,
                     move_robot: MoveRobotCallback,
                     send_feedback: SendFeedbackCallback) -> bool:
        self._log("OptimalPolicy.insert_cable() start")
        self._log(f"  task: cable={task.cable_name}, plug={task.plug_name}, "
                  f"target_module={task.target_module_name}, port={task.port_name}")
        self._task = task

        port_frame = f"task_board/{task.target_module_name}/{task.port_name}_link"
        plug_frame = f"{task.cable_name}/{task.plug_name}_link"

        for frame in [port_frame, plug_frame]:
            if not self._wait_for_tf("base_link", frame):
                return False

        try:
            port_tf_stamped = self._parent_node._tf_buffer.lookup_transform(
                "base_link", port_frame, Time())
        except TransformException as e:
            self.get_logger().error(f"port TF failed: {e}")
            return False
        port_transform = port_tf_stamped.transform

        # port type 판별
        is_sc = "sc_port" in task.port_name or "sc_port" in task.target_module_name
        depth_threshold = DEPTH_THRESHOLD_SC if is_sc else DEPTH_THRESHOLD_SFP
        self._log(f"  port_type={'SC' if is_sc else 'SFP'}, "
                  f"depth_threshold={depth_threshold}")

        # F/T baseline calibration
        send_feedback("F/T baseline calibration")
        self._calibrate_wrench_baseline(get_observation)

        # ════════════════════════════════════════════════════════════
        # Phase 1: Smooth Approach (현재 TCP → port 상방)
        # ════════════════════════════════════════════════════════════
        send_feedback("Phase 1: Smooth approach")
        z_offset = APPROACH_Z_OFFSET

        # 거리 기반 스텝 수 계산 (일정 속도 유지)
        try:
            gripper_tf = self._parent_node._tf_buffer.lookup_transform(
                "base_link", "gripper/tcp", Time())
            cur_pos = np.array([gripper_tf.transform.translation.x,
                                gripper_tf.transform.translation.y,
                                gripper_tf.transform.translation.z])
            # approach 목표 위치 (대략적 — 정확한 값은 calc_gripper_pose가 계산)
            pr = port_transform.rotation
            port_z_axis = _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)[:, 2]
            port_pos = np.array([port_transform.translation.x,
                                 port_transform.translation.y,
                                 port_transform.translation.z])
            target_pos = port_pos + port_z_axis * z_offset
            dist = float(np.linalg.norm(cur_pos - target_pos))
            approach_steps = max(APPROACH_MIN_STEPS, int(dist / (APPROACH_VELOCITY * DT)))
        except TransformException:
            approach_steps = 75  # fallback

        self._log(f"  Phase 1: approach to z_offset={z_offset}m, "
                  f"dist={dist:.3f}m, steps={approach_steps}")

        import time as _time
        phase1_start = _time.monotonic()
        for t in range(approach_steps):
            linear_frac = t / approach_steps
            # S-curve: cosine ease-in-out (시작/끝 가감속 부드럽게)
            frac = 0.5 * (1.0 - np.cos(np.pi * linear_frac))
            try:
                pose = self.calc_gripper_pose(
                    port_transform,
                    slerp_fraction=frac,
                    position_fraction=frac,
                    z_offset=z_offset,
                    reset_xy_integrator=True,
                )
                self.set_pose_target(move_robot=move_robot, pose=pose)
            except TransformException:
                pass
            self.sleep_for(DT)
            # 매 10스텝 로깅
            if (t + 1) % 10 == 0 or t == 0:
                try:
                    tcp = self._parent_node._tf_buffer.lookup_transform(
                        "base_link", "gripper/tcp", Time()).transform.translation
                    self._log(f"  P1[{t+1}/{approach_steps}] frac={frac:.2f} "
                              f"tcp=({tcp.x:.4f},{tcp.y:.4f},{tcp.z:.4f})")
                except TransformException:
                    pass
        phase1_elapsed = _time.monotonic() - phase1_start
        self._log(f"  Phase 1 complete ({phase1_elapsed:.1f}s)")

        # Phase 1 끝에서 PI integrator 활성화 + baseline 기록
        baseline_err = 0.001  # 초기값
        # F/T baseline 재측정 (삽입 자세에서)
        self._calibrate_wrench_baseline(get_observation)

        # ════════════════════════════════════════════════════════════
        # Phase 3: Continuous Descent + Insertion
        # ════════════════════════════════════════════════════════════
        send_feedback("Phase 3: Descent + Insertion")
        phase3_start = _time.monotonic()
        self._log(f"  Phase 3: descent from z_offset={z_offset}m, "
                  f"step_slow={DESCENT_STEP_SLOW}/fast={DESCENT_STEP_FAST}, entry_depth={ENTRY_DEPTH}, limit={INSERT_Z_LIMIT}m")

        descent_step_count = 0
        excessive_force_start = None
        stall_history = []
        retry_count = 0
        depth = None

        while z_offset < INSERT_Z_LIMIT:
            # ── F/T monitoring ──
            obs = get_observation()
            f_abs = 0.0
            f_insert = 0.0
            if obs:
                f, t = self._read_wrench(obs)
                pr = port_transform.rotation
                port_z = _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)[:, 2]
                f_insert = float(np.dot(f, port_z))
                f_abs = float(np.linalg.norm(f))

            # ── Depth 계산 ──
            depth = self._compute_depth(port_transform, plug_frame)

            # ── 삽입 완료 판정 ──
            if depth is not None and depth >= depth_threshold:
                self._log(f"  Phase 3 EXIT [insert_complete]: "
                          f"depth={depth:.5f}m >= {depth_threshold}m")
                break

            # ── Force safety (20N penalty 방지) ──
            now_sec = self.time_now().nanoseconds * 1e-9
            if f_abs > FORCE_SAFETY_THRESHOLD:
                if excessive_force_start is None:
                    excessive_force_start = now_sec
                    self._log(f"  Force warning: |f|={f_abs:.1f}N")
                elif (now_sec - excessive_force_start) > FORCE_SAFETY_DURATION:
                    z_offset -= FORCE_SAFETY_RETRACT  # 삽입 반대 방향으로 후퇴
                    excessive_force_start = None
                    self._log(f"  Force retract: z_offset→{z_offset:.4f}m")
            else:
                excessive_force_start = None

            # ── Stall detection ──
            if depth is not None:
                stall_history.append(depth)
                if len(stall_history) > STALL_WINDOW:
                    stall_history.pop(0)
                if (len(stall_history) >= STALL_WINDOW and
                        abs(max(stall_history) - min(stall_history)) < STALL_DEPTH_THRESHOLD
                        and abs(f_insert) > STALL_FORCE_MIN):
                    if retry_count < STALL_MAX_RETRIES:
                        retry_count += 1
                        z_offset -= STALL_RETRACT  # 삽입 반대 방향으로 후퇴
                        stall_history.clear()
                        self._log(f"  Stall retract (retry {retry_count}): "
                                  f"z_offset→{z_offset:.4f}m")
                    else:
                        self._log(f"  Phase 3 EXIT [stall_exhausted]: depth={depth:.5f}m")
                        break

            # ── 2단계 descent step: 진입 전 느리게, 진입 후 빠르게 ──
            entered = depth is not None and depth > ENTRY_DEPTH
            base_step = DESCENT_STEP_FAST if entered else DESCENT_STEP_SLOW
            if f_abs > 5.0:
                step = max(DESCENT_STEP_MIN, base_step * (1.0 - f_abs / 20.0))
            else:
                step = base_step

            z_offset += step  # 삽입 방향 (port z축 양수) 으로 진행
            descent_step_count += 1

            # ── Stiffness 점진적 전환 (z=-0.04 ~ z=-0.02 구간 선형 보간) ──
            transition_start = STIFFNESS_TRANSITION_Z - 0.02  # -0.04
            transition_end = STIFFNESS_TRANSITION_Z            # -0.02
            if z_offset <= transition_start:
                stiffness = list(STIFFNESS_DEFAULT)
            elif z_offset >= transition_end:
                stiffness = list(STIFFNESS_INSERT)
            else:
                blend = (z_offset - transition_start) / (transition_end - transition_start)
                stiffness = [
                    STIFFNESS_DEFAULT[i] + blend * (STIFFNESS_INSERT[i] - STIFFNESS_DEFAULT[i])
                    for i in range(6)
                ]

            # ── Pose 계산 + 발행 ──
            try:
                pose = self.calc_gripper_pose(port_transform, z_offset=z_offset)
                self.set_pose_target(
                    move_robot=move_robot,
                    pose=pose,
                    stiffness=stiffness,
                )
            except TransformException:
                pass
            self.sleep_for(DT)

            # ── 적응형 재정렬 (AutoCode 방식) ──
            if descent_step_count % ALIGN_CHECK_INTERVAL == 0:
                current_err = max(abs(self._tip_x_error_integrator),
                                  abs(self._tip_y_error_integrator))
                if baseline_err > 0 and current_err > baseline_err * ALIGN_DEGRADE_RATIO:
                    self._log(f"  Re-align: err={current_err:.4f} > "
                              f"{baseline_err:.4f}×{ALIGN_DEGRADE_RATIO}")
                    for _ in range(ALIGN_HOLD_STEPS):
                        try:
                            self.set_pose_target(
                                move_robot=move_robot,
                                pose=self.calc_gripper_pose(
                                    port_transform, z_offset=z_offset),
                                stiffness=stiffness,
                            )
                        except TransformException:
                            pass
                        self.sleep_for(DT)
                    baseline_err = max(abs(self._tip_x_error_integrator),
                                       abs(self._tip_y_error_integrator))

            # ── 로깅 (매 5스텝) ──
            if descent_step_count % 5 == 0 or descent_step_count == 1:
                ds = f"{depth:.5f}" if depth is not None else "N/A"
                elapsed = _time.monotonic() - phase3_start
                entry_str = " ENTERED" if (depth is not None and depth > ENTRY_DEPTH) else ""
                self._log(f"  P3[{descent_step_count:4d}] t={elapsed:.1f}s z_off={z_offset:.4f}m "
                          f"depth={ds}m f_ins={f_insert:.1f}N |f|={f_abs:.1f}N "
                          f"step={step:.4f}{entry_str} "
                          f"retries={retry_count}")

        # z_offset limit 도달 시
        if z_offset >= INSERT_Z_LIMIT:
            self._log(f"  Phase 3 EXIT [z_limit]: z_offset={z_offset:.4f}m, depth={depth}")

        # ════════════════════════════════════════════════════════════
        # Stabilize
        # ════════════════════════════════════════════════════════════
        self._log(f"  Stabilizing for {STABILIZE_DURATION}s...")
        self.sleep_for(STABILIZE_DURATION)

        # 최종 상태
        total_elapsed = _time.monotonic() - phase1_start
        phase3_elapsed = _time.monotonic() - phase3_start
        final_depth = self._compute_depth(port_transform, plug_frame)
        self._log(f"  FINAL: depth={final_depth:.5f}m" if final_depth is not None
                  else "  FINAL: depth=N/A")
        self._log(f"  TIMING: total={total_elapsed:.1f}s "
                  f"phase1={phase1_elapsed:.1f}s phase3={phase3_elapsed:.1f}s "
                  f"stabilize={STABILIZE_DURATION}s")
        self._log("OptimalPolicy.insert_cable() done")
        return True
