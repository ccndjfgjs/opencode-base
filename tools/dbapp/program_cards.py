# -*- coding: utf-8 -*-
"""Карточки вкладки «Программы»: что показать и какие кнопки дать.

Этап 5 раздела 7 плана. Модуль отвечает на вопрос «какая карточка и с
какими кнопками», но **ничего не выполняет** — установку запускает
`winget_install`, а прорисовывает `main.ProgramsTab`. Разделение
намеренное: карточки можно проверить в селфтесте без окна Qt.

**Состояние программы выводится из требований серверов, а не заводится
списком.** Отдельный список программ заводить нельзя: он сразу
разойдётся с реестром, и вкладка начнёт врать о том, что стоит. У
сервера уже есть требование с типом `program` или `command`, и вот оно
и говорит «стоит или нет»:

| Программа | Требование | Что означает |
|---|---|---|
| Node.js | `Node.js 18+`, команда `node` | v24.18.0 |
| Blender | `Blender 3.0+`, программа `blender.exe` | не найдена |
| Android Studio | `Android Studio 2025.2+` | полный путь к studio64.exe |

**Состояние — это про саму программу, а не про сервер.** Иначе карточка
`uv / uvx` сказала бы «не установлена» из-за того, что не стоит Blender,
и человек искал бы не там. Поэтому «не установлена» значит только одно:
не выполнено требование самой программы. А что ещё мешает мосту —
отдельная строка `bridge_pending`, там живут ручные требования вроде
«включи enableMcpServer».

**Node.js — одна карточка, а не две.** В реестре она описана дважды: как
программа сервера `windows-admin` и в разделе `bridge_requirements`,
где её требуют `windows-admin`, `excel` и `obs`. Обе записи нужны, но
человек должен видеть один предмет и список тех, кому он нужен.

**Чего модуль не делает и не должен делать:**

* не выдумывает состояние — нет требования, значит «чем проверять,
  не описано», а не «не установлена»;
* не молчит об отсутствии кнопки — у каждой карточки, которой кнопка
  не полагается, обязан быть заполнен `install.reason`;
* не обещает сверку подписи, если сверять не с чем: подписант есть
  только у Node.js, у остальных карточка говорит, что файла нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import mcp_registry  # type: ignore[import-not-found]
    import programs  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - запуск как пакет
    from . import mcp_registry  # type: ignore[no-redef]
    from . import programs  # type: ignore[no-redef]


#: Программа стоит и мостом можно пользоваться.
STATE_OK = "ok"
#: Программа не стоит — её можно ставить.
STATE_MISSING = "missing"
#: Чем именно проверять наличие программы, реестр не описывает.
STATE_UNKNOWN = "unknown"

#: Кнопки, которые вкладка умеет показать. Проверка — всегда.
BTN_CHECK = "check"
BTN_INSTALL = "install"
BTN_FOLDER = "folder"
BTN_PAGE = "page"

#: Метод реестра, при котором у варианта программы есть своя кнопка
#: установки. Константа, а не строковое сравнение в разных местах:
#: опечатка в «winget» выглядела бы как «кнопки нет» и ничем себя не
#: выдавала бы.
METHOD_WINGET = "winget"


@dataclass
class Card:
    """Одна карточка вкладки «Программы»."""

    key: str                       # устойчивый ключ для Qt
    name: str
    servers: list[str] = field(default_factory=list)     # кому нужна
    state: str = STATE_UNKNOWN
    state_text: str = ""           # живым языком, что именно найдено
    status: str = ""               # заголовок состояния
    bridge_pending: list[str] = field(default_factory=list)
    install: programs.InstallView = field(default_factory=programs.InstallView)
    verify: programs.VerifyView = field(default_factory=programs.VerifyView)
    bridge: programs.BridgeView = field(default_factory=programs.BridgeView)
    alternatives: list[dict] = field(default_factory=list)
    exe_path: str = ""             # что открывать кнопкой «Открыть папку»

    @property
    def needs_admin(self) -> bool:
        return bool(self.install.needs_admin)

    def pending_text(self) -> str:
        """Что ещё не готово — с оговоркой, чьё это требование.

        Список собирается из серверов, которым нужна программа, и для
        общей программы в него попадает то, что касается других
        серверов: у Node.js там окажется «включи WebSocket в OBS».
        Прятать нельзя — список полезен, — но и называть «что нужно
        Node.js» тоже нельзя. Поэтому подпись называет, чьи это
        требования.
        """
        if not self.bridge_pending:
            return ""
        tail = ", ".join(self.bridge_pending)
        if len(self.servers) == 1:
            return f"что ещё не готово: {tail}"
        return (f"что ещё не готово у серверов, которым нужна эта программа "
                f"({len(self.servers)} шт.): {tail}")

    @property
    def hand_over(self) -> bool:
        """Дальше нужен человек: вход, оплата, галочка."""
        return bool(self.install.hand_over)

    @property
    def can_install(self) -> bool:
        """Есть ли смысл показывать кнопку установки.

        Кнопка нужна, когда программа **не установлена**. «Нечем
        проверять» — это не «установлена»: у Adobe Creative Cloud в
        реестре записано `method: winget`, а требования с типом
        `program` нет (клиент проверяет не файл, а учётную запись).
        Считать такое «не установлено» нельзя — тогда кнопка пропала бы
        у программы, которой она нужна.

        Сверка подписи не блокирует, и вот почему. Пока файла нет, наша
        сверка честно молчит: сверять нечего, а не «всё хорошо». Пакет
        ставит winget, и он сверяет **хеш** установщика с манифестом
        своего источника — но подписанта (`expected_signer`) он не
        сверяет, такого механизма у него нет. Значит наша сверка нужна
        тогда, когда файл попадает к нам, а не когда его ставит winget;
        запрещать установку до этого было бы запретом без причины.
        """
        if not self.install.has_button:
            return False
        return self.state != STATE_OK

    def buttons(self) -> list[tuple[str, str, str]]:
        """Какие кнопки показать: (код, надпись, подсказка)."""
        out: list[tuple[str, str, str]] = [
            (BTN_CHECK, "Проверить", "Перечитать состояние заново"),
        ]
        if self.can_install:
            label = f"Установить {self.install.program or self.name}"
            hint = "Поставит winget"
            if self.needs_admin:
                hint += "; может запросить права администратора"
            if self.hand_over:
                hint += "; после установки нужно будет войти в учётную запись"
            out.append((BTN_INSTALL, label, hint))
        elif self.state == STATE_MISSING:
            reason = self.install.reason or "установка не описана в реестре"
            out.append((BTN_INSTALL, "Установить", f"недоступно: {reason}"))
        if self.exe_path:
            out.append((BTN_FOLDER, "Открыть папку", self.exe_path))
        if self.install.official_url:
            out.append((BTN_PAGE, "Официальная страница", self.install.official_url))
        return out


# ----------------------------------------------------------------- слияние

def _fold(name: str) -> str:
    """Ключ для склейки записей. Регистр и лишние пробелы — не различие."""
    return " ".join(str(name or "").split()).casefold()


#: Строковые поля InstallView: первая непустая побеждает.
_TEXT_FIELDS = (
    "program", "winget_id", "catalog_version", "official_url",
    "instructions", "reason",
)


def _fill_gaps(install: programs.InstallView, other: programs.InstallView
               ) -> programs.InstallView:
    """Дописать пустые поля из второй записи.

    Порядок важен: первая запись — главная, вторая только дополняет.
    Иначе запись из `bridge_requirements` затёрла бы кусок серверной или
    наоборот, и карточка зависела бы от того, в каком порядке сошлись.

    **Булевы поля сливаются по правилам, а не копируются.** Здесь была
    ошибка: копировались только строки, и `needs_admin` оставался
    `False` у всех карточек — то есть вкладка никогда не говорила, что
    установщику понадобятся права администратора, хотя это требование
    раздела 14.5 плана. Молчаливое «прав не надо» опаснее отсутствия
    кнопки, поэтому:

    * `needs_admin` и `hand_over` — «или»: если хоть один источник говорит
      «да», карточка говорит «да»;
    * `publisher_trusted` — «и»: недоверенный издатель нельзя объявить
      доверенным, потому что другой источник его проверил.
    """
    out = programs.InstallView(**vars(install))
    for field_name in _TEXT_FIELDS:
        if not getattr(out, field_name) and getattr(other, field_name):
            setattr(out, field_name, getattr(other, field_name))
    if not out.alternatives and other.alternatives:
        out.alternatives = list(other.alternatives)
    if out.action == programs.ACTION_NONE and other.action != programs.ACTION_NONE:
        out.action = other.action
    out.needs_admin = bool(install.needs_admin or other.needs_admin)
    out.hand_over = bool(install.hand_over or other.hand_over)
    out.publisher_trusted = bool(install.publisher_trusted
                                 and other.publisher_trusted)
    return out


@dataclass
class _Draft:
    """Черновик карточки, пока сведения ещё не сведены."""

    name: str
    servers: list[str] = field(default_factory=list)
    is_extra: bool = False   # программа вне серверов
    install: programs.InstallView = field(default_factory=programs.InstallView)
    verify: programs.VerifyView = field(default_factory=programs.VerifyView)
    bridge: programs.BridgeView = field(default_factory=programs.BridgeView)


def _drafts(base: Path) -> list[_Draft]:
    """Черновики по всем источникам: серверы и раздел «нужно мостам»."""
    out: dict[str, _Draft] = {}

    def slot(name: str) -> _Draft:
        key = _fold(name)
        if key not in out:
            out[key] = _Draft(name=str(name))
        return out[key]

    for view in programs.server_views(base):
        draft = slot(view.install.program or view.name)
        draft.servers.append(view.id)
        draft.install = _fill_gaps(draft.install, view.install)
        # Сверка нужна карточке вся — включая честное «сверять не с чем».
        # Копировать её только когда есть подписант нельзя: тогда у семи
        # программ из восьми пропадало бы объяснение, почему сверки не
        # будет, и строка про подпись молчала бы.
        if view.verify.expected_signer and not draft.verify.expected_signer:
            draft.verify = view.verify
        elif not draft.verify.detail and view.verify.detail:
            draft.verify = view.verify
        if view.bridge.bundled and not draft.bridge.bundled:
            draft.bridge = view.bridge

    for need in programs.bridge_needs(base):
        draft = slot(need.program)
        for server_id in need.required_by:
            if server_id not in draft.servers:
                draft.servers.append(server_id)
        # Раздел «нужно мостам» — главный: в нём и required_by, и signer_proof
        draft.install = _fill_gaps(need.install, draft.install)
        if need.install.instructions:
            draft.install.instructions = need.install.instructions

    # Прочие программы — в конец, после серверов и мостов. Порядок важен:
    # девятая программа не должна вставать в ряд с восемью серверами,
    # иначе она читается как девятый сервер.
    for block in mcp_registry.load_extra_programs(base):
        draft = slot(block.program or "без названия")
        draft.is_extra = True
        draft.install = _fill_gaps(
            draft.install, programs._install_from_block(block))
        draft.verify = programs.VerifyView(
            expected_signer=block.expected_signer,
            expected_publisher=block.expected_publisher,
            detail="программа вне списка серверов MCP")

    return list(out.values())


# ------------------------------------------------------- состояние программы

def _requirement_matches(program: str, requirement) -> bool:
    """Относится ли требование к этой программе.

    Сравнение по первому слову и по началу строки. Оба нужны: у Node.js
    требование называется «Node.js 18+», а у Excel программа записана как
    «Microsoft Office 2016 (Excel)», а требованием — «Microsoft Excel
    2016+». Подстановка целиком была бы угадыванием.
    """
    what = " ".join(str(getattr(requirement, "what", "") or "").split())
    name = " ".join(str(program or "").split())
    if not what or not name:
        return False
    low_what, low_name = what.casefold(), name.casefold()
    if low_what.startswith(low_name) or low_name.startswith(low_what):
        return True
    return low_what.split(" ", 1)[0] == low_name.split(" ", 1)[0]


def _executable(matched) -> str:
    """Путь к исполняемому файлу, если требование его нашло."""
    for _, requirement in matched:
        detail = str(getattr(requirement, "detail", "") or "")
        if len(detail) > 3 and detail[1:3] == ":\\":
            return detail
    return ""


@dataclass
class _State:
    """Разобранное состояние программы. Собирать карточку из строк вместо
    этого означало бы распутывать кортежи по индексу."""

    state: str = STATE_UNKNOWN
    text: str = ""
    status: str = ""
    pending: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    exe: str = ""


def _state(draft: _Draft, servers_by_id: dict) -> _State:
    """Состояние программы — по требованиям её серверов."""
    matched: list[tuple[str, object]] = []
    pending: list[str] = []
    blocking: list[str] = []
    for server_id in draft.servers:
        server = servers_by_id.get(server_id)
        if server is None:
            continue
        for requirement in server.requirements:
            if requirement.kind in ("program", "command") \
                    and _requirement_matches(draft.name, requirement):
                matched.append((server_id, requirement))
        for requirement in server.requirements:
            if requirement.kind == "manual" and not requirement.ok:
                pending.append(requirement.what)
                if requirement.blocks:
                    blocking.append(requirement.what)

    out = _State(exe=_executable(matched))

    if getattr(draft, "is_extra", False):
        # Серверов нет, и общая ветка ниже сказала бы «нечем
        # проверять». Это неправда в обе сторонах: программа
        # ставится вручную по официальному адресу, и кнопка установки не будет.
        out.status = "обход блокировок, не сервер"
        out.text = ("не сервер MCP: обходчик сам качает Xray с "
                    "официального GitHub при первом запуске и "
                    "поднимает SOCKS5. Живых узлов подписок нет, "
                    "работают запасные прокси. Кнопки в вкладке нет: "
                    "запускается обходчик отдельно")
        out.pending = pending
        return out

    if not matched:
        if draft.install.action == programs.ACTION_NONE:
            out.text = draft.install.reason or "программа не ставится и не нужна"
            out.status = "не нужна"
        elif blocking:
            # Так у Adobe: проверяет не файл, а человек — приложения и
            # подписку. Сказать «нечем проверять» тут значило бы скрыть
            # настоящую причину.
            out.text = ("проверяет человек, не программа: " + ", ".join(blocking))
            out.status = "проверяет человек"
        else:
            out.text = ("реестр не описывает, как проверить, стоит ли программа: "
                        "нечем сказать «установлена» или «нет»")
            out.status = "нечем проверять"
        out.pending = pending
        return out

    bad = [r for _, r in matched if not r.ok]
    if bad:
        out.state = STATE_MISSING
        out.status = "не установлена"
        out.text = "не хватает: " + ", ".join(str(r.what) for r in bad)
        out.pending = pending
        return out

    # Одна и та же программа требуется несколькими серверами, и требование
    # повторяется столько же раз. Показывать «v24.18.0; v24.18.0;
    # v24.18.0» бессмысленно — оставляем по одной строке на разные
    # находки, порядок сохраняем.
    seen: list[str] = []
    for _, requirement in matched:
        line = f"{requirement.what} — {requirement.detail}" if requirement.detail \
            else str(requirement.what)
        if line not in seen:
            seen.append(line)
    out.state = STATE_OK
    out.status = "установлена, мост не настроен" if pending else "установлена"
    out.text = "; ".join(seen) or "требование выполнено"
    out.pending = pending
    return out


# ------------------------------------------------------------------- сборка

def cards(base: Path) -> list[Card]:
    """Все карточки вкладки — из одного только реестра.

    Порядок: сначала серверы в том порядке, в каком они в реестре, потом
    предметы раздела «нужно мостам», которых среди серверов не было.
    """
    servers = mcp_registry.load_servers(base)
    servers_by_id = {s.id: s for s in servers}
    out: list[Card] = []
    for draft in _drafts(base):
        state = _state(draft, servers_by_id)
        out.append(Card(
            key=_fold(draft.name),
            name=draft.name,
            servers=list(draft.servers),
            state=state.state,
            state_text=state.text,
            status=state.status,
            bridge_pending=state.pending,
            install=draft.install,
            verify=draft.verify,
            bridge=draft.bridge,
            alternatives=list(draft.install.alternatives),
            exe_path=state.exe,
        ))
    return out


def section_problem(base: Path) -> str:
    """Проблемы с данными, из которых строятся карточки. Пусто — всё в порядке.

    Вкладка обязана показать это, а не молча нарисовать половину
    предметов: потерянный раздел «нужно мостам» снаружи выглядит так же,
    как «ставить нечего».
    """
    problems: list[str] = []
    section = programs.bridge_section_problem(base)
    if section:
        problems.append(section)
    bad = programs.agrees_with_registry(base)
    if bad:
        problems.append("движок разошёлся с реестром: " + "; ".join(bad))
    if not mcp_registry.load_servers(base):
        problems.append(f"реестр не прочитан: серверов 0 по пути {base}")
    return " | ".join(problems)


def needed_by_text(card: Card, servers_by_name: dict[str, str]) -> str:
    """Кому нужна программа, именами а не идентификаторами.

    Идентификаторы в виду не годятся: человек знает «Excel», а не
    `excel`. Если имя не найдено, показываем идентификатор как есть —
    молча выкидывать его нельзя, потеряется след в реестре.
    """
    names = [servers_by_name.get(sid, sid) for sid in card.servers]
    if not names:
        return ""
    if len(names) == 1:
        return f"нужна: {names[0]}"
    return "нужна: " + ", ".join(names)


def servers_by_name(base: Path) -> dict[str, str]:
    """Идентификатор сервера -> его название."""
    return {s.id: s.name for s in mcp_registry.load_servers(base)}
