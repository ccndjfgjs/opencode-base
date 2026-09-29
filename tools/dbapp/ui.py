"""Оформление окна: палитра, шкала, шрифты, общие элементы.

Отдельный модуль, чтобы основное окно не росло и все числа вида
«какой рамкой обвести кнопку» жили в одном месте.

Устройство простым языком:
- ПОВЕРХНОСТИ — четыре слоя: фон окна, панель, поле ввода, карточка.
  Они отличаются ровно на один шаг, и глаз различает их сам.
- АКЦЕНТ задаёт РАЗДЕЛ, а не украшает. У базы он синий, у opencode
  бирюзовый, у оформления сиреневый, у справки янтарный. Видно, где
  находишься, не читая заголовок.
- ТЕКСТ — четыре уровня, а не два. Раньше подпись и пояснение были
  одного размера, и глаз не знал, что важнее.
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

# ------------------------------------------------------------- поверхности
# Каждая темнее предыдущей на один шаг. Если слои не различаются глазом,
# окно выглядит как одна серая масса.
BG = "#15171c"          # фон окна
PANEL = "#1b1e25"      # панель: поля, группы
PANEL_ALT = "#21252e"   # карточки и плашки поверх панели
FIELD = "#111318"      # поля ввода: темнее панели, чтобы «утоплены»
BORDER = "#2c313c"     # рамка обычная
BORDER_SOFT = "#242832"  # рамка внутри таблиц, слабее обычной

# ------------------------------------------------------------------- текст
TEXT = "#e8eaef"        # заголовки и значения
TEXT_2 = "#a3aab8"      # пояснения
TEXT_3 = "#6f7787"      # подписи, то, что человек не обязан читать

# ------------------------------------------------------- акценты по разделам
ACCENT = "#5b9cf5"     # База
ACCENT_OPEN = "#43c2ad"  # opencode
ACCENT_LOOK = "#9b8cf0"  # Оформление
ACCENT_HELP = "#e0a35c"  # Справка

OK = "#4fbf80"
WARN = "#d8a657"
ERROR = "#e2707a"

# ------------------------------------------------------------------- шкала
# Отступы кратны четырём. Раньше их задавали по месту и попадались 10, 12,
# 14 рядом друг с другом - глаз спотыкался.
S1, S2, S3, S4, S5 = 4, 8, 14, 22, 34
R_S, R_M, R_L = 5, 9, 13  # скругления: мелкий, средний, крупный

# Акцент раздела выбирается по имени раздела. Один словарь вместо
# разбросанных по окну цветов.
SECTION_ACCENT = {
    "base": ACCENT,
    "open": ACCENT_OPEN,
    "look": ACCENT_LOOK,
    "help": ACCENT_HELP,
}


def section_accent(key: str) -> str:
    return SECTION_ACCENT.get(key, ACCENT)


def apply_dark_theme(app) -> None:
    """Тёмная тема окна. Одна функция задаёт всё оформление."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(FIELD))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0d1117"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_3))
    app.setPalette(palette)

    app.setFont(app_font())

    app.setStyleSheet(
        f"""
        QWidget {{
            font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
            font-size: 14px;
            color: {TEXT};
        }}

        /* --- вкладки остаются как есть, но выглядят частью окна,
               а не набором кнопок. Боковая навигация придёт позже. */
        QTabWidget::pane {{
            border: 1px solid {BORDER}; border-radius: {R_M}px;
            background: {PANEL}; top: -1px;
        }}
        QTabBar::tab {{
            background: transparent; color: {TEXT_2};
            padding: 9px 18px; border: 1px solid transparent;
            border-bottom: 2px solid transparent;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            color: {TEXT}; border-bottom-color: {ACCENT};
        }}
        QTabBar::tab:hover {{ color: {TEXT}; }}

        /* --- кнопки: три роли, чтобы главное действие отличалось */
        QPushButton {{
            background: {PANEL_ALT}; border: 1px solid {BORDER};
            border-radius: {R_S}px; padding: 8px 15px; color: {TEXT_2};
        }}
        QPushButton:hover {{ background: {BORDER}; color: {TEXT}; }}
        QPushButton:pressed {{ background: {PANEL}; }}
        QPushButton:disabled {{ color: {TEXT_3}; background: {PANEL};
                                border-color: {BORDER_SOFT}; }}
        QPushButton#primary {{
            background: {ACCENT}; border-color: {ACCENT};
            color: #0d1117; font-weight: 600;
        }}
        QPushButton#primary:hover {{ background: #74acf7; color: #0d1117; }}
        QPushButton#primary:disabled {{
            background: {PANEL}; border-color: {BORDER};
            color: {TEXT_3};
        }}
        QPushButton#danger {{
            background: transparent; border-color: rgba(226,112,122,.45);
            color: {ERROR};
        }}
        QPushButton#danger:hover {{ background: rgba(226,112,122,.12); }}

        /* --- поля: темнее панели, чтобы читались как «утопленные» */
        QLineEdit, QPlainTextEdit, QTextEdit {{
            background: {FIELD}; border: 1px solid {BORDER};
            border-radius: {R_S}px; padding: 8px 11px; color: {TEXT};
            selection-background-color: {ACCENT};
            selection-color: #0d1117;
        }}
        QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
        QLineEdit[bad="true"] {{ border-color: {ERROR}; }}

        QPlainTextEdit#mono {{
            font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
            font-size: 13px;
        }}

        /* --- списки */
        QListWidget {{
            background: {PANEL}; border: 1px solid {BORDER};
            border-radius: {R_M}px; padding: {S1}px; outline: none;
        }}
        QListWidget::item {{
            padding: 9px 11px; border-radius: {R_S}px; color: {TEXT_2};
        }}
        QListWidget::item:selected {{ background: {PANEL_ALT}; color: {TEXT}; }}
        QListWidget::item:hover {{ background: {PANEL_ALT}; color: {TEXT}; }}

        /* --- таблица */
        QTableWidget {{
            background: {PANEL}; alternate-background-color: {PANEL_ALT};
            border: 1px solid {BORDER}; border-radius: {R_M}px;
            gridline-color: {BORDER_SOFT}; outline: none;
        }}
        QTableWidget::item {{ padding: 7px 9px; border: none; }}
        QTableWidget::item:selected {{ background: {PANEL_ALT}; color: {TEXT}; }}
        QHeaderView::section {{
            background: {FIELD}; color: {TEXT_3};
            border: none; border-bottom: 1px solid {BORDER};
            padding: 8px 9px; font-weight: 600;
        }}

        /* --- группы: рамка одна, она не лепит всё подряд в коробки */
        QGroupBox {{
            border: 1px solid {BORDER}; border-radius: {R_M}px;
            margin-top: {S3}px; padding: {S3}px {S3}px {S3}px {S3}px;
            background: {PANEL};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; left: {S3}px; padding: 0 {S1}px;
            color: {TEXT_2}; font-weight: 600;
        }}

        QCheckBox, QRadioButton {{ color: {TEXT}; spacing: 8px; }}
        /* Флажок и переключатель отличаются только формой углов:
           4 у флажка и 8 у переключателя. При 5 у обоих флажок
           становится кружком и отмеченное перестаёт читаться. */
        QCheckBox::indicator {{
            width: 15px; height: 15px;
            border: 1px solid {BORDER}; background: {FIELD};
            border-radius: 4px;
        }}
        QRadioButton::indicator {{
            width: 15px; height: 15px;
            border: 1px solid {BORDER}; background: {FIELD};
            border-radius: 8px;
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
            border-color: {ACCENT};
        }}
        QCheckBox::indicator:checked {{
            background: {ACCENT}; border-color: {ACCENT};
        }}
        /* У переключателя своё правило выбора. Без него Fusion
           перестаёт рисовать точку, и выбранный вариант становится
           неотличим от невыбранного - видно только на снимке. */
        QRadioButton::indicator:checked {{
            background: {ACCENT}; border-color: {ACCENT};
        }}
        QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
            background: {PANEL}; border-color: {BORDER_SOFT};
        }}

        /* --- четыре уровня текста вместо двух */
        QLabel#h1 {{
            font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
            font-size: 22px; font-weight: 600; color: {TEXT};
        }}
        QLabel#h2 {{
            font-size: 16px; font-weight: 600; color: {TEXT};
        }}
        QLabel#lead {{ color: {TEXT_2}; font-size: 14.5px; }}
        QLabel#hint {{ color: {TEXT_3}; font-size: 13px; }}
        QLabel#ok {{ color: {OK}; }}
        QLabel#warn {{ color: {WARN}; }}
        QLabel#error {{ color: {ERROR}; }}

        QScrollBar:vertical {{
            background: transparent; width: 11px; margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {BORDER}; border-radius: 5px; min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover {{ background: #3a4150; }}
        QScrollBar:horizontal {{
            background: transparent; height: 11px; margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background: {BORDER}; border-radius: 5px; min-width: 28px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

        QToolTip {{
            background: {PANEL_ALT}; color: {TEXT};
            border: 1px solid {BORDER}; padding: 5px 8px;
        }}
        """
    )


