"""Check that the Docker COPY list includes local Python dependencies."""
import ast
import unittest
from pathlib import Path


class DockerPackagingTests(unittest.TestCase):
    def test_all_local_imports_are_copied_into_image(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / 'Dockerfile').read_text(encoding='utf-8')
        copied = {name for line in dockerfile.splitlines() if line.startswith('COPY ')
                  for name in line.split()[1:-1] if name.endswith('.py')}
        local_modules = {p.stem: p.name for p in root.glob('*.py')}
        for filename in copied:
            tree = ast.parse((root / filename).read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                names = ([a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import)
                         else [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module else [])
                for name in names:
                    if name in local_modules:
                        with self.subTest(source=filename, dependency=name):
                            self.assertIn(local_modules[name], copied)
