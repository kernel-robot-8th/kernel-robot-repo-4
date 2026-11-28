"""One-command Linux/WSL Bash setup. Does not install OS/GPU drivers or control robots."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '# >>> omx-rl environment >>>'
END = '# <<< omx-rl environment <<<'


def register_bashrc(path, source):
    old = path.read_text() if path.exists() else ''
    if old.count(BEGIN) != old.count(END) or old.count(BEGIN) > 1:
        raise ValueError('Malformed OMX RL block in bashrc; fix it before retrying.')
    block = f'{BEGIN}\nsource {shlex.quote(str(source))}\n{END}'
    pattern = re.escape(BEGIN) + r'.*?' + re.escape(END)
    new = re.sub(pattern, lambda _: block, old, flags=re.S) if BEGIN in old else old.rstrip()+'\n\n'+block+'\n'
    if new == old:
        return
    if path.exists():
        backup = path.with_name(path.name+'.rl-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new)


def resolve_install_device(requested):
    if requested != 'auto':
        return requested
    if shutil.which('nvidia-smi'):
        try:
            result = subprocess.run(['nvidia-smi','-L'], capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and 'GPU' in result.stdout:
                return 'cuda'
        except subprocess.TimeoutExpired:
            pass
    return 'cpu'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device', choices=['auto','cpu','cuda'], default='auto')
    p.add_argument('--torch-index-url', help='Override wheel index, e.g. https://download.pytorch.org/whl/cu128')
    p.add_argument('--bashrc', type=Path, default=Path.home()/'.bashrc')
    p.add_argument('--no-shell', action='store_true')
    p.add_argument('--skip-install', action='store_true', help='Verify an already installed rl environment')
    args = p.parse_args()
    if sys.platform != 'linux':
        raise SystemExit('This script supports Linux/WSL Bash. Use WSL2 on Windows.')
    if not (3,11) <= sys.version_info[:2] <= (3,13):
        raise SystemExit('Use Python 3.11–3.13 (3.12 recommended), e.g. RL_PYTHON=python3.12 bash setup.sh')
    target = resolve_install_device(args.device)
    env_dir = ROOT/'.venvs/rl'
    python = env_dir/'bin/python'
    if not python.exists():
        subprocess.run([sys.executable,'-m','venv','--prompt','rl',str(env_dir)],check=True)
    cache = ROOT/'.local'; cache.mkdir(exist_ok=True)
    version = (ROOT/'CURRENT').read_text().strip()
    runtime = dict(os.environ)
    runtime['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    runtime['PYTHONPATH'] = str(ROOT/'versions'/version/'code')
    runtime['MPLCONFIGDIR'] = str(cache/'matplotlib')
    def run(cmd, **kwargs):
        return subprocess.run([str(python), *cmd],check=True,env=runtime,**kwargs)
    if not args.skip_install:
        run(['-m','pip','install','--upgrade','pip'])
        index = args.torch_index_url or ('https://download.pytorch.org/whl/cu128' if target=='cuda' else 'https://download.pytorch.org/whl/cpu')
        # Force switching CPU/CUDA build when setup is re-run with a different target.
        run(['-m','pip','install','--upgrade','--force-reinstall','--no-deps','torch==2.11.0','--index-url',index])
        # Install runtime deps of the selected wheel and the rest of the project.
        run(['-m','pip','install','-r',str(ROOT/'requirements.txt')])
    code = "import json,torch; from omx_rl.device import resolve_device; print(json.dumps({'device':resolve_device(%r),'torch':torch.__version__,'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))" % target
    result = run(['-c',code],capture_output=True,text=True)
    details = json.loads(result.stdout)
    run(['-m','pip','check'])
    run(['-m','pytest','-q',str(ROOT/'versions'/version/'tests')])
    frozen = run(['-m','pip','freeze'],capture_output=True,text=True)
    (cache/'requirements.resolved.txt').write_text(frozen.stdout)
    (cache/'setup.json').write_text(json.dumps({'version':version,'requested_device':args.device,**details},indent=2)+'\n')
    if not args.no_shell:
        register_bashrc(args.bashrc.expanduser(),ROOT/'shell/aliases.bash')
    print(json.dumps(details,indent=2))
    print('Setup complete. For this terminal run:\nsource '+shlex.quote(str(ROOT/'shell/aliases.bash'))+'\nrl\ncdrl')

if __name__ == '__main__':
    main()
