# 관제 PC 전용 이미지. 실제 Pinky의 드라이버·Nav2 bringup은 로봇에 유지한다.
ARG ROS_BASE_IMAGE=ros:jazzy-ros-base@sha256:8eed0a4669bbf43ee331878a4c39bd8ebddea8e3312a58b4fae8edb14526b617
# 고객 주문 화면(cobot_gui/web) 빌드 전용. 결과 dist 파일만 아래 이미지로 옮기고 Node 는 남기지 않는다.
ARG NODE_BUILD_IMAGE=node:22-bookworm@sha256:e13726ca604184d7a91fcacab1fc09eefd642dc28e79ac34e85540dd93b78cfb

FROM ${NODE_BUILD_IMAGE} AS customer-web
WORKDIR /web
COPY .docker-context/control-center/src/cobot_gui/web/package.json .docker-context/control-center/src/cobot_gui/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY .docker-context/control-center/src/cobot_gui/web ./
RUN npm run build && test -f dist/customer.html

FROM ${ROS_BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG DEBIAN_FRONTEND=noninteractive
ARG SOURCE_REVISION=unknown
ARG SOURCE_DIRTY=unknown
ARG BUILD_JOBS=2
LABEL org.opencontainers.image.title="cobot-fleet-control" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      cobot.source.dirty="${SOURCE_DIRTY}"

# apt는 이미지 빌드 시 설치한다. 배포는 같은 완성 이미지 ID/digest를 재사용한다.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake ca-certificates python3-venv python3-colcon-common-extensions \
      python3-yaml python3-fastapi python3-uvicorn libyaml-cpp-dev libzstd-dev \
      ros-jazzy-rclpy ros-jazzy-rclcpp ros-jazzy-rclcpp-components \
      ros-jazzy-rcutils ros-jazzy-rosbag2-cpp ros-jazzy-rosidl-default-generators \
      ros-jazzy-rosidl-default-runtime ros-jazzy-rosidl-typesupport-cpp \
      ros-jazzy-yaml-cpp-vendor ros-jazzy-zstd-vendor \
      ros-jazzy-launch-ros ros-jazzy-std-msgs ros-jazzy-geometry-msgs \
      ros-jazzy-sensor-msgs ros-jazzy-nav-msgs ros-jazzy-tf2-msgs \
      ros-jazzy-rmw-fastrtps-cpp ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

COPY cobot_fleet_control/config/docker/requirements.lock /opt/cobot/requirements.lock
# PEP 668에 따라 시스템 pip 대신 별도 venv를 사용한다. ROS apt 경로는 공유한다.
RUN python3 -m venv --system-site-packages /opt/cobot/venv \
    && /opt/cobot/venv/bin/python -m pip install --no-cache-dir --require-hashes \
         -r /opt/cobot/requirements.lock
ENV PATH="/opt/cobot/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/cobot_ws
COPY cobot_fleet_control src/cobot_fleet_control
COPY cobot_zone_traffic_control src/cobot_zone_traffic_control
COPY cobot_domain_bridge src/cobot_domain_bridge
# 웹 패키지는 build 스크립트가 같은 체크아웃에서 복사해 둔 것을 쓴다 (context 밖이라서).
COPY .docker-context/control-center/src/cobot_control_center src/cobot_control_center
COPY .docker-context/control-center/src/cobot_patrol_interfaces src/cobot_patrol_interfaces
# 로봇팔 명령 노드(arm_command_node)가 쓰는 ArmCommand·ArmStatus·CommandAck.
COPY .docker-context/control-center/src/cobot_interfaces src/cobot_interfaces
# 고객 주문 화면 게이트웨이. setup.py 가 web/dist 를 install 하므로 colcon 전에 넣는다.
COPY .docker-context/control-center/src/cobot_gui src/cobot_gui
COPY --from=customer-web /web/dist src/cobot_gui/web/dist
# 로봇 노드는 빌드하지 않고 웹 지도·지점 검증에 필요한 데이터만 포함한다.
COPY cobot_pinky_patrol/config src/cobot_pinky_patrol/config
COPY map_view_pc/maps/cobot_map_v9.yaml map_view_pc/maps/cobot_map_v9.pgm src/map_view_pc/maps/
# 런타임에는 호스트 소스를 마운트하지 않는다. 이미지 자체가 배포 코드 버전이다.
RUN source /opt/ros/jazzy/setup.bash \
    && CMAKE_BUILD_PARALLEL_LEVEL="${BUILD_JOBS}" MAKEFLAGS="-j${BUILD_JOBS}" \
       python -m colcon build --merge-install --parallel-workers "${BUILD_JOBS}" --cmake-args -DBUILD_TESTING=OFF \
         --packages-select cobot_interfaces cobot_patrol_interfaces cobot_control_center \
                           cobot_fleet_control cobot_zone_traffic_control cobot_domain_bridge cobot_gui \
    && source install/setup.bash \
    && python -c 'import py_trees, fastapi, uvicorn; import cobot_control_center.fleet_api_node; import cobot_control_center.fleet_status_node; import cobot_control_center.arm_command_node; import cobot_gui.customer_gateway_node' \
    && test -f install/share/cobot_gui/web/dist/customer.html \
    && ros2 launch cobot_fleet_control control_center_web.launch.xml --show-args \
    && ros2 run cobot_fleet_control control_center_web \
         --navigation-root /opt/cobot_ws/src --mode preview --fleet existing \
    && mkdir -p /opt/cobot/build-versions \
    && dpkg-query -W > /opt/cobot/build-versions/dpkg.tsv \
    && python -m pip freeze > /opt/cobot/build-versions/python.txt \
    && printf '%s\n' "${SOURCE_REVISION}" > /opt/cobot/build-versions/source-revision.txt \
    && printf '%s\n' "${SOURCE_DIRTY}" > /opt/cobot/build-versions/source-dirty.txt

COPY cobot_fleet_control/config/docker/entrypoint.sh /opt/cobot/entrypoint.sh
COPY cobot_fleet_control/config/docker/smoke_check.py /opt/cobot/smoke_check.py
COPY cobot_fleet_control/config/docker/cyclonedds.xml /opt/cobot/cyclonedds.xml
RUN chmod 755 /opt/cobot/entrypoint.sh \
    && groupadd --gid 10001 cobot \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash cobot \
    && mkdir -p /var/lib/cobot /home/cobot/.ros/cobot_control_center \
    && chown cobot:cobot /var/lib/cobot \
    && chown -R cobot:cobot /home/cobot/.ros
USER cobot
ENTRYPOINT ["/opt/cobot/entrypoint.sh"]
CMD ["ros2", "launch", "cobot_fleet_control", "fleet_control.launch.xml"]
