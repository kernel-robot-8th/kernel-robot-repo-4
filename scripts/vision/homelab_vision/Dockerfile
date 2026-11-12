# homelab-vision: 관제 PC(omen-8)용 YOLO 근거 컨테이너. 2a 단계(중계에서 빌드·CPU 검증만).
# ROS 없음. 프레임을 디스크에 쓰지 않음. 듣는 포트 없음.
FROM python:3.12-slim

LABEL project="homelab-vision" stage="2a" built_on="relay"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    YOLO_OFFLINE=true \
    YOLO_AUTOINSTALL=false \
    YOLO_VERBOSE=false \
    YOLO_CONFIG_DIR=/app/ultralytics-config \
    MPLCONFIGDIR=/tmp/mpl \
    HF_HUB_OFFLINE=1

# 1) GPU 판 torch (CUDA 12.8 휠). 가장 큰 층이라 따로 둔다.
RUN pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128

# 2) ultralytics 는 opencv-python(화면 라이브러리 필요)을 끌고 오므로 지우고 headless contrib(cv2.aruco 포함)로 바꾼다.
RUN pip install ultralytics==8.4.193 paho-mqtt==2.2.0 numpy \
 && pip uninstall -y opencv-python \
 && pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.14.0.94 \
 && python -c "import cv2; cv2.aruco.ArucoDetector; print('cv2', cv2.__version__)"

# 3) 실행 사용자, ultralytics 설정(원격 동기화 끔), 설치 판 기록
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app/ultralytics-config \
 && chown -R app:app /app \
 && pip freeze > /app/requirements.lock
USER app
RUN python -c "from ultralytics import settings; settings.update({'sync': False}); print('sync', settings['sync'])" \
 && test -f /app/ultralytics-config/Ultralytics/settings.json \
 && rm -rf /tmp/mpl /tmp/Ultralytics

WORKDIR /app
COPY --chown=app:app PACKET_SHA256SUMS /app/PACKET_SHA256SUMS
COPY --chown=app:app weights/ /app/weights/
COPY --chown=app:app zone/ /app/zone/
# 구운 가중치·구역 파일이 패킷 해시와 같은지 빌드에서 확인한다(README 줄은 이미지에 없으므로 뺀다).
# 패킷 목록은 "해시 *./경로"(이진 표시 '*') 형식이다. 남은 줄이 정확히 13개(가중치 2 + 구역 11)인지도 본다.
RUN grep -v '[ *]\./README\.md$' /app/PACKET_SHA256SUMS > /tmp/sums \
 && test "$(wc -l < /tmp/sums)" = 13 \
 && sha256sum -c --strict --quiet /tmp/sums \
 && rm /tmp/sums

COPY --chown=app:app app/ /app/

ENTRYPOINT ["python", "-B", "/app/main.py"]
