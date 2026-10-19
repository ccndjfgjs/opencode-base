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

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer
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
import omniroute
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
    # На Node.js. Мост поднимается через npm или npx.
    "windows-admin": "javascript",
    "excel": "javascript",
    "obs": "javascript",
    "dbhub": "javascript",
    "browsers": "javascript",
    "omniroute": "javascript",
    "unreal": "javascript",
    "tiktok": "javascript",
    "spotify": "javascript",
    # На Python: uvx тянет сервер Unity и godot-ai.
    # ghidra-mcp тоже Python: мост поднимается через uv из папки
    # репозитория. Правило раздела — «по тому, чем он поднят», а не по
    # тому, к какой программе подключается. Без этой строки сервер молча
    # уезжал в раздел «Прочее», а панель врала о подключённом: полный
    # прогон самопроверки поймал это 16.10.2026.
    "ghidra-mcp": "python",
    "blender": "python",
    "android-emulator": "python",
    "ldplayer": "python",
    "unity": "python",
    "godot": "python",
    # Смотритель мостов — тоже Python: он лежит в программе и поднимается
    # её лаунчером. Без этой строки он уезжал в «Прочее», а панель врала
    # о подключённых мостах — полный прогон самопроверки поймал это
    # 19.10.2026.
    "mcp-doctor": "python",
    # Настоящего рантайма нет: плагин внутри IDE или сервер на стороне вендора.
    "android-studio": "ide",
    "roblox-studio": "ide",
    "adobe-creativity": "cloud",
    "capcut": "cloud",
    "chatgpt": "cloud",
    "codex": "cloud",
    "cursor": "cloud",
    # Claude — такой же облачный разговор, как Codex и Cursor: поднимается
    # локальной командой, а сама программа живёт в облаке.
    "claude": "cloud",
}

BASE_BRIDGES_TITLE = "Мосты базы"
REVIEWERS_TITLE = "Ревьюеры"

#: Мосты, у которых поднимается локальная веб-панель, и функция,
#: отдающая её адрес. Значение вызывается в момент нажатия, а не
#: хранится строкой: адрес собирается из порта по умолчанию, и
#: завёрнутая в строку копия разошлась бы с настоящей при первом же
#: изменении порта.
#:
#: Список не выдумывается: сюда попадает только тот мост, который
#: действительно поднимает веб-панель. У остальных кнопка «Открыть»
#: была бы враньём — нажатие нечего открывать.
PANEL_URLS = {
    "omniroute": lambda: omniroute.panel_url(),
}


def _open_server_panel(window, url: str) -> None:
    """Открыть панель моста: сначала живая проверка, потом браузер.

    Порядок обязателен. Открыть страницу при выключенном сервере
    бессмысленно: человек увидит ошибку подключения и решит, что
    программа сломалась. Поэтому сначала спрашиваем сервер, что он
    жив, и только потом открываем.

    Открывает `ui.open_link`, а не `webbrowser.open`: тот запускает
    внешнюю программу, а программа работает на pythonw, и Windows
    показал бы чёрное окно. Это и случилось 19.10.2026.
    """
    ok, note = omniroute.panel_ready(omniroute.find_settings_dir())
    if not ok:
        _notify(window, note)
        return
    if not ui.open_link(url):
        _notify(window, "Браузер не взял адрес — открой его сам: " + url)


def _notify(window, text: str) -> None:
    """Показать строку человеку: в журнал вкладки или в панель."""
    caps = getattr(window, "caps_tab", None)
    log = getattr(caps, "log", None)
    if log is not None:
        try:
            log.clear_log()
            log.add(text, "warn")
            return
        except Exception:  # noqa: BLE001 — журнала может не быть
            pass
    panel = panel_of(window)
    if panel is not None:
        panel.show_note(text)

# Значок закрытия. Крестик, а не «×» из другого шрифта: у этого знака
# оптическая масса больше, чем у буквы, поэтому он на пару пикселей
# меньше по размеру иначе кажется тяжелее соседней кнопки.
CLOSE_CAPTION = "✕"

