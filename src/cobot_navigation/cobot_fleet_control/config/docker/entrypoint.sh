#!/usr/bin/env bash
# exec로 신호를 실제 ROS 프로세스에 전달한다. 호스트의 ROS·venv는 필요 없다.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/cobot_ws/install/setup.bash
exec "$@"
