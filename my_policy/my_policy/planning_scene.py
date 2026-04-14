"""
planning_scene.py

MoveIt2 planning scene 구성 모듈.
ground truth TF를 읽어 task board, enclosure, 컴포넌트 마운트의
collision object를 등록한다. trial 시작 시 1회 호출.

collision geometry 출처:
  - task board: aic_assets/models/Task Board Base/model.sdf
  - enclosure:  aic_assets/models/Enclosure/model.sdf
  - SC mount:   aic_assets/models/SC Mount/sc_mount_macro.xacro (bounding box)
  - SFP mount:  aic_assets/models/SFP Mount/sfp_mount_macro.xacro (bounding box)
"""

from __future__ import annotations

import numpy as np
from geometry_msgs.msg import Point, Pose, Quaternion, Vector3
from moveit_msgs.msg import CollisionObject, PlanningScene
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import Header
from tf2_ros.buffer import Buffer
from tf2_ros import TransformException


class PlanningSceneManager:
    """ground truth TF 기반 MoveIt2 planning scene collision object 관리."""

    def __init__(self, node: Node, tf_buffer: Buffer):
        self._node = node
        self._tf = tf_buffer
        self._scene_pub = node.create_publisher(
            PlanningScene, "/planning_scene", 10
        )

    def setup(self, timeout_sec: float = 10.0) -> bool:
        """collision object 전체 등록. trial 시작 시 1회 호출.

        NOTE: 현재 collision check 비활성화 상태 (개발 중).
        추가해야 할 구조물이 남아있어 활성화 시 false positive 발생 ���능.
        """
        self._node.get_logger().info(
            "PlanningSceneManager: collision check DISABLED (under development)"
        )
        return True

        # --- 아래 코드는 collision check 활성화 시 사용 ---
        objects: list[CollisionObject] = []

        tb = self._make_task_board(timeout_sec)
        if tb:
            objects.extend(tb)

        mounts = self._make_mounts(timeout_sec)
        objects.extend(mounts)

        if not objects:
            self._node.get_logger().warn("PlanningSceneManager: no collision objects added")
            return False

        scene_msg = PlanningScene()
        scene_msg.is_diff = True
        scene_msg.world.collision_objects = objects
        self._scene_pub.publish(scene_msg)
        self._node.get_logger().info(
            f"PlanningSceneManager: registered {len(objects)} collision objects"
        )
        return True

    # ── Task Board ──────────────────────────────────────────────────────────

    def _make_task_board(self, timeout_sec: float) -> list[CollisionObject]:
        """task_board/base_link TF 기반 collision object.

        Task Board Base model.sdf:
          - 전체 보드: 0.3 × 0.425 × 0.012m at (0, 0, 0.006)
          - 상단 구조: 0.14 × 0.087 × 0.005m at (-0.075, 0.05, 0.011)
        """
        # TF tree 기준 task board 루트 프레임은 "task_board" (base_link 아님)
        try:
            tf = self._tf.lookup_transform(
                "world", "task_board", Time(),
                timeout=Duration(seconds=timeout_sec)
            )
        except TransformException as e:
            self._node.get_logger().warn(f"task_board TF not available: {e}")
            return []

        obj = CollisionObject()
        obj.header.frame_id = "world"
        obj.id = "task_board"
        obj.operation = CollisionObject.ADD

        board_pose = _tf_to_pose(tf)

        # 전체 보드
        prim1 = SolidPrimitive(type=SolidPrimitive.BOX)
        prim1.dimensions = [0.3, 0.425, 0.012]
        obj.primitives.append(prim1)
        local1 = Pose(
            position=Point(x=0.0, y=0.0, z=0.006),
            orientation=Quaternion(w=1.0)
        )
        obj.primitive_poses.append(_compose_pose(board_pose, local1))

        # 상단 구조
        prim2 = SolidPrimitive(type=SolidPrimitive.BOX)
        prim2.dimensions = [0.14, 0.087, 0.005]
        obj.primitives.append(prim2)
        local2 = Pose(
            position=Point(x=-0.075, y=0.05, z=0.011),
            orientation=Quaternion(w=1.0)
        )
        obj.primitive_poses.append(_compose_pose(board_pose, local2))

        return [obj]

    # ── Mounts ──────────────────────────────────────────────────────────────

    def _make_mounts(self, timeout_sec: float) -> list[CollisionObject]:
        """SC/SFP mount TF 기반 bounding box collision objects.

        각 마운트를 단일 bounding box로 근사 (상세 geometry 대신).
        SC mount bounding box: ~0.05 × 0.014 × 0.025m
        SFP mount bounding box: ~0.045 × 0.018 × 0.020m
        """
        objects = []

        # TF tree 기준 실제 프레임명 (tf2_tools view_frames 확인)
        mount_configs = [
            # (frame, box_size, local_offset_z)
            ("task_board/nic_card_mount_0/nic_card_mount_link", (0.05, 0.018, 0.020), 0.010),
            ("task_board/sc_port_0/sc_port_base_link",          (0.05, 0.014, 0.025), 0.012),
        ]

        for frame, size, z_off in mount_configs:
            try:
                tf = self._tf.lookup_transform(
                    "world", frame, Time(),
                    timeout=Duration(seconds=1.0)
                )
            except TransformException:
                # 해당 마운트가 scene에 없으면 스킵
                continue

            obj = CollisionObject()
            obj.header.frame_id = "world"
            obj.id = frame.replace("/", "_")
            obj.operation = CollisionObject.ADD

            prim = SolidPrimitive(type=SolidPrimitive.BOX)
            prim.dimensions = list(size)
            obj.primitives.append(prim)

            mount_pose = _tf_to_pose(tf)
            local = Pose(
                position=Point(x=0.0, y=0.0, z=z_off),
                orientation=Quaternion(w=1.0)
            )
            obj.primitive_poses.append(_compose_pose(mount_pose, local))
            objects.append(obj)

        return objects


