import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_resources_include_workers_and_tolerate_exited_processes():
    tree = ast.parse(Path('web_app.py').read_text(encoding='utf-8'))
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ApplicationResources')
    parent = Mock(pid=1)
    worker = Mock(pid=2)
    exited = Mock(pid=3)
    parent.children.return_value = [worker, exited]
    parent.memory_info.return_value = SimpleNamespace(rss=100 * 1024 ** 2)
    worker.memory_info.return_value = SimpleNamespace(rss=50 * 1024 ** 2)
    exited.memory_info.side_effect = ProcessLookupError
    from collections import namedtuple
    Times = namedtuple('Times', 'user system idle')
    snapshots = iter([Times(10, 10, 80), Times(20, 20, 100), Times(30, 30, 120)])
    namespace = {'psutil': SimpleNamespace(Process=lambda: parent, cpu_times=lambda: next(snapshots), Error=ProcessLookupError)}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), 'web_app.py', 'exec'), namespace)
    monitor = namespace['ApplicationResources']()
    assert monitor.sample() == 'System CPU: 50.0% | App RAM: 150 MiB'
    parent.children.side_effect = ProcessLookupError
    assert monitor.sample() == 'System CPU: 50.0% | App RAM: unavailable'
