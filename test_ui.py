"""Regression checks for result identity, bounded previews and desktop error paths."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from app import MAX_DISPLAY_CELLS, Workbench
    from run_data import RunDataError
    from ui_state import UiState
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False
else:
    HAS_QT = True


@unittest.skipUnless(HAS_QT, "Install the pinned PySide6 dependency to run desktop tests")
class DesktopRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings_path = self.root / "preferences.ini"
        self.state = UiState(QSettings(str(self.settings_path), QSettings.Format.IniFormat))
        self.window = Workbench(state=self.state)
        self.addCleanup(self.window.close)

    def bundle(self, name, **changes):
        folder = self.root / name
        folder.mkdir()
        (folder / "tables").mkdir()
        (folder / "figures").mkdir()
        manifest = {"run_id": name, "backend": "test", "task": "review",
                    "dataset": "fixture", "parameters": {}, **changes}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "tables" / "values.csv").write_text("gene,value\nSTAT3,1.25\nJUN,2.50\n", encoding="utf-8")
        return folder

    def test_reimport_refreshes_metadata_and_does_not_duplicate_the_run(self):
        folder = self.bundle("first")
        self.window.add_run(folder)
        updated = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        updated.update(title="New title", dataset="new dataset")
        (folder / "manifest.json").write_text(json.dumps(updated), encoding="utf-8")
        self.window.add_run(folder)
        self.assertEqual(len(self.window.runs), 1)
        self.assertEqual(self.window.current_run().dataset, "new dataset")
        self.assertEqual(self.window.run_list.currentItem().text(), "New title")
        self.assertIn("New title", self.window.left_box.currentText())

    def test_failed_refresh_retains_the_open_result_and_selection(self):
        folder = self.bundle("original")
        self.window.add_run(folder)
        old_run = self.window.current_run()
        old_status = self.window.status.text()
        (folder / "manifest.json").write_text("{broken", encoding="utf-8")
        with patch.object(QMessageBox, "warning") as warning:
            self.window.reload_current_run()
        warning.assert_called_once()
        self.assertIs(self.window.current_run(), old_run)
        self.assertEqual(self.window.status.text(), old_status)
        self.assertEqual(self.window.data_table.item(0, 1).text(), "1.25")

    def test_closing_reindexes_comparison_by_path_and_clears_last_result(self):
        folders = [self.bundle(name) for name in ("one", "two", "three")]
        for folder in folders:
            self.window.add_run(folder)
        self.window.left_box.setCurrentIndex(0)
        self.window.right_box.setCurrentIndex(2)
        self.window.run_list.setCurrentRow(1)
        self.window.close_current_run()
        self.assertEqual([run.root for run in self.window.comparison_pair()], [folders[0], folders[2]])
        self.window.close_current_run()
        self.assertIsNone(self.window.comparison_pair())
        self.window.close_current_run()
        self.assertIsNone(self.window.current_run())
        self.assertEqual(self.window.metadata.rowCount(), 0)
        self.assertEqual(self.window.data_table.rowCount(), 0)
        self.assertEqual(self.window.metric_table.rowCount(), 0)
        self.assertEqual(self.window.chart.points, [])
        self.assertEqual(self.window.report.toPlainText(), "")
        self.assertFalse(self.window.export_btn.isEnabled())
        self.assertFalse(self.window.reload_btn.isEnabled())
        self.assertTrue(all((folder / "manifest.json").is_file() for folder in folders))

    def test_wide_gene_table_preserves_order_and_stays_within_widget_budget(self):
        folder = self.bundle("wide")
        headers = [f"G{number}" for number in range(978)]
        lines = [",".join(headers)]
        lines.extend(",".join(str(row * 1000 + col) for col in range(978)) for row in range(80))
        (folder / "tables" / "values.csv").write_text("\n".join(lines), encoding="utf-8")
        self.window.add_run(folder)
        table = self.window.data_table
        self.assertLessEqual(table.rowCount() * table.columnCount(), MAX_DISPLAY_CELLS)
        self.assertEqual(table.item(0, 511).text(), "511")
        self.assertEqual(table.item(1, 511).text(), "1511")
        self.assertIn("978", self.window.table_info.text())
        self.assertIn("512", self.window.table_info.text())
        self.assertIn("截断", self.window.table_info.text())
        self.assertTrue(self.window.preview.columns_truncated)
        self.assertTrue(self.window.preview.truncated)
        self.assertEqual(self.window.chart.points[0], (1, 0.0))

    def test_changed_invalid_table_clears_previous_preview_and_chart(self):
        folder = self.bundle("badtable")
        self.window.add_run(folder)
        self.assertTrue(self.window.chart.points)
        (folder / "tables" / "values.csv").write_text("gene,value\nmissing-value\n", encoding="utf-8")
        self.window.show_table(0)
        self.assertIsNone(self.window.preview)
        self.assertEqual(self.window.chart.points, [])
        self.assertEqual(self.window.data_table.rowCount(), 0)
        self.assertIn("预览失败", self.window.table_info.text())

    def test_recent_paths_are_persistent_bounded_and_do_not_autoload(self):
        for index in range(UiState.MAX_RECENT + 2):
            folder = self.bundle(f"run-{index}")
            self.window.add_run(folder)
        self.window.add_run(self.root / "run-5")
        self.state.sync()
        other = UiState(QSettings(str(self.settings_path), QSettings.Format.IniFormat))
        self.assertEqual(len(other.recent_paths()), UiState.MAX_RECENT)
        self.assertEqual(other.recent_paths()[0], str(self.root / "run-5"))
        reopened = Workbench(state=other)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.runs, [])
        missing = self.root / "removed"
        with self.assertRaises(RunDataError):
            reopened.add_run(missing)
        self.assertNotIn(str(missing), other.recent_paths())

    def test_save_without_suffix_confirms_the_actual_existing_target(self):
        self.window.add_run(self.bundle("input"))
        target = self.root / "existing.html"
        target.write_text("retain this report", encoding="utf-8")
        selection = (str(target.with_suffix("")), "HTML (*.html)")
        with patch.object(QFileDialog, "getSaveFileName", return_value=selection), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            self.window.choose_export()
        question.assert_called_once()
        self.assertEqual(target.read_text(encoding="utf-8"), "retain this report")
        with patch.object(QFileDialog, "getSaveFileName", return_value=selection), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, "warning") as warning:
            self.window.choose_export()
        warning.assert_not_called()
        self.assertIn("<!DOCTYPE html>", target.read_text(encoding="utf-8"))
        self.assertEqual(self.state.directory("export"), str(self.root))

    def test_save_rejects_unexpected_suffix_without_overwriting_other_file(self):
        self.window.add_run(self.bundle("input"))
        existing = self.root / "report.html"
        existing.write_text("keep", encoding="utf-8")
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(self.root / "report.txt"), "")), \
                patch.object(QMessageBox, "warning") as warning:
            self.window.choose_export()
        warning.assert_called_once()
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.root / "report.txt").exists())

    def test_generic_passed_does_not_appear_as_independent_validation(self):
        folder = self.bundle("technical", status="completed")
        (folder / "validation.json").write_text('{"status":"passed"}', encoding="utf-8")
        self.window.add_run(folder)
        rows = {self.window.metadata.item(i, 0).text(): self.window.metadata.item(i, 1).text()
                for i in range(self.window.metadata.rowCount())}
        self.assertIn("未知", rows["独立验证状态"])
        self.assertIn("响应检查", rows)
        self.assertIn("排名检查", rows)
        self.assertIn("不能替代独立验证", self.window.notes.toPlainText())

    def test_figure_resizes_to_the_visible_viewport(self):
        folder = self.bundle("figure")
        image = QImage(1600, 1000, QImage.Format.Format_RGB32)
        image.fill(0xFFDCEEEA)
        self.assertTrue(image.save(str(folder / "figures" / "image.png")))
        self.window.add_run(folder)
        self.window.tabs.setCurrentIndex(1)
        self.window.show()
        self.window.resize(1000, 720)
        self.application.processEvents()
        small = self.window.figure_image.pixmap().size()
        viewport = self.window.figure_scroll.viewport().size()
        self.assertLessEqual(small.width(), viewport.width())
        self.assertLessEqual(small.height(), viewport.height())
        self.window.resize(1500, 1000)
        self.application.processEvents()
        large = self.window.figure_image.pixmap().size()
        self.assertGreater(large.width(), small.width())
        self.assertLessEqual(abs(large.width() / large.height() - 1.6), 0.02)

    def test_missing_system_browser_reports_a_failure(self):
        self.window.add_run(self.bundle("source", source_url="https://example.org/paper"))
        with patch("app.QDesktopServices.openUrl", return_value=False), \
                patch.object(QMessageBox, "warning") as warning:
            self.window.open_public_source()
        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