# Ширина панели. Меньше, чем хотелось сначала: окно у трея — не рабочее
# окно, а быстрый список, и оно перекрывает угол экрана. Широкое окно
# здесь только мешает: чем больше площади, тем труднее пройти мимо него
# к значку обратно. Ширины хватает под название, состояние и две кнопки;
# длинные названия и состояния обрезаются, а полный текст — в подсказке.
PANEL_WIDTH = 340

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


#: Сколько ждать живой проверки, прежде чем смотреть на неё. Проверка
#: идёт в рабочем потоке и зовёт внешние программы — на 12 серверов уходит
#: около секунды, но на медленной машине и с медленным Node.js больше.
CHECK_TIMEOUT_MS = 90_000


def _server_entry(caps, window, server) -> Entry:
    """Состояние и кнопки одного сервера — теми же словами, что таблица.

    Отдельная оговорка про непроверенное. Слово «не проверено» в таблице
    означает не «проверять нечем», а «проверка отложена»: при открытии
    вкладки требования читаются без проверки, иначе окно открывалось бы
    на минуту дольше — каждая проверка зовёт внешнюю программу. Живая
    проверка живёт за кнопкой и на программе уже написана.
    """
    checked = bool(server.requirements)
    text = caps._reg_state_text(server)
    kind = "dim"
    if checked and not server.installed:
        kind = "warn" if server.missing else "ok"
    elif server.installed:
        kind = "warn" if server.missing else "ok"

    actions: list = []
    if server.installed:
        actions.append(("Отключить",
                        lambda srv=server: _run_server(window, caps, srv, False)))
    elif server.has_connection:
        actions.append(("Включить",
                        lambda srv=server: _run_server(window, caps, srv, True)))
    # Мосты, у которых есть локальная веб-панель, получают кнопку
    # «Открыть». Список не выдумывается: PANEL_URLS задан по одному
    # на мост, у которых такая панель правда есть.
    panel = PANEL_URLS.get(server.id)
    if panel is not None:
        actions.append(("Открыть",
                        lambda srv=server, url=panel: _open_server_panel(
                            window, url)))
    if checked:
        # Требования уже проверены: повторно звать проверку незачем,
        # достаточно открыть подробности.
        actions.append(("Подробнее", lambda srv=server: _open_tab_check(window, srv)))
    else:
        # Не проверено — вот здесь «Проверить» и делает живую проверку.
        actions.append(("Проверить",
                        lambda: _check_all(window, caps)))
    return Entry(server.name, text, kind, actions)


def run_check(window) -> None:
    """Живая проверка требований всех серверов. Точка входа снаружи.

    Этим же методом пользуются кнопка «Проверить» в панели и пункт
    «Проверить мосты» в меню трея. Один вход на оба: две копии этой
    проверки разошлись бы, и одна из них рано или поздно перестала бы
    перечитывать состояние по факту.
    """
    caps = getattr(window, "caps_tab", None)
    if caps is None:
        return
    window.showNormal()
    window.raise_()
    for i in range(window.tabs.count()):
        if window.tabs.widget(i) is caps:
            window.tabs.setCurrentIndex(i)
            break
    caps._reg_check_all()
    _await_check(window, caps)


def _check_all(window, caps) -> None:
    """Обертка кнопки «Проверить» в панели.

    Зовём готовый метод вкладки: он уже умеет уводить работу в поток,
    показывать ход дела и перечитывать состояние по факту записи. Свой
    второй набор проверок означал бы две разные правды об одном сервере.
    """
    run_check(window)


