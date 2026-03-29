from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # Launch arguments
    config_file_arg = DeclareLaunchArgument(
        "config_file",
        default_value=PathJoinSubstitution([
            FindPackageShare("aic_engine"), "config", "sample_config.yaml"
        ]),
        description="Path to trial config YAML",
    )
    target_episodes_arg = DeclareLaunchArgument("target_episodes", default_value="10")
    max_attempts_arg = DeclareLaunchArgument("max_attempts", default_value="0")
    task_timeout_arg = DeclareLaunchArgument("task_timeout_sec", default_value="180.0")
    bag_output_dir_arg = DeclareLaunchArgument("bag_output_dir", default_value="bags")
    trial_mode_arg = DeclareLaunchArgument("trial_mode", default_value="static",
                                          description="Trial mode: 'static' or 'dynamic'")
    trials_arg = DeclareLaunchArgument("trials", default_value="['']",
                                       description="Trial names to collect, empty=all")

    # Include bringup (no aic_engine — we orchestrate directly)
    bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("aic_bringup"), "launch", "aic_gz_bringup.launch.py"
            ])
        ),
        launch_arguments={
            "ground_truth": "true",
            "start_aic_engine": "false",
            "shutdown_on_aic_engine_exit": "false",
        }.items(),
    )

    # Auto data collector node
    collector = Node(
        package="aic_data_collection",
        executable="auto_data_collector",
        output="screen",
        parameters=[{
            "config_file": LaunchConfiguration("config_file"),
            "target_episodes": LaunchConfiguration("target_episodes"),
            "max_attempts": LaunchConfiguration("max_attempts"),
            "task_timeout_sec": LaunchConfiguration("task_timeout_sec"),
            "bag_output_dir": LaunchConfiguration("bag_output_dir"),
            "trial_mode": LaunchConfiguration("trial_mode"),
            "trials": LaunchConfiguration("trials"),
            "use_sim_time": True,
        }],
    )

    return LaunchDescription([
        config_file_arg,
        target_episodes_arg,
        max_attempts_arg,
        task_timeout_arg,
        bag_output_dir_arg,
        trial_mode_arg,
        trials_arg,
        bringup,
        collector,
    ])
