"""Copy shareable project files to a NEW path, excluding machine/runtime artifacts."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    out = args.out.expanduser().resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit('Destination must be outside this project.')
    if out.exists():
        raise SystemExit(f'Destination exists; choose a new path: {out}')
    shutil.copytree(ROOT,out,ignore=shutil.ignore_patterns(
        '.venvs','.venv','.local','.git','__pycache__','.pytest_cache',
        '.cache','runs','.env','.vscode','*.pyc'))
    print(f'Exported to {out}')

if __name__ == '__main__': main()
