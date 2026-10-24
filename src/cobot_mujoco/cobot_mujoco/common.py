"""Shared paths, provenance, and atomic experiment records."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

SOURCE_REPO = "Sungah/omx_1024_test_jihyeok_success"
SOURCE_REVISION = "3502381b21fe15eae125dc36570779737ca85a71"
ROBOT_REPO = "ROBOTIS-GIT/open_manipulator"
ROBOT_REVISION = "ee9a720bcc45acda9c0df8fe689b1182844307db"
PACKAGE = Path(__file__).resolve().parent.parent
REPOSITORY = PACKAGE.parent.parent


def utc_now():
    """Return an unambiguous timestamp for persisted evidence."""
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    """Atomically replace a JSON record so interrupted runs remain readable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def read_json(path):
    """Read a UTF-8 JSON experiment record."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
