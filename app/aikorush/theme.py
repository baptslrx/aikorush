"""Charte Aiko : noir ou blanc selon le système + bleu clair."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

ACCENT = QColor("#7DC8FF")
ON_ACCENT = QColor("#05121C")

DARK = dict(bg=QColor(10, 10, 12), surface=QColor("#17171A"), line=QColor(255, 255, 255, 23),
            text=QColor("#F5F7FA"), subtext=QColor("#8C949E"))
LIGHT = dict(bg=QColor(255, 255, 255), surface=QColor("#F2F7FC"), line=QColor(0, 0, 0, 20),
             text=QColor("#0A0D10"), subtext=QColor("#6B7380"))


def is_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except AttributeError:
        pass
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def theme() -> dict:
    return DARK if is_dark() else LIGHT


def css(c: QColor) -> str:
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha() / 255:.3f})"


def ui_font(px: float, weight: QFont.Weight = QFont.Weight.Normal, mono: bool = False) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont) if mono else QFont()
    f.setPixelSize(max(1, round(px)))
    f.setWeight(weight)
    return f
