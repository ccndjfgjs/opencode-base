"""Боковая навигация вместо вкладок.

Зачем это вместо QTabWidget:
- Шесть вкладок читаются как «список кнопок», между которыми надо
  помнить, где находишься. Боковая колонка с подписью под названием
  отвечает на вопрос «что здесь будет» до того, как человек нажал.
- Разделы собираются в группы, поэтому шесть пунктов выглядят как
  четыре раздела, а не как шесть равноправных кнопок.
- Акцент у каждого пункта свой: видно, где находишься, не читая заголовок.

Совместимость с вкладками: класс умеет всё, что нужно остальному коду
от QTabWidget — addTab, count, tabText, currentIndex, setCurrentIndex,
widget. Поэтому переход на боковую навигацию не трогает ни одну
проверку в selftest.py и ни одного вызова tabs.setCurrentIndex(...).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import ui
from ui_status import StatusBar

NAV_WIDTH = 214


def nav_qss() -> str:
    """Оформление боковой колонки. Отдельной функцией, чтобы панель
    не зависела от общей темы и её можно было бы снять одним вызовом."""
    return f"""
    QFrame#nav {{
        background: {ui.PANEL};
        border: 1px solid {ui.BORDER};
        border-radius: {ui.R_M}px;
    }}
    QLabel#navgroup {{
        color: {ui.TEXT_3};
        font-size: 10.5px;
        font-weight: 700;
        letter-spacing: 1.1px;
        padding: {ui.S3}px {ui.S2}px {ui.S1}px {ui.S3}px;
        background: transparent;
    }}
    QToolButton#navitem {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {ui.R_S}px;
        padding: 0;
        text-align: left;
    }}
    QToolButton#navitem:hover {{
        background: {ui.PANEL_ALT};
        border-color: {ui.BORDER_SOFT};
    }}
    QToolButton#navitem:checked {{
        background: {ui.PANEL_ALT};
        border-color: {ui.BORDER};
    }}
    QToolButton#navitem:focus {{ border-color: {ui.ACCENT}; }}
    QLabel#navtitle {{
        color: {ui.TEXT_2};
        font-size: 14px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel#navsub {{
        color: {ui.TEXT_3};
        font-size: 11.5px;
        background: transparent;
    }}
    QFrame#navbar {{
        background: transparent;
        border-top-left-radius: 1px;
        border-bottom-left-radius: 1px;
    }}
    """


class NavItem(QToolButton):
    """Пункт навигации: полоса-акцент, название и короткая подпись.

    Полоса слева — единственный элемент, который меняет цвет при выборе.
    Она короче и тоньше подписи, поэтому взгляд цепляется за неё, а не за
    весь прямоугольник.
    """

    def __init__(self, title: str, subtitle: str, accent: str) -> None:
        super().__init__()
        self.setObjectName("navitem")
        self.setCheckable(True)
        # autoExclusive выключен намеренно. Он снимает отметку с прежнего
        # пункта внутри Qt, мимо нашего кода, и полоса прежнего пункта
        # остаётся гореть. Отметками управляет NavStack: он и снимает, и
        # красит, поэтому состояние видно всегда и живёт в одном месте.
        self.setAutoExclusive(False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(48)
        self.setToolTip(f"{title} — {subtitle}" if subtitle else title)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.bar = QFrame()
        self.bar.setObjectName("navbar")
        self.bar.setFixedWidth(3)
        row.addWidget(self.bar, 0)

        text = QVBoxLayout()
        text.setContentsMargins(11, 7, 9, 7)
        text.setSpacing(1)
        self.title_label = ui.label(title, kind="")
        self.title_label.setObjectName("navtitle")
        text.addWidget(self.title_label)
        if subtitle:
            sub = ui.label(subtitle, kind="")
            sub.setObjectName("navsub")
            sub.setWordWrap(True)
            text.addWidget(sub)
        row.addLayout(text, 1)

        self._accent = accent
        self._apply()

    def nextCheckState(self) -> None:  # noqa: N802 - имя Qt
        """Запретить самопереключение флажка.

        Отметка здесь — часть оформления, а не состояние: пункту нельзя
        «снять галочку», на него можно только перейти. Без этого клик по
        уже открытому разделу гасил его полосу, и человек видел, что
        раздел открыт, но не выбран.
        """

    def setChecked(self, value: bool) -> None:  # noqa: N802 - имя Qt
        """Перекрашивать пункт при любом снятии флажка, а не только при
        установке.

        Причина. Флажки помечены autoExclusive, и когда выбирают новый
        пункт, Qt сам снимает отметку с прежнего — вызывает setChecked
        напрямую, мимо нашего кода. Раньше покраска жила только в
        setCurrentIndex, поэтому полоса прошлого пункта навсегда
        оставалась гореть: на снимке это выглядело как «выбраны два
        раздела сразу».
        """
        super().setChecked(value)
        self._apply()

    def _apply(self) -> None:
        """Перекрасить полосу: у выбранного пункта она яркая,
        у остальных — едва заметная, чтобы полоса читалась как метка
        выбора, а не как украшение каждого пункта."""
        active = self.isChecked()
        if active:
            self.bar.setStyleSheet(f"background: {self._accent};")
            self.title_label.setStyleSheet(f"color: {ui.TEXT};")
        else:
            self.bar.setStyleSheet("background: transparent;")
            self.title_label.setStyleSheet(f"color: {ui.TEXT_2};")


class NavStack(QWidget):
    """Боковая колонка + содержимое. Замена QTabWidget."""

    page_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages: list[QWidget] = []
        self._titles: list[str] = []
        self._items: list[NavItem] = []
        self._current = -1
        self._last_group = ""

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- левая колонка
        self.nav = QFrame()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(NAV_WIDTH)
        self.nav.setStyleSheet(nav_qss())
        nav_layout = QVBoxLayout(self.nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._items_box = QWidget()
        self._items_layout = QVBoxLayout(self._items_box)
        self._items_layout.setContentsMargins(ui.S1, ui.S1, ui.S1, ui.S2)
        self._items_layout.setSpacing(2)
        self._items_layout.addStretch(1)
        self._scroll.setWidget(self._items_box)
        nav_layout.addWidget(self._scroll, 1)

        # Панель состояния — внизу колонки и всегда на виду: путь,
        # состояние моста и счётчики не должны прятаться в разделах.
        self.status = StatusBar()
        nav_layout.addWidget(self.status, 0)
        outer.addWidget(self.nav)

        # --- полоса акцента между колонкой и содержимым
        self.accent_strip = QFrame()
        self.accent_strip.setFixedWidth(3)
        outer.addWidget(self.accent_strip)

        # --- содержимое
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

    # ------------------------------------------------------------ сборка

    def addPage(
        self,
        page: QWidget,
        title: str,
        subtitle: str = "",
        accent: str | None = None,
        group: str = "",
    ) -> None:
        """Добавить страницу. Группа — надпись над пунктами, появляется
        один раз: сколько бы пунктов в группе ни было."""
        accent = accent or ui.ACCENT
        if group and (not self._titles or self._last_group != group):
            head = ui.label(group.upper(), kind="")
            head.setObjectName("navgroup")
            self._items_layout.insertWidget(
                self._items_layout.count() - 1, head
            )
        self._last_group = group

        index = len(self._pages)
        self._pages.append(page)
        self._titles.append(title)
        self.stack.addWidget(page)

        item = NavItem(title, subtitle, accent)
        item.clicked.connect(lambda _=False, i=index: self.setCurrentIndex(i))
        self._items_layout.insertWidget(self._items_layout.count() - 1, item)
        self._items.append(item)

        if self._current < 0:
            self.setCurrentIndex(0)

    def addTab(self, page: QWidget, title: str) -> None:
        """Совместимость с QTabWidget: обычная вкладка без группы."""
        self.addPage(page, title)

    # ------------------------------------------------- как у QTabWidget

    def count(self) -> int:
        return len(self._pages)

    def tabText(self, index: int) -> str:
        return self._titles[index]

    def widget(self, index: int) -> QWidget:
        return self._pages[index]

    def currentIndex(self) -> int:
        return self._current

    def currentWidget(self) -> QWidget | None:
        if self._current < 0:
            return None
        return self._pages[self._current]

    def setCurrentIndex(self, index: int) -> None:
        if not (0 <= index < len(self._pages)):
            return
        if index == self._current:
            return
        self._current = index
        self.stack.setCurrentIndex(index)
        # Гасим все, потом зажигаем нужный: иначе при переходе видно
        # мигание двух пунктов сразу.
        for item in self._items:
            if item.isChecked():
                item.setChecked(False)
        self._items[index].setChecked(True)
        accent = self._items[index]._accent
        self.accent_strip.setStyleSheet(f"background: {accent};")
        self.page_changed.emit(index)

    # для проверок: подпись пункта навигации
    def item_title(self, index: int) -> str:
        return self._items[index].title_label.text()
