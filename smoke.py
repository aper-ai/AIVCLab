"""Exercise the desktop workflow against the bundled public results."""
from __future__ import annotations

import json
import platform
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt, qVersion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox


def run_smoke(app, window, output: Path) -> int:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks = []

    def verify(condition, description):
        if not condition:
            raise AssertionError(description)
        checks.append(description)

    def click(widget, **kwargs):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, **kwargs)
        app.processEvents()

    def tab(index):
        bar = window.tabs.tabBar()
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(index).center())
        app.processEvents()

    def shot(filename):
        app.processEvents()
        verify(window.grab().save(str(output / filename)), f"保存窗口截图：{filename}")

    error = ""
    try:
        app.processEvents()
        verify(window.isVisible(), "桌面窗口正常显示")
        verify(not window.export_btn.isEnabled(), "无运行时禁用导出")
        with patch.object(QMessageBox, "warning") as warn:
            click(window.sample_btn)
            if warn.called:
                raise AssertionError(f"内置 AIVC 样例无法打开：{warn.call_args.args[2]}")
            verify(len(window.runs) == 2, "内置 AIVC 样例无错误打开")
        by_id = {run.run_id: index for index, run in enumerate(window.runs)}
        verify(set(by_id) == {"aivc-stat3-ko", "aivc-jun-ko"}, "两项公开历史条件均已载入")
        stat3, jun = by_id["aivc-stat3-ko"], by_id["aivc-jun-ko"]
        window.run_list.setCurrentRow(stat3)
        verify(window.source_btn.isEnabled() and "GSE198291" in window.status.text(), "显示数据集和公开来源")
        verify(any(window.metadata.item(i, 1).text() == "未经独立验证"
                   for i in range(window.metadata.rowCount())), "概览明确标记未经独立验证")
        tab(1)
        verify(window.tabs.currentIndex() == 1 and not window.figure_image.pixmap().isNull(), "原始公开图在图表页可见")
        shot("01-公开图件.png")
        tab(2)
        verify(window.data_table.rowCount() == 3 and window.data_table.item(0, 1).text() == "0.546",
               "源表显示 3 项原始指标，首项 0.546")
        verify(window.column_box.currentText() == "value" and len(window.chart.points) == 3, "数值列绘制三条源数据点")
        shot("02-源表与图.png")
        tab(3)
        verify("STAT3 KO" in window.parameters.toPlainText() and "0.20.0" in window.parameters.toPlainText(),
               "参数页展示条件和后端版本")
        window.doc_box.setCurrentIndex(2)
        verify("unvalidated" in window.parameters.toPlainText(), "验证记录可核对")
        tab(5)
        verify("历史" in window.report.toPlainText(), "上游整理报告可查看")

        tab(4)
        window.left_box.setCurrentIndex(stat3)
        window.right_box.setCurrentIndex(jun)
        verify("同一历史批次" in window.compare_info.text(), "明确区分同批次条件和独立运行")
        metrics = {window.metric_table.item(i, 0).text(): window.metric_table.item(i, 3).text()
                   for i in range(window.metric_table.rowCount())}
        verify(metrics == {"位移幅度": "+0.035", "随机对照": "+0.013", "向量差长度": "+0.024"},
               "三个公开指标差值与上游报告核算一致")
        click(window.differences_only, pos=QPoint(8, window.differences_only.height() // 2))
        verify(window.comparison_table.rowCount() > 0 and all(
            window.comparison_table.item(i, 3).text() == "不同" for i in range(window.comparison_table.rowCount())
        ), "仅差异开关有效")
        shot("03-运行对比.png")
        window.right_box.setCurrentIndex(stat3)
        verify(not window.export_btn.isEnabled(), "同一运行不能导出成对比")
        window.right_box.setCurrentIndex(jun)

        compare_path = output / "Aper AI 公开样例对比.html"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(compare_path), "HTML (*.html)")), \
                patch.object(QMessageBox, "warning") as warn:
            click(window.export_btn)
            verify(not warn.called and compare_path.is_file(), "从界面导出 HTML 对比报告")
        report = compare_path.read_text(encoding="utf-8")
        verify(all(token in report for token in ("aivc-stat3-ko", "aivc-jun-ko", "0.035",
                                                  "unvalidated", "587579e7", "data:image/png;base64")),
               "对比报告包含参数、差值、验证、固定来源和内嵌图")
        tab(0)
        one_path = output / "Aper AI 单次运行.html"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(one_path), "HTML (*.html)")), \
                patch.object(QMessageBox, "warning") as warn:
            click(window.export_btn)
            verify(not warn.called and one_path.is_file(), "从界面导出单次运行报告")

        source = window.runs[stat3].root
        external = output / "外部导入样例"
        shutil.copytree(source, external, dirs_exist_ok=True)
        manifest = external / "manifest.json"
        changed = json.loads(manifest.read_text(encoding="utf-8"))
        changed.update(run_id="external-aivc-stat3", dataset="different-dataset")
        manifest.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        (external / "figures" / "figure_manifest.csv").write_text("file,status\nfigure.png,available\n", encoding="utf-8")
        (external / "errors.jsonl").write_text('{"status":"fixture_skipped"}\n', encoding="utf-8")
        (external / "raw").mkdir(exist_ok=True)
        (external / "raw" / "fixture.bin").write_bytes(b"sample inventory fixture")
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(external)), \
                patch.object(QMessageBox, "warning") as warn:
            click(window.import_btn)
            verify(not warn.called and window.current_run().run_id == "external-aivc-stat3",
                   "导入外部 AIVC 结果文件夹（中文路径）")
        tab(1)
        click(window.figure_source_btn)
        verify(window.tabs.currentIndex() == 2 and window.table_box.currentText() == "figures/figure_manifest.csv",
               "从图表页打开上游图件来源清单")
        tab(5)
        window.artifact_box.setCurrentIndex(1)
        verify("fixture_skipped" in window.report.toPlainText(), "错误记录可查看")
        window.artifact_box.setCurrentIndex(2)
        verify(window.report.toPlainText() == "raw/fixture.bin", "原始输出按文件名索引")
        tab(4)
        window.right_box.setCurrentIndex(len(window.runs) - 1)
        verify("数据集不一致" in window.compare_info.text() and not window.metric_table.isVisible(),
               "数据集不同，标记不可比并隐藏数值差")
        tab(0)
        invalid = output / "无效清单"
        invalid.mkdir(exist_ok=True)
        (invalid / "manifest.json").write_text("{broken", encoding="utf-8")
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(invalid)), \
                patch.object(QMessageBox, "warning") as warn:
            click(window.import_btn)
            verify(warn.call_count == 1 and len(window.runs) == 3, "损坏清单提示错误并保留当前运行")
    except Exception:
        error = traceback.format_exc()
    result = {
        "passed": not error,
        "checks": checks,
        "error": error,
        "executable": sys.executable,
        "packaged": bool(getattr(sys, "frozen", False)),
        "platform": platform.platform(),
        "qt_version": qVersion(),
        "display_backend": app.platformName(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (output / "smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    return 1 if error else 0
