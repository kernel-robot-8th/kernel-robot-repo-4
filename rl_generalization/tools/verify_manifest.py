"""Verify version snapshot hashes; optional --source verifies external original video."""
import argparse
import hashlib
import json
from pathlib import Path

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()

parser = argparse.ArgumentParser()
parser.add_argument('version', type=Path)
parser.add_argument('--source', action='store_true')
args = parser.parse_args()
manifest = json.loads((args.version / 'manifest.json').read_text())
for name, record in manifest['files'].items():
    path = args.version / name
    if digest(path) != record['sha256'] or path.stat().st_size != record['bytes']:
        raise SystemExit(f'MISMATCH: {path}')
if args.source:
    source = manifest['source_video']
    if digest(Path(source['path'])) != source['sha256']:
        raise SystemExit('MISMATCH: source video')
print(f"Verified {len(manifest['files'])} snapshot files" + (' and source video' if args.source else ''))
