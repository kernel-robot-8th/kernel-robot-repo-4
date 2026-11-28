import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest
from omx_rl import device

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('bootstrap', ROOT/'tools/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_bashrc_idempotent_and_backup(tmp_path):
    rc = tmp_path/'bashrc'
    rc.write_text('export EXISTING=keep\n')
    source = tmp_path/"folder with spaces"/'aliases.bash'
    bootstrap.register_bashrc(rc, source)
    first = rc.read_text()
    bootstrap.register_bashrc(rc, source)
    assert rc.read_text() == first
    assert first.count(bootstrap.BEGIN) == 1
    assert 'export EXISTING=keep' in first
    assert len(list(tmp_path.glob('bashrc.rl-backup-*'))) == 1


def test_relocated_shell_with_legacy_alias(tmp_path):
    root = tmp_path/'relocated checkout'
    (root/'shell').mkdir(parents=True)
    (root/'versions/v003').mkdir(parents=True)
    (root/'.venvs/rl/bin').mkdir(parents=True)
    (root/'CURRENT').write_text('v003\n')
    (root/'.venvs/rl/bin/activate').write_text('export TEST_ACTIVATED=yes\n')
    shutil.copyfile(ROOT/'shell/aliases.bash',root/'shell/aliases.bash')
    result = subprocess.run(['bash','--noprofile','--norc','-c',
        'alias rl=old; source "$1/shell/aliases.bash"; rl; cdrl; printf "%s\\n%s\\n" "$TEST_ACTIVATED" "$PWD"',
        'bash',str(root)], capture_output=True,text=True,check=True)
    assert result.stdout.splitlines() == ['yes',str(root/'versions/v003')]


def test_cuda_requested_never_silently_downgrades(monkeypatch):
    monkeypatch.setattr(device.torch.cuda,'is_available',lambda:False)
    assert device.resolve_device('auto')=='cpu'
    assert device.resolve_device('cpu')=='cpu'
    with pytest.raises(RuntimeError): device.resolve_device('cuda')


def test_malformed_bashrc_not_modified(tmp_path):
    rc = tmp_path/'bashrc'; rc.write_text(bootstrap.BEGIN)
    with pytest.raises(ValueError): bootstrap.register_bashrc(rc,tmp_path/'source')
    assert rc.read_text()==bootstrap.BEGIN
