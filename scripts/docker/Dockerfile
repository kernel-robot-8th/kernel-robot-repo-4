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

# 팀 개발·시험용 이미지. colcon build / colcon test 만 한다.
# - 실물 장치(시리얼·카메라)를 연결하지 않는다. 실물 구동은 CLAUDE.md §9 를 따른다.
# - 레포 파일을 이미지 안에 복사하지 않는다. 레포는 실행할 때 /ws 로 마운트한다.
# - 비밀값(토큰·암호·실IP)을 이 파일이나 --build-arg 에 넣지 않는다.
# - 직접 docker build 하지 말고 scripts/docker/dev.sh build-image 를 쓴다.
#   태그 규칙: cobot-dev:jazzy-<YYYYMMDD> (dev.sh 의 IMAGE_VERSION).
#   이 파일을 고치는 PR 은 IMAGE_VERSION 도 그날 날짜로 바꾼다.
# 설명서: docs/dev_docker_guide.md

ARG BASE_IMAGE=ros:jazzy-ros-base
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive

# 팀 빌드·시험에 쓰는 ROS·Ubuntu 표준 apt 패키지(rosdep 키)만 둔다.
# ros-dev-tools 는 README '처음 설치하기' 와 같다. 린트(flake8 플러그인 등)가
# 직접 설치한 PC 와 같게 돌도록 README 처럼 추천 패키지도 함께 설치한다.
# 새 패키지를 더하려면 PR 과 팀 허락이 먼저다 (CLAUDE.md §9).
RUN apt-get update \
    && apt-get install -y \
        ros-dev-tools \
        python3-colcon-common-extensions \
        python3-pytest \
        python3-yaml \
        ros-jazzy-ament-copyright \
        ros-jazzy-ament-flake8 \
        ros-jazzy-ament-pep257 \
        ros-jazzy-ament-lint-auto \
        ros-jazzy-ament-lint-common \
        ros-jazzy-ament-cmake-pytest \
        ros-jazzy-rosidl-default-generators \
        ros-jazzy-rosidl-default-runtime \
    && rm -rf /var/lib/apt/lists/*

# 호스트 사용자와 같은 UID·GID 의 일반 사용자를 만든다.
# 그래야 build/ install/ log/ 파일의 주인이 호스트 사용자로 남는다.
# Ubuntu 24.04 이미지에는 UID 1000 인 'ubuntu' 사용자가 이미 있어서 먼저 지운다.
# root(0) 로는 만들지 않는다. dev 에게 sudo 권한을 주지 않는다 (sudoers 에 넣지 않는다).
# 기본 이미지에 sudo 명령은 있지만 dev 는 쓸 수 없고, dev.sh 의 no-new-privileges 로도 막힌다.
# 그래서 컨테이너 안에서 apt install 을 할 수 없다 (일부러다).
ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000
RUN set -eu; \
    if [ "${USER_UID}" = "0" ] || [ "${USER_GID}" = "0" ]; then \
        echo "USER_UID/USER_GID 에 0(root) 을 쓰지 않는다" >&2; \
        exit 1; \
    fi; \
    old_user="$(getent passwd "${USER_UID}" | cut -d: -f1)"; \
    if [ -n "${old_user}" ]; then userdel "${old_user}"; fi; \
    if ! getent group "${USER_GID}" > /dev/null; then \
        groupadd --gid "${USER_GID}" "${USERNAME}"; \
    fi; \
    useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home \
        --shell /bin/bash "${USERNAME}"; \
    if [ -d /root/.ros/rosdep ]; then \
        mkdir -p "/home/${USERNAME}/.ros"; \
        cp -r /root/.ros/rosdep "/home/${USERNAME}/.ros/"; \
        chown -R "${USER_UID}:${USER_GID}" "/home/${USERNAME}/.ros"; \
    fi; \
    printf '%s\n' \
        '' \
        '# cobot-dev' \
        'source /opt/ros/jazzy/setup.bash' \
        'echo "[cobot-dev] /ws = 레포 루트. 빌드 뒤에는: source install/setup.bash (나가기: exit)"' \
        >> "/home/${USERNAME}/.bashrc"

# ROS 탐색을 컨테이너 안(localhost)으로 묶는다. dev.sh 는 기본으로 --network none 이라
# 바깥과 통신하지 않지만, 직접 docker run 을 해도 실물 로봇과 섞이지 않게 한 겹 더 둔다.
# ROS_DOMAIN_ID 는 정하지 않는다 (도메인 규칙은 팀 결정 D2).
ENV ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
    PYTHONDONTWRITEBYTECODE=1

# dev.sh 가 이 값으로 '이미지가 낡았는지', 'UID 가 맞는지' 를 확인한다.
ARG DOCKERFILE_SHA256=unknown
LABEL org.opencontainers.image.title="cobot-dev" \
      org.opencontainers.image.description="Pinky_Team4 ROS 2 Jazzy build and test image" \
      org.opencontainers.image.licenses="Apache-2.0" \
      cobot.dev.uid="${USER_UID}" \
      cobot.dev.gid="${USER_GID}" \
      cobot.dev.dockerfile_sha256="${DOCKERFILE_SHA256}"

USER ${USERNAME}
WORKDIR /ws
CMD ["bash"]
