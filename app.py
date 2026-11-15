"""Local desktop workbench for reviewing existing AIVC results."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from run_data import MAX_FIGURE_BYTES, RunDataError, compare_runs, export_report, load_run, read_table, resolve_asset


TITLE = "AIVCLab · 虚拟细胞研究平台"
APP_ROOT = Path(__file__).resolve().parent
ASSETS = APP_ROOT / "samples"
ICON = APP_ROOT / "installer" / "aper-workbench.ico"
STYLE = """
QWidget { background: #f4f7fb; color: #142338; font: 13px 'Microsoft YaHei UI'; }
QFrame#sidebar { background: #0e2136; }
QFrame#sidebar QLabel { background: transparent; color: #dcebf4; }
QFrame#sidebar QPushButton { background: #213950; color: #eff7ff; border: 1px solid #35516a; }
QFrame#sidebar QPushButton:hover { background: #2d4e69; }
QFrame#sidebar QLabel#brand { color: #8dd6cd; font-size: 23px; font-weight: 700; }
QLabel#headline { font-size: 28px; font-weight: 700; color: #142338; }
QLabel#muted { color: #4c6176; }
QLabel#notice { background: #e5f3f0; color: #154b49; padding: 10px 12px; border-radius: 5px; }
QPushButton { background: #fff; border: 1px solid #c3d0dc; border-radius: 5px; padding: 8px 12px; }
QPushButton:hover { background: #eaf2fa; }
QPushButton#primary { background: #11695e; color: white; border: 1px solid #11695e; }
QPushButton#primary:hover { background: #09584f; }
QPushButton:disabled, QPushButton#primary:disabled { background: #e5ebf1; color: #6a7786; border-color: #d1d9e2; }
QListWidget, QTableWidget, QPlainTextEdit, QComboBox { background: #fff; border: 1px solid #d4dfe9; border-radius: 4px; }
QListWidget#runs { background: #152b42; color: #e1edf7; border: 1px solid #304b63; }
QListWidget::item { padding: 8px; }
QListWidget::item:selected { background: #dceeea; color: #153a3b; }
QListWidget#runs::item:selected { background: #26756e; color: white; }
QTableWidget { gridline-color: #e3eaf0; alternate-background-color: #f6f9fb; }
QHeaderView::section { background: #e9f0f6; color: #243e56; padding: 7px; border: 0; font-weight: 600; }
QTabWidget::pane { border: 1px solid #d4dfe9; border-radius: 4px; background: #f4f7fb; }
QTabBar::tab { background: #e9eef4; padding: 10px 18px; border: 1px solid #d4dfe9; }
QTabBar::tab:selected { background: #fff; color: #11695e; font-weight: 700; }
QComboBox { padding: 6px 9px; min-width: 150px; }
"""


def label(text, style=None):
    item = QLabel(text)
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setWordWrap(True)
    if style:
        item.setObjectName(style)
    return item


def button(text, handler, primary=False):
    item = QPushButton(text)
    if primary:
        item.setObjectName("primary")
    item.clicked.connect(handler)
    return item


def table_widget():
    table = QTableWidget()
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def populate(table, headers, rows):
    table.clear()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setRowCount(len(rows))
    for row_number, row in enumerate(rows):
        for column, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row_number, column, item)
    if headers:
        table.setColumnWidth(0, 205 if len(headers) < 5 else 130)


def display(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class NumericChart(QWidget):
    """Read-only view of the selected source column in its original row order."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(225)
        self.points = []

    def set_points(self, points):
        self.points = points
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#4c6176"))
        if not self.points:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "选择含有限数值的列以查看源表图")
            return
        left, top, right, bottom = 112, 25, self.width() - 25, self.height() - 40
        values = [value for _, value in self.points]
        low, high = min(values), max(values)
        magnitude = max(abs(low), abs(high), 1)
        lower, upper = low / magnitude, high / magnitude
        span = upper - lower
        first_row, last_row = self.points[0][0], self.points[-1][0]
        for step in range(5):
            fraction = step / 4
            y = int(bottom - fraction * (bottom - top))
            painter.setPen(QColor("#e1ebf1"))
            painter.drawLine(left, y, right, y)
            painter.setPen(QColor("#42596e"))
            painter.drawText(8, y + 4, f"{((1 - fraction) * lower + fraction * upper) * magnitude:.5g}")
        painter.setPen(QPen(QColor("#1b8273"), 2))
        for row, value in self.points:
            x = int(left + (right - left) * (row - first_row) / max(1, last_row - first_row))
            ratio = (value / magnitude - lower) / span if span else 0.5
            y = int(bottom - ratio * (bottom - top))
            painter.drawEllipse(x - 2, y - 2, 5, 5)
        painter.setPen(QColor("#42596e"))
        painter.drawText(left, bottom + 22, f"数据行 {first_row}–{last_row}（不含表头）")


class Workbench(QMainWindow):
    def __init__(self):
        super().__init__()
        self.runs = []
        self.preview = None
        self.setWindowTitle(TITLE)
        self.resize(1240, 820)
        self.setMinimumSize(950, 670)
        self.setStyleSheet(STYLE)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(248)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(17, 22, 17, 17)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(QIcon(str(ICON)).pixmap(34, 34))
        brand.addWidget(mark)
        brand.addWidget(label("APER AI", "brand"), 1)
        side.addLayout(brand)
        side.addWidget(label("AIVCLab · 结果工作台"))
        side.addSpacing(15)
        self.import_btn = button("导入运行目录…", self.import_directory)
        self.sample_btn = button("打开 AIVC 公开样例", self.load_samples)
        side.addWidget(self.import_btn)
        side.addWidget(self.sample_btn)
        side.addSpacing(14)
        side.addWidget(label("已打开的运行"))
        self.run_list = QListWidget()
        self.run_list.setObjectName("runs")
        self.run_list.setAccessibleName("已打开的运行")
        side.addWidget(self.run_list, 1)
        side.addWidget(label("本地查看 · Windows 预览版 0.1.0"))
        layout.addWidget(sidebar)

        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(24, 18, 24, 12)
        header = QHBoxLayout()
        header.addWidget(label("AIVCLab", "headline"), 1)
        self.export_btn = button("导出报告…", self.choose_export, primary=True)
        self.export_btn.setEnabled(False)
        header.addWidget(self.export_btn)
        content.addLayout(header)
        self.status = label("导入一份 AIVC 结果目录，或打开两个内置公开样例。", "notice")
        content.addWidget(self.status)
        self.tabs = QTabWidget()
        content.addWidget(self.tabs, 1)
        layout.addWidget(body, 1)
        self.setCentralWidget(central)
        self._create_overview()
        self._create_figures()
        self._create_tables()
        self._create_parameters()
        self._create_comparison()
        self._create_artifacts()
        self.run_list.currentRowChanged.connect(self.show_run)
        self.tabs.currentChanged.connect(self.refresh_export)
        self.show_comparison()

    def _tab(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(13, 12, 13, 12)
        self.tabs.addTab(page, title)
        return layout

    def _create_overview(self):
        layout = self._tab("运行概览")
        line = QHBoxLayout()
        self.summary = label("导入后查看数据、方法、来源和验证状态。", "muted")
        line.addWidget(self.summary, 1)
        self.source_btn = button("查看公开来源 ↗", self.open_public_source)
        self.source_btn.setEnabled(False)
        line.addWidget(self.source_btn)
        layout.addLayout(line)
        self.metadata = table_widget()
        layout.addWidget(self.metadata, 1)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(150)
        self.notes.setPlaceholderText("运行备注与导入提示")
        layout.addWidget(self.notes)

    def _create_figures(self):
        layout = self._tab("图表")
        self.figure_info = label("已保存的图与图表来源。", "muted")
        layout.addWidget(self.figure_info)
        self.figure_box = QComboBox()
        self.figure_box.setAccessibleName("选择图表")
        self.figure_box.currentIndexChanged.connect(self.show_figure)
        layout.addWidget(self.figure_box)
        self.figure_source_btn = button("打开图表来源清单", self.open_figure_source)
        self.figure_source_btn.setEnabled(False)
        layout.addWidget(self.figure_source_btn, 0, Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.figure_image = label("当前运行无可预览的图。", "muted")
        self.figure_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.figure_image)
        layout.addWidget(scroll, 1)

    def _create_tables(self):
        layout = self._tab("源表")
        choices = QHBoxLayout()
        self.table_box = QComboBox()
        self.table_box.setAccessibleName("选择源表")
        self.table_box.currentIndexChanged.connect(self.show_table)
        self.column_box = QComboBox()
        self.column_box.setAccessibleName("图表数值列")
        self.column_box.currentIndexChanged.connect(self.show_column)
        choices.addWidget(label("表格"))
        choices.addWidget(self.table_box, 2)
        choices.addWidget(label("绘图列"))
        choices.addWidget(self.column_box, 1)
        layout.addLayout(choices)
        self.table_info = label("选择源表查看数据。", "muted")
        layout.addWidget(self.table_info)
        split = QSplitter(Qt.Orientation.Vertical)
        self.data_table = table_widget()
        self.chart = NumericChart()
        split.addWidget(self.data_table)
        split.addWidget(self.chart)
        split.setSizes([390, 235])
        layout.addWidget(split, 1)

    def _create_parameters(self):
        layout = self._tab("参数与验证")
        self.doc_box = QComboBox()
        self.doc_box.addItems(["参数", "运行清单", "验证记录", "溯源记录"])
        self.doc_box.currentIndexChanged.connect(self.show_parameters)
        layout.addWidget(self.doc_box)
        self.parameters = QPlainTextEdit()
        self.parameters.setReadOnly(True)
        self.parameters.setPlaceholderText("选择运行后查看完整记录")
        layout.addWidget(self.parameters, 1)

    def _create_comparison(self):
        layout = self._tab("运行对比")
        choices = QHBoxLayout()
        self.left_box, self.right_box = QComboBox(), QComboBox()
        self.left_box.setAccessibleName("左侧运行")
        self.right_box.setAccessibleName("右侧运行")
        for name, box in (("左侧", self.left_box), ("右侧", self.right_box)):
            choices.addWidget(label(name))
            choices.addWidget(box, 1)
            box.currentIndexChanged.connect(self.show_comparison)
        layout.addLayout(choices)
        self.compare_info = label("至少打开两次运行。", "notice")
        layout.addWidget(self.compare_info)
        self.metric_title = label("同名、同单位的汇总指标 · 差值 = 右侧 − 左侧", "muted")
        layout.addWidget(self.metric_title)
        self.metric_table = table_widget()
        self.metric_table.setMaximumHeight(190)
        layout.addWidget(self.metric_table)
        self.metric_notes = label("", "muted")
        layout.addWidget(self.metric_notes)
        self.differences_only = QCheckBox("仅显示不同的参数与记录")
        self.differences_only.toggled.connect(self.show_comparison)
        layout.addWidget(self.differences_only)
        self.comparison_table = table_widget()
        layout.addWidget(self.comparison_table, 1)

    def _create_artifacts(self):
        layout = self._tab("报告与文件")
        line = QHBoxLayout()
        self.artifact_box = QComboBox()
        self.artifact_box.addItems(["运行报告", "运行错误记录", "原始输出清单"])
        self.artifact_box.setAccessibleName("选择运行文件记录")
        self.artifact_box.currentIndexChanged.connect(self.show_artifact)
        line.addWidget(self.artifact_box, 1)
        self.open_dir_btn = button("打开结果目录", self.open_source_directory)
        self.open_dir_btn.setEnabled(False)
        line.addWidget(self.open_dir_btn)
        layout.addLayout(line)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("导入后查看 AIVC 报告、错误记录与原始输出清单。")
        layout.addWidget(self.report, 1)

    def current_run(self):
        row = self.run_list.currentRow()
        return self.runs[row] if 0 <= row < len(self.runs) else None

    def import_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "选择含 manifest.json 的结果目录")
        if folder:
            try:
                self.add_run(folder)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "导入失败", str(exc))

    def add_run(self, folder):
        path = Path(folder).resolve()
        for index, run in enumerate(self.runs):
            if run.root == path:
                self.run_list.setCurrentRow(index)
                return run
        run = load_run(path)
        self.runs.append(run)
        title = run.manifest.get("title")
        name = title.strip() if isinstance(title, str) and title.strip() else run.run_id
        self.run_list.addItem(name)
        self.run_list.item(self.run_list.count() - 1).setToolTip(f"{run.run_id}\n{run.root}")
        for box in (self.left_box, self.right_box):
            box.addItem(f"{name}  ·  {len(self.runs):02d}")
            box.setItemData(box.count() - 1, f"{run.run_id}\n{run.root}", Qt.ItemDataRole.ToolTipRole)
        if len(self.runs) == 2:
            self.right_box.setCurrentIndex(1)
        self.run_list.setCurrentRow(len(self.runs) - 1)
        self.refresh_export()
        return run

    def load_samples(self):
        try:
            samples = sorted(path.parent for path in ASSETS.glob("*/manifest.json"))
            if len(samples) < 2:
                raise RunDataError("安装目录缺少两份公开样例。")
            runs = [self.add_run(path) for path in samples]
            left, right = (self.runs.index(run) for run in runs[:2])
            self.left_box.setCurrentIndex(left)
            self.right_box.setCurrentIndex(right)
            self.run_list.setCurrentRow(left)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "样例打开失败", str(exc))

    def show_run(self, row):
        run = self.current_run()
        if run is None:
            return
        self.status.setText(f"{run.run_id}  ·  {run.backend}  ·  {run.dataset}")
        self.summary.setText(f"运行任务：{run.task}\n结果目录：{run.root}")
        self.source_btn.setEnabled(self.public_source(run) is not None)
        self.open_dir_btn.setEnabled(True)
        status = run.manifest.get("status", "未记录")
        validation = run.validation.get("validation_status", run.validation.get(
            "status", run.manifest.get("validation_status", "未记录")))
        validation = {"unvalidated": "未经独立验证", "validated": "上游标记为已验证",
                      "not_performed": "未进行"}.get(validation, validation) if isinstance(validation, str) else validation
        populate(self.metadata, ("字段", "记录"), [
            ("运行标识", run.run_id), ("后端", run.backend), ("任务", run.task),
            ("数据集", run.dataset), ("运行状态", display(status)),
            ("独立验证状态", display(validation)), ("来源", run.source_url or "未记录"),
            ("结果类别", "公开历史条件" if run.manifest.get("source_kind") ==
             "public-historical-condition-view" else display(run.manifest.get("source_kind", "未记录"))),
            ("源表 / 图", f"{len(run.tables)} / {len(run.figures)}"),
        ])
        self.notes.setPlainText("\n\n".join(value for value in (run.notes, *run.warnings) if value))
        for box, paths in ((self.figure_box, run.figures), (self.table_box, run.tables)):
            with QSignalBlocker(box):
                box.clear()
                box.addItems([path.relative_to(run.root).as_posix() for path in paths])
        self.figure_source_btn.setEnabled(any(path.name == "figure_manifest.csv" for path in run.tables))
        self.show_figure(self.figure_box.currentIndex())
        self.show_table(self.table_box.currentIndex())
        self.show_parameters()
        self.show_artifact()

    def show_figure(self, index):
        self.figure_image.clear()
        run = self.current_run()
        if run is None or index < 0 or index >= len(run.figures):
            self.figure_info.setText("已保存的图与图表来源。")
            self.figure_image.setText("当前运行无可预览的图。可在「源表」中查看数值列。")
            return
        path = run.figures[index]
        self.figure_info.setText(str(path.relative_to(run.root)))
        formats = {".png": b"png", ".jpg": b"jpeg", ".jpeg": b"jpeg",
                   ".webp": b"webp", ".bmp": b"bmp", ".gif": b"gif"}
        if (image_format := formats.get(path.suffix.lower())) is None:
            self.figure_image.setText("该文件可从结果目录打开。当前内置预览支持 PNG、JPEG、WebP、BMP 和 GIF 首帧。")
            return
        try:
            safe_path = resolve_asset(run.root, path)
            if safe_path.stat().st_size > MAX_FIGURE_BYTES:
                raise RunDataError("图件超过 8 MiB，可在结果目录查看原件。")
            reader = QImageReader(str(safe_path), image_format)
            reader.setAutoDetectImageFormat(False)
        except (OSError, ValueError) as exc:
            self.figure_image.setText(f"预览失败：{exc}")
            return
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 24_000_000:
            self.figure_image.setText("图片尺寸超过预览限制或无法读取。")
            return
        pixmap = QPixmap.fromImage(reader.read())
        if pixmap.isNull():
            self.figure_image.setText("无法解码此图片。")
            return
        self.figure_image.setPixmap(pixmap.scaled(890, 560, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def open_figure_source(self):
        if run := self.current_run():
            index = next((i for i, path in enumerate(run.tables) if path.name == "figure_manifest.csv"), -1)
            if index >= 0:
                self.table_box.setCurrentIndex(index)
                self.tabs.setCurrentIndex(2)

    def show_table(self, index):
        self.preview = None
        self.column_box.clear()
        self.chart.set_points([])
        run = self.current_run()
        if run is None or not 0 <= index < len(run.tables):
            populate(self.data_table, (), ())
            self.table_info.setText("当前运行无源表。")
            return
        path = run.tables[index]
        try:
            self.preview = read_table(path, limit=600, root=run.root)
        except (OSError, ValueError) as exc:
            populate(self.data_table, (), ())
            self.table_info.setText(f"预览失败：{exc}")
            return
        populate(self.data_table, self.preview.headers, self.preview.rows)
        self.table_info.setText(f"{path.relative_to(run.root)} · 展示 {len(self.preview.rows)} 行"
                                + ("（预览已截断，完整文件保留在原目录）" if self.preview.truncated else ""))
        for col, title in enumerate(self.preview.headers):
            if any(self.numeric(row, col) is not None for row in self.preview.rows):
                self.column_box.addItem(title, col)

    @staticmethod
    def numeric(row, col):
        try:
            result = float(row[col])
        except (IndexError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def show_column(self, index):
        if self.preview is None or index < 0:
            self.chart.set_points([])
            return
        col = self.column_box.itemData(index)
        points = [(n, value) for n, row in enumerate(self.preview.rows, 1)
                  if (value := self.numeric(row, col)) is not None]
        self.chart.set_points(points)

    def show_parameters(self, _index=0):
        run = self.current_run()
        if run is None:
            return
        record = (run.parameters, run.manifest, run.validation, run.provenance)[self.doc_box.currentIndex()]
        self.parameters.setPlainText(json.dumps(record, indent=2, ensure_ascii=False) if record else "没有记录。")

    def comparison_pair(self):
        left, right = self.left_box.currentIndex(), self.right_box.currentIndex()
        if left >= 0 and right >= 0 and left != right:
            return self.runs[left], self.runs[right]
        return None

    def show_comparison(self, _index=0):
        pair = self.comparison_pair()
        self.refresh_export()
        if pair is None:
            self.compare_info.setText("打开两次运行后选择不同的左右运行。")
            populate(self.comparison_table, (), ())
            self.metric_title.hide()
            self.metric_table.hide()
            self.metric_notes.hide()
            return
        comparison = compare_runs(*pair)
        reasons = "；".join(comparison.reasons)
        left, right = pair
        shared_history = all(run.manifest.get("source_kind") == "public-historical-condition-view" for run in pair)
        batch = left.manifest.get("source_batch")
        history_note = " 同一历史批次中的两个条件，未独立重跑。" if (
            shared_history and batch and batch == right.manifest.get("source_batch")
        ) else ""
        self.compare_info.setText(("运行上下文可并列核对。" if comparison.compatible
                                   else "比较条件未确认一致。") + history_note + (f" {reasons}" if reasons else ""))
        metrics = comparison.metrics
        self.metric_title.setVisible(bool(metrics))
        self.metric_table.setVisible(bool(metrics))
        self.metric_notes.setText("；".join(comparison.metric_notes))
        self.metric_notes.setVisible(bool(comparison.metric_notes))
        if metrics:
            populate(self.metric_table, ("指标", "左侧", "右侧", "差值", "单位"),
                     [(row.name, row.left, row.right, f"{row.delta:+}", row.unit) for row in metrics])
            self.metric_table.setColumnWidth(0, 205)
        rows = [row for row in comparison.rows if row.changed or not self.differences_only.isChecked()]
        populate(self.comparison_table, ("字段", "左侧运行", "右侧运行", "差异"),
                 [(row.field, row.left, row.right, "不同" if row.changed else "相同") for row in rows])
        self.comparison_table.setColumnWidth(1, 246)
        self.comparison_table.setColumnWidth(2, 246)
        for index, row in enumerate(rows):
            if row.changed:
                self.comparison_table.item(index, 3).setBackground(QColor("#dceeea"))
                self.comparison_table.item(index, 3).setForeground(QColor("#0e5b50"))

    @staticmethod
    def public_source(run):
        url = QUrl(run.source_url, QUrl.ParsingMode.StrictMode)
        if url.isValid() and url.scheme() in {"http", "https"} and url.host() and not url.userInfo():
            return url
        return None

    def open_public_source(self):
        if (run := self.current_run()) and (url := self.public_source(run)):
            QDesktopServices.openUrl(url)

    def open_source_directory(self):
        if run := self.current_run():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(run.root)))

    def show_artifact(self, _index=0):
        run = self.current_run()
        if run is None:
            return
        index = self.artifact_box.currentIndex()
        if index == 0:
            text = run.report or "当前目录没有 report.md。"
        elif index == 1:
            text = run.errors_text or "当前目录未记录 errors.jsonl，或文件为空。"
        else:
            text = "\n".join(path.relative_to(run.root).as_posix() for path in run.raw_files)
            text = text or "当前目录没有可列出的 raw/ 文件。"
        self.report.setPlainText(text)

    def refresh_export(self, _index=0):
        compare = self.tabs.currentIndex() == 4
        self.export_btn.setText("导出对比报告…" if compare else "导出运行报告…")
        self.export_btn.setEnabled(bool(self.comparison_pair()) if compare else bool(self.runs))

    def choose_export(self):
        run = self.current_run()
        if run is None:
            return
        pair = self.comparison_pair() if self.tabs.currentIndex() == 4 else None
        path, _ = QFileDialog.getSaveFileName(self, "导出 HTML 复核报告",
                                             "Aper AI 运行对比.html" if pair else "Aper AI 运行报告.html",
                                             "HTML (*.html)")
        if not path:
            return
        try:
            saved = export_report(Path(path).with_suffix(".html"), *(pair or (run,)))
            self.status.setText(f"已导出报告：{saved}")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导出失败", str(exc))


def main():
    app = QApplication(sys.argv[:1])
    QImageReader.setAllocationLimit(128)
    app.setApplicationName(TITLE)
    app.setOrganizationName("Aper AI")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(ICON)))
    window = Workbench()
    window.show()
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        from smoke import run_smoke

        return run_smoke(app, window, Path(sys.argv[2]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
