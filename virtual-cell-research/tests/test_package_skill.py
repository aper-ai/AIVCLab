"""Protect the source package from environments created by the user guides."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location(
    'package_skill', Path(__file__).resolve().parents[1] / 'scripts/package_skill.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class SourcePackageTests(unittest.TestCase):
    def test_documented_and_custom_environments_never_enter_source_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {
                'SKILL.md': '---\nname: example\ndescription: Example\n---\n',
                'scripts/example.py': 'print("source")\n',
                'cases/example/evidence.json': '{"model_status":"not_run"}\n',
                '.venv-data/site-packages/top_level.py': 'not source\n',
                'examples/.venv-model/site-packages/nested.py': 'not source\n',
                'examples/custom-python/pyvenv.cfg': 'home = example\n',
                'examples/custom-python/site-packages/custom.py': 'not source\n',
                'examples/custom-conda/conda-meta/history': 'example\n',
                'examples/custom-conda/site-packages/custom.py': 'not source\n',
                'cases/example/local-runs/report.md': 'local result\n',
                'cases/example/data/private.json': '{}\n',
            }
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            self.assertEqual(PACKAGE.build(root), 3)
            with zipfile.ZipFile(root / 'dist/virtual-cell-research.zip') as archive:
                manifest = json.loads(archive.read('virtual-cell-research/package_manifest.json'))
                self.assertEqual(set(manifest), {'SKILL.md', 'scripts/example.py', 'cases/example/evidence.json'})
                self.assertEqual(len(archive.namelist()), 4)
                self.assertEqual(archive.read('virtual-cell-research/scripts/example.py'),
                                 (root / 'scripts/example.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
