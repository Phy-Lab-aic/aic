"""
PilzPolicy: 완전 독립 torque-aware cable insertion policy.

Policy(aic_model) 직접 상속.

- Phase 1: PTP 직행 (중간점 없음, torque-aware execution이 안전 보장)
- Phase 2: LIN → PTP fallback
- Phase 3: Joint IK 삽입 + depth+force 완료 판정
- MoveItPy: /robot_description topic URDF → 로컬 mesh 경로 치환
- Trajectory execution: KDL gravity torque 검사, 초과 시 fine interpolation
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import PyKDL
import yaml
from geometry_msgs.msg import Point, Pose, Quaternion, PoseStamped
from moveit.planning import MoveItPy, PlanRequestParameters
from aic_control_interfaces.msg import JointMotionUpdate, TrajectoryGenerationMode
from aic_model.policy import (
    GetObservationCallback, MoveRobotCallback, Policy, SendFeedbackCallback,
)
from aic_task_interfaces.msg import Task
from rclpy.duration import Duration
from rclpy.time import Time
from tf2_ros import TransformException
from ament_index_python.packages import get_package_share_directory

# ══════════════════════════════════════════════════════════════════════
# 상수 — 모든 파라미터를 여기에 모아 관리
# ══════════════════════════════════════════════════════════════════════

# ── 타임아웃 / 초기화 ─────────────────────────────────────────────────
URDF_TIMEOUT_SEC = 5.0            # /robot_description 토픽 수신 대기 (초)
URDF_POLL_INTERVAL = 0.1          # URDF 수신 폴링 간격 (초)
TF_WAIT_TIMEOUT_SEC = 10.0        # TF 프레임 대기 타임아웃 (초)
TF_POLL_INTERVAL = 0.1            # TF 대기 폴링 간격 (초)
PLANNING_SCENE_TIMEOUT_SEC = 10.0 # planning scene 구성 타임아웃 (초)

# ── PILZ Planning ─────────────────────────────────────────────────────
PLANNING_TIME_SEC = 5.0           # MoveIt2 planning 최대 시간 (초)
PLANNING_ATTEMPTS = 3             # planning 시도 횟수
PHASE1_VELOCITY_SCALE = 0.3      # Phase 1 PTP velocity/acceleration scaling (0~1)
PHASE2_LIN_VELOCITY_SCALE = 0.3  # Phase 2 LIN velocity/acceleration scaling
PHASE2_PTP_VELOCITY_SCALE = 0.1  # Phase 2 PTP fallback velocity/acceleration scaling

# ── Phase 1-2 접근 오프셋 (port z축 방향, 음수=port 위) ──────────────
Z_OFFSET_APPROACH_SFP = -0.05    # Phase 1: SFP port 위 5cm 접근 (m)
Z_OFFSET_APPROACH_SC  = -0.02    # Phase 1: SC port 위 2cm 접근 (m)
Z_OFFSET_PREINSERT_SFP = -0.01   # Phase 2: SFP 삽입 직전 위치 (m)
Z_OFFSET_PREINSERT_SC  = -0.001     # Phase 2: SC 삽입 완료 위치 (m)

# ── Impedance (전 Phase 공유 — VLA 데이터 수집 호환) ────────────────
EXEC_STIFFNESS = [400.0, 400.0, 400.0, 150.0, 150.0, 150.0]  # joint stiffness (VLA 통일)
EXEC_DAMPING   = [60.0,  60.0,  60.0,  30.0, 30.0, 30.0]   # joint damping (VLA 통일)

# ── Trajectory Execution ──────────────────────────────────────────────
SETTLE_DURATION = 0.5            # trajectory/insertion 종료 후 안정화 시간 (초)
SETTLE_INTERVAL = 0.05           # 안정화 중 명령 발행 간격 (초)
FINE_INTERP_FACTOR = 8           # torque violation 시 waypoint 간 보간 배수

# ── IK 보정 (Phase 1 후 TCP 수렴) ────────────────────────────────────
IK_CONVERGE_THRESHOLD = 0.001    # TCP position 수렴 threshold (m, 1mm)
IK_CONVERGE_MAX_LOOPS = 100      # 최대 보정 루프 (100 × 0.05 = 5초)
IK_CONVERGE_DT = 0.05            # 보정 루프 주기 (초)

# ── Phase 3 삽입 제어 ─────────────────────────────────────────────────
INSERT_VELOCITY = 0.01           # TCP 삽입 속도 (m/s), 실제 이동량 = INSERT_VELOCITY × DT per step
DT = 0.05                        # Phase 3 제어 루프 주기 (초, 20Hz)
MAX_LOOPS = 2000                  # Phase 3 최대 루프 (2000 × 0.05 = 100초)

# ── Phase 3 힘/깊이 판정 ──────────────────────────────────────────────
DEPTH_THRESHOLD_SFP = 0.0        # SFP 삽입 완료 최소 depth (m, port 표면)
DEPTH_THRESHOLD_SC  = -0.0008     # SC 삽입 완료 최소 depth (m, port 표면보다 0.8mm 위)
FORCE_SLOPE_WINDOW = 5          # force 기울기 계산 window (샘플 수, 25 × 0.05s = 0.25초)
FORCE_SLOPE_THRESHOLD = -2.0     # force 기울기 threshold (N/s), 이 이하면 감소 중
FORCE_LOW_THRESHOLD = 5.0        # 삽입 완료 force 한계 (N), 이 이하 + slope 감소 → 즉시 종료
FORCE_STOP_THRESHOLD = 20.0      # 안전 정지 |force| 기준 (N, 채점 penalty 기준과 동일)
FORCE_PENALTY_DURATION = 1.5     # 20N 초과 시 정지 판정 대기 (초, 채점 1초 전 정지)

# ── Torque Safety (KDL gravity torque 검사) ───────────────────────────
EFFORT_LIMITS = np.array([150.0, 150.0, 150.0, 28.0, 28.0, 28.0])  # UR5e 관절별 토크 한계 (Nm)
TORQUE_SAFETY_MARGIN = 0.5       # 토크 한계의 50%를 안전 threshold로 사용

# ── KDL Tool Chain ────────────────────────────────────────────────────
CABLE_MASS_KG = 0.15             # 케이블 추정 무게 (kg, URDF 미포함)
TOOL_COM_Z_APPROX = -0.10       # tool chain 무게중심 z (wrist_3 기준, m)



# ── 유틸리티 함수 ────────────────────────────────────────────────────

def _quat_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    return np.array([
        [1 - 2*(y*y + z*z),   2*(x*y - z*w),       2*(x*z + y*w)],
        [2*(x*y + z*w),       1 - 2*(x*x + z*z),   2*(y*z - x*w)],
        [2*(x*z - y*w),       2*(y*z + x*w),       1 - 2*(x*x + y*y)],
    ])


def _quat_multiply(q1: tuple, q2: tuple) -> tuple:
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return (
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    )


class PilzPolicy(Policy):
    """torque-aware cable insertion policy."""

    def __init__(self, parent_node):
        super().__init__(parent_node)
        self._moveit: MoveItPy | None = None
        self._arm = None
        self._planning_scene_manager = None
        self._kdl_chain = None
        self._kdl_gravity_solver = None
        self._cached_urdf: str | None = None

        # 디버그 로그 파일
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path.cwd() / "tmp"
        log_dir.mkdir(exist_ok=True)
        self._log_path = log_dir / f"pilz_policy_{ts}.log"
        self._log_file = open(self._log_path, "w")
        self.get_logger().info(f"Debug log: {self._log_path}")

    def _log(self, msg: str):
        self.get_logger().info(msg)
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_file.write(f"[{ts}] {msg}\n")
        self._log_file.flush()

    # ══════════════════════════════════════════════════════════════════
    # 초기화: URDF / MoveItPy / KDL
    # ══════════════════════════════════════════════════════════════════

    def _get_robot_description(self) -> str | None:
        if self._cached_urdf is not None:
            return self._cached_urdf

        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, DurabilityPolicy

        urdf_str = None

        def _cb(msg: String):
            nonlocal urdf_str
            urdf_str = msg.data

        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        sub = self._parent_node.create_subscription(String, "/robot_description", _cb, qos)
        start = self.time_now()
        while urdf_str is None:
            if (self.time_now() - start).nanoseconds * 1e-9 > URDF_TIMEOUT_SEC:
                break
            self.sleep_for(URDF_POLL_INTERVAL)
        self._parent_node.destroy_subscription(sub)

        if urdf_str is None:
            self._log("  robot_description topic not available")
            return None

        local_ur = get_package_share_directory("ur_description")
        urdf_str = urdf_str.replace("/ws_aic/install/share/ur_description", local_ur)
        self._log(f"  robot_description: loaded, mesh path → {local_ur}")
        self._cached_urdf = urdf_str
        return urdf_str

    def _init_moveit(self):
        if self._moveit is not None:
            return

        urdf_str = self._get_robot_description()

        pkg_share = Path(get_package_share_directory("my_policy"))
        srdf_str = (pkg_share / "config" / "ur5e.srdf").read_text()
        with open(pkg_share / "config" / "kinematics.yaml") as f:
            kinematics = yaml.safe_load(f)
        with open(pkg_share / "config" / "pilz_cartesian_limits.yaml") as f:
            cartesian_limits = yaml.safe_load(f)

        config_dict = {
            "robot_description_semantic": srdf_str,
            "robot_description_kinematics": kinematics,
            **cartesian_limits,
            "planning_pipelines": {"pipeline_names": ["pilz_industrial_motion_planner"]},
            "pilz_industrial_motion_planner": {
                "planning_plugins": ["pilz_industrial_motion_planner/CommandPlanner"],
                "request_adapters": [
                    "default_planning_request_adapters/ResolveConstraintFrames",
                    "default_planning_request_adapters/ValidateWorkspaceBounds",
                    "default_planning_request_adapters/CheckStartStateBounds",
                    "default_planning_request_adapters/CheckStartStateCollision",
                ],
                "response_adapters": [
                    "default_planning_response_adapters/DisplayMotionPath",
                ],
            },
        }
        if urdf_str:
            config_dict["robot_description"] = urdf_str

        self._moveit = MoveItPy(node_name="my_policy_node", config_dict=config_dict)
        self._arm = self._moveit.get_planning_component("manipulator")

        from .planning_scene import PlanningSceneManager
        self._planning_scene_manager = PlanningSceneManager(
            self._parent_node, self._parent_node._tf_buffer,
        )
        self.get_logger().info("MoveItPy initialized (V6)")

    def _init_kdl(self):
        if self._kdl_gravity_solver is not None:
            return

        from urdf_parser_py.urdf import URDF
        urdf_str = self._get_robot_description()
        if not urdf_str:
            self._log("  KDL: robot_description not available")
            return

        try:
            robot = URDF.from_xml_string(urdf_str)
        except Exception as e:
            self._log(f"  KDL: URDF parse failed: {e}")
            return

        joint_names = [
            "shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
            "wrist_1_joint", "wrist_2_joint", "wrist_3_joint",
        ]

        # wrist_3 이후 tool chain의 총 질량 계산 (KDL chain에 미포함 → wrist_3에 합산)
        tool_chain_links = [
            "flange", "tool0", "cam_mount/cam_mount_link",
            "ati/base_link", "ati/tool_link", "gripper/hande_base_link",
            "gripper/hande_finger_link_l", "gripper/hande_finger_link_r",
            "left_camera/camera_link", "center_camera/camera_link", "right_camera/camera_link",
        ]
        tool_mass = 0.0
        for lname in tool_chain_links:
            lnk = next((l for l in robot.links if l.name == lname), None)
            if lnk and lnk.inertial and lnk.inertial.mass:
                tool_mass += lnk.inertial.mass
        tool_mass += CABLE_MASS_KG
        self._log(f"  KDL: tool chain mass = {tool_mass:.3f}kg (added to wrist_3)")

        chain = PyKDL.Chain()
        for jname in joint_names:
            uj = next((j for j in robot.joints if j.name == jname), None)
            if uj is None:
                self._log(f"  KDL: joint '{jname}' not found")
                return
            cl = next((l for l in robot.links if l.name == uj.child), None)

            origin = uj.origin
            if origin:
                xyz = origin.xyz or [0, 0, 0]
                rpy = origin.rpy or [0, 0, 0]
                frame = PyKDL.Frame(PyKDL.Rotation.RPY(*rpy), PyKDL.Vector(*xyz))
            else:
                frame = PyKDL.Frame.Identity()

            if cl and cl.inertial:
                iner = cl.inertial
                mass = iner.mass or 0.0
                com_xyz = iner.origin.xyz if iner.origin else [0, 0, 0]

                # wrist_3_link에 tool chain 질량 합산
                if cl.name == "wrist_3_link":
                    mass += tool_mass
                    # tool chain COM을 wrist_3 기준 z축 아래 ~0.1m로 근사
                    total_mass = mass
                    orig_mass = iner.mass or 0.0
                    if total_mass > 0:
                        # 가중 평균 COM: (원래 COM * 원래 mass + tool COM * tool mass) / total
                        tool_com_z = TOOL_COM_Z_APPROX
                        com_z = (com_xyz[2] * orig_mass + tool_com_z * tool_mass) / total_mass
                        com_xyz = [com_xyz[0], com_xyz[1], com_z]
                    self._log(f"  KDL: wrist_3 total mass = {mass:.3f}kg, com_z = {com_xyz[2]:.4f}m")

                com = PyKDL.Vector(*com_xyz)
                ii = iner.inertia
                rot_i = PyKDL.RotationalInertia(
                    ii.ixx or 0, ii.iyy or 0, ii.izz or 0,
                    ii.ixy or 0, ii.ixz or 0, ii.iyz or 0,
                ) if ii else PyKDL.RotationalInertia()
                inertia = PyKDL.RigidBodyInertia(mass, com, rot_i)
            else:
                inertia = PyKDL.RigidBodyInertia()

            chain.addSegment(PyKDL.Segment(jname, PyKDL.Joint(jname, PyKDL.Joint.RotZ), frame, inertia))

        self._kdl_chain = chain
        self._kdl_gravity_solver = PyKDL.ChainDynParam(chain, PyKDL.Vector(0, 0, -9.81))
        self._log(f"  KDL: initialized, {chain.getNrOfJoints()} joints")

    # ══════════════════════════════════════════════════════════════════
    # 헬퍼
    # ══════════════════════════════════════════════════════════════════

    def _wait_for_tf(self, target_frame: str, source_frame: str, timeout_sec: float = TF_WAIT_TIMEOUT_SEC) -> bool:
        start = self.time_now()
        while (self.time_now() - start) < Duration(seconds=timeout_sec):
            try:
                self._parent_node._tf_buffer.lookup_transform(target_frame, source_frame, Time())
                return True
            except TransformException:
                self.sleep_for(TF_POLL_INTERVAL)
        self.get_logger().error(f"TF '{source_frame}' not available after {timeout_sec}s")
        return False

    def _compute_tcp_target(self, port_tf, plug_to_tcp_tf, z_offset: float, is_sc: bool = False) -> Pose:
        pt = port_tf.transform.translation
        pr = port_tf.transform.rotation
        q_port = np.array([pr.x, pr.y, pr.z, pr.w])
        R_port = _quat_to_matrix(*q_port[:3], q_port[3])
        insert_axis = R_port[:, 2]
        desired_pos = np.array([pt.x, pt.y, pt.z]) + insert_axis * z_offset

        tt = plug_to_tcp_tf.transform.translation
        tr = plug_to_tcp_tf.transform.rotation
        q_plug_tcp = np.array([tr.x, tr.y, tr.z, tr.w])
        R_plug = _quat_to_matrix(*q_port[:3], q_port[3])
        tcp_world = desired_pos + R_plug @ np.array([tt.x, tt.y, tt.z])
        q_tcp = _quat_multiply(tuple(q_port), tuple(q_plug_tcp))

        return Pose(
            position=Point(x=tcp_world[0], y=tcp_world[1], z=tcp_world[2]),
            orientation=Quaternion(x=q_tcp[0], y=q_tcp[1], z=q_tcp[2], w=q_tcp[3]),
        )

    def _port_insert_direction(self, port_tf) -> np.ndarray:
        pr = port_tf.transform.rotation
        return _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)[:, 2]

    def _pose_to_stamped(self, pose: Pose) -> PoseStamped:
        ps = PoseStamped()
        ps.header.frame_id = "world"
        ps.header.stamp = self._parent_node.get_clock().now().to_msg()
        ps.pose = pose
        return ps

    def _compute_gravity_torque(self, joint_positions: np.ndarray) -> np.ndarray | None:
        if self._kdl_gravity_solver is None:
            return None
        n = self._kdl_chain.getNrOfJoints()
        q = PyKDL.JntArray(n)
        for i in range(min(n, len(joint_positions))):
            q[i] = float(joint_positions[i])
        grav = PyKDL.JntArray(n)
        self._kdl_gravity_solver.JntToGravity(q, grav)
        return np.array([grav[i] for i in range(n)])


    def _check_trajectory_torque(self, points) -> list[int]:
        limits = EFFORT_LIMITS * TORQUE_SAFETY_MARGIN
        violations = []
        max_torque = 0.0
        max_torque_idx = 0
        jnames = ["shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3"]

        for i, pt in enumerate(points):
            g = self._compute_gravity_torque(np.array(pt.positions[:6]))
            if g is None:
                continue
            abs_g = np.abs(g)
            peak_j = int(abs_g.argmax())
            peak_val = abs_g[peak_j]

            if peak_val > max_torque:
                max_torque = peak_val
                max_torque_idx = i

            if np.any(abs_g > limits):
                violations.append(i)
                if len(violations) <= 3:
                    # 실제 초과한 joint들 표시
                    exceeded = [
                        f"{jnames[j]}={abs_g[j]:.1f}/{limits[j]:.0f}Nm"
                        for j in range(6) if abs_g[j] > limits[j]
                    ]
                    self._log(
                        f"  TorqueCheck VIOLATION wp[{i}/{len(points)}] "
                        f"{', '.join(exceeded)}"
                    )

        # peak waypoint의 전 joint gravity torque 출력
        if len(points) > 0:
            g_peak = self._compute_gravity_torque(np.array(points[max_torque_idx].positions[:6]))
            if g_peak is not None:
                torques_str = ", ".join(f"{jnames[j]}={abs(g_peak[j]):.1f}" for j in range(6))
                self._log(
                    f"  TorqueCheck: {len(violations)}/{len(points)} violations, "
                    f"peak wp[{max_torque_idx}]: [{torques_str}]Nm"
                )
                limits_str = ", ".join(f"{limits[j]:.0f}" for j in range(6))
                self._log(f"  TorqueCheck: thresholds=[{limits_str}]Nm")
        return violations

    # ══════════════════════════════════════════════════════════════════
    # Planning
    # ══════════════════════════════════════════════════════════════════

    def _plan_only(self, target_pose: Pose, planner_id: str, velocity_scale: float):
        self._arm.set_start_state_to_current_state()
        self._arm.set_goal_state(pose_stamped_msg=self._pose_to_stamped(target_pose), pose_link="gripper/tcp")

        plan_params = PlanRequestParameters(self._moveit, "pilz_industrial_motion_planner")
        plan_params.planning_pipeline = "pilz_industrial_motion_planner"
        plan_params.planner_id = planner_id
        plan_params.planning_time = PLANNING_TIME_SEC
        plan_params.max_velocity_scaling_factor = velocity_scale
        plan_params.max_acceleration_scaling_factor = velocity_scale
        plan_params.planning_attempts = PLANNING_ATTEMPTS

        plan_result = self._arm.plan(single_plan_parameters=plan_params)
        if not plan_result or not plan_result.trajectory:
            self._log(f"  PILZ {planner_id} planning failed")
            return None

        n_pts = len(plan_result.trajectory.get_robot_trajectory_msg().joint_trajectory.points)
        self._log(f"  Plan OK: {planner_id}, {n_pts} waypoints")
        return plan_result.trajectory

    def _plan_and_execute(self, target_pose, planner_id, velocity_scale, move_robot,
                          get_observation=None) -> bool:
        traj = self._plan_only(target_pose, planner_id, velocity_scale)
        if traj is None:
            return False
        self._execute_joint_trajectory(traj, move_robot, get_observation)
        return True

    # ══════════════════════════════════════════════════════════════════
    # insert_cable — torque-aware 경로 선택
    # ══════════════════════════════════════════════════════════════════

    def _phase1_torque_aware(self, tcp_target: Pose, move_robot, get_observation) -> bool:
        """Phase 1: 직행 시도 → torque violation 시 현재 높이 중간점으로 merged trajectory."""
        self._init_kdl()

        # 1) 직행 PTP plan + torque check
        traj = self._plan_only(tcp_target, "PTP", PHASE1_VELOCITY_SCALE)
        if traj is None:
            self._log("  Phase 1: PTP planning failed")
            return False

        points = traj.get_robot_trajectory_msg().joint_trajectory.points
        violations = self._check_trajectory_torque(points)

        if not violations:
            self._log("  Phase 1: direct path torque-safe")
            self._execute_waypoints(points, move_robot, get_observation)
            return True

        # 2) violation → 현재 높이에서 목표 XY로 이동 후 하강하는 merged trajectory
        try:
            cur_tcp = self._parent_node._tf_buffer.lookup_transform("world", "gripper/tcp", Time())
            cur_z = cur_tcp.transform.translation.z
        except TransformException:
            self._log("  Phase 1: cannot read current TCP, using fine interpolation")
            self._execute_fine_interpolated(points, move_robot)
            return True

        self._log(f"  Phase 1: {len(violations)} violations, using intermediate z={cur_z:.3f}m")

        intermediate = Pose(
            position=Point(x=tcp_target.position.x, y=tcp_target.position.y, z=cur_z),
            orientation=tcp_target.orientation,
        )

        # leg1: current → intermediate (현재 높이에서 XY 이동)
        traj1 = self._plan_only(intermediate, "PTP", PHASE1_VELOCITY_SCALE)
        if traj1 is None:
            self._log("  Phase 1: leg1 planning failed, using fine interpolation")
            self._execute_fine_interpolated(points, move_robot)
            return True

        pts1 = traj1.get_robot_trajectory_msg().joint_trajectory.points

        # leg2: intermediate → target (하강) — start state를 leg1 끝으로 설정
        psm = self._moveit.get_planning_scene_monitor()
        with psm.read_write() as scene:
            rs = scene.current_state
            rs.set_joint_group_positions("manipulator", list(pts1[-1].positions[:6]))
        self._arm.set_start_state(robot_state=rs)
        self._arm.set_goal_state(
            pose_stamped_msg=self._pose_to_stamped(tcp_target),
            pose_link="gripper/tcp",
        )
        from moveit.planning import PlanRequestParameters
        plan_params = PlanRequestParameters(self._moveit, "pilz_industrial_motion_planner")
        plan_params.planning_pipeline = "pilz_industrial_motion_planner"
        plan_params.planner_id = "PTP"
        plan_params.planning_time = PLANNING_TIME_SEC
        plan_params.max_velocity_scaling_factor = PHASE1_VELOCITY_SCALE
        plan_params.max_acceleration_scaling_factor = PHASE1_VELOCITY_SCALE
        plan_params.planning_attempts = PLANNING_ATTEMPTS
        plan_result = self._arm.plan(single_plan_parameters=plan_params)

        if not plan_result or not plan_result.trajectory:
            self._log("  Phase 1: leg2 planning failed, executing leg1 only")
            self._execute_waypoints(pts1, move_robot, get_observation)
            return True

        pts2 = plan_result.trajectory.get_robot_trajectory_msg().joint_trajectory.points

        # 두 trajectory 합치기 (시간 연속, 접합점 중복 제거)
        from trajectory_msgs.msg import JointTrajectoryPoint
        from builtin_interfaces.msg import Duration as DurationMsg

        leg1_dur = pts1[-1].time_from_start.sec + pts1[-1].time_from_start.nanosec * 1e-9
        merged = list(pts1)
        for pt in pts2[1:]:
            new_pt = JointTrajectoryPoint()
            new_pt.positions = pt.positions
            new_pt.velocities = pt.velocities
            new_pt.accelerations = pt.accelerations
            t2 = pt.time_from_start.sec + pt.time_from_start.nanosec * 1e-9
            mt = leg1_dur + t2
            new_pt.time_from_start = DurationMsg(sec=int(mt), nanosec=int((mt - int(mt)) * 1e9))
            merged.append(new_pt)

        total_dur = merged[-1].time_from_start.sec + merged[-1].time_from_start.nanosec * 1e-9
        self._log(f"  Phase 1 merged: {len(pts1)}+{len(pts2)-1}={len(merged)} wp, duration={total_dur:.2f}s")
        self._execute_waypoints(merged, move_robot, get_observation)
        return True

    def insert_cable(self, task: Task, get_observation: GetObservationCallback,
                     move_robot: MoveRobotCallback, send_feedback: SendFeedbackCallback) -> bool:
        self._log("PilzPolicy.insert_cable() start")
        self._log(f"  task: cable={task.cable_name}, plug={task.plug_name}, "
                  f"target_module={task.target_module_name}, port={task.port_name}")
        self._init_moveit()

        port_frame = f"task_board/{task.target_module_name}/{task.port_name}_link"
        plug_frame = f"{task.cable_name}/{task.plug_name}_link"

        for frame in [port_frame, plug_frame]:
            if not self._wait_for_tf("world", frame):
                return False

        send_feedback("registering planning scene")
        self._planning_scene_manager.setup(timeout_sec=PLANNING_SCENE_TIMEOUT_SEC)

        try:
            port_tf = self._parent_node._tf_buffer.lookup_transform("world", port_frame, Time())
        except TransformException as e:
            self.get_logger().error(f"port TF failed: {e}")
            return False
        try:
            plug_to_tcp_tf = self._parent_node._tf_buffer.lookup_transform(plug_frame, "gripper/tcp", Time())
        except TransformException as e:
            self.get_logger().error(f"plug→tcp TF failed: {e}")
            return False

        is_sc = "sc_port" in task.port_name or "sc_port" in task.target_module_name
        self._log(f"  port_type={'SC' if is_sc else 'SFP'}")

        # ── Phase 1: Torque-aware PTP ──
        send_feedback("Phase 1: PTP approach")
        tcp_approach = self._compute_tcp_target(
            port_tf, plug_to_tcp_tf,
            z_offset=Z_OFFSET_APPROACH_SC if is_sc else Z_OFFSET_APPROACH_SFP, is_sc=is_sc,
        )
        self._log(f"  Phase 1 target: ({tcp_approach.position.x:.4f}, "
                  f"{tcp_approach.position.y:.4f}, {tcp_approach.position.z:.4f})")
        if not self._phase1_torque_aware(tcp_approach, move_robot, get_observation):
            self.get_logger().error("Phase 1 failed")
            return False
        self._log("  Phase 1 complete")

        # ── Phase 1.5: IK 보정 (TCP 수렴) ──
        send_feedback("Phase 1.5: IK convergence")
        converge_err = self._ik_converge(tcp_approach, get_observation, move_robot, label="Phase1.5")
        self._log(f"  Phase 1.5 final error: {converge_err:.4f}m")

        # ── Phase 2: LIN → PTP fallback ──
        send_feedback("Phase 2: LIN descent")
        tcp_preinsert = self._compute_tcp_target(
            port_tf, plug_to_tcp_tf,
            z_offset=Z_OFFSET_PREINSERT_SC if is_sc else Z_OFFSET_PREINSERT_SFP, is_sc=is_sc,
        )
        self._log(f"  Phase 2 target: ({tcp_preinsert.position.x:.4f}, "
                  f"{tcp_preinsert.position.y:.4f}, {tcp_preinsert.position.z:.4f})")
        if not self._plan_and_execute(tcp_preinsert, "LIN", PHASE2_LIN_VELOCITY_SCALE, move_robot, get_observation):
            self._log("  Phase 2 LIN failed, trying PTP")
            if not self._plan_and_execute(tcp_preinsert, "PTP", PHASE2_PTP_VELOCITY_SCALE, move_robot, get_observation):
                self.get_logger().error("Phase 2 failed")
                return False
        self._log("  Phase 2 complete")

        # ── Phase 3: Joint IK 삽입 ──
        depth_threshold = DEPTH_THRESHOLD_SC if is_sc else DEPTH_THRESHOLD_SFP
        send_feedback("Phase 3: insertion")
        self._force_insert(port_tf, plug_to_tcp_tf, plug_frame,
                           get_observation, move_robot, depth_threshold)
        self._log("PilzPolicy.insert_cable() done")
        return True

    # ══════════════════════════════════════════════════════════════════
    # Phase 1-2: torque-aware trajectory execution
    # ══════════════════════════════════════════════════════════════════

    def _execute_joint_trajectory(self, trajectory, move_robot: MoveRobotCallback,
                                  get_observation: GetObservationCallback = None):
        self._init_kdl()
        ros_traj = trajectory.get_robot_trajectory_msg()
        points = ros_traj.joint_trajectory.points
        if not points:
            return

        n_pts = len(points)
        duration = points[-1].time_from_start.sec + points[-1].time_from_start.nanosec * 1e-9
        violations = self._check_trajectory_torque(points)

        if violations:
            self._log(f"  Execute: {len(violations)}/{n_pts} torque violations → fine interpolation")
            self._execute_fine_interpolated(points, move_robot)
        else:
            self._log(f"  Execute: {n_pts} wp torque-safe, duration={duration:.2f}s")
            self._execute_waypoints(points, move_robot, get_observation)

    def _execute_waypoints(self, points, move_robot, get_observation=None):
        n_pts = len(points)
        t_start = self.time_now()

        for i, point in enumerate(points):
            t_sec = point.time_from_start.sec + point.time_from_start.nanosec * 1e-9
            wait = (t_start + Duration(seconds=t_sec) - self.time_now()).nanoseconds * 1e-9
            if wait > 0:
                self.sleep_for(wait)

            ju = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS,
                target_damping=EXEC_DAMPING,
                trajectory_generation_mode=TrajectoryGenerationMode(mode=TrajectoryGenerationMode.MODE_POSITION),
            )
            ju.target_state.positions = list(point.positions)
            move_robot(joint_motion_update=ju)

            # 첫/마지막/매 10번째만 로그
            if get_observation and (i == 0 or i == n_pts - 1 or (i + 1) % 10 == 0):
                obs = get_observation()
                if obs and obs.joint_states and obs.joint_states.position:
                    actual = np.array(obs.joint_states.position[:6])
                    jerr = np.abs(actual - np.array(point.positions[:6])).max()
                    fz = obs.wrist_wrench.wrench.force.z
                    # 실제 joint effort
                    effort = np.array(obs.joint_states.effort[:6]) if len(obs.joint_states.effort) >= 6 else None
                    eff_str = ""
                    if effort is not None:
                        eff_ratio = np.abs(effort) / EFFORT_LIMITS
                        peak_j = int(eff_ratio.argmax())
                        eff_str = f" eff_peak=j{peak_j}:{effort[peak_j]:.1f}Nm({eff_ratio[peak_j]*100:.0f}%)"
                    try:
                        tp = self._parent_node._tf_buffer.lookup_transform("world", "gripper/tcp", Time()).transform.translation
                        self._log(f"  wp[{i}/{n_pts}] jerr={jerr:.5f} pos=({tp.x:.4f},{tp.y:.4f},{tp.z:.4f}) fz={fz:.1f}N{eff_str}")
                    except TransformException:
                        self._log(f"  wp[{i}/{n_pts}] jerr={jerr:.5f} fz={fz:.1f}N{eff_str}")

        # 안정화
        t0 = self.time_now()
        while (self.time_now() - t0) < Duration(seconds=SETTLE_DURATION):
            ju = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS, target_damping=EXEC_DAMPING,
                trajectory_generation_mode=TrajectoryGenerationMode(mode=TrajectoryGenerationMode.MODE_POSITION),
            )
            ju.target_state.positions = list(points[-1].positions)
            move_robot(joint_motion_update=ju)
            self.sleep_for(SETTLE_INTERVAL)

    def _execute_fine_interpolated(self, points, move_robot):
        pos_list = [np.array(p.positions) for p in points]
        t_list = [p.time_from_start.sec + p.time_from_start.nanosec * 1e-9 for p in points]

        interp_pos, interp_t = [], []
        for i in range(len(pos_list) - 1):
            for k in range(FINE_INTERP_FACTOR):
                f = k / FINE_INTERP_FACTOR
                interp_pos.append(pos_list[i] + f * (pos_list[i+1] - pos_list[i]))
                interp_t.append(t_list[i] + f * (t_list[i+1] - t_list[i]))
        interp_pos.append(pos_list[-1])
        interp_t.append(t_list[-1])

        self._log(f"  FineInterp: {len(points)} → {len(interp_pos)} wp")
        t_start = self.time_now()
        for pos, t_sec in zip(interp_pos, interp_t):
            wait = (t_start + Duration(seconds=t_sec) - self.time_now()).nanoseconds * 1e-9
            if wait > 0:
                self.sleep_for(wait)
            ju = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS, target_damping=EXEC_DAMPING,
                trajectory_generation_mode=TrajectoryGenerationMode(mode=TrajectoryGenerationMode.MODE_POSITION),
            )
            ju.target_state.positions = pos.tolist()
            move_robot(joint_motion_update=ju)

        t0 = self.time_now()
        while (self.time_now() - t0) < Duration(seconds=SETTLE_DURATION):
            ju = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS, target_damping=EXEC_DAMPING,
                trajectory_generation_mode=TrajectoryGenerationMode(mode=TrajectoryGenerationMode.MODE_POSITION),
            )
            ju.target_state.positions = interp_pos[-1].tolist()
            move_robot(joint_motion_update=ju)
            self.sleep_for(SETTLE_INTERVAL)

    # ══════════════════════════════════════════════════════════════════
    # IK 보정: 고정 목표 pose에 TCP 수렴
    # ══════════════════════════════════════════════════════════════════

    def _ik_converge(self, target_pose: Pose, get_observation: GetObservationCallback,
                     move_robot: MoveRobotCallback, label: str = "IK_converge") -> float:
        """고정 목표 TCP pose에 IK 반복으로 수렴. 최종 position error(m) 반환."""
        psm = self._moveit.get_planning_scene_monitor()
        last_joints = None

        # 초기 joint state
        obs = get_observation()
        if obs and obs.joint_states and obs.joint_states.position:
            last_joints = list(obs.joint_states.position[:6])

        best_error = float("inf")
        for lc in range(1, IK_CONVERGE_MAX_LOOPS + 1):
            # IK 풀기
            ik_ok = False
            try:
                with psm.read_only() as scene:
                    rs = scene.current_state
                    ik_ok = rs.set_from_ik("manipulator", target_pose, "gripper/tcp")
                    if ik_ok:
                        last_joints = list(rs.get_joint_group_positions("manipulator"))
            except Exception:
                pass

            if last_joints is None:
                self.sleep_for(IK_CONVERGE_DT)
                continue

            # joint command 발행
            ju = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS, target_damping=EXEC_DAMPING,
                trajectory_generation_mode=TrajectoryGenerationMode(mode=TrajectoryGenerationMode.MODE_POSITION),
            )
            ju.target_state.positions = last_joints
            move_robot(joint_motion_update=ju)
            self.sleep_for(IK_CONVERGE_DT)

            # TCP error 측정
            try:
                tcp_tf = self._parent_node._tf_buffer.lookup_transform("world", "gripper/tcp", Time())
                actual = np.array([tcp_tf.transform.translation.x,
                                   tcp_tf.transform.translation.y,
                                   tcp_tf.transform.translation.z])
                target = np.array([target_pose.position.x,
                                   target_pose.position.y,
                                   target_pose.position.z])
                error = float(np.linalg.norm(actual - target))
                best_error = min(best_error, error)
            except TransformException:
                error = float("inf")

            if lc % 20 == 0 or lc == 1:
                self._log(f"  {label}[{lc}] error={error:.4f}m best={best_error:.4f}m")

            if error < IK_CONVERGE_THRESHOLD:
                self._log(f"  {label} converged: {error:.4f}m in {lc} loops")
                return error

        self._log(f"  {label} timeout: best={best_error:.4f}m after {IK_CONVERGE_MAX_LOOPS} loops")
        return best_error

    # ══════════════════════════════════════════════════════════════════
    # Phase 3: Joint IK 삽입 + depth+force 완료 판정
    # ══════════════════════════════════════════════════════════════════

    def _force_insert(self, port_tf, plug_to_tcp_tf, plug_frame: str,
                      get_observation: GetObservationCallback,
                      move_robot: MoveRobotCallback, depth_threshold: float = 0.0):
        exit_reason = "timeout"
        excessive_force_start: float | None = None
        f_insert_history: list[float] = []

        port_z = self._port_insert_direction(port_tf)
        port_pos = np.array([port_tf.transform.translation.x,
                             port_tf.transform.translation.y,
                             port_tf.transform.translation.z])
        pr = port_tf.transform.rotation
        R_port = _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)

        self._log(f"  Phase 3 START: vel={INSERT_VELOCITY}, dt={DT}, max={MAX_LOOPS}, "
                  f"force_stop={FORCE_STOP_THRESHOLD}N/{FORCE_PENALTY_DURATION}s")

        try:
            tcp_tf = self._parent_node._tf_buffer.lookup_transform("world", "gripper/tcp", Time())
            tcp_pos = np.array([tcp_tf.transform.translation.x,
                                tcp_tf.transform.translation.y,
                                tcp_tf.transform.translation.z])
            tcp_ori = tcp_tf.transform.rotation
        except TransformException as e:
            self._log(f"  Phase 3: TCP TF failed: {e}")
            return

        obs = get_observation()
        if not (obs and obs.joint_states and obs.joint_states.position):
            self._log("  Phase 3: no joint state")
            return
        last_joints = list(obs.joint_states.position[:6])

        # 초기 depth
        try:
            pf = self._parent_node._tf_buffer.lookup_transform("world", plug_frame, Time())
            pp = np.array([pf.transform.translation.x, pf.transform.translation.y, pf.transform.translation.z])
            d0 = np.dot(pp - port_pos, port_z)
            xy_x = float(np.dot(pp - port_pos, R_port[:, 0]))
            xy_y = float(np.dot(pp - port_pos, R_port[:, 1]))
            self._log(f"  Phase 3 init: depth={d0:.4f}m, xy_err=({xy_x:.4f},{xy_y:.4f})m")
        except TransformException:
            pass

        psm = self._moveit.get_planning_scene_monitor()
        ik_fails = 0
        depth = None

        for lc in range(1, MAX_LOOPS + 1):
            obs = get_observation()
            if obs is None:
                self.sleep_for(DT)
                continue

            # wrench → 삽입 방향 투영 force
            f_raw = np.array([obs.wrist_wrench.wrench.force.x,
                              obs.wrist_wrench.wrench.force.y,
                              obs.wrist_wrench.wrench.force.z])
            f_insert = -float(np.dot(f_raw, port_z))  # 양수=삽입방향, 음수=반발 (FTS와 port_z 부호 반전)
            f_abs = float(np.linalg.norm(f_raw))      # 전체 크기 (안전 정지용)
            now = self.time_now().nanoseconds * 1e-9

            try:
                pf = self._parent_node._tf_buffer.lookup_transform("world", plug_frame, Time())
                pp = np.array([pf.transform.translation.x, pf.transform.translation.y, pf.transform.translation.z])
                depth = float(np.dot(pp - port_pos, port_z))
            except TransformException:
                depth = None

            if lc % 10 == 0 or lc == 1:
                ds = f"{depth:.5f}" if depth is not None else "N/A"
                slope_str = f" slope={f_slope:.1f}N/s" if len(f_insert_history) >= FORCE_SLOPE_WINDOW else ""
                self._log(f"  P3[{lc:4d}] depth={ds}m f_ins={f_insert:.1f}N |f|={f_abs:.1f}N{slope_str} f=({f_raw[0]:.1f},{f_raw[1]:.1f},{f_raw[2]:.1f})N")

            # force 이력 기록 + 기울기 계산
            f_insert_history.append(f_insert)
            if len(f_insert_history) > FORCE_SLOPE_WINDOW:
                f_insert_history.pop(0)

            f_slope = 0.0
            if len(f_insert_history) >= FORCE_SLOPE_WINDOW:
                # 선형 회귀 기울기 (N/s): window 내 force 변화율
                y = np.array(f_insert_history)
                x = np.arange(len(y)) * DT
                f_slope = float((len(y) * np.dot(x, y) - x.sum() * y.sum()) /
                                (len(y) * np.dot(x, x) - x.sum()**2))

            # 삽입 완료 조건: depth >= threshold AND f_insert <= 5N AND force 감소 중 → 즉시 종료
            depth_ok = depth is not None and depth >= depth_threshold
            if depth_ok and f_insert <= FORCE_LOW_THRESHOLD and f_slope < FORCE_SLOPE_THRESHOLD:
                exit_reason = f"insert_complete: depth={depth:.5f}m f_ins={f_insert:.1f}N slope={f_slope:.1f}N/s"
                self._log(f"  Phase 3 EXIT [{exit_reason}]")
                break

            # 조건 3: 안전 정지 (|force| > 20N)
            if f_abs > FORCE_STOP_THRESHOLD:
                if excessive_force_start is None:
                    excessive_force_start = now
                    self._log(f"  Phase 3: |force| {f_abs:.1f}N > {FORCE_STOP_THRESHOLD}N")
                elif (now - excessive_force_start) > FORCE_PENALTY_DURATION:
                    exit_reason = f"force_stop: |f|={f_abs:.1f}N for {now - excessive_force_start:.2f}s, depth={depth}"
                    self._log(f"  Phase 3 EXIT [{exit_reason}]")
                    break
            else:
                excessive_force_start = None

            # TCP 증분 + IK
            prev = tcp_pos.copy()
            tcp_pos += port_z * INSERT_VELOCITY * DT

            target_pose = Pose(
                position=Point(x=float(tcp_pos[0]), y=float(tcp_pos[1]), z=float(tcp_pos[2])),
                orientation=tcp_ori,
            )
            ik_ok = False
            try:
                with psm.read_only() as scene:
                    rs = scene.current_state
                    ik_ok = rs.set_from_ik("manipulator", target_pose, "gripper/tcp")
                    if ik_ok:
                        last_joints = list(rs.get_joint_group_positions("manipulator"))
                        ik_fails = 0
            except Exception:
                pass
            if not ik_ok:
                ik_fails += 1
                tcp_pos = prev
                if ik_fails % 20 == 1:
                    self._log(f"  Phase 3: IK failed (x{ik_fails})")

            ju = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS, target_damping=EXEC_DAMPING,
                trajectory_generation_mode=TrajectoryGenerationMode(mode=TrajectoryGenerationMode.MODE_POSITION),
            )
            ju.target_state.positions = last_joints
            move_robot(joint_motion_update=ju)
            self.sleep_for(DT)
        else:
            exit_reason = f"max_loops={MAX_LOOPS}, depth={depth}"
            self._log(f"  Phase 3 EXIT [{exit_reason}]")

        # 최종 상태
        try:
            pf = self._parent_node._tf_buffer.lookup_transform("world", plug_frame, Time())
            pp = np.array([pf.transform.translation.x, pf.transform.translation.y, pf.transform.translation.z])
            fd = float(np.dot(pp - port_pos, port_z))
            xy_x = float(np.dot(pp - port_pos, R_port[:, 0]))
            xy_y = float(np.dot(pp - port_pos, R_port[:, 1]))
            self._log(f"  Phase 3 FINAL: loops={lc}, exit=[{exit_reason}], depth={fd:.5f}m, xy_err=({xy_x:.4f},{xy_y:.4f})m")
        except (TransformException, UnboundLocalError):
            self._log(f"  Phase 3 FINAL: exit=[{exit_reason}]")

