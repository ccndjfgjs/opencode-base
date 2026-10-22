"""Вспомогательные элементы окна: цвета, шрифты, мелкие блоки.

Отдельный модуль, чтобы основное окно не распухало.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractButton,
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

# Дизайн-система «Управление базой» — тёмная тема в духе X/Twitter:
# почти чёрный фон, серые поверхности, один синий акцент (#1d9bf0).
# Иерархия — тоном поверхности и лёгкой границей, без теней.
BG = "#000000"          # база: окно, сайдбар, врезанные поля
PANEL = "#16181c"       # поверхности: панель вкладок, сайдбар
PANEL_ALT = "#1d1f23"   # приподнятый слой: поля ввода, кнопки, hover
CARD = "#16181c"        # карточки-группы внутри панели
BORDER = "#2f3336"
BORDER_LIGHT = "#3e4144"  # граница при наведении/фокусе
TEXT = "#e7e9ea"
TEXT_DIM = "#8b949e"
ACCENT = "#1d9bf0"
ACCENT_DIM = "#1a8cd8"
OK = "#00ba7c"
WARN = "#ffd400"
ERROR = "#f4212e"

# Окно у значка трея. Оно открывается поверх всего, поэтому рамка и тень
# обязательны: без рамки светлое содержимое уезжает на светлый рабочий
# стол и панель не читается как отдельное окно.
PANEL_QSS = f"""
#TrayPanel {{
    background: {PANEL};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
}}
/* Селектор намеренно не QWidget: правило по QWidget цепляется ко всем
   вложенным элементам, и каждая подпись в панели получала рамку с
   фоном — панель выглядела как таблица в рамках на каждой строке. */
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QPushButton {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 999px;
    padding: 3px 10px;
}}
QPushButton:hover {{ border-color: {BORDER_LIGHT}; background: {BORDER}; }}
QPushButton:pressed {{ background: {PANEL}; }}
/* Крестик закрытия. Без рамки: он не действие, а выход, и рамка на нём
   превращала бы его в такую же кнопку, как соседнюю, и тянула взгляд на
   пустое место. Цвет приглушённый: крестик заметен, но не спорит с
   заголовком панели. */
QPushButton#TrayPanelClose {{
    background: transparent;
    border: none;
    border-radius: 999px;
    color: {TEXT_DIM};
    padding: 0;
    font-size: 13px;
}}
QPushButton#TrayPanelClose:hover {{
    background: {PANEL_ALT};
    color: {TEXT};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}


