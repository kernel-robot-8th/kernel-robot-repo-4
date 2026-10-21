#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=========================================================="
echo "🦾 Launching OMX Teleop & LeRobot Studio (Sprint 2 / PT-23)"
echo "=========================================================="

# Check if Docker LiveKit is desired
if command -v docker >/dev/null 2>&1; then
    if [ "$1" == "--with-livekit" ]; then
        echo "[1/2] Starting local LiveKit SFU server via Docker..."
        docker compose up -d
        echo "LiveKit SFU running on ws://localhost:7880"
    fi
fi

# Activate Python Virtual Environment
if [ -d ".venv" ]; then
    PYTHON=".venv/bin/python"
    UVICORN=".venv/bin/uvicorn"
else
    PYTHON="python3"
    UVICORN="uvicorn"
fi

echo "[2/2] Starting Studio Web Server on http://0.0.0.0:8080..."
echo "----------------------------------------------------------"
echo "  👉 Open your browser at: http://localhost:8080"
echo "  🎮 Plug in your USB Gamepad or use Space / Enter keys"
echo "  📹 Dual Camera feeds: Top (720p) & Wrist (480p)"
echo "  📁 LeRobot datasets saved to: ~/.cache/huggingface/lerobot/pinky_omx_tasks/"
echo "----------------------------------------------------------"

exec $UVICORN server.app:app --host 0.0.0.0 --port 8080 --reload