def app_font() -> QFont:
    """Шрифт окна: системный, с моноширинными цифрами.

    Моноширинные цифры нужны в столбцах чисел - иначе единицы и
    восьмёрки разной ширины и столбец «танцует».
    """
    font = QFont("Segoe UI Variable Text")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPointSizeF(10.5)
    return font


def mono_font(size: int = 13) -> QFont:
    """Моноширинный шрифт - только для путей, кода и чисел в столбцах."""
    font = QFont("Cascadia Mono")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(size * 0.75)
    return font


def line() -> QFrame:
    """Тонкая разделительная линия."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.HLine)
    frame.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
    frame.setFixedHeight(1)
    return frame


def label(text: str, *, kind: str = "", wrap: bool = False) -> QLabel:
    """Подпись нужного уровня и цвета.

    Уровни: h1 (заголовок раздела), h2 (название блока), lead (пояснение
    к разделу), hint (подпись, которую не обязательно читать).
    Раньше было два уровня, и глаз не различал главное и второстепенное.
    """
    # Алиасы: окно зовёт kind="title" и kind="dim" - имена из прежней
    # версии. Без них заголовки и подписи тихо теряют оформление, и
    # это видно только на снимке, не в коде.
    item = QLabel(text)
    kind = {"title": "h1", "sub": "h2", "dim": "hint"}.get(kind, kind)
    if kind in ("h1", "h2", "lead", "hint", "ok", "warn", "error"):
        item.setObjectName(kind)
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
        # По вертикали окно отчёта не растягивается. Раньше оно забирало
        # в себя всё лишнее место страницы и выглядело пустой рамкой
        # высотой в пол-экрана. Свою высоту держит, лишнее — колесо мыши.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFont(mono_font(13))

    def add(self, text: str, tag: str = "info") -> None:
        color = {
            "info": TEXT,
            "dim": TEXT_3,
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
    layout.setSpacing(S2)
    for index, widget in enumerate(widgets):
        if stretch_last and index == len(widgets) - 1:
            layout.addWidget(widget, 1)
        else:
            layout.addWidget(widget)
    return holder


def column(*widgets, spacing: int = S2) -> QWidget:
    """Вертикальный столбец элементов."""
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return holder