"""


def app_icon() -> QIcon:
    """Значок программы — рисуется сам, файлов с картинками в ней нет.

    Три скруглённые «полки» с прорезью в каждой — образ базы данных:
    тот же значок встаёт и в заголовок окна, и в трей, и в уведомления
    Windows, поэтому выглядит везде одинаково.
    """
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gap = size * 0.09          # зазор между полками
        shelf_h = (size - 2 * gap) / 3.0
        width = size
        top = 0.0
        for _ in range(3):
            # сама полка
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(
                QRectF(0, top, width, shelf_h), shelf_h * 0.32, shelf_h * 0.32,
            )
            # прорезь — тёмная линия через середину полки
            painter.setBrush(QColor(BG))
            cut_h = max(1.0, size * 0.045)
            painter.drawRoundedRect(
                QRectF(width * 0.10, top + shelf_h / 2 - cut_h / 2,
                       width * 0.80, cut_h),
                cut_h / 2, cut_h / 2,
            )
            top += shelf_h + gap
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
        self.setWindowTitle("Управление базой")
        self.setWindowIcon(app_icon())
        # Селектор по имени: иначе стиль окна (фон, рамка) сходит и на
        # подписи внутри, и те обводятся рамками — выглядит как чертёж.
        self.setObjectName("splashWindow")
        self.setStyleSheet(
            f"QWidget#splashWindow {{ background: {BG};"
            f" border: 1px solid {BORDER}; border-radius: 24px; }}"
            f"QLabel {{ border: none; background: transparent; }}"
        )
        self.setFixedWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(14)
        badge = QLabel()
        # Логотип не тянет ни при каком размере окна: пропорции храним
        # (KeepAspectRatio), масштабируем плавно, больше оригинала не
        # растём (фиксированные 48x48) и рисуем по центру своей ячейки.
        # Без фиксации лейбл сжимался раскладкой на маленькой высоте окна
        # (на экране 150% меряно 48x28) и логотип срезался снизу.
        logo_pm = app_icon().pixmap(48, 48)
        # scaled() считает в физических пикселях: на экране с масштабом
        # 150% прямой scaled(48, 48) уменьшил бы логотип до 32. Поэтому
        # цель умножаем на плотность экрана и возвращаем ей DPR назад —
        # картинка остаётся 48x48 в логических пикселях при любой DPR.
        _dpr = logo_pm.devicePixelRatio() or 1.0
        logo_pm = logo_pm.scaled(
            round(48 * _dpr), round(48 * _dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        logo_pm.setDevicePixelRatio(_dpr)
        badge.setPixmap(logo_pm)
        badge.setScaledContents(False)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Размер метки считаем от самой картинки (в логических пикселях),
        # а не зашиваем: на любом масштабе Windows метка и картинка
        # совпадают, и логотип не срезается и не растягивается.
        _logo_w = round(logo_pm.width() / _dpr)
        _logo_h = round(logo_pm.height() / _dpr)
        badge.setFixedSize(_logo_w, _logo_h)
        badge.setStyleSheet("border: none; background: transparent;")
        head.addWidget(badge)
        title = QLabel("Управление базой")
        title.setStyleSheet(
            f"QLabel {{ color: {TEXT}; font-size: 22px; font-weight: 700;"
            " border: none; background: transparent; }"
        )
        head.addWidget(title)
        head.addStretch(1)
        layout.addLayout(head)
        self.percent = QLabel("")
        self.percent.setStyleSheet(
            f"QLabel {{ color: {TEXT_DIM}; font-size: 12px;"
            " border: none; background: transparent; }}"
        )
        self.step = QLabel("Запуск…")
        self.step.setStyleSheet(
            f"QLabel {{ color: {TEXT_DIM}; font-size: 13px;"
            " border: none; background: transparent; }}"
        )
        self.step.setWordWrap(True)
        # Шкала загрузки. Полоска идёт слева направо и показывает
        # пройденный путь по шагам: без неё надпись «Запуск…» ничего
        # не сообщала — непонятно, идёт дело или зависло.
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(
            f"QProgressBar {{ background: {PANEL}; border: none;"
            f" border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT};"
            " border-radius: 4px; }"
        )
        layout.addStretch(1)
        layout.addWidget(self.percent)
        layout.addWidget(self.step)
        layout.addSpacing(4)
        layout.addWidget(self.bar)
        # Высота — по содержимому. Прежние жёсткие 158px не вмещали шапку
        # с логотипом на экранах с масштабом 150% (меряно: содержимому
        # нужно 178), раскладка сжимала шапку и срезала логотип. Максимум
        # прежних 158 и собственных потребностей раскладки: на обычных
        # экранах размер остаётся прежним, на крупных растёт ровно
        # настолько, сколько нужно.
        self.setFixedHeight(max(158, self.sizeHint().height()))

    def say(self, text: str, percent: int | None = None) -> None:
        """Подписать шаг и сдвинуть шкалу."""
        self.step.setText(text)
        if percent is not None:
            value = max(0, min(100, int(percent)))
            self.bar.setValue(value)
            self.percent.setText(f"{value}%")
        for part in (self.step, self.bar, self.percent):
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
        self._panel = None
        self.setIcon(app_icon())
        self.setToolTip(
            "OpenCodeBase — левая кнопка открывает панель, "
            "правая — меню, двойная — окно")
        # Меню держим в поле: если отдать его только setContextMenu,
        # сборщик мусора вправе унести объект вместе с пунктами, и
        # правая кнопка перестанет открывать меню вовсе.
        self._menu = QMenu()
        self._menu.setToolTipsVisible(True)
        # Порядок меню: посмотреть, проверить, открыть панель, выход.
        #
        # Разделитель стоит ПЕРЕД «Закрыть программу», а не после неё.
        # add_action вставляет новые пункты перед разделителем, и стоял
        # бы он после выхода — все будущие пункты оказались бы ниже
        # «Закрыть программу», то есть после выхода из программы.
        # Разделитель отделяет выход от всего остального: это единственное
        # место в меню, где нажатие необратимо.
        self.act_open = self._menu.addAction("Открыть окно")
        self.act_check = self._menu.addAction("Проверить мосты")
        self.act_panel = self._menu.addAction("Открыть панель «Подключено»")
        self.menu_extra = self._menu.addSeparator()
        self.menu_extra.setText("Дальше — служебное")
        self.act_quit = self._menu.addAction("Закрыть программу")
        self.act_open.triggered.connect(self.show_window)
        self.act_check.triggered.connect(self.check_bridges)
        self.act_panel.triggered.connect(self.show_panel)
        self.act_quit.triggered.connect(self.quit_program)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self._hinted = False

    @property
    def panel(self):
        """Панель трея. Создаётся в первый раз, дальше просто показывается.

        Панель сама запоминает себя на окне (tray_panel._attach), поэтому
        кнопки внутри неё находят её независимо от трея: тот появляется
        не сразу и может быть вовсе выключен.
        """
        if self._panel is None:
            from tray_panel import TrayPanel  # локальный импорт: цикл

            self._panel = TrayPanel(self._window)
        return self._panel

    def add_action(self, text: str, handler) -> object:
        """Добавить пункт в меню трея. Для будущих функций.

        Вставляет перед строкой-разделителем, а значит перед «Закрыть
        программу»: выход остаётся последним и всегда на своём месте.
        """
        action = QAction(text, self._menu)
        action.triggered.connect(handler)
        self._menu.insertAction(self.menu_extra, action)
        return action

    def show_panel(self) -> None:
        """Открыть панель «Подключено» из меню.

        Тот же вход, что и левая кнопка по значку: одна и та же панель,
        одна и та же проверка внутри. Второй способ открыть её нужен
        потому, что левая кнопка не всегда под рукой: на узком экране
        значок сворачивается в Overflow, и до него не добраться, не
        вываливаясь с панели задач.
        """
        self.panel.toggle()

    def _on_activated(self, reason) -> None:
        # Левая кнопка открывает панель «что подключено». Раньше она
        # открывала главное окно, но по этому окно и находилось в трее,
        # а состояние мостов и серверов было видно только через четыре
        # разных вкладки. Двойная кнопка по-прежнему открывает окно.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.panel.toggle()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    def show_window(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def refresh_state(self) -> None:
        """Перечитать состояние без живой проверки.

        Отдельный ход от «Проверить мосты»: он ничего не запускает
        и потому мгновенный. Оставлен как публичный метод — им пользуется
        панель и код, который просто хочет освежить список.
        """
        refresh = getattr(self._window, "refresh_now", None)
        if callable(refresh):
            refresh()
        # Открытая панель обязана перечитать состояние тем же жестом:
        # иначе «Обновить» в меню обновлял окно, а панель рядом показывала
        # прошлый список и выглядела сломанной.
        if self._panel is not None and self._panel.isVisible():
            self._panel.refresh()

    def check_bridges(self) -> None:
        """Живая проверка мостов и серверов из меню трея.

        Зовёт тот же код, что кнопка «Проверить» в панели, и ждёт конца:
        до него состояние прежнее, и человек увидел бы «не проверено»
        сразу после нажатия. Проверка идёт в рабочем потоке и занимает
        около секунды на этой машине, так что результат стоит дождаться.
        """
        from tray_panel import run_check  # локальный импорт: цикл

        run_check(self._window)

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
        # Панель у значка держится отдельно от окна, и без этого осталась
        # бы висеть на экране после выхода — значок убрали, а панель нет.
        if self._panel is not None:
            self._panel.hide()
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
        #sidebar {{
            background: {BG};
            border-right: 1px solid {BORDER};
        }}
        QPushButton#nav {{
            background: transparent;
            border: none;
            border-radius: 999px;
            color: {TEXT};
            text-align: left;
            padding: 5px 12px;
        }}
        QPushButton#nav:hover {{ background: {PANEL_ALT}; }}
        QPushButton#nav:checked {{
            background: {ACCENT};
            color: #ffffff;
            font-weight: 700;
        }}
        /* Подменю категорий мостов: мельче основного меню и без плашки,
           чтобы не спорить с выбранным разделом. */
        QPushButton#subnav {{
            background: transparent;
            border: none;
            border-radius: 999px;
            color: {TEXT_DIM};
            text-align: left;
            padding: 2px 10px;
            font-size: 11px;
        }}
        QPushButton#subnav:hover {{ background: {PANEL_ALT}; color: {TEXT}; }}
        QPushButton#subnav:checked {{
            color: {ACCENT};
            font-weight: 700;
            background: transparent;
        }}
        /* Значок подсказки: маленькая серая «i», полный текст в тултипе. */
        QLabel#infoDot {{
            color: {TEXT_DIM};
            font-size: 14px;
            padding: 0 4px;
        }}
        /* Спойлер внутри карточки: без рамки и фона, только стрелка. */
        QToolButton#cardSpoiler {{
            background: transparent;
            border: none;
            border-radius: 6px;
            padding: 2px 4px;
            color: {TEXT_DIM};
            font-size: 12px;
            font-weight: 600;
            text-align: left;
        }}
        QToolButton#cardSpoiler:hover {{ color: {ACCENT}; }}
        QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 16px;
                            background: {PANEL}; }}
        QTabBar::tab {{ background: {BG}; color: {TEXT_DIM};
                        padding: 8px 18px; border: 1px solid {BORDER};
                        border-bottom: none;
                        border-top-left-radius: 10px;
                        border-top-right-radius: 10px; margin-right: 2px; }}
        QTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; }}
        QTabBar::tab:hover {{ color: {TEXT}; }}

        QListWidget {{ background: {BG}; border: 1px solid {BORDER};
                       border-radius: 12px; padding: 4px; outline: none; }}
        QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
        QListWidget::item:selected {{ background: {ACCENT}; color: #ffffff; }}
        QListWidget::item:hover {{ background: {PANEL_ALT}; }}

        QLineEdit {{ background: {BG}; border: 1px solid {BORDER};
                     border-radius: 8px; padding: 7px 12px; color: {TEXT};
                     selection-background-color: {ACCENT}; }}
        QLineEdit:hover {{ border: 1px solid {BORDER_LIGHT}; }}
        QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
        QLineEdit:disabled {{ color: {TEXT_DIM}; background: {PANEL}; }}
        QLineEdit[bad="true"] {{ border: 1px solid {ERROR}; }}

        QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {BG}; border: 1px solid {BORDER};
            border-radius: 8px; padding: 6px 12px; color: {TEXT};
        }}
        QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
            border: 1px solid {BORDER_LIGHT};
        }}
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {ACCENT};
        }}
        QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
            color: {TEXT_DIM}; background: {PANEL};
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{
            background: {PANEL_ALT}; border: 1px solid {BORDER_LIGHT};
            border-radius: 8px; padding: 4px;
            selection-background-color: {ACCENT};
            selection-color: #ffffff; outline: none;
        }}

        QPushButton {{ background: {PANEL_ALT}; border: 1px solid {BORDER};
                       border-radius: 999px; padding: 7px 18px; color: {TEXT}; }}
        QPushButton:hover {{ background: {BORDER}; border-color: {BORDER_LIGHT}; }}
        QPushButton:pressed {{ background: {PANEL}; }}
        QPushButton:disabled {{ color: {TEXT_DIM}; background: {PANEL}; }}
        QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT};
                               color: #ffffff; font-weight: 700; }}
        QPushButton#primary:hover {{ background: {ACCENT_DIM}; border-color: {ACCENT_DIM};
                                     color: #ffffff; }}
        QPushButton#primary:disabled {{ background: {PANEL};
                                        border-color: {BORDER};
                                        color: {TEXT_DIM}; }}
        QPushButton#ghost {{ background: transparent; border: 1px solid {ACCENT};
                             color: {ACCENT}; font-weight: 600; }}
        QPushButton#ghost:hover {{ background: rgba(29, 155, 240, 0.12); }}
        QPushButton#ghost:disabled {{ background: transparent;
                                      border-color: {BORDER};
                                      color: {TEXT_DIM}; }}
        /* Опасное действие: красная рамка и красный текст, заливка
           только при наведении. Стоит отдельно от безопасных кнопок. */
        QPushButton#danger {{
            background: transparent;
            border: 1px solid {ERROR};
            color: {ERROR};
            font-weight: 600;
        }}
        QPushButton#danger:hover {{
            background: rgba(244, 33, 46, 0.12);
            color: {ERROR};
        }}
        QPushButton#danger:disabled {{
            background: transparent;
            border-color: {BORDER};
            color: {TEXT_DIM};
        }}

        QToolButton {{ background: {CARD}; border: 1px solid {BORDER};
                       border-radius: 12px; padding: 12px 16px;
                       color: {TEXT}; text-align: left;
                       font-size: 14px; font-weight: 600; }}
        QToolButton:hover {{ border-color: {BORDER_LIGHT}; background: {PANEL_ALT}; }}
        QToolButton:pressed {{ background: {PANEL_ALT}; }}

        QPlainTextEdit {{ background: {BG}; border: 1px solid {BORDER};
                          border-radius: 12px; color: {TEXT};
                          padding: 6px;
                          font-family: Consolas, "Courier New", monospace; }}

        /* Карточка секции: заголовок стоит СНАРУЖИ рамки, отдельной
           строкой над ней. Раньше он рисовался в полосе margin впритык
           к границе, и текст визуально врезался в блок. */
        QGroupBox {{ background: {CARD};
                     border: 1px solid {BORDER}; border-radius: 16px;
                     margin-top: 30px; padding: 16px 14px 14px 14px; }}
        QGroupBox::title {{ subcontrol-origin: margin;
                            subcontrol-position: top left;
                            left: 2px; top: 0;
                            padding: 0;
                            color: {TEXT};
                            font-size: 14px; font-weight: 700; }}
        /* Карточка программы: имя стоит внутри, заголовка у рамки нет. */
        QGroupBox#programCard {{ margin-top: 0; padding: 16px; }}

        QCheckBox {{ color: {TEXT}; spacing: 8px; }}
        QRadioButton {{ color: {TEXT}; spacing: 8px; }}

        QToolTip {{ background: {PANEL_ALT}; color: {TEXT};
                    border: 1px solid {BORDER_LIGHT};
                    border-radius: 8px; padding: 6px 10px; }}

        QProgressBar {{
            background: {BORDER};
            border: none;
            border-radius: 5px;
            text-align: center;
            color: {TEXT_DIM};
        }}
        QProgressBar::chunk {{
            background: {ACCENT};
            border-radius: 5px;
        }}

        QTableWidget {{
            background: {BG};
            alternate-background-color: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 12px;
            gridline-color: {BORDER};
            selection-background-color: {ACCENT};
            selection-color: #ffffff;
            font-size: 12px;
        }}
        QTableWidget::item {{ padding: 4px 6px; }}
        QTableWidget::item:selected {{ color: #ffffff; }}
        QHeaderView::section {{
            background: {PANEL};
            color: {TEXT_DIM};
            border: none;
            border-bottom: 1px solid {BORDER};
            padding: 6px 6px;
            font-weight: 600;
            text-align: left;
        }}

        QLabel#hint {{ color: {TEXT_DIM}; }}
        QLabel#title {{ font-size: 20px; font-weight: 700; }}
        QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px;
                                       min-height: 24px; }}
        QScrollBar::handle:vertical:hover {{ background: {BORDER_LIGHT}; }}
        QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px;
                                         min-width: 24px; }}
        QScrollBar::handle:horizontal:hover {{ background: {BORDER_LIGHT}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
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


class FlowRow(QWidget):
    """Ряд элементов, который переносится на следующую строку сам.

    Обычный QHBoxLayout не переносится. Когда ряд не помещается, Qt не
    переносит кнопки на следующую строку, а сжимает их, и подписи
    обрезаются. Измерено на вкладке «Программы»: кнопке «Проверить
    обновление» при окне 895 досталось 125 пикселей вместо 160, и
    человек видел «Проверить обновле…».

    Здесь строки пересобираются при каждой смене ширины: что не
    поместилось — уходит на следующую строку целиком. Разбивка идёт по
    настоящей ширине элемента (sizeHint), а не по минимальной: если
    мерить по минимальной, ряд снова схлопнется и подписи срежутся.

    Последняя строка добивается растягивателем до края, иначе кнопки
    висели бы сбоку без причины.
    """

    def __init__(self, parent=None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._labels: list[QWidget] = []
        self._rows: list[QWidget] = []
        self._spacing = spacing
        self._last_width = -1
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(spacing)
        # Ряд сам решает, сколько ему строк, поэтому по высоте он
        # занимает ровно столько, сколько занял, а по ширине не должен
        # требовать больше, чем есть.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )

    def add(self, widget: QWidget) -> QWidget:
        """Добавляет элемент в ряд. Возвращает его же — для цепочек."""
        self._items.append(widget)
        self._last_width = -1
        self._reflow()
        return widget

    def setLabels(self, labels: list[QWidget]) -> None:
        """Задаёт подписи, которые всегда остаются на первой строке.

        Это имя блока слева от кнопок: на следующую строку оно уходить
        не должно, иначе кнопки окажутся без своего названия. Ширина
        подписи входит в счёт первой строки — иначе ряд решит, что
        поместилось больше, чем на самом деле есть места.
        """
        self._labels = list(labels)
        self._last_width = -1

    def count(self) -> int:
        """Сколько элементов в ряду."""
        return len(self._items)

    def _row_at(self, index: int) -> QWidget:
        while len(self._rows) <= index:
            holder = QWidget()
            holder.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
            )
            inner = QHBoxLayout(holder)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(self._spacing)
            self.layout().addWidget(holder)
            self._rows.append(holder)
        return self._rows[index]

    def _reflow(self, force: bool = False) -> None:
        width = self.width()
        if width <= 0:
            return
        if not force and width == self._last_width:
            return
        self._last_width = width
        # Сначала вынимаем всё из прежних строк: при переносе элемент
        # должен уйти в новую строку целиком, а не остаться в старой.
        for holder in self._rows:
            inner = holder.layout()
            while inner.count():
                inner.takeAt(0)
        rows_used = 0

        def start_row() -> tuple[QWidget, int]:
            """Заводит новую строку. Первая сразу получает подписи."""
            nonlocal rows_used
            holder = self._row_at(rows_used)
            rows_used += 1
            holder.setVisible(True)
            taken = 0
            if rows_used == 1:
                for label in self._labels:
                    holder.layout().addWidget(label)
                    taken += (self._spacing if taken else 0)
                    taken += label.sizeHint().width()
            return holder, taken

        current, used = start_row()
        for widget in self._items:
            need = widget.sizeHint().width()
            if used and used + self._spacing + need > width:
                current, used = start_row()
            current.layout().addWidget(widget)
            used += (self._spacing if used else 0) + need
        if current is not None:
            current.layout().addStretch(1)
        for index in range(rows_used, len(self._rows)):
            self._rows[index].setVisible(False)
        self.layout().activate()

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self._reflow()

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        self._reflow(force=True)


def wrap_button_rows(root: QWidget) -> int:
    """Заменяет ряды из одних кнопок на переносящиеся. Возвращает, сколько.

    Ряды кнопок в программе собраны обычными QHBoxLayout — их много, и
    переписывать каждый вручную бессмысленно: при другой ширине окна
    поедут другие ряды. Общее правило надёжнее: любой ряд, где лежат
    только кнопки (плюс растягиватели), перестаёт сжимать подписи и
    переносит не поместившееся на следующую строку.

    Измерено на вкладке opencode при окне 720, минимальном для
    программы: таких рядов было 8, и подписи обрезались с двух сторон —
    «Проверить окруже|», «збрать greenligh|t», «ить iOS-прилож|».

    Ряд заменяется на FlowRow один раз: пометка на самом layout
    защищает от повторной переделки при каждой смене ширины.
    """
    changed = 0
    for layout in list(root.findChildren(QHBoxLayout)):
        if layout.parent() is None:
            continue
        if layout.property("flow_ready"):
            continue
        labels: list[QWidget] = []
        buttons: list[QWidget] = []
        plain = True
        seen_button = False
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.spacerItem() is not None:
                continue
            widget = item.widget()
            if widget is None:
                plain = False
                break
            if isinstance(widget, QAbstractButton):
                seen_button = True
                buttons.append(widget)
            elif isinstance(widget, QLabel) and not seen_button:
                # Подпись слева от кнопок — имя того, что переключают.
                # На новые строки она не уходит: иначе карточка перестаёт
                # читаться, имя оказывается в стороне от своих кнопок.
                labels.append(widget)
            else:
                plain = False
                break
        # Ряд из одной кнопки переносить некуда, и пустой — не дело.
        if not plain or len(buttons) < 2:
            continue
        parent_layout = layout.parent()
        position = -1
        for index in range(parent_layout.count()):
            if parent_layout.itemAt(index).layout() is layout:
                position = index
                break
        if position < 0:
            continue
        layout.setProperty("flow_ready", True)
        row = FlowRow()
        row.setLabels(labels)
        for button in buttons:
            row.add(button)
        # Элементы переедут в новый ряд сами: у виджета может быть только
        # одна раскладка. Старый ряд вынимаем и убираем — иначе он
        # продолжит держать страницу широкой.
        parent_layout.takeAt(position)
        layout.deleteLater()
        parent_layout.insertWidget(position, row)
        changed += 1
    return changed


def flow_row(*widgets: QWidget, spacing: int = 8) -> FlowRow:
    """Ряд, который сам переносится на следующую строку."""
    holder = FlowRow(spacing=spacing)
    for widget in widgets:
        holder.add(widget)
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


def open_link(url: str) -> bool:
    """Открыть адрес в браузере по умолчанию. True — браузер принял.

    Живёт здесь, а не в модулях мостов, потому что это действие вида:
    им пользуются и главное окно, и панель трея, и второе место не
    должно заводить свою копию.

    Почему `QDesktopServices`, а не `webbrowser.open`. Программа
    работает на pythonw — у неё самой консоли нет, и Windows на каждый
    запуск внешней программы открывает чёрное окно. `webbrowser.open`
    запускает процесс; `QDesktopServices` обращается к системе и
    окна не создаёт. Разница видна была прямо на экране 19.10.2026.

    Адрес проверяется ДО передачи: `QDesktopServices` откроет что
    угодно, включая `file://` и `javascript:`. Здесь нужны только
    `http` и `https` — локальная панель моста и обычные сайты.
    """
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    text = str(url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return False
    return bool(QDesktopServices.openUrl(QUrl(text)))
