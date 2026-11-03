cmake_minimum_required(VERSION 3.8)
project(pinky_interfaces)

# 시뮬 PC 전용 대체 패키지. 실물 로봇 워크스페이스에서는 빌드하지 않는다 (README.md).
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/SetLed.srv"
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
