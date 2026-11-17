"""Shared top-camera preprocessing. No random crop of the lid seam."""
from pathlib import Path
import json

CLASSES = ('not_verified', 'closed_verified')
CAMERA = 'observation.images.top'

def is_pointer(path):
    with Path(path).open('rb') as f:
        return f.read(80).startswith(b'version https://git-lfs.github.com/spec/v1')

def read_json(path):
    return json.loads(Path(path).read_text())

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)

def square(image, size=320):
    import cv2
    import numpy as np
    h, w = image.shape[:2]
    scale = size / max(h, w)
    nw, nh = round(w * scale), round(h * scale)
    out = np.full((size, size, 3), 114, dtype=np.uint8)
    x, y = (size-nw)//2, (size-nh)//2
    out[y:y+nh, x:x+nw] = cv2.resize(image, (nw, nh))
    return out
