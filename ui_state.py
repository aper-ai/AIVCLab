"""Small, injectable desktop preferences; result bundles remain untouched."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings


class UiState:
    MAX_RECENT = 8

    def __init__(self, settings: QSettings | None = None):
        self.settings = settings if settings is not None else QSettings("Aper AI", "Virtual Cell Workbench")

    def recent_paths(self) -> list[str]:
        value = self.settings.value("recent_runs", [])
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        return list(dict.fromkeys(path for path in value if isinstance(path, str) and path))[:self.MAX_RECENT]

    def remember_run(self, root: Path) -> None:
        path = str(root)
        recent = [path, *(item for item in self.recent_paths() if item != path)]
        self.settings.setValue("recent_runs", recent[:self.MAX_RECENT])
        self.settings.setValue("import_directory", str(root.parent))

    def clear_recent(self) -> None:
        self.settings.remove("recent_runs")

    def directory(self, kind: str) -> str:
        value = self.settings.value(f"{kind}_directory", "")
        return value if isinstance(value, str) else ""

    def remember_export(self, destination: Path) -> None:
        self.settings.setValue("export_directory", str(destination.parent))

    def sync(self) -> None:
        self.settings.sync()
