#include <cstdlib>
#include <thread>

#include "auto_data_collector.hpp"
#include "rclcpp/rclcpp.hpp"

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);

  auto node = std::make_shared<aic::AutoDataCollector>();

  std::thread spin_thread([&node]() {
    rclcpp::executors::MultiThreadedExecutor executor;
    executor.add_node(node);
    executor.spin();
  });

  node->run_collection();

  rclcpp::shutdown();
  if (spin_thread.joinable()) {
    spin_thread.join();
  }
  return EXIT_SUCCESS;
}