# ── 변환 유틸리티 ───────────────────────────────────────────────────────────

def _rpy_to_quaternion(roll: float, pitch: float, yaw: float):
    """RPY → (x, y, z, w) 쿼터니언."""
    cr, sr = np.cos(roll / 2), np.sin(roll / 2)
    cp, sp = np.cos(pitch / 2), np.sin(pitch / 2)
    cy, sy = np.cos(yaw / 2), np.sin(yaw / 2)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def _tf_to_pose(tf_stamped) -> Pose:
    """TransformStamped → Pose (world 기준)."""
    t = tf_stamped.transform.translation
    r = tf_stamped.transform.rotation
    return Pose(
        position=Point(x=t.x, y=t.y, z=t.z),
        orientation=Quaternion(x=r.x, y=r.y, z=r.z, w=r.w),
    )


def _compose_pose(parent: Pose, local: Pose) -> Pose:
    """parent 포즈 기준 local 오프셋을 world 좌표로 변환.

    회전이 없는 local offset (orientation=identity)을 가정하면
    단순 회전 행렬 × 오프셋 + 부모 위치.
    일반 경우도 쿼터니언 합성으로 처리.
    """
    # parent quaternion → rotation matrix
    q = parent.orientation
    R = _quat_to_matrix(q.x, q.y, q.z, q.w)

    lp = local.position
    local_vec = np.array([lp.x, lp.y, lp.z])
    world_vec = R @ local_vec + np.array([
        parent.position.x, parent.position.y, parent.position.z
    ])

    # orientation: compose quaternions
    lq = local.orientation
    result_q = _quat_multiply(
        (q.x, q.y, q.z, q.w),
        (lq.x, lq.y, lq.z, lq.w)
    )

    return Pose(
        position=Point(x=world_vec[0], y=world_vec[1], z=world_vec[2]),
        orientation=Quaternion(
            x=result_q[0], y=result_q[1], z=result_q[2], w=result_q[3]
        ),
    )


def _quat_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    """단위 쿼터니언 → 3×3 회전 행렬."""
    return np.array([
        [1 - 2*(y*y + z*z),   2*(x*y - z*w),       2*(x*z + y*w)],
        [2*(x*y + z*w),       1 - 2*(x*x + z*z),   2*(y*z - x*w)],
        [2*(x*z - y*w),       2*(y*z + x*w),       1 - 2*(x*x + y*y)],
    ])


def _quat_multiply(q1, q2):
    """쿼터니언 곱: q1 * q2 (각각 (x,y,z,w))."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return (
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    )