def _await_check(window, caps) -> None:
    """Дождаться конца проверки и перерисовать панель.

    Проверка идёт в рабочем потоке, поэтому сразу после её запуска
    состояние ещё прежнее: перерисовав в этот момент, панель показала
    бы «не проверено» сразу после живой проверки. Пока поток жив — видно
    «идёт проверка», и кнопки погашены; поток закончился — панель
    перечитывает состояние по факту.

    Ждём поток, а не время: срок нужен только затем, чтобы при
    зависшем потоке панель не осталась погашенной навсегда.

    Опрос идёт по таймеру, то есть в главном потоке Qt, а не в рабочем:
    трогать виджеты из чужого потока нельзя. Таймер каждый раз новый
    и без повтора, поэтому накопления и утечки нет.
    """
    panel = panel_of(window)
    if panel is not None:
        panel.mark_checking()
    waited = [0]

    def poll() -> None:
        waited[0] += 400
        if getattr(caps, "_worker", None) is not None and waited[0] < CHECK_TIMEOUT_MS:
            QTimer.singleShot(400, poll)
            return
        if panel is not None:
            panel.checking_done()

    QTimer.singleShot(400, poll)


def panel_of(window):
    """Панель, если она уже создана. Не создаём её тут.

    Панель вешается на окно, а не ищется через трей: трей появляется не
    сразу и может быть выключен, а кнопка «Проверить» внутри панели
    обязана находить саму себя всегда. Иначе кнопка молча ничего не
    делает — ровно то, что и случилось при первой проверке.
    """
    return getattr(window, "_tray_panel", None)


