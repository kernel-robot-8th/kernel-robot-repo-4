cmake_minimum_required(VERSION 3.8)
project(pinky_gz_sim)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

if(CMAKE_SYSTEM_PROCESSOR STREQUAL "aarch64")
  return()
endif()

find_package(ament_cmake REQUIRED)
find_package(ros_gz QUIET)
find_package(gz_ros2_control QUIET)
find_package(gz-sim8 QUIET)
find_package(gz-plugin2 QUIET)

include_directories(plugins)

if(gz-sim8_FOUND AND gz-plugin2_FOUND)
  add_library(gz-sim-lamp-control-system
    SHARED
    plugins/gz_lamp_control_plugin.cpp
  )
  
  target_link_libraries(gz-sim-lamp-control-system PRIVATE gz-sim8::core gz-plugin2::register)
  
  ament_target_dependencies(gz-sim-lamp-control-system)

  install(
    TARGETS
    gz-sim-lamp-control-system
    DESTINATION
    lib
  )
endif()

install(
  DIRECTORY
    worlds
    models
    launch
    params
    scripts
    rviz
  DESTINATION share/${PROJECT_NAME}
)

install(
  PROGRAMS
    scripts/27_pinky_gz_sim_telemetry_monitor.py
    scripts/27_pinky_gz_teleop_keyboard.py
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
