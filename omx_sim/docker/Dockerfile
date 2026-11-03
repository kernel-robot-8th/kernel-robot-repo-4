# LeRobot training image (ACT etc.) for OMX datasets
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# ffmpeg (with libdav1d) is needed to decode the AV1 videos in the dataset
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git build-essential cmake libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ARG LEROBOT_VERSION=0.6.1
RUN pip install --upgrade pip && \
    pip install "lerobot[training]==${LEROBOT_VERSION}"

# Writable home/cache for running as a non-root host user (--user)
# (USER avoids getpwuid() failures in torch when the uid has no passwd entry)
ENV USER=lerobot \
    HOME=/workspace/.home \
    HF_HOME=/workspace/.home/hf
WORKDIR /workspace
