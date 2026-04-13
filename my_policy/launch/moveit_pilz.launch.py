"""
moveit_pilz.launch.py

Launches move_group with:
  - UR5e URDF loaded from robot_state_publisher node (already running via aic_gz_bringup)
  - UR5e SRDF from my_policy/config/ur5e.srdf
  - KDL kinematics from config/kinematics.yaml
  - PILZ Industrial Motion Planner as primary planning pipeline
  - OMPL as secondary pipeline (fallback for obstacle avoidance)

Run AFTER aic_gz_bringup.launch.py is already running.

Usage:
  ros2 launch my_policy moveit_pilz.launch.py
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def _load_yaml(package: str, rel_path: str) -> dict:
    share = Path(get_package_share_directory(package))
    with open(share / rel_path) as f:
        return yaml.safe_load(f)


def _read_text(package: str, rel_path: str) -> str:
    share = Path(get_package_share_directory(package))
    return (share / rel_path).read_text()


def generate_launch_description() -> LaunchDescription:
    pkg_moveit_cfg = get_package_share_directory("my_policy")

    # robot_description: read from robot_state_publisher node at runtime.
    # move_group will fetch it automatically via the /robot_description topic
    # that robot_state_publisher publishes. No need to re-evaluate xacro here.
    robot_description = {}

    # SRDF
    srdf_str = (Path(pkg_moveit_cfg) / "config" / "ur5e.srdf").read_text()
    robot_description_semantic = {"robot_description_semantic": srdf_str}

    # Kinematics
    kinematics = _load_yaml("my_policy", "config/kinematics.yaml")
    robot_description_kinematics = {"robot_description_kinematics": kinematics}

    # PILZ Cartesian limits
    pilz_cartesian_limits = _load_yaml(
        "my_policy", "config/pilz_cartesian_limits.yaml"
    )

    # Planning pipelines: PILZ only
    # MoveIt2 Kilted API: planning_plugin(string) → planning_plugins(string_array)
    planning_pipelines = {
        "planning_pipelines": ["pilz_industrial_motion_planner"],
        "default_planning_pipeline": "pilz_industrial_motion_planner",
        "pilz_industrial_motion_planner": {
            "planning_plugins": ["pilz_industrial_motion_planner/CommandPlanner"],
            "request_adapters": [
                "default_planning_request_adapters/ResolveConstraintFrames",
                "default_planning_request_adapters/ValidateWorkspaceBounds",
                "default_planning_request_adapters/CheckStartStateBounds",
                "default_planning_request_adapters/CheckStartStateCollision",
            ],
            "response_adapters": [
                "default_planning_response_adapters/ValidateSolution",
                "default_planning_response_adapters/DisplayMotionPath",
            ],
        },
    }

    # Trajectory execution: move_group acts as planning server only.
    # PilzPolicy streams waypoints directly to aic_controller.
    trajectory_execution = {
        "moveit_manage_controllers": False,
        "trajectory_execution": {
            "allowed_execution_duration_scaling": 1.2,
            "allowed_goal_duration_margin": 0.5,
            "allowed_start_tolerance": 0.01,
        },
    }

    move_group_node = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=[
            robot_description,
            robot_description_semantic,
            robot_description_kinematics,
            pilz_cartesian_limits,
            planning_pipelines,
            trajectory_execution,
            {"use_sim_time": True},
        ],
    )

    return LaunchDescription([move_group_node])
