# ACT training image: lerobot 0.4.4 (torch with CUDA from PyPI)
# Build: docker build -t omx-act:0.4.4 .
#   0.6.1 이미지: docker build --build-arg LEROBOT_SPEC="lerobot[training]==0.6.1" -t omx-act:0.6.1 .
#   (0.4.4에는 [training] extra가 없음 — accelerate·wandb·datasets가 기본 의존성에 포함)
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# ffmpeg (with libdav1d) decodes the AV1 videos in LeRobot datasets
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git build-essential cmake libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ARG LEROBOT_SPEC="lerobot==0.4.4"
RUN pip install --upgrade pip && \
    pip install "${LEROBOT_SPEC}"

# Writable home/cache when running as the host user (--user).
# USER avoids getpwuid() failures in torch when the uid has no passwd entry.
ENV USER=lerobot \
    HOME=/workspace/.home \
    HF_HOME=/workspace/.home/hf
WORKDIR /workspace
