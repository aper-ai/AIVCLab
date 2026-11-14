"""Protect the source package from environments created by the user guides."""
import importlib.util
import gzip
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
    def test_language_switch_targets_survive_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'SKILL.md').write_text('---\nname: example\ndescription: Example\n---\n', encoding='utf-8')
            documents = {
                'README.md': '[简体中文](README.zh-CN.md)\n\n# Research workflows\n',
                'README.zh-CN.md': '[English](README.md)\n\n# 研究工作流\n',
            }
            for name, content in documents.items():
                (root / name).write_text(content, encoding='utf-8')
            PACKAGE.build(root)
            with zipfile.ZipFile(root / 'dist/virtual-cell-research.zip') as archive:
                manifest = json.loads(archive.read('virtual-cell-research/package_manifest.json'))
                for name, content in documents.items():
                    self.assertIn(name, manifest)
                    self.assertEqual(archive.read('virtual-cell-research/' + name).decode('utf-8'), content)

    def test_figure_source_tables_are_bundled_without_general_data_matrices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {
                'SKILL.md': b'---\nname: example\ndescription: Example\n---\n',
                'cases/gallery/demo/target_setting_source.csv': b'cell,setting\nc1,0\n',
                'cases/gallery/demo/cell_state_shift_source.csv.gz': gzip.compress(b'cell,dx,dy\nc1,0.1,-0.2\n'),
                'cases/gallery/demo/environment-freeze.txt': b'numpy==2.3.5\n',
                'cases/gallery/demo/unit_metrics.csv': b'unit,rmse\nu1,0.1\n',
                'cases/public-case/figure_data.csv': b'gene,response\nG1,0.2\n',
                'cases/public-case/sample_mapping.csv': b'sample,donor\ns1,d1\n',
                'cases/gallery/demo/full_expression.csv': b'cell,G1\nc1,18\n',
                'cases/gallery/demo/unrelated.txt': b'not a figure source\n',
                'cases/demo/input_source.csv': b'cell,G1\nc1,18\n',
                'cases/gallery/demo/data/private_source.csv': b'private\n',
            }
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            self.assertEqual(PACKAGE.build(root), 7)
            with zipfile.ZipFile(root / 'dist/virtual-cell-research.zip') as archive:
                manifest = json.loads(archive.read('virtual-cell-research/package_manifest.json'))
                expected = {'SKILL.md', 'cases/gallery/demo/target_setting_source.csv',
                            'cases/gallery/demo/cell_state_shift_source.csv.gz',
                            'cases/gallery/demo/environment-freeze.txt',
                            'cases/gallery/demo/unit_metrics.csv',
                            'cases/public-case/figure_data.csv',
                            'cases/public-case/sample_mapping.csv'}
                self.assertEqual(set(manifest), expected)
                for name in expected:
                    self.assertEqual(archive.read('virtual-cell-research/' + name), files[name])

    def test_oversized_figure_source_table_stops_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'SKILL.md').write_text('skill', encoding='utf-8')
            source = root / 'cases/gallery/demo/matrix_source.csv.gz'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'x' * (PACKAGE.MAX_GALLERY_TABLE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, 'exceeds 2 MiB'):
                PACKAGE.build(root)
            self.assertFalse((root / 'dist/virtual-cell-research.zip').exists())

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

