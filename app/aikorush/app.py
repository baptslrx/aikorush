"""AikoRush : préparation des rushs (Mac, Windows, Linux)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from .ui import MainWindow


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for cand in (base / "assets" / name, base.parent / "assets" / name):
        if cand.exists():
            return cand
    return base / name


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("AikoRush")
    app.setOrganizationName("Aikographic")
    icon = resource("icon-256.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: win.apply_theme())
    win.show()
    # Dossiers passés en argument (ex. glissés sur l'icône de l'appli)
    paths = [Path(a) for a in sys.argv[1:] if Path(a).exists()]
    if paths:
        win.add_sources(paths)
    return app.exec()
