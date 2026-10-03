# -*- coding: utf-8 -*-
"""Движок вкладки «Программы»: что показывать и что можно сделать.

Этап 3 раздела 7 плана. Модуль отвечает на четыре вопроса по каждому
серверу и по каждому предмету раздела «нужно мостам»:

| Вопрос | Что отвечает |
|---|---|
| `check` | выполнены ли требования — то же, что считает `mcp_registry` |
| `install` | что сделает кнопка «Установить», и будет ли она вообще |
| `verify` | кому обязана совпасть подпись, и **сделана ли проверка** |
| `bridge` | лежит ли мост внутри программы или его надо ставить отдельно |

**Модуль ничего не выполняет.** Ни одной команды установки тут нет и быть не
должно на этом этапе: кнопок ещё не существует, их будет этап 5, а
установку и откат — этапы 8 и 9. Движок считает состояние и говорит, что
можно было бы сделать. Если сюда попадёт запуск winget, то проверка
«движок выдаёт то же, что текущая проверка» превратится в установку
программ на машину человека — а это ровно то, чего проверка делать не должна.

**`verify` честно говорит, что проверки подписи ещё нет.** Поле
`expected_signer` записано как намерение, самой сверки в коде нет ни разу
(раздел 2.2 плана). Поэтому `verified` всегда `False`, а `check` возвращает
`False` с причиной. Когда появится сверка — этап 4 — здесь станет `True`, и
до тех пор вкладка не имеет права показывать «подпись проверена».

**Третий раздел «нужно мостам» приходит из `bridge_requirements`**, а не
выводится из требований серверов. Требования записаны командами (`node`,
`uvx`), а не программами, и превращать команду в программу значило бы
угадывать. Но расхождение между разделом и требованиями ловится тестом:
каждый сервер из `required_by` обязан действительно требовать этот предмет.

**Согласие с текущей проверкой — главное свойство.** `check` обязан давать
тот же результат, что и `mcp_registry`, иначе вкладка и окно мостов
разойдутся, и человек увидит одно, а работать будет другое. Расхождение
проверяется в селфтесте, а не на словах.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Импорт двойной: при плоском запуске папка лежит в sys.path, при запуске
# как пакет нужен относительный.
try:
    import mcp_registry  # type: ignore[import-not-found]
    import signature  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - запуск как пакет
    from . import mcp_registry  # type: ignore[no-redef]
    from . import signature  # type: ignore[no-redef]


#: Что вкладка умеет делать с программой. Смысл этих значений — из раздела
#: 2.3а плана, и он же записан в реестре полем method.
ACTION_NONE = "none"             # ставить нечего
ACTION_WINGET = "winget"         # кнопка «Установить» через winget
ACTION_DOWNLOAD = "download"     # кнопка качает с официального адреса
ACTION_MANUAL = "manual"         # кнопки нет: страница и команда в буфер

#: Значение метода из реестра -> действие вкладки. Метод `none` означает
#: разные вещи в разных серверах, поэтому подпись к нему обязательна: молча
#: читать `none` как «делать нечего» нельзя, у android-emulator это «подойдёт
#: любая», а у windows-admin было «программа не нужна».
METHOD_TO_ACTION = {
    "winget": ACTION_WINGET,
    "official-download": ACTION_DOWNLOAD,
    "manual": ACTION_MANUAL,
    "none": ACTION_NONE,
}

#: Мост уже лежит внутри программы.
BRIDGE_BUNDLED = "bundled"


@dataclass
class CheckView:
    """Выполнены ли требования. Значения повторяют те, что считает реестр."""

    ok: bool = False
    missing: list[str] = field(default_factory=list)
    blocking_manual: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class InstallView:
    """Что сделает кнопка «Установить» — и будет ли она."""

    action: str = ACTION_NONE
    program: str = ""
    winget_id: str = ""
    catalog_version: str = ""
    needs_admin: bool = False
    hand_over: bool = False
    official_url: str = ""
    instructions: str = ""
    publisher_trusted: bool = True
    reason: str = ""              # почему кнопки нет — молчать нельзя
    alternatives: list[dict] = field(default_factory=list)

    @property
    def has_button(self) -> bool:
        return self.action in (ACTION_WINGET, ACTION_DOWNLOAD)


@dataclass
class VerifyView:
    """Кому обязана совпасть подпись, и что сказала сверка.

    Различает три состояния, и смешивать их нельзя:

    * сверки ещё не было — ждём файла;
    * сверка прошла, но подписал не тот;
    * сверка прошла и подписал тот, кого ждали.

    Раньше здесь стояло одно поле verified с постоянным False и словами
    «сверки ещё нет». Теперь сверка есть (модуль signature), но файла, который
    она проверяет, ещё нет: скачивание появится на этапе 8. Поэтому состояние
    «ждаем файл» отделено от состояния «отказали».
    """

    expected_signer: str = ""
    expected_publisher: str = ""
    winget_id: str = ""
    signer_checked: str = ""      # когда CN подтверждён на настоящем файле
    verified: bool = False        # проверено по-настоящему и подписант тот
    checked: bool = False         # сверка вообще дала ответ
    safe_to_run: bool = False     # запускать можно (неизвестность = отказ)
    detail: str = ""

    @property
    def can_check(self) -> bool:
        """Есть ли смысл запускать сверку: файл появится, имя известно."""
        return bool(self.expected_signer)


@dataclass
class BridgeView:
    """Где живёт мост."""

    kind: str = ""                # bundled — лежит внутри программы
    note: str = ""

    @property
    def bundled(self) -> bool:
        return self.kind == BRIDGE_BUNDLED


@dataclass
class ProgramView:
    """Всё по одной программе — для карточки вкладки."""

    id: str
    name: str
    check: CheckView = field(default_factory=CheckView)
    install: InstallView = field(default_factory=InstallView)
    verify: VerifyView = field(default_factory=VerifyView)
    bridge: BridgeView = field(default_factory=BridgeView)


# --------------------------------------------------------------------- разделы

def _method_to_action(method: str) -> str:
    """Метод реестра -> действие вкладки. Неизвестный метод — ручной.

    Молчалить про неизвестный метод нельзя: метод из будущей правки вкладки
    иначе выглядел бы так же, как «кнопки нет», и человек решил бы, что
    кнопки не будет никогда.
    """
    return METHOD_TO_ACTION.get(str(method or "").strip().lower(), ACTION_MANUAL)


def _install_from_block(block: mcp_registry.ProgramInstall | None) -> InstallView:
    """Разобрать блок программы. None — блока нет, это не ошибка.

    Отсутствие блока бывает у сервера без старания: старый реестр или сервер,
    которому программа не нужна. Молча превращать это в «ставить нечего»
    нельзя — причина обязана попасть в поле reason.
    """
    if block is None:
        return InstallView(
            action=ACTION_NONE,
            reason="блока установки в реестре нет — это старый реестр или сервер, "
                   "которому программа не нужна",
        )
    action = _method_to_action(block.method)
    reason = ""
    if action == ACTION_NONE:
        reason = "программа не ставится: " + block.instructions[:120] if block.instructions \
            else "программа не ставится — причина не записана в реестре"
    return InstallView(
        action=action,
        program=block.program,
        winget_id=block.winget_id,
        catalog_version=block.catalog_version,
        needs_admin=block.needs_admin,
        hand_over=block.hand_over,
        official_url=block.official_url,
        instructions=block.instructions,
        publisher_trusted=block.publisher_trusted,
        reason=reason,
        alternatives=list(block.alternatives),
    )


def _check_from_server(server: mcp_registry.Server) -> CheckView:
    """Требования сервера. Считаются ровно так же, как в самом реестре.

    Дублирование здесь намеренное: движок должен уметь посчитать состояние
    сам, иначе он не сможет объяснить, почему показал именно то. Расхождение
    с `mcp_registry` ловится в селфтесте — это главная проверка модуля.
    """
    missing = [r.what for r in server.requirements if not r.ok and r.kind != "manual"]
    blocking = [r.what for r in server.requirements if r.kind == "manual" and r.blocks]
    return CheckView(
        ok=not missing and not blocking,
        missing=missing,
        blocking_manual=blocking,
        detail="; ".join(missing + blocking) if (missing or blocking) else "все требования выполнены",
    )


def _verify_from_block(block: mcp_registry.ProgramInstall | None) -> VerifyView:
    """Что известно о подписи, пока файла нет.

    Сверка живёт в модуле signature и требует файл. Пока файла нет, здесь
    только то, что решено заранее: кого мы ждём и подтверждён ли этот подписант
    на настоящем файле. Отвечать «сверки нет» больше нельзя — сверка есть,
    нет файла, и разницу вкладке показывать надо.
    """
    if block is None:
        return VerifyView(
            detail="подпись проверять нечего: блока установки в реестре нет",
        )
    if not block.expected_signer:
        # Издатель из каталога winget НЕ подписант: на Node.js это
        # «Node.js Foundation» против настоящего «OpenJS Foundation». Подставлять
        # издателя на место подписанта нельзя — сверка объявила бы настоящий
        # файл поддельным. Поэтому здесь честно «проверять не с чем».
        return VerifyView(
            expected_publisher=block.expected_publisher,
            winget_id=block.winget_id,
            detail=(
                f"имя подписанта неизвестно, сверять не с чем. Издатель из "
                f"каталога winget — {block.expected_publisher or '—'} — это "
                f"другое поле: он не подписант. Имя появится, когда "
                f"установщик будет скачан (этап 8)"
            ),
        )
    return VerifyView(
        expected_signer=block.expected_signer,
        expected_publisher=block.expected_publisher,
        winget_id=block.winget_id,
        signer_checked=block.signer_checked,
        detail=(f"ждём подписанта {block.expected_signer}; файл ещё не скачан, "
                f"поэтому сверка не запускалась"),
    )


def verify_file(view: VerifyView, path: Path) -> VerifyView:
    """Сверить подпись настоящего файла и вернуть то же представление.

    Отдельная функция, а не поле, вычисляемое само: сверка стоит около
    0,3–0,8 с на файл, и вызывать её из представления означало бы дёргать
    PowerShell каждый раз, когда вкладка перерисовывает карточку.
    """
    if not view.can_check:
        return view
    result = signature.check_signature(path, view.expected_signer)
    return VerifyView(
        expected_signer=view.expected_signer,
        expected_publisher=view.expected_publisher,
        winget_id=view.winget_id,
        signer_checked=view.signer_checked,
        verified=result.verified,
        checked=result.checked,
        safe_to_run=result.safe_to_run,
        detail=signature.describe(result),
    )


def _bridge_from_block(block: mcp_registry.ProgramInstall | None) -> BridgeView:
    """Где живёт мост."""
    if block is None:
        return BridgeView(kind="", note="мост в реестре не описан")
    if block.bridge == BRIDGE_BUNDLED:
        return BridgeView(kind=BRIDGE_BUNDLED, note="мост лежит внутри программы, ставить не нужно")
    return BridgeView(kind="", note="мост ставится отдельно — смотри поле install сервера")


def server_view(server: mcp_registry.Server) -> ProgramView:
    """Всё по одному серверу — то, из чего вкладка рисует карточку."""
    block = server.program_install
    return ProgramView(
        id=server.id,
        name=server.name,
        check=_check_from_server(server),
        install=_install_from_block(block),
        verify=_verify_from_block(block),
        bridge=_bridge_from_block(block),
    )


def server_views(base: Path) -> list[ProgramView]:
    """Все серверы реестра. Требования проверяются живьём."""
    return [server_view(s) for s in mcp_registry.load_servers(base)]


# ------------------------------------------------- третий раздел: нужно мостам

@dataclass
class BridgeNeed:
    """Предмет раздела «нужно мостам»: нужен мостам и не входит в список программ."""

    program: str
    install: InstallView = field(default_factory=InstallView)
    required_by: list[str] = field(default_factory=list)

    @property
    def wanted_by_count(self) -> int:
        return len(self.required_by)


def bridge_needs(base: Path) -> list[BridgeNeed]:
    """Что требуется мостам и не входит в список программ.

    Пустой раздел — не ошибка, а «ставить нечего». Но отсутствие самого
    раздела в реестре — ошибка: значит, данные потеряны, и вкладка молча
    покажет пустоту вместо Node.js.
    """
    raw = mcp_registry.load_registry(base)
    section = raw.get("bridge_requirements")
    if not isinstance(section, dict):
        return []
    out: list[BridgeNeed] = []
    for item in section.get("items") or []:
        if not isinstance(item, dict):
            continue
        block = mcp_registry.ProgramInstall(
            program=str(item.get("program") or ""),
            method=str(item.get("method") or ACTION_MANUAL),
            winget_id=str(item.get("winget_id") or ""),
            catalog_version=str(item.get("catalog_version") or ""),
            expected_signer=str(item.get("expected_signer") or ""),
            needs_admin=bool(item.get("needs_admin")),
            needs_admin_verified=bool(item.get("needs_admin_verified")),
            official_url=str(item.get("official_url") or ""),
            hand_over=bool(item.get("hand_over")),
            publisher_trusted=bool(item.get("publisher_trusted", True)),
            instructions=str(item.get("instructions") or ""),
            checked=str(item.get("checked") or ""),
        )
        out.append(BridgeNeed(
            program=block.program,
            install=_install_from_block(block),
            required_by=[str(x) for x in (item.get("required_by") or [])],
        ))
    return out


# ------------------------------------------------------- сверка с настоящим реестром

def disagreement(server: mcp_registry.Server, view: ProgramView) -> str:
    """Расходится ли вид движка с тем, что считает сам реестр.

    Пустая строка — согласие. Непустая — описание расхождения словами,
    чтобы тест мог показать его человеку, а не молча упасть.
    """
    registry_ok = server.ready
    registry_missing = sorted(r.what for r in server.missing)
    registry_blocking = sorted(r.what for r in server.blocking_manual)
    problems: list[str] = []
    if view.check.ok != registry_ok:
        problems.append(f"итог разный: движок {view.check.ok}, реестр {registry_ok}")
    if sorted(view.check.missing) != registry_missing:
        problems.append(
            f"не хватает разное: движок {sorted(view.check.missing)}, реестр {registry_missing}")
    if sorted(view.check.blocking_manual) != registry_blocking:
        problems.append(
            f"ручное разное: движок {sorted(view.check.blocking_manual)}, "
            f"реестр {registry_blocking}")
    return "; ".join(problems)


def bridge_section_problem(base: Path) -> str:
    """Что не так с разделом «нужно мостам». Пустая строка — всё в порядке.

    Отличать «раздел пуст» от «раздела нет» обязательно. Пустой раздел —
    это «ставить нечего», и он честен. Отсутствующий раздел — значит, данные
    потеряны, и вкладка молча покажет пустоту вместо Node.js. Оба случая
    выглядели бы снаружи одинаково, поэтому проверка их различает.
    """
    raw = mcp_registry.load_registry(base)
    if "bridge_requirements" not in raw:
        return "в реестре нет раздела bridge_requirements"
    section = raw.get("bridge_requirements")
    if not isinstance(section, dict):
        return "раздел bridge_requirements не объект"
    items = section.get("items")
    if not isinstance(items, list):
        return "в разделе bridge_requirements нет списка items"
    if not items:
        return ""  # пустой раздел честен: ставить нечего
    bad = [str(i.get("program")) for i in items
           if not isinstance(i, dict) or not i.get("program")]
    if bad:
        return f"в разделе предметы без имени: {bad}"
    return ""


def agrees_with_registry(base: Path) -> list[str]:
    """Разойдутся ли где-нибудь движок и реестр. Пустой список — согласие.

    Эта функция — самый честный тест модуля: она сравнивает движок не с
    ожиданием, записанной в тесте, а с живым реестром. Расхождение появляется
    само, когда правят любую сторону.

    **Пустой реестр — это расхождение, а не согласие.** Так было на самом
    деле: движок получил неверный путь, прочитал ноль серверов, сравнил
    два пустых списка и радостно вернул «расхождений нет». Проверка, которая
    проходит на пустом входе, ничего не проверяет, поэтому ноль серверов
    здесь считается ошибкой с честным текстом.
    """
    servers = mcp_registry.load_servers(base)
    if not servers:
        return [f"реестр не прочитан: серверов 0 по пути {base} — "
                f"проверять нечего, а «согласие» означало бы, что всё в порядке"]
    bad: list[str] = []
    for server in servers:
        problem = disagreement(server, server_view(server))
        if problem:
            bad.append(f"{server.id}: {problem}")
    return bad
