"""Вспомогательные элементы окна: цвета, шрифты, мелкие блоки.

Отдельный модуль, чтобы основное окно не распухало.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------- оформление

BG = "#1e1f22"
PANEL = "#26272b"
PANEL_ALT = "#2d2e33"
BORDER = "#3a3b41"
TEXT = "#e6e6e8"
TEXT_DIM = "#9a9ba1"
ACCENT = "#4c9aff"
ACCENT_DIM = "#2f5f9e"
OK = "#5fbf7f"
WARN = "#d9a441"
ERROR = "#e06c75"


def apply_dark_theme(app) -> None:
    """Тёмная тема окна — как в самой системе пользователя."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    app.setPalette(palette)

    app.setStyleSheet(
        f"""
        QWidget {{ font-size: 13px; }}
        QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px;
                            background: {PANEL}; }}
        QTabBar::tab {{ background: {BG}; color: {TEXT_DIM};
                        padding: 8px 18px; border: 1px solid {BORDER};
                        border-bottom: none;
                        border-top-left-radius: 6px;
                        border-top-right-radius: 6px; margin-right: 2px; }}
        QTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; }}
        QTabBar::tab:hover {{ color: {TEXT}; }}

        QListWidget {{ background: {PANEL}; border: 1px solid {BORDER};
                       border-radius: 6px; padding: 4px; outline: none; }}
        QListWidget::item {{ padding: 8px 10px; border-radius: 4px; }}
        QListWidget::item:selected {{ background: {ACCENT_DIM}; color: #ffffff; }}
        QListWidget::item:hover {{ background: {PANEL_ALT}; }}

        QLineEdit {{ background: {PANEL_ALT}; border: 1px solid {BORDER};
                     border-radius: 4px; padding: 6px 8px; color: {TEXT}; }}
        QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
        QLineEdit[bad="true"] {{ border: 1px solid {ERROR}; }}

        QPushButton {{ background: {PANEL_ALT}; border: 1px solid {BORDER};
                       border-radius: 4px; padding: 7px 16px; color: {TEXT}; }}
        QPushButton:hover {{ background: {BORDER}; }}
        QPushButton:disabled {{ color: {TEXT_DIM}; background: {PANEL}; }}
        QPushButton#primary {{ background: {ACCENT_DIM}; border-color: {ACCENT};
                               font-weight: 600; }}
        QPushButton#primary:hover {{ background: {ACCENT}; color: #ffffff; }}
        QPushButton#primary:disabled {{ background: {PANEL};
                                        border-color: {BORDER};
                                        color: {TEXT_DIM}; }}

        QPlainTextEdit {{ background: {BG}; border: 1px solid {BORDER};
                          border-radius: 6px; color: {TEXT};
                          font-family: Consolas, "Courier New", monospace; }}

        QGroupBox {{ border: 1px solid {BORDER}; border-radius: 6px;
                     margin-top: 10px; padding: 12px 10px 10px 10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px;
                            padding: 0 4px; color: {TEXT_DIM}; }}

        QCheckBox {{ color: {TEXT}; }}
        QRadioButton {{ color: {TEXT}; }}
        QLabel#hint {{ color: {TEXT_DIM}; }}
        QLabel#title {{ font-size: 17px; font-weight: 600; }}
        QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px;
                                       min-height: 24px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """
    )


def line() -> QFrame:
    """Тонкая разделительная линия."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.HLine)
    frame.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
    frame.setFixedHeight(1)
    return frame


def label(text: str, *, kind: str = "", wrap: bool = False) -> QLabel:
    """Подпись с нужным цветом и, при желании, переносом строк."""
    item = QLabel(text)
    if kind == "dim":
        item.setObjectName("hint")
    elif kind == "title":
        item.setObjectName("title")
    elif kind == "ok":
        item.setStyleSheet(f"color: {OK};")
    elif kind == "warn":
        item.setStyleSheet(f"color: {WARN};")
    elif kind == "error":
        item.setStyleSheet(f"color: {ERROR};")
    if wrap:
        item.setWordWrap(True)
    item.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    return item


class LogView(QPlainTextEdit):
    """Окошко для отчёта о ходе работы."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(140)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

    def add(self, text: str, tag: str = "info") -> None:
        color = {
            "info": TEXT,
            "dim": TEXT_DIM,
            "ok": OK,
            "warn": WARN,
            "error": ERROR,
        }.get(tag, TEXT)
        safe = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        self.appendHtml(f'<span style="color:{color}">{safe}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear_log(self) -> None:
        self.clear()


def row(*widgets, stretch_last: bool = False) -> QWidget:
    """Горизонтальный ряд элементов."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for index, widget in enumerate(widgets):
        if stretch_last and index == len(widgets) - 1:
            layout.addWidget(widget, 1)
        else:
            layout.addWidget(widget)
    return holder


def column(*widgets, spacing: int = 8) -> QWidget:
    """Вертикальный столбец элементов."""
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return holder
