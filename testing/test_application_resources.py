import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_resources_show_available_system_memory_and_tolerate_unavailable_stats(tmp_path):
    tree = ast.parse(Path('web_app.py').read_text(encoding='utf-8'))
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ApplicationResources')
    from collections import namedtuple
    Times = namedtuple('Times', 'user system idle')
    snapshots = iter([Times(10, 10, 80), Times(20, 20, 100), Times(30, 30, 120)])
    disk_usage = Mock(return_value=SimpleNamespace(free=25 * 1024 ** 3))
    virtual_memory = Mock(return_value=SimpleNamespace(available=8 * 1024 ** 3, free=1 * 1024 ** 3))
    namespace = {'Path': Path, 'sys': SimpleNamespace(frozen=True, executable=str(tmp_path / 'LogComparator.exe')),
                 'psutil': SimpleNamespace(cpu_times=lambda: next(snapshots), disk_usage=disk_usage, virtual_memory=virtual_memory)}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), 'web_app.py', 'exec'), namespace)
    monitor = namespace['ApplicationResources']()
    assert monitor.sample() == 'System CPU: 50.0% | System RAM available: 8.0 GiB | Disk free: 25.0 GiB'
    disk_usage.assert_called_once_with(str(tmp_path))
    disk_usage.side_effect = OSError('Disk not accessible')
    virtual_memory.side_effect = OSError('Memory statistics not accessible')
    assert monitor.sample() == 'System CPU: 50.0% | System RAM available: unavailable | Disk free: unavailable'
