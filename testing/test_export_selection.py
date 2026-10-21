import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('mode,selection,expected', [
    ('download_all', [{'transuid': 'one'}], ['one', 'two']),
    ('download_selected', [{'transuid': 'two'}], ['two']),
    ('download_selected', [], None),
])
def test_file_exports_distinguish_all_and_selected(tmp_path, mode, selection, expected):
    tree = ast.parse(Path('web_app.py').read_text(encoding='utf-8'))
    index = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'index')
    callback = next(node for node in index.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'export_action')
    class CapturedExport(Exception):
        pass
    captured = []
    async def perform(action):
        await action()
    async def io_bound(function, loaded, uids, output, **kwargs):
        captured.extend(uids)
        raise CapturedExport
    import tempfile
    namespace = dict(loaded=object(), table=SimpleNamespace(selected=selection, rows=[{'transuid': 'one'}, {'transuid': 'two'}]),
                     perform=perform, run=SimpleNamespace(io_bound=io_bound), export_logs=object(), options=lambda: {},
                     Path=Path, tempfile=tempfile, WORKSPACE=SimpleNamespace(name=str(tmp_path)), status=SimpleNamespace(set_text=lambda value: None))
    exec(compile(ast.Module(body=[callback], type_ignores=[]), 'web_app.py', 'exec'), namespace)
    if expected is None:
        with pytest.raises(ValueError, match='Select one or more transactions to export'):
            asyncio.run(namespace['export_action'](mode))
        assert not captured
    else:
        with pytest.raises(CapturedExport):
            asyncio.run(namespace['export_action'](mode))
        assert captured == expected
