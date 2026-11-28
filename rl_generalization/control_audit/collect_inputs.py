"""Read selected control metadata only; never imports drivers or opens robot devices."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

p = argparse.ArgumentParser()
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
home = Path.home()
patterns = [
 'il_ws/bundles/omx_arrange_shoe_zc/v1/**/*.json',
 'il_ws/bundles/omx_load_zc/v1/**/*.json',
 'il_ws/poses/rest_pose_omx3.json',
 '.cache/huggingface/lerobot/calibration/robots/omx_follower/*.json',
 'jihye/kernel-robot-repo-4-omx-dashboard/act_ensemble.py',
 'il_ws/src/lerobot/src/lerobot/robots/omx_follower/*.py',
 'il_ws/src/lerobot/src/lerobot/motors/motors_bus.py',
 'venv/il/lib/python*/site-packages/lerobot/robots/omx_follower/*.py',
 'venv/il/lib/python*/site-packages/lerobot/motors/motors_bus.py',
]
files = {}
missing = []
for pattern in patterns:
    hits = list(home.glob(pattern))
    if not hits: missing.append(pattern)
    for f in hits:
        if f.is_file() and f.stat().st_size < 2_000_000:
            files[str(f.relative_to(home))] = f
report = {'missing_patterns': missing, 'files': {}}
# Exclusive creation prevents replacing an earlier evidence archive.
with a.out.expanduser().open('xb') as stream:
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for name, f in sorted(files.items()):
            data = f.read_bytes()
            report['files'][name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
            info = tarfile.TarInfo(name); info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        data = json.dumps(report, indent=2).encode()
        info = tarfile.TarInfo('collection_manifest.json'); info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
print(f'Collected {len(files)} files -> {a.out}; missing patterns: {len(missing)} (see manifest).')
