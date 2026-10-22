"""Exercise the actual host-side launcher with a fake Docker CLI."""
import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('count,expected', [('8', '7'), ('6', '5'), ('2', '1'), ('16', '15'), ('1', None), ('0', None), ('invalid', None), ('', None), ('fail', None)])
def test_detects_host_cpus_and_rejects_missing_budget(tmp_path, count, expected):
    shell = Path('C:/Program Files/Git/bin/bash.exe') if os.name == 'nt' else shutil.which('sh')
    if not shell or not Path(shell).is_file():
        pytest.skip('A POSIX shell is required for the Docker launcher test')
    launcher = tmp_path / 'docker_compose.sh'
    shutil.copyfile(ROOT / 'docker_compose.sh', launcher)
    fake = tmp_path / 'docker'
    fake.write_text("""#!/bin/sh
if [ "$1" = info ]; then
    [ "$MOCK_CPUS" != fail ] || exit 1
    printf '%s\n' "$MOCK_CPUS"
else
    printf 'COMPOSE_LIMIT=%s\n' "$LOGCOMPARATOR_CPU_LIMIT"
    printf 'ARG=%s\n' "$@"
fi
""", encoding='utf-8', newline='\n')
    fake.chmod(0o755)
    env = dict(os.environ, MOCK_CPUS=count, LOGCOMPARATOR_CPU_LIMIT='999')
    env['PATH'] = str(tmp_path) + os.pathsep + env['PATH']
    result = subprocess.run([str(shell), str(launcher), '-f', 'compose.remote.yaml', 'up', '-d'], env=env, capture_output=True, text=True, timeout=15)
    if expected is None:
        assert result.returncode != 0
        assert 'COMPOSE_LIMIT=' not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert 'COMPOSE_LIMIT=' + expected + '\n' in result.stdout
        assert 'ARG=-f\nARG=compose.remote.yaml\nARG=up\nARG=-d\n' in result.stdout
        assert 'Tango allowance: 1.' in result.stderr
