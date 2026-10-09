"""Панель трея: что подключено, что работает, что готово.

Отдельное маленькое окно без рамки, открывается левой кнопкой по значку
в трее. Внутри — разделы по устройству сервера, каждый раскрывается по
нажатию на заголовок со стрелочкой.

Что здесь важно и не перепутано:

— Панель не знает, как включать серверы. Она зовёт те же методы вкладки
  opencode, что и кнопки в главном окне. Второй набор логики означал бы
  две разные правды об одном сервере: включилось в одном месте, а в
  другом осталось выключенным.

— Состояние берётся из того же `_reg_state_text`, что рисует таблица.
  Своих слов про «работает» панель не выдумывает.

— Кнопки зависят от состояния, а не от категории. У того, что уже
  включено, есть «Отключить», у того, что не подключено, — «Включить».
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import core
import qwen_review
import ui

# Порядок разделов — от того, за чем ходят чаще, к тому, что подключают
# один раз. Модели и ревьюеры вверху не случайно: это ежедневная работа,
# а мосты настраивают и потом забывают.
CATEGORY_ORDER = ("models", "javascript", "python", "ide", "cloud")

CATEGORY_TITLES = {
    "models": "Модели",
    "javascript": "JavaScript",
    "python": "Python",
    "ide": "IDE-плагины",
    "cloud": "Облачные",
    "other": "Прочее",
}

# Категория сервера — по тому, чем он поднят: рантайм, плагин внутри
# программы или сервер на стороне вендора.
#
# Почему это словарь в коде, а не поле в mcp-registry.json. Реестр
# программа читает из папки базы, а копия реестра в базе может быть
# старее той, что едет с программой: обновляется она не при запуске, а
# отдельной переноской. Поле из реестра тогда молча пропадало бы, и все
# серверы съезжали в один раздел — то есть панель врала бы тихо, а это
# худший вид вранья. Со словарём сервер, которого здесь нет, попадает в
# «Прочее» и виден как неопознанный.
CATEGORY_BY_ID = {
    # Модели: не мост к программе, а источник моделей для opencode.
    "lmarena": "models",
    # На Node.js. У всех шести мост поднимается через npm или npx.
    "windows-admin": "javascript",
    "excel": "javascript",
    "obs": "javascript",
    "dbhub": "javascript",
    "browsers": "javascript",
    "omniroute": "javascript",
    # На Python.
    "blender": "python",
    "android-emulator": "python",
    "ldplayer": "python",
    # Настоящего рантайма нет: плагин внутри IDE и сервер вендора.
    "android-studio": "ide",
    "adobe-creativity": "cloud",
}

BASE_BRIDGES_TITLE = "Мосты базы"
REVIEWERS_TITLE = "Ревьюеры"

# Значок раздела: закрыт и открыт. Треугольник читается однозначно —
# по нему видно, что нажатие раскроет список, а не запустит.
ARROW_CLOSED = "▶"
ARROW_OPEN = "▼"


def short_name(name: str) -> str:
    """Имя без пояснения в скобках.

    В реестре названия длинные и объясняющие: «OmniRoute (шлюз к
    провайдерам моделей, 358 провайдеров)». В панели такая строка
    обрезалась посреди слова. Пояснение переносится в подсказку, а
    строка остаётся читаемой.
    """
    cut = name.find(" (")
    return name[:cut].strip() if cut > 0 else name


class Entry:
    """Одна строка панели: имя, состояние и кнопки под это состояние."""

    __slots__ = ("name", "state", "kind", "actions")

    def __init__(self, name: str, state: str, kind: str = "dim",
                 actions: list | None = None) -> None:
        self.name = name
        self.state = state
        self.kind = kind
        # Список пар (подпись, обработчик). Обработчика может не быть:
        # тогда строка показывается, а кнопки у неё нет вовсе.
        self.actions = actions or []


class Section:
    """Раздел панели: заголовок со стрелочкой и список строк под ним."""

    __slots__ = ("title", "entries", "expanded")

    def __init__(self, title: str, entries: list, expanded: bool = False) -> None:
        self.title = title
        self.entries = entries
        self.expanded = expanded


# ---- сбор состояния


def _server_entries(caps, window) -> list:
    """Строки для серверов из реестра, разложенные по разделам."""
    servers = list(getattr(caps, "reg_servers", None) or [])
    by_cat: dict[str, list] = {}
    for server in servers:
        cat = CATEGORY_BY_ID.get(server.id, "other")
        by_cat.setdefault(cat, []).append(server)

    result = []
    for cat in CATEGORY_ORDER:
        items = by_cat.pop(cat, None)
        if not items:
            continue
        result.append(Section(
            CATEGORY_TITLES.get(cat, cat),
            [_server_entry(caps, window, srv) for srv in items],
            # Первые два раздела открыты: иначе панель приходится
            # раскрывать перед каждым взглядом.
            expanded=cat in ("models", "javascript"),
        ))
    # Всё, чего нет в CATEGORY_ORDER, показывается отдельным разделом
    # под настоящим именем — новый сервер обязан быть виден, а не
    # растворяться в первом разделе.
    for cat, items in sorted(by_cat.items()):
        result.append(Section(
            CATEGORY_TITLES.get(cat, cat),
            [_server_entry(caps, window, srv) for srv in items],
        ))
    return result


def _server_entry(caps, window, server) -> Entry:
    """Состояние и кнопки одного сервера — теми же словами, что таблица."""
    text = caps._reg_state_text(server)
    kind = "dim"
    if not server.installed:
        kind = "dim"
    elif server.missing:
        kind = "warn"
    else:
        kind = "ok"

    actions: list = []
    if server.installed:
        actions.append(("Отключить",
                        lambda srv=server: _run_server(window, caps, srv, False)))
    elif server.has_connection:
        actions.append(("Включить",
                        lambda srv=server: _run_server(window, caps, srv, True)))
    # «Проверить» есть всегда: это единственное действие, которое
    # говорит правду о том, чего программа не знает.
    actions.append(("Проверить", lambda srv=server: _open_tab_check(window, srv)))
    return Entry(server.name, text, kind, actions)


def _run_server(window, caps, server, enable: bool) -> None:
    """Включить или отключить сервер через вкладку opencode.

    Ряд выбирается в таблице и зовётся её же метод: так панель получает
    все диалоги, которые уже есть — настройку подключения у DBHub,
    вопрос про ручную настройку, отчёт о ходе дела.
    """
    servers = list(getattr(caps, "reg_servers", None) or [])
    row = -1
    for i, item in enumerate(servers):
        if item.id == server.id:
            row = i
            break
    if row >= 0:
        caps.reg_table.setCurrentCell(row, 0)
    if enable:
        caps._reg_enable()
    else:
        caps._reg_disable()
    window.refresh_now()


def _open_tab_check(window, server) -> None:
    """Открыть вкладку opencode на этом сервере — там есть подробности."""
    window.showNormal()
    window.raise_()
    caps = getattr(window, "caps_tab", None)
    if caps is None:
        return
    for i in range(window.tabs.count()):
        if window.tabs.widget(i) is caps:
            window.tabs.setCurrentIndex(i)
            break
    servers = list(getattr(caps, "reg_servers", None) or [])
    for row, item in enumerate(servers):
        if item.id == server.id:
            caps.reg_table.setCurrentCell(row, 0)
            break
    caps._reg_show_detail()


def _base_bridge_entries(base, window) -> list:
    """Мосты базы: NCP и PC. Свои, протокол свой, состояние — из папки."""
    entries = []
    for name in core.BASE_BRIDGES:
        title = "Мост NCP" if name.startswith("ncp") else "Мост PC"
        folder = core.bridge_dir(base, name)
        actions = [
            ("Открыть папку", lambda p=folder: _open_folder(p)),
            ("Настроить", lambda: _open_bridge_tab(window)),
        ]
        try:
            status = core.bridge_status(folder)
        except Exception as exc:  # состояние не прочиталось — это не повод падать
            entries.append(Entry(title, f"не прочиталось: {exc}", "error", actions))
            continue
        if not status.exists:
            entries.append(Entry(title, "мост не развёрнут", "dim", actions))
            continue
        if status.problem:
            entries.append(Entry(title, status.problem, "warn", actions))
            continue
        entries.append(Entry(title, "мост на месте", "ok", actions))
    return entries


def _open_folder(folder: Path) -> None:
    """Открыть папку моста в проводнике. Папки может не быть — это не беда."""
    try:
        if folder.is_dir():
            os.startfile(str(folder))  # noqa: S606 — так открывают проводник
    except Exception:
        pass


def _open_bridge_tab(window) -> None:
    """Открыть вкладку «Мост NCP» — там настройка мостов и есть."""
    window.showNormal()
    window.raise_()
    for i in range(window.tabs.count()):
        if "мост" in window.tabs.tabText(i).lower():
            window.tabs.setCurrentIndex(i)
            return


def _reviewer_entries(window, dest) -> list:
    """Ревьюеры. Сейчас один — Qwen, но раздел сделан на будущее."""
    try:
        selection = qwen_review.chosen(dest)
    except Exception:
        selection = {}
    model = (selection or {}).get("model") or ""
    if model:
        state, kind = f"выбрана {model}", "ok"
    else:
        state, kind = "модель не выбрана", "warn"
    actions = [("Модель", lambda: _focus_qwen_model(window)),
               ("Журнал", lambda d=dest: _open_qwen_log(window, d))]
    return [Entry("Qwen", state, kind, actions)]


def _open_qwen_log(window, dest: Path) -> None:
    """Открыть журнал ревьюера, если он уже есть.

    Журнала может не быть — ревьюер ни разу не запускали. Тогда молча
    ничего не делаем: пустой файл открывать незачем, а сообщение об
    ошибке здесь только пугает.
    """
    try:
        path = qwen_review.log_file(dest)
    except Exception:
        return
    if path.is_file():
        _open_folder(path.parent)


def _focus_qwen_model(window) -> None:
    """Открыть вкладку opencode и поставить курсор в выбор модели."""
    window.showNormal()
    window.raise_()
    caps = getattr(window, "caps_tab", None)
    if caps is None:
        return
    for i in range(window.tabs.count()):
        if window.tabs.widget(i) is caps:
            window.tabs.setCurrentIndex(i)
            break
    combo = getattr(caps, "qw_model", None)
    if combo is not None:
        combo.setFocus()
        try:
            combo.showPopup()
        except Exception:
            pass


def collect(window, base) -> list:
    """Разделы панели целиком, по состоянию на сейчас."""
    caps = getattr(window, "caps_tab", None)
    sections: list = []
    if caps is not None:
        sections.extend(_server_entries(caps, window))
    dest = getattr(caps, "_reg_dest", None)
    dest_path = dest() if callable(dest) else None
    if dest_path is not None:
        sections.append(Section(BASE_BRIDGES_TITLE,
                               _base_bridge_entries(base, window),
                               expanded=True))
        sections.append(Section(REVIEWERS_TITLE,
                               _reviewer_entries(window, dest_path),
                               expanded=True))
    return sections


# ---- окно


class TrayPanel(QWidget):
    """Маленькое окно у значка трея: разделы, состояния, кнопки."""

    def __init__(self, window) -> None:
        super().__init__(None)
        self.setObjectName("TrayPanel")
        self._window = window
        self._sections: list = []
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(ui.PANEL_QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = ui.label("Подключено", kind="title")
        head.addWidget(title, 1)
        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.setFixedHeight(24)
        self.btn_refresh.clicked.connect(self.refresh)
        head.addWidget(self.btn_refresh, 0)
        outer.addLayout(head)
        outer.addWidget(ui.line())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 4, 0)
        self.body_layout.setSpacing(4)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)

        self.setFixedWidth(430)
        self.refresh()

    # ---- содержимое

    def refresh(self) -> None:
        """Пересобрать список. Состояние читается заново, каждый раз."""
        self._discard()
        base = self._base()
        # Состояние раскрытия переносим по названию раздела. Без этого
        # нажатие на заголовок не работало вовсе: refresh() собирает
        # разделы заново, новые объекты приходят с исходным expanded,
        # и раскрытый раздел тут же закрывался обратно.
        was_open = {s.title: s.expanded for s in self._sections}
        self._sections = collect(self._window, base)
        for section in self._sections:
            if section.title in was_open:
                section.expanded = was_open[section.title]
        for index, section in enumerate(self._sections):
            self.body_layout.insertWidget(index, self._build(section), 0,
                                          Qt.AlignmentFlag.AlignTop)

    def _base(self) -> Path:
        try:
            return core.current_base("opencode")
        except Exception:
            return Path.cwd()

    def _build(self, section: Section) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)

        head = QPushButton()
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        head.setFlat(True)
        arrow = ARROW_OPEN if section.expanded else ARROW_CLOSED
        head.setText("  %s  %s   %d" % (arrow, section.title, len(section.entries)))
        head.setStyleSheet(
            f"QPushButton {{ text-align: left; padding: 4px 2px;"
            f" color: {ui.TEXT}; background: transparent; border: none;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ color: {ui.ACCENT}; }}")
        head.clicked.connect(lambda _=False, s=section: self._toggle(s))
        column.addWidget(head)

        if section.expanded:
            for entry in section.entries:
                column.addWidget(self._build_entry(entry), 0,
                                 Qt.AlignmentFlag.AlignTop)
        return box

    def _toggle(self, section: Section) -> None:
        section.expanded = not section.expanded
        self.refresh()

    def _discard(self) -> None:
        """Убрать виджеты списка, не трогая растяжку в конце.

        Списком в макете был один QWidget, а в конце стоял stretch. Чтобы
        дышать, элементы пересобираются каждый раз, и старые удаляются
        с задержкой: виджеты, на которые ещё ссылается макет, нельзя
        убивать сразу. Из-за этого на скриншоте наезжали друг на друга
        два поколения списка — старое и новое.
        """
        layout = self.body_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _build_entry(self, entry: Entry) -> QWidget:
        # Строка в две линии, а не в одну: в одной не помещались и длинное
        # название, и две-три кнопки — панель становилась шире экрана,
        # и кнопки уезжали за край, где их нельзя было нажать.
        line = QWidget()
        column = QVBoxLayout(line)
        column.setContentsMargins(12, 3, 4, 5)
        column.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(8)
        short = short_name(entry.name)
        name = ui.label(short)
        name.setToolTip(entry.name)
        top.addWidget(name, 0)

        state = ui.label(entry.state, kind=entry.kind)
        top.addWidget(state, 1)
        column.addLayout(top)

        if entry.actions:
            buttons = QHBoxLayout()
            buttons.setSpacing(6)
            for caption, handler in entry.actions:
                button = QPushButton(caption)
                button.setFixedHeight(22)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _=False, fn=handler: self._act(fn))
                buttons.addWidget(button, 0)
            buttons.addStretch(1)
            column.addLayout(buttons)
        return line

    def _act(self, handler) -> None:
        """Кнопка: сначала действие, потом пересборка панели.

        Пересборка нужна, чтобы состояние не расходилось с тем, что
        человек только что сделал: включил сервер — и он сразу переехал
        из «не подключено» в «включён».
        """
        try:
            handler()
        finally:
            self.refresh()

    # ---- показ и скрытие

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.popup()

    def popup(self) -> None:
        self.refresh()
        self.adjustSize()
        self.move_near_tray()
        self.show()
        self.raise_()

    def move_near_tray(self) -> None:
        """Поставить панель у значка трея, а не в центр экрана."""
        tray = getattr(self._window, "tray", None)
        point = None
        if tray is not None:
            geometry = tray.geometry()
            if geometry.isValid() and not geometry.isEmpty():
                point = QPoint(geometry.center())
        if point is None:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
            point = QPoint(area.right() - self.width(), area.bottom() - self.height())
        else:
            screen = QApplication.screenAt(point) or QApplication.primaryScreen()
            area = screen.availableGeometry() if screen is not None else None
            if area is not None:
                x = point.x() - self.width() // 2
                y = point.y() + 18
                x = max(area.left(), min(x, area.right() - self.width()))
                if y + self.height() > area.bottom():
                    y = max(area.top(), point.y() - self.height() - 18)
                self.move(x, y)
                return
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        if area is not None:
            self.move(area.right() - self.width(), area.bottom() - self.height())

    def hideEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        super().hideEvent(event)