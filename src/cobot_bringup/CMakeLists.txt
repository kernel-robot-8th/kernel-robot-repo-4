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
project(cobot_bringup)

find_package(ament_cmake REQUIRED)

# Install shared config (map contract under config/maps) and the system launch.
# FMS and the onboard guard read the map from this install (share/cobot_bringup).
install(
  DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  # Note: this package has no .py files, so ament_copyright checks 0 files here.
  # License headers in CMakeLists.txt, package.xml and launch XML are checked in review.
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
