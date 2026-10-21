#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Running OMX Teleoperation & LeRobot Test Suite..."
PYTHONPATH=. .venv/bin/pytest tests/ -v --tb=short

echo "✅ All tests passed successfully!"
