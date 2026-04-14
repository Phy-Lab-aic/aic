"""
PilzPolicy: 수렴 대기 제거 + 현재 위치 기반 재계획.

Phase 1/2 trajectory 완료 후 긴 수렴 대기 대신 짧은 안정화만 하고,
다음 Phase를 실제 현재 joint 상태에서 재계획.
→ 중력 잔차에 의한 정적 오프셋을 무시하고, 실제 위치 기반으로 다음 경로 생성.
→ stiffness 낮게 유지 (smoothness) + 수렴 대기 시간 제거 (duration 단축).
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Point, Pose, Quaternion, Vector3
from moveit.planning import MoveItPy, PlanRequestParameters
from aic_control_interfaces.msg import JointMotionUpdate, MotionUpdate, TrajectoryGenerationMode
from aic_model.policy import GetObservationCallback, MoveRobotCallback, Policy, SendFeedbackCallback
from aic_task_interfaces.msg import Task
from rclpy.duration import Duration
from rclpy.time import Time
from std_msgs.msg import Header
from tf2_ros import TransformException

from .planning_scene import PlanningSceneManager

# 삽입 단계 파라미터
INTERMEDIATE_THRESHOLD = 0.12  # m: 이 이상 이동 시 중간점 경유
INTERMEDIATE_Z_DROP = 0.03     # m: 초기 tip 높이에서 아래로 내리는 양
Z_OFFSET_APPROACH_SFP = -0.05      # m: port z축 반대 방향으로 5cm (접근 대기)
Z_OFFSET_APPROACH_SC = -0.02   
Z_OFFSET_PREINSERT_SFP = -0.02  # m: SFP — port 앞 2cm (plug가 긴 타입)
Z_OFFSET_PREINSERT_SC  = 0.0    # m: SC — port 원점까지 (Phase 2에서 삽입)
# Phase 3: 매우 느리게 삽입, force 17N 0.8초 이상이면 정지
# 삽입 완료 조건: depth가 threshold 이상 AND force가 15N 이상이 0.5초 지속
DEPTH_THRESHOLD_SFP = 0.0      # SFP: plug tip이 port 원점 도달 (고착 +0.001m)
DEPTH_THRESHOLD_SC  = -0.001   # SC: plug tip이 port 원점 -1mm (고착 ~-0.00007m)
FORCE_INSERT_THRESHOLD = 15.0 # N: 삽입 완료 판정 최소 force
FORCE_INSERT_SUSTAIN = 0.5    # sec: force 지속 시간
# 안전 정지: 과도한 force
FORCE_STOP_THRESHOLD = 20.0   # N: 강제 정지 (penalty 방지)
FORCE_PENALTY_DURATION = 0.8  # sec
INSERT_VELOCITY = 0.005       # m/s: 삽입 속도 (SC 저항 극복용)

# trajectory 실행 파라미터 (낮은 stiffness — smoothness 우선)
EXEC_STIFFNESS_APPROACH = [400.0, 400.0, 400.0, 150.0, 150.0, 150.0]
EXEC_DAMPING_APPROACH   = [60.0,  60.0,  60.0,  30.0,  30.0,  30.0]


class PilzPolicyV1(Policy):
    """MoveIt2 PILZ planner 기반 cable insertion policy."""

    def __init__(self, parent_node):
        super().__init__(parent_node)
        self._moveit: MoveItPy | None = None
        self._planning_scene_manager: PlanningSceneManager | None = None
        # 디버그 로그 파일 초기화 (실행 디렉토리의 tmp/ 하위)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path.cwd() / "tmp"
        log_dir.mkdir(exist_ok=True)
        self._log_path = log_dir / f"pilz_v5_debug_{ts}.log"
        self._log_file = open(self._log_path, "w")
        self.get_logger().info(f"Debug log: {self._log_path}")

    def _log(self, msg: str):
        """터미널(ROS logger) + 파일 동시 기록."""
        self.get_logger().info(msg)
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_file.write(f"[{ts}] {msg}\n")
        self._log_file.flush()

    def _init_moveit(self):
        """첫 insert_cable 호출 시 MoveItPy 초기화.

        config_dict로 SRDF/kinematics/pipeline을 직접 전달하여
        별도 move_group 노드 없이 내부 planning 실행.
        """
        if self._moveit is not None:
            return

        pkg_share = Path(get_package_share_directory("my_policy"))
        srdf_str = (pkg_share / "config" / "ur5e.srdf").read_text()
        with open(pkg_share / "config" / "kinematics.yaml") as f:
            kinematics = yaml.safe_load(f)
        with open(pkg_share / "config" / "pilz_cartesian_limits.yaml") as f:
            cartesian_limits = yaml.safe_load(f)

        # MoveIt2 Kilted 실제 파라미터 구조 (moveit_cpp.hpp 기준):
        #   planning_pipelines.pipeline_names  ← MoveItCpp가 읽는 실제 키
        #   {pipeline_name}.planning_plugins   ← PlanningPipeline이 읽는 키
        config_dict = {
            "robot_description_semantic": srdf_str,
            "robot_description_kinematics": kinematics,
            **cartesian_limits,
            "planning_pipelines": {
                "pipeline_names": ["pilz_industrial_motion_planner"],
            },
            "pilz_industrial_motion_planner": {
                "planning_plugins": ["pilz_industrial_motion_planner/CommandPlanner"],
                "request_adapters": [
                    "default_planning_request_adapters/ResolveConstraintFrames",
                    "default_planning_request_adapters/ValidateWorkspaceBounds",
                    "default_planning_request_adapters/CheckStartStateBounds",
                    "default_planning_request_adapters/CheckStartStateCollision",
                ],
                "response_adapters": [
                    # ValidateSolution 제거: planning scene collision이 false positive로
                    # 유효한 경로를 거부하는 문제 방지. aic_controller가 실행 안전성 담당.
                    "default_planning_response_adapters/DisplayMotionPath",
                ],
            },
        }

        self._moveit = MoveItPy(
            node_name="my_policy_node",
            config_dict=config_dict,
        )
        self._arm = self._moveit.get_planning_component("manipulator")
        self._planning_scene_manager = PlanningSceneManager(
            self._parent_node,
            self._parent_node._tf_buffer,
        )
        self.get_logger().info("MoveItPy initialized (standalone, no move_group needed)")

    def insert_cable(
        self,
        task: Task,
        get_observation: GetObservationCallback,
        move_robot: MoveRobotCallback,
        send_feedback: SendFeedbackCallback,
    ) -> bool:
        self._log("PILZPolicy.insert_cable() start")
        self._log(
            f"  task: cable={task.cable_name}, plug={task.plug_name}, "
            f"target_module={task.target_module_name}, port={task.port_name}"
        )
        self._init_moveit()

        port_frame = f"task_board/{task.target_module_name}/{task.port_name}_link"
        plug_frame = f"{task.cable_name}/{task.plug_name}_link"
        self._log(f"  port_frame: {port_frame}")
        self._log(f"  plug_frame: {plug_frame}")

        # TF 대기
        for frame in [port_frame, plug_frame]:
            if not self._wait_for_tf("world", frame):
                self.get_logger().error(f"TF not available: {frame}")
                return False

        send_feedback("registering planning scene")
        self._planning_scene_manager.setup(timeout_sec=10.0)

        # port TF 고정 (trial 동안 변하지 않음)
        try:
            port_tf = self._parent_node._tf_buffer.lookup_transform(
                "world", port_frame, Time()
            )
        except TransformException as e:
            self.get_logger().error(f"port TF lookup failed: {e}")
            return False

        pt = port_tf.transform.translation
        pr = port_tf.transform.rotation
        self._log(
            f"  port TF (world): pos=({pt.x:.4f}, {pt.y:.4f}, {pt.z:.4f}), "
            f"rot=({pr.x:.4f}, {pr.y:.4f}, {pr.z:.4f}, {pr.w:.4f})"
        )

        # plug → gripper/tcp 변환 (그리퍼가 plug를 잡고 있는 동안 고정)
        try:
            plug_to_tcp_tf = self._parent_node._tf_buffer.lookup_transform(
                plug_frame, "gripper/tcp", Time()
            )
        except TransformException as e:
            self.get_logger().error(f"plug→tcp TF lookup failed: {e}")
            return False

        tt = plug_to_tcp_tf.transform.translation
        tr = plug_to_tcp_tf.transform.rotation
        self._log(
            f"  plug→tcp TF: pos=({tt.x:.4f}, {tt.y:.4f}, {tt.z:.4f}), "
            f"rot=({tr.x:.4f}, {tr.y:.4f}, {tr.z:.4f}, {tr.w:.4f})"
        )

        # 현재 로봇 상태 확인 (joints + FT + gripper)
        obs = get_observation()
        if obs and obs.joint_states and obs.joint_states.position:
            joint_names = list(obs.joint_states.name)
            joint_pos = [f"{p:.4f}" for p in obs.joint_states.position]
            self._log(f"  current joints: {dict(zip(joint_names, joint_pos))}")

            w = obs.wrist_wrench.wrench
            self._log(
                f"  initial FT: force=({w.force.x:.2f},{w.force.y:.2f},{w.force.z:.2f})N "
                f"torque=({w.torque.x:.3f},{w.torque.y:.3f},{w.torque.z:.3f})Nm"
            )
            if len(obs.joint_states.position) > 6:
                gp = obs.joint_states.position[6]
                ge = obs.joint_states.effort[6] if len(obs.joint_states.effort) > 6 else 0.0
                self._log(f"  initial gripper: pos={gp:.4f}m effort={ge:.2f}N")

        # 포트 타입 판별
        is_sc = "sc_port" in task.port_name or "sc_port" in task.target_module_name
        self._log(f"  port_type={'SC' if is_sc else 'SFP'}")

        # Phase 1: PTP — plug를 port 앞으로 접근
        send_feedback("Phase 1: PTP approach")

        tcp_target_approach = self._compute_tcp_target(
            port_tf, plug_to_tcp_tf, z_offset=Z_OFFSET_APPROACH_SC if is_sc else Z_OFFSET_APPROACH_SFP, is_sc=is_sc
        )

        # 이동 거리 판단 → 중간점 경유 여부
        need_intermediate = False
        try:
            cur_tcp = self._parent_node._tf_buffer.lookup_transform(
                "world", "gripper/tcp", Time()
            )
            cur_pos = np.array([
                cur_tcp.transform.translation.x,
                cur_tcp.transform.translation.y,
                cur_tcp.transform.translation.z,
            ])
            tgt_pos = np.array([
                tcp_target_approach.position.x,
                tcp_target_approach.position.y,
                tcp_target_approach.position.z,
            ])
            dist = np.linalg.norm(cur_pos - tgt_pos)
            need_intermediate = dist > INTERMEDIATE_THRESHOLD
            self._log(
                f"  Phase 1: move dist={dist:.3f}m, intermediate={'YES' if need_intermediate else 'NO'}"
            )
        except TransformException:
            pass

        if need_intermediate:
            # Phase 1a: 초기 tip 높이에서 약간만 내려서, 최종 목표의 XY+축 정렬
            # → 높이 유지하며 수평 이동 (중력 토크 최소)
            intermediate_z = cur_pos[2] - INTERMEDIATE_Z_DROP
            tcp_intermediate = Pose(
                position=Point(
                    x=tcp_target_approach.position.x,
                    y=tcp_target_approach.position.y,
                    z=intermediate_z,
                ),
                orientation=tcp_target_approach.orientation,
            )
            self._log(
                f"  Phase 1a intermediate (tcp, world): pos=("
                f"{tcp_target_approach.position.x:.4f}, "
                f"{tcp_target_approach.position.y:.4f}, {intermediate_z:.4f})"
            )
            if not self._plan_and_execute(
                tcp_intermediate, planner_id="PTP",
                velocity_scale=0.5, move_robot=move_robot,
                get_observation=get_observation,
            ):
                self.get_logger().error("Phase 1a intermediate PTP failed")
                return False
            self._log("  Phase 1a intermediate complete")

        # Phase 1b (또는 Phase 1 직접): 최종 approach 위치
        self._log(
            f"  Phase 1 target (tcp, world): pos=({tcp_target_approach.position.x:.4f}, "
            f"{tcp_target_approach.position.y:.4f}, {tcp_target_approach.position.z:.4f})"
        )

        if not self._plan_and_execute(
            tcp_target_approach, planner_id="PTP",
            velocity_scale=0.5, move_robot=move_robot,
            get_observation=get_observation,
        ):
            self.get_logger().error("Phase 1 PTP planning failed")
            return False
        self._log("  Phase 1 PTP complete")

        # Phase 2: LIN — 포트 입구로 직선 접근
        send_feedback("Phase 2: LIN descent")
        tcp_target_preinsert = self._compute_tcp_target(
            port_tf, plug_to_tcp_tf,
            z_offset=Z_OFFSET_PREINSERT_SC if is_sc else Z_OFFSET_PREINSERT_SFP,
            is_sc=is_sc
        )
        self._log(
            f"  Phase 2 target (tcp, world): pos=({tcp_target_preinsert.position.x:.4f}, "
            f"{tcp_target_preinsert.position.y:.4f}, {tcp_target_preinsert.position.z:.4f})"
        )
        if not self._plan_and_execute(
            tcp_target_preinsert, planner_id="LIN",
            velocity_scale=0.3, move_robot=move_robot,
            get_observation=get_observation,
        ):
            self._log("Phase 2 LIN failed, trying PTP fallback")
            if not self._plan_and_execute(
                tcp_target_preinsert, planner_id="PTP",
                velocity_scale=0.3, move_robot=move_robot,
                get_observation=get_observation,
            ):
                self.get_logger().error("Phase 2 fallback also failed")
                return False
        self._log("  Phase 2 complete")

        # Phase 3: velocity control + FTS 모니터링 삽입
        depth_threshold = DEPTH_THRESHOLD_SC if is_sc else DEPTH_THRESHOLD_SFP
        send_feedback("Phase 3: force-compliant insertion")
        self._log(
            f"  Phase 3: port_type={'SC' if is_sc else 'SFP'}, "
            f"depth_threshold={depth_threshold}"
        )
        self._force_insert(port_tf, plug_to_tcp_tf, plug_frame,
                           get_observation, move_robot, depth_threshold)

        self._log("PILZPolicy.insert_cable() done")
        return True

    # ── Phase 1~2: PILZ planning + execution ───────────────────────────────

    def _plan_only(self, target_pose: Pose, planner_id: str,
                   velocity_scale: float):
        """PILZ planning만 수행, trajectory 반환 (None이면 실패)."""
        self._arm.set_start_state_to_current_state()
        self._arm.set_goal_state(
            pose_stamped_msg=self._pose_to_stamped(target_pose),
            pose_link="gripper/tcp",
        )

        plan_params = PlanRequestParameters(self._moveit, "pilz_industrial_motion_planner")
        plan_params.planning_pipeline = "pilz_industrial_motion_planner"
        plan_params.planner_id = planner_id
        plan_params.planning_time = 5.0
        plan_params.max_velocity_scaling_factor = velocity_scale
        plan_params.max_acceleration_scaling_factor = velocity_scale
        plan_params.planning_attempts = 3

        self._log(
            f"  Planning: pipeline=pilz, planner_id={planner_id}, "
            f"vel_scale={velocity_scale}, target=({target_pose.position.x:.4f}, "
            f"{target_pose.position.y:.4f}, {target_pose.position.z:.4f})"
        )

        plan_result = self._arm.plan(single_plan_parameters=plan_params)

        if not plan_result or not plan_result.trajectory:
            self._log(f"PILZ {planner_id} planning failed (no trajectory)")
            return None

        ros_traj = plan_result.trajectory.get_robot_trajectory_msg()
        points = ros_traj.joint_trajectory.points
        joint_names = list(ros_traj.joint_trajectory.joint_names)
        n_pts = len(points)
        if n_pts > 0:
            last_pt = points[-1]
            duration = last_pt.time_from_start.sec + last_pt.time_from_start.nanosec * 1e-9
            self._log(f"  Plan OK: {n_pts} waypoints, duration={duration:.2f}s")
            self._log(f"  Plan joints: {joint_names}")
            # 첫/마지막/중간 waypoint 로그
            for idx in [0, n_pts // 2, n_pts - 1]:
                if idx < n_pts:
                    pt = points[idx]
                    t = pt.time_from_start.sec + pt.time_from_start.nanosec * 1e-9
                    pos_str = ", ".join(f"{p:.4f}" for p in pt.positions)
                    self._log(
                        f"  Plan wp[{idx}/{n_pts}] t={t:.3f}s: [{pos_str}]"
                    )

        return plan_result.trajectory

    def _plan_and_execute(
        self,
        target_pose: Pose,
        planner_id: str,
        velocity_scale: float,
        move_robot: MoveRobotCallback,
        get_observation: GetObservationCallback = None,
    ) -> bool:
        """PILZ로 경로 계획 후 aic_controller에 waypoint stream 전송."""
        traj = self._plan_only(target_pose, planner_id, velocity_scale)
        if traj is None:
            return False
        self._execute_joint_trajectory(traj, move_robot, get_observation)
        return True

    def _execute_joint_trajectory(self, trajectory, move_robot: MoveRobotCallback,
                                  get_observation: GetObservationCallback = None):
        """RobotTrajectory waypoint를 JointMotionUpdate로 publish."""
        ros_traj = trajectory.get_robot_trajectory_msg()
        points = ros_traj.joint_trajectory.points
        if not points:
            self._log("  Execute: trajectory has 0 points, skipping")
            return

        last_pt = points[-1]
        traj_duration = last_pt.time_from_start.sec + last_pt.time_from_start.nanosec * 1e-9
        n_pts = len(points)

        self._log(
            f"  Execute: sending {n_pts} waypoints (traj_duration={traj_duration:.2f}s)"
        )

        # 절대 시간 기준 전송
        t_start = self.time_now()

        for i, point in enumerate(points):
            # 절대 시간 대기
            target_sec = point.time_from_start.sec + point.time_from_start.nanosec * 1e-9
            target_time = t_start + Duration(seconds=target_sec)
            now = self.time_now()
            wait = (target_time - now).nanoseconds * 1e-9
            if wait > 0:
                self.sleep_for(wait)

            joint_update = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS_APPROACH,
                target_damping=EXEC_DAMPING_APPROACH,
                trajectory_generation_mode=TrajectoryGenerationMode(
                    mode=TrajectoryGenerationMode.MODE_POSITION
                ),
            )
            joint_update.target_state.positions = list(point.positions)
            move_robot(joint_motion_update=joint_update)

            # 매 waypoint마다 joint error + TCP 6D + FT + gripper 로그
            if get_observation is not None:
                obs = get_observation()
                if obs and obs.joint_states and obs.joint_states.position:
                    actual = np.array(obs.joint_states.position[:6])
                    target = np.array(point.positions[:6])
                    errors = np.abs(actual - target)
                    elapsed = (self.time_now() - t_start).nanoseconds * 1e-9

                    # FT 센서
                    w = obs.wrist_wrench.wrench
                    ft_str = f"ft=({w.force.x:.1f},{w.force.y:.1f},{w.force.z:.1f})N"

                    # 그리퍼
                    gp = obs.joint_states.position[6] if len(obs.joint_states.position) > 6 else None
                    ge = obs.joint_states.effort[6] if len(obs.joint_states.effort) > 6 else None
                    grip_str = f"grip={gp:.6f}m/{ge:.2f}N" if gp is not None else ""

                    try:
                        tcp_tf = self._parent_node._tf_buffer.lookup_transform(
                            "world", "gripper/tcp", Time()
                        )
                        tp = tcp_tf.transform.translation
                        tr = tcp_tf.transform.rotation
                        self._log(
                            f"  Exec wp[{i}/{n_pts}] t={target_sec:.3f}s dt={elapsed:.3f}s "
                            f"jerr={errors.max():.5f} "
                            f"pos=({tp.x:.4f},{tp.y:.4f},{tp.z:.4f}) "
                            f"quat=({tr.x:.4f},{tr.y:.4f},{tr.z:.4f},{tr.w:.4f}) "
                            f"{ft_str} {grip_str}"
                        )
                    except TransformException:
                        self._log(
                            f"  Exec wp[{i}/{n_pts}] t={target_sec:.3f}s dt={elapsed:.3f}s "
                            f"jerr={errors.max():.5f} {ft_str} {grip_str}"
                        )

        # 짧은 안정화 대기 (수렴 대기 제거 — 다음 Phase에서 재계획)
        # 마지막 waypoint를 1초간 유지하며 로봇 안정화
        stabilize_sec = 1.0
        self._log(f"  Stabilize: {stabilize_sec}s (no converge wait)")
        stabilize_start = self.time_now()
        while (self.time_now() - stabilize_start) < Duration(seconds=stabilize_sec):
            joint_update = JointMotionUpdate(
                target_stiffness=EXEC_STIFFNESS_APPROACH,
                target_damping=EXEC_DAMPING_APPROACH,
                trajectory_generation_mode=TrajectoryGenerationMode(
                    mode=TrajectoryGenerationMode.MODE_POSITION
                ),
            )
            joint_update.target_state.positions = list(points[-1].positions)
            move_robot(joint_motion_update=joint_update)
            self.sleep_for(0.05)

        # 안정화 후 상태 로그
        if get_observation is not None:
            obs = get_observation()
            if obs and obs.joint_states and obs.joint_states.position:
                goal_positions = np.array(points[-1].positions)
                current = np.array(obs.joint_states.position[:6])
                errors = np.abs(current - goal_positions[:6])

                w = obs.wrist_wrench.wrench
                ft_str = f"ft=({w.force.x:.1f},{w.force.y:.1f},{w.force.z:.1f})N"
                gp = obs.joint_states.position[6] if len(obs.joint_states.position) > 6 else None
                ge = obs.joint_states.effort[6] if len(obs.joint_states.effort) > 6 else None
                grip_str = f"grip={gp:.6f}m/{ge:.2f}N" if gp is not None else ""

                try:
                    tcp_tf = self._parent_node._tf_buffer.lookup_transform(
                        "world", "gripper/tcp", Time()
                    )
                    tp = tcp_tf.transform.translation
                    tr = tcp_tf.transform.rotation
                    self._log(
                        f"  Stabilized: jerr={errors.max():.5f}(j{int(errors.argmax())}) "
                        f"pos=({tp.x:.4f},{tp.y:.4f},{tp.z:.4f}) "
                        f"quat=({tr.x:.4f},{tr.y:.4f},{tr.z:.4f},{tr.w:.4f}) "
                        f"{ft_str} {grip_str}"
                    )
                except TransformException:
                    self._log(
                        f"  Stabilized: jerr={errors.max():.5f} {ft_str} {grip_str}"
                    )

    # ── Phase 3: force-compliant insertion ─────────────────────────────────

    def _force_insert(
        self,
        port_tf,
        plug_to_tcp_tf,
        plug_frame: str,
        get_observation: GetObservationCallback,
        move_robot: MoveRobotCallback,
        depth_threshold: float,
    ):
        """매우 느린 속도로 삽입. depth+force 조합으로 완료 판단."""
        exit_reason = "timeout"
        excessive_force_start: float | None = None
        insert_complete_start: float | None = None  # depth+force 완료 판정 시작

        port_z_world = self._port_insert_direction(port_tf)
        port_pos = np.array([
            port_tf.transform.translation.x,
            port_tf.transform.translation.y,
            port_tf.transform.translation.z,
        ])
        pr = port_tf.transform.rotation
        R_port = _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)

        self._log(
            f"  Phase 3 START: vel={INSERT_VELOCITY}m/s, "
            f"force_stop={FORCE_STOP_THRESHOLD}N/{FORCE_PENALTY_DURATION}s"
        )

        # 초기 상태
        try:
            plug_tf = self._parent_node._tf_buffer.lookup_transform(
                "world", plug_frame, Time()
            )
            plug_pos = np.array([
                plug_tf.transform.translation.x,
                plug_tf.transform.translation.y,
                plug_tf.transform.translation.z,
            ])
            depth = np.dot(plug_pos - port_pos, port_z_world)
            xy_x = float(np.dot(plug_pos - port_pos, R_port[:, 0]))
            xy_y = float(np.dot(plug_pos - port_pos, R_port[:, 1]))
            self._log(
                f"  Phase 3 init: depth={depth:.4f}m, xy_err=({xy_x:.4f},{xy_y:.4f})m"
            )
        except TransformException:
            self._log("  Phase 3 init: TF failed")

        loop_count = 0
        max_loops = 600  # 30초
        depth = None
        while loop_count < max_loops:
            obs = get_observation()
            if obs is None:
                self.sleep_for(0.05)
                continue

            fz = abs(obs.wrist_wrench.wrench.force.z)
            now_sec = self.time_now().nanoseconds * 1e-9
            loop_count += 1

            # plug tip depth
            try:
                plug_tf = self._parent_node._tf_buffer.lookup_transform(
                    "world", plug_frame, Time()
                )
                plug_pos = np.array([
                    plug_tf.transform.translation.x,
                    plug_tf.transform.translation.y,
                    plug_tf.transform.translation.z,
                ])
                depth = float(np.dot(plug_pos - port_pos, port_z_world))
            except TransformException:
                depth = None

            # 매 10 루프 로그
            if loop_count % 10 == 0:
                depth_str = f"{depth:.5f}" if depth is not None else "N/A"
                dur_str = ""
                if excessive_force_start is not None:
                    dur_str = f" ({now_sec - excessive_force_start:.2f}s)"
                self._log(
                    f"  P3[{loop_count}] depth={depth_str}m fz={fz:.1f}N{dur_str} "
                    f"vel={INSERT_VELOCITY}m/s"
                )

            # 조건 1: 삽입 완료 — depth가 threshold 이상 AND force 지속
            if depth is not None and depth >= depth_threshold and fz > FORCE_INSERT_THRESHOLD:
                if insert_complete_start is None:
                    insert_complete_start = now_sec
                    self._log(
                        f"  Phase 3: insert complete detected depth={depth:.5f}m fz={fz:.1f}N"
                    )
                elif (now_sec - insert_complete_start) > FORCE_INSERT_SUSTAIN:
                    exit_reason = (
                        f"insert_complete: depth={depth:.5f}m fz={fz:.1f}N "
                        f"sustained {now_sec - insert_complete_start:.2f}s"
                    )
                    self._log(f"  Phase 3 EXIT [{exit_reason}]")
                    break
            else:
                insert_complete_start = None

            # 조건 2: 안전 정지 — 과도한 force
            if fz > FORCE_STOP_THRESHOLD:
                if excessive_force_start is None:
                    excessive_force_start = now_sec
                    self._log(f"  Phase 3: force {fz:.1f}N > {FORCE_STOP_THRESHOLD}N")
                elif (now_sec - excessive_force_start) > FORCE_PENALTY_DURATION:
                    exit_reason = (
                        f"force_stop: fz={fz:.1f}N for "
                        f"{now_sec - excessive_force_start:.2f}s, depth={depth}"
                    )
                    self._log(f"  Phase 3 EXIT [{exit_reason}]")
                    break
            else:
                excessive_force_start = None

            # 일정 속도로 삽입 방향 이동
            motion_update = MotionUpdate(
                header=Header(frame_id="base_link"),
                trajectory_generation_mode=TrajectoryGenerationMode(
                    mode=TrajectoryGenerationMode.MODE_VELOCITY
                ),
                target_stiffness=np.diag([
                    200.0, 200.0, 30.0, 50.0, 50.0, 50.0
                ]).flatten().tolist(),
                target_damping=np.diag([
                    150.0, 150.0, 25.0, 30.0, 30.0, 30.0
                ]).flatten().tolist(),
            )
            motion_update.velocity.linear.x = port_z_world[0] * INSERT_VELOCITY
            motion_update.velocity.linear.y = port_z_world[1] * INSERT_VELOCITY
            motion_update.velocity.linear.z = port_z_world[2] * INSERT_VELOCITY
            move_robot(motion_update=motion_update)
            self.sleep_for(0.05)

        if loop_count >= max_loops:
            exit_reason = f"max_loops={max_loops}, depth={depth}"
            self._log(f"  Phase 3 EXIT [{exit_reason}]")

        # 최종 상태
        try:
            plug_tf = self._parent_node._tf_buffer.lookup_transform(
                "world", plug_frame, Time()
            )
            plug_pos = np.array([
                plug_tf.transform.translation.x,
                plug_tf.transform.translation.y,
                plug_tf.transform.translation.z,
            ])
            final_depth = float(np.dot(plug_pos - port_pos, port_z_world))
            xy_x = float(np.dot(plug_pos - port_pos, R_port[:, 0]))
            xy_y = float(np.dot(plug_pos - port_pos, R_port[:, 1]))
            self._log(
                f"  Phase 3 FINAL: loops={loop_count}, exit=[{exit_reason}], "
                f"depth={final_depth:.5f}m, xy_err=({xy_x:.4f},{xy_y:.4f})m"
            )
        except TransformException:
            self._log(f"  Phase 3 FINAL: loops={loop_count}, exit=[{exit_reason}]")

        self.sleep_for(1.0)

    # ── 헬퍼 ────────────────────────────────────────────────────────────────

    def _wait_for_tf(
        self, target_frame: str, source_frame: str, timeout_sec: float = 10.0
    ) -> bool:
        """TF 프레임이 사용 가능해질 때까지 대기."""
        start = self.time_now()
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
                        f"Waiting for TF '{source_frame}' → '{target_frame}'..."
                        " (ground_truth:=true required)"
                    )
                attempt += 1
                self.sleep_for(0.1)
        self.get_logger().error(
            f"TF '{source_frame}' not available after {timeout_sec}s"
        )
        return False

    def _compute_tcp_target(self, port_tf, plug_to_tcp_tf, z_offset: float,
                            is_sc: bool = False) -> Pose:
        """plug를 port z축 방향 z_offset 위치에 정렬하기 위한 gripper/tcp 목표 포즈 계산.

        T_world_tcp = T_world_plug_desired × T_plug_tcp

        plug 방향 = port 방향 (축 동일 정렬), offset along port z축.
        SFP/SC 공통.
        """
        pt = port_tf.transform.translation
        pr = port_tf.transform.rotation
        q_port = np.array([pr.x, pr.y, pr.z, pr.w])
        R_port = _quat_to_matrix(*q_port[:3], q_port[3])

        insert_axis = R_port[:, 2]  # port z축 = 삽입 방향
        desired_pos = np.array([pt.x, pt.y, pt.z]) + insert_axis * z_offset
        q_plug_desired = tuple(q_port)

        self._log(
            f"    insert_axis (world): ({insert_axis[0]:.4f}, {insert_axis[1]:.4f}, {insert_axis[2]:.4f})"
        )

        # plug → tcp 변환 적용
        tt = plug_to_tcp_tf.transform.translation
        tr = plug_to_tcp_tf.transform.rotation
        q_plug_tcp = np.array([tr.x, tr.y, tr.z, tr.w])
        R_plug_desired = _quat_to_matrix(*q_plug_desired[:3], q_plug_desired[3])

        tcp_local = np.array([tt.x, tt.y, tt.z])
        tcp_world = desired_pos + R_plug_desired @ tcp_local

        q_tcp_world = _quat_multiply(q_plug_desired, tuple(q_plug_tcp))

        return Pose(
            position=Point(x=tcp_world[0], y=tcp_world[1], z=tcp_world[2]),
            orientation=Quaternion(
                x=q_tcp_world[0], y=q_tcp_world[1],
                z=q_tcp_world[2], w=q_tcp_world[3]
            ),
        )

    def _port_insert_direction(self, port_tf) -> np.ndarray:
        """port z축 방향 (삽입 방향)을 world 좌표로 반환. SFP/SC 공통."""
        pr = port_tf.transform.rotation
        R = _quat_to_matrix(pr.x, pr.y, pr.z, pr.w)
        return R[:, 2]

    def _pose_to_stamped(self, pose: Pose):
        """Pose → PoseStamped (world 프레임)."""
        from geometry_msgs.msg import PoseStamped
        ps = PoseStamped()
        ps.header.frame_id = "world"
        ps.header.stamp = self._parent_node.get_clock().now().to_msg()
        ps.pose = pose
        return ps


# ── 변환 유틸리티 ────────────────────────────────────────────────────────────

def _quat_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    """단위 쿼터니언 → 3×3 회전 행렬."""
    return np.array([
        [1 - 2*(y*y + z*z),   2*(x*y - z*w),       2*(x*z + y*w)],
        [2*(x*y + z*w),       1 - 2*(x*x + z*z),   2*(y*z - x*w)],
        [2*(x*z - y*w),       2*(y*z + x*w),       1 - 2*(x*x + y*y)],
    ])


def _quat_multiply(q1: tuple, q2: tuple) -> tuple:
    """쿼터니언 곱: q1 * q2 (각각 (x,y,z,w))."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return (
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    )


