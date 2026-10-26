# SmolVLA training image: lerobot 0.6.1 + SmolVLA dependencies (torch with CUDA from PyPI)
# Build: docker build -t omx-smolvla:0.6.1 .
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# ffmpeg (with libdav1d) decodes the AV1 videos in LeRobot datasets
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git build-essential cmake libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ARG LEROBOT_VERSION=0.6.1
RUN pip install --upgrade pip && \
    pip install "lerobot[training,smolvla]==${LEROBOT_VERSION}"

# Writable home/cache when running as the host user (--user).
# USER avoids getpwuid() failures in torch when the uid has no passwd entry.
ENV USER=lerobot \
    HOME=/workspace/.home \
    HF_HOME=/workspace/.home/hf
WORKDIR /workspace
