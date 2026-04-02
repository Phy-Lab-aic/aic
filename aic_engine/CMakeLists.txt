cmake_minimum_required(VERSION 3.20)
project(aic_engine)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)

find_package(aic_scoring REQUIRED)
find_package(aic_control_interfaces REQUIRED)
find_package(aic_engine_interfaces REQUIRED)
find_package(aic_task_interfaces REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(controller_manager_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(lifecycle_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(simulation_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(trajectory_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(yaml_cpp_vendor REQUIRED)
find_package(yaml-cpp REQUIRED)
find_package(Eigen3 REQUIRED)
find_package(nlohmann_json REQUIRED)

# Shared utility library (used by both aic_engine and auto_data_collector)
add_library(aic_engine_utils STATIC
  src/utils/tf_helper.cpp
  src/utils/scene_spawner.cpp
  src/utils/homing_helper.cpp
)
target_include_directories(aic_engine_utils PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
)
target_link_libraries(aic_engine_utils
  ament_index_cpp::ament_index_cpp
  rclcpp::rclcpp
  tf2::tf2
  tf2_ros::tf2_ros
  yaml-cpp
  ${aic_engine_interfaces_TARGETS}
  ${controller_manager_msgs_TARGETS}
  ${geometry_msgs_TARGETS}
  ${simulation_interfaces_TARGETS}
  ${std_srvs_TARGETS}
)

# Data collection library (components specific to auto_data_collector)
add_library(aic_data_collection STATIC
  src/completion_monitor.cpp
  src/trial_config_provider.cpp
  src/rosbag_manager.cpp
)
target_include_directories(aic_data_collection PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
)
target_link_libraries(aic_data_collection
  aic_engine_utils
  Eigen3::Eigen
  nlohmann_json::nlohmann_json
  yaml-cpp
)

# Existing aic_engine executable
add_executable(aic_engine
  src/aic_engine.cpp
  src/main.cpp
)
target_link_libraries(aic_engine
  aic_engine_utils
  aic_scoring::aic_scoring
  ament_index_cpp::ament_index_cpp
  rclcpp::rclcpp
  rclcpp_action::rclcpp_action
  tf2::tf2
  tf2_ros::tf2_ros
  yaml-cpp
  ${aic_control_interfaces_TARGETS}
  ${aic_engine_interfaces_TARGETS}
  ${aic_task_interfaces_TARGETS}
  ${controller_manager_msgs_TARGETS}
  ${geometry_msgs_TARGETS}
  ${lifecycle_msgs_TARGETS}
  ${trajectory_msgs_TARGETS}
  ${simulation_interfaces_TARGETS}
  ${std_srvs_TARGETS}
  ${tf2_ros_TARGETS}
)

# New auto_data_collector executable
add_executable(auto_data_collector
  src/auto_data_collector.cpp
  src/auto_data_collector_main.cpp
)
target_link_libraries(auto_data_collector
  aic_engine_utils
  aic_data_collection
  rclcpp::rclcpp
  rclcpp_action::rclcpp_action
  yaml-cpp
  Eigen3::Eigen
  ${aic_task_interfaces_TARGETS}
  ${lifecycle_msgs_TARGETS}
  ${sensor_msgs_TARGETS}
  ${std_msgs_TARGETS}
)

install(
  TARGETS aic_engine auto_data_collector
  DESTINATION lib/${PROJECT_NAME}
)

# Install directories.
install(
  DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

# Tests
if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)

  ament_add_gtest(test_completion_monitor test/test_completion_monitor.cpp)
  target_link_libraries(test_completion_monitor aic_data_collection)

  ament_add_gtest(test_trial_config_provider test/test_trial_config_provider.cpp)
  target_link_libraries(test_trial_config_provider aic_data_collection)

  ament_add_gtest(test_dynamic_trial_provider test/test_dynamic_trial_provider.cpp)
  target_link_libraries(test_dynamic_trial_provider aic_data_collection)

  ament_add_gtest(test_rosbag_manager test/test_rosbag_manager.cpp)
  target_link_libraries(test_rosbag_manager aic_data_collection)

  ament_add_gtest(test_collection_flow test/test_collection_flow.cpp)
  target_link_libraries(test_collection_flow
    aic_data_collection
    aic_engine_utils
    rclcpp::rclcpp
    rclcpp_action::rclcpp_action
    ${aic_task_interfaces_TARGETS}
    ${lifecycle_msgs_TARGETS}
    ${std_msgs_TARGETS}
    ${sensor_msgs_TARGETS}
  )
endif()

ament_package()
