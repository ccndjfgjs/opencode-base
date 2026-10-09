"""Вспомогательные элементы окна: цвета, шрифты, мелкие блоки.

Отдельный модуль, чтобы основное окно не распухало.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QSystemTrayIcon,
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


def app_icon() -> QIcon:
    """Значок программы — рисуется сам, файлов с картинками в ней нет.

    Рисуем скруглённый квадрат в акцентном цвете с белой полосой
    «корешка папки»: тот же значок встаёт и в заголовок окна, и в трей,
    и в уведомления Windows, поэтому выглядит везде одинаково.
    """
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        margin = size * 0.08
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(
            QRectF(margin, margin, size - 2 * margin, size - 2 * margin),
            size * 0.22, size * 0.22,
        )
        # полоса «папки» — единственная деталь, читаемая и в 16 пикселей
        painter.setBrush(QColor("#ffffff"))
        left = size * 0.26
        painter.drawRect(
            QRectF(left, size * 0.30, size * 0.48, max(1.0, size * 0.10))
        )
        painter.drawRect(
            QRectF(left, size * 0.48, size * 0.34, max(1.0, size * 0.10))
        )
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class SplashWindow(QWidget):
    """Окно загрузки: пока программа просыпается, видно, что идёт работа.

    Раньше на экране было окно консоли cmd, которое потом исчезало, и
    человек не понимал, запустилась программа или нет. Теперь вместо
    него — понятная надпись с названием и текущим шагом.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Управление базой")
        self.setWindowIcon(app_icon())
        self.setFixedSize(360, 158)
        # Селектор по имени: иначе стиль окна (фон, рамка) сходит и на
        # подписи внутри, и те обводятся рамками — выглядит как чертёж.
        self.setObjectName("splashWindow")
        self.setStyleSheet(
            f"QWidget#splashWindow {{ background: {PANEL};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
            f"QLabel {{ border: none; background: transparent; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        title = QLabel("Управление базой")
        title.setStyleSheet(
            f"QLabel {{ color: {TEXT}; font-size: 15px; font-weight: 600;"
            " border: none; background: transparent; }"
        )
        self.step = QLabel("Запуск…")
        self.step.setStyleSheet(
            f"QLabel {{ color: {TEXT_DIM}; font-size: 12px;"
            " border: none; background: transparent; }"
        )
        self.step.setWordWrap(True)
        # Шкала загрузки. Полоска идёт слева направо и показывает
        # пройденный путь по шагам: без неё надпись «Запуск…» ничего
        # не сообщала — непонятно, идёт дело или зависло.
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(
            f"QProgressBar {{ background: {PANEL_ALT}; border: none;"
            f" border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT};"
            " border-radius: 3px; }"
        )
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(self.step)
        layout.addSpacing(2)
        layout.addWidget(self.bar)

    def say(self, text: str, percent: int | None = None) -> None:
        """Подписать шаг и сдвинуть шкалу.

        Здесь намеренно НЕ processEvents. Сначала стоял именно он, и он
        стоил четыре секунды запуска: очередь событий прогоняла
        перерисовку полусобранного главного окна, а шагов десять.
        Измерено: MainWindow() 2.9 с в покое против 7.1 с с очередью
        событий на каждом шаге. Надпись и полосу достаточно перерисовать
        точечно — очередь крутить не нужно.
        """
        self.step.setText(text)
        if percent is not None:
            self.bar.setValue(max(0, min(100, int(percent))))
        for part in (self.step, self.bar):
            part.repaint()


class TrayIcon(QSystemTrayIcon):
    """Значок в трее: окно сворачивается туда вместо закрытия.

    Закрывать программу крестиком больше нельзя — иначе она исчезает
    вместе с окном, а мосты, которые она подняла, продолжают работать.
    Выход — в меню значка, и он единственный.
    """

    def __init__(self, parent, window) -> None:
        super().__init__(parent)
        self._window = window
        self.setIcon(app_icon())
        self.setToolTip("OpenCodeBase — правая кнопка открывает меню")
        # Меню держим в поле: если отдать его только setContextMenu,
        # сборщик мусора вправе унести объект вместе с пунктами, и
        # правая кнопка перестанет открывать меню вовсе.
        self._menu = QMenu()
        self._menu.setToolTipsVisible(True)
        # Пункты-разделители помечены, чтобы следующие функции легко
        # встали в своё место, не переписывая это место целиком.
        self.act_open = self._menu.addAction("Открыть окно")
        self.act_refresh = self._menu.addAction("Обновить состояние")
        self.menu_extra = self._menu.addSeparator()
        self.menu_extra.setText("Дальше — служебное")
        self.menu_extra.setEnabled(False)
        self.act_quit = self._menu.addAction("Закрыть программу")
        self.act_open.triggered.connect(self.show_window)
        self.act_refresh.triggered.connect(self.refresh_state)
        self.act_quit.triggered.connect(self.quit_program)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self._hinted = False

    def add_action(self, text: str, handler) -> object:
        """Добавить пункт в меню трея. Для будущих функций.

        Вставляет перед строкой-разделителем, чтобы «Закрыть
        программу» оставалась последней и всегда на своём месте.
        """
        action = QAction(text, self._menu)
        action.triggered.connect(handler)
        self._menu.insertAction(self.menu_extra, action)
        return action

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def refresh_state(self) -> None:
        refresh = getattr(self._window, "refresh_now", None)
        if callable(refresh):
            refresh()

    def quit_program(self) -> None:
        """Закрыть программу по-настоящему, а не свернуть в трей.

        Порядок здесь важен в первую очередь для зависшей программы.
        Раньше значок трея при этом исчезал: закрыли окно — и на экране
        не осталось ни окна, ни значка, то есть выключить программу
        было уже нечем. Именно это и случилось: человек жал крестик и
        не мог её закрыть. Поэтому значок убираем последним и только
        если окно действительно закрылось.

        Если окно не закрылось (программа занята и не отвечает) —
        значок остаётся на месте, и выход есть снова: правая кнопка
        по нему и «Закрыть программу».
        """
        self._window.tray_quitting = True
        self._window.close()
        if not self._window.isVisible():
            self.hide()

    def hide_to_tray(self) -> None:
        """Свернуть окно в трей и один раз сказать, как выйти."""
        self._window.hide()
        if not self._hinted:
            self._hinted = True
            self.showMessage(
                "Управление базой свёрнуто в трей",
                "Окно вернётся двойным щелчком по значку. "
                "Закрыть программу: правый клик по значку → «Выход».",
                QSystemTrayIcon.MessageIcon.Information, 6000,
            )


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
    """Окошко для отчёта о ходе работы.

    Пока отчёта нет, занимает минимум и показывает подсказку. Раньше у
    него был задан только минимум, и Qt отдавал ему всё свободное место
    страницы: под кнопками появлялся огромный пустой ящик во весь экран.
    Теперь пустой журнал не занимает место, а по первой же записи
    разворачивается — и остаётся достаточно высоким, чтобы читать.
    """

    #: Высота пустого журнала и развёрнутого. Развёрнутый не растёт
    #: бесконечно: длинный вывод прокручивается, но страницу не тянет.
    EMPTY_HEIGHT = 170
    OPEN_HEIGHT = 320

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(140)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setPlaceholderText(
            "Журнал пока пуст — здесь появятся результаты проверок."
        )
        self.setMaximumHeight(self.EMPTY_HEIGHT)

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
        if not self.toPlainText().strip():
            self.setMaximumHeight(self.OPEN_HEIGHT)
        self.appendHtml(f'<span style="color:{color}">{safe}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear_log(self) -> None:
        self.clear()
        self.setMaximumHeight(self.EMPTY_HEIGHT)


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
