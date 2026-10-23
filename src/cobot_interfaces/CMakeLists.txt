# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

cmake_minimum_required(VERSION 3.8)
project(cobot_interfaces)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(action_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# 파일을 더하거나 지우면 이 목록도 고친다.
# test/test_interface_schema.py 가 이 목록과 msg/ srv/ action/ 폴더를 대조한다.
set(msg_files
  "msg/AlarmEvent.msg"
  "msg/ArmCommand.msg"
  "msg/ArmMode.msg"
  "msg/ArmStatus.msg"
  "msg/Assignment.msg"
  "msg/AuditEvent.msg"
  "msg/CameraHealth.msg"
  "msg/CommandAck.msg"
  "msg/CommandHeader.msg"
  "msg/CompletionEvidence.msg"
  "msg/DeviceDiag.msg"
  "msg/DiagSnapshot.msg"
  "msg/DropEvent.msg"
  "msg/FleetCommand.msg"
  "msg/FleetSafetyState.msg"
  "msg/FmsHeartbeat.msg"
  "msg/HwEstopState.msg"
  "msg/InventoryItem.msg"
  "msg/InventoryState.msg"
  "msg/LaneLeaseState.msg"
  "msg/MapInfo.msg"
  "msg/MediaHealth.msg"
  "msg/NodeDiag.msg"
  "msg/OrderStatus.msg"
  "msg/ReconcileItem.msg"
  "msg/RobotStatus.msg"
  "msg/TopicDiag.msg"
  "msg/UnloadQueue.msg"
  "msg/VisionEvent.msg"
  "msg/Waypoint.msg"
)

set(srv_files
  "srv/ConsoleLease.srv"
  "srv/OperatorCommand.srv"
  "srv/QueryAudit.srv"
  "srv/ReconcileReport.srv"
  "srv/SubmitOrder.srv"
)

set(action_files
  "action/HandoverTask.action"
  "action/RecoveryTask.action"
)

rosidl_generate_interfaces(${PROJECT_NAME}
  ${msg_files}
  ${srv_files}
  ${action_files}
  DEPENDENCIES
    action_msgs
    builtin_interfaces
    geometry_msgs
    std_msgs
)

ament_export_dependencies(rosidl_default_runtime)

if(BUILD_TESTING)
  # 린트: package.xml 의 test_depend(ament_cmake_copyright, ament_cmake_flake8,
  # ament_cmake_pep257)를 시험으로 등록한다. ament_cmake 패키지에서는 ament_cmake_* 이름이어야
  # 등록된다. ament_flake8 처럼 적으면 경고 없이 빠진다 (test/interface_schema.py 가 본다).
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()

  find_package(ament_cmake_pytest REQUIRED)

  # (a) .msg/.srv/.action 글자를 읽어 필수 필드를 본다. ROS 없이도 돈다.
  ament_add_pytest_test(test_interface_schema
    test/test_interface_schema.py
    TIMEOUT 60
  )

  # (b) 빌드로 생긴 Python 타입을 import 해서 필드를 본다. 빌드 산출물 경로를 넘긴다.
  ament_add_pytest_test(test_generated_types
    test/test_generated_types.py
    APPEND_ENV "PYTHONPATH=${CMAKE_CURRENT_BINARY_DIR}/rosidl_generator_py"
    APPEND_LIBRARY_DIRS "${CMAKE_CURRENT_BINARY_DIR}"
    TIMEOUT 60
  )
endif()

ament_package()