def _attach(window, panel) -> None:
    """Запомнить панель на окне, чтобы её нашла и кнопка, и трей."""
    window._tray_panel = panel


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
    actions = [("Настройка", lambda: _focus_qwen_setup(window)),
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


def _focus_qwen_setup(window) -> None:
    """Открыть вкладку opencode и поставить курсор на «Настроить через скилл»."""
    window.showNormal()
    window.raise_()
    caps = getattr(window, "caps_tab", None)
    if caps is None:
        return
    for i in range(window.tabs.count()):
        if window.tabs.widget(i) is caps:
            window.tabs.setCurrentIndex(i)
            break
    button = getattr(caps, "btn_qw_setup", None)
    if button is not None:
        button.setFocus()


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
        # Крестик в шапке. Без него панель было нечем закрыть: ни одного
        # элемента управления для выхода нет, а вернуться к значку в
        # трее, чтобы нажать на него ещё раз, — отдельный квест. У
        # всплывающего окна выход должен быть видно сразу.
        self.btn_close = QPushButton(CLOSE_CAPTION)
        self.btn_close.setObjectName("TrayPanelClose")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Закрыть панель (Esc)")
        self.btn_close.clicked.connect(self.hide)
        head.addWidget(self.btn_close, 0)
        outer.addLayout(head)
        outer.addWidget(ui.line())

        # Строка для коротких сообщений. Без неё панель умела только
        # показывать состояние и ничего не могла сказать: кнопка
        # «Открыть» при выключенном сервере отказала бы молча, и человек
        # решил бы, что кнопка не работает.
        self.lbl_note = ui.label("", kind="warn", wrap=True)
        self.lbl_note.setVisible(False)
        outer.addWidget(self.lbl_note)

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

        self.setFixedWidth(PANEL_WIDTH)
        self._checking = False
        # Панель запоминает себя на окне сразу при создании. Ищут её
        # потом и трей, и кнопка «Проверить» изнутри самой панели.
        _attach(window, self)
        # Наведение мыши на саму панель гасим, иначе под курсором
        # остаётся серый прямоугольник — окно без рамки, но с рамкой
        # от подсветки Qt, и это выглядит как чужой элемент.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.refresh()

    # ---- закрытие

    def showEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        """Включить перехват кликов, пока панель на экране.

        Перехват включается на время показа и снимается при закрытии:
        постоянный фильтр на всё приложение перехватывал бы события
        зря, даже когда панели на экране нет.
        """
        super().showEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def hideEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 — имя из Qt
        """Клик мимо панели закрывает её.

        Так ведёт себя любое всплывающее окно: нажал в стороне — оно
        спряталось. Без этого единственный способ закрыть панель —
        дотянуться до значка в трее, ради чего окно и появлялось.
        """
        if event.type() == QEvent.Type.DeferredDelete:
            # Панель уничтожается, а hideEvent при этом не обязательно
            # приходит — например, когда её снимают вместе с родителем.
            # Оставшийся фильтр на QApplication заставил бы Qt звать
            # метод уже мёртвого объекта. Снимаем себя первым делом.
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            point = event.globalPosition().toPoint()
            if not self.geometry().contains(point):
                self.hide()
        elif event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(watched, event)

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
        head.setToolTip("Нажмите, чтобы раскрыть или свернуть список")
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
        column.setContentsMargins(10, 2, 2, 4)
        column.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        short = short_name(entry.name)
        name = ui.label(short)
        name.setToolTip(entry.name)
        # Длинное название сжимается и обрезается, а не распирает строку.
        # Политика тут обычная, а не Ignored: та даёт виджету нулевую
        # ширину, и название пропадало совсем — измерено: все подписи
        # схлопнулись в 0 пикселей. Минимум в 40 пикселей оставляет
        # место под начало имени, а полное — в подсказке.
        name.setMinimumWidth(40)
        top.addWidget(name, 0)

        # Пока идёт проверка, состояние прежнее и показывать его нельзя:
        # человек увидел бы «не проверено» сразу после нажатия и решил
        # бы, что кнопка не сработала.
        pending = self._check_state()
        if pending is not None:
            state = ui.label(pending, kind="dim")
        else:
            state = ui.label(entry.state, kind=entry.kind)
            if entry.state == "не проверено":
                state.setToolTip(
                    "Требования этого сервера ещё не проверялись на этой "
                    "машине. Нажмите «Проверить» — программа запустит "
                    "внешние программы и покажет, чего не хватает.")
        # Состояние тоже сжимается: «нужно: Аддон MCP for Blender
        # включён в самом Blender» — это четыре слова, и в узкой панели
        # они не поместятся. Полный текст — в подсказке, чтобы ничего не
        # потерялось молча.
        state.setMinimumWidth(40)
        if not state.toolTip() and entry.state != "не проверено":
            state.setToolTip(entry.state)
        top.addWidget(state, 1)
        column.addLayout(top)

        if entry.actions:
            buttons = QHBoxLayout()
            buttons.setSpacing(4)
            for caption, handler in entry.actions:
                button = QPushButton(caption)
                button.setFixedHeight(22)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                # На время проверки кнопки гаснут: дело уже идёт, а
                # повторное нажатие заставило бы гонять проверку заново.
                button.setEnabled(pending is None)
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

    def mark_checking(self) -> None:
        """Показать, что идёт живая проверка, и не врать про результат.

        Проверка требований зовёт внешние программы и идёт в рабочем
        потоке. До её конца состояние прежнее, и панель показала бы
        «не проверено» сразу после нажатия «Проверить» — человек решил
        бы, что кнопка не сработала.
        """
        self._checking = True
        self.refresh()

    def checking_done(self) -> None:
        """Снять отметку проверки и перечитать состояние по факту.

        Отдельный метод, а не сброс флага на месте: вызывается он из
        таймера, и панель обязана сама себя привести в порядок —
        иначе забытый флаг оставил бы её погашенной навсегда.
        """
        self._checking = False
        self.refresh()

    def _check_state(self) -> str | None:
        """Что показать вместо состояния, пока идёт проверка."""
        if getattr(self, "_checking", False):
            return "идёт проверка…"
        return None

    def show_note(self, text: str, msec: int = 14_000) -> None:
        """Показать короткое сообщение и убрать его само.

        Отдельный метод, а не надпись в списке: строка сообщения — не
        состояние моста, и через `refresh()` она бы уехала вместе со
        списком. Таймер гасит её сама, потому что панель живёт поверх
        всего и забытая надпись мешала бы читать состояния.
        """
        self.lbl_note.setText(str(text or ""))
        self.lbl_note.setVisible(bool(text))
        if text:
            QTimer.singleShot(msec, self.lbl_note.hide)

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