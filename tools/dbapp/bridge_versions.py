"""Что нужно каждому мосту: версия программы, версия MCP-сервера, версия плагина.

Таблица `данные/bridge-versions.json` — единственное место, где записаны все
три. Модуль не только читает её, но и **сверяет с реальностью**: иначе
таблица через месяц станет красивым враньём.

Что сверяется и зачем:

1. **Каждому мосту реестра есть запись, и наоборот.** Забыли про новый мост —
   сверка скажет. Это и есть «при добавлении моста проверка автоматическая».
2. **`pinned_in` против значения в коде.** Именно так нашёлся класс ошибок с
   Unreal: в коде было `0.6.0-beta-e`, в указателе `beta-f`, и мост падал бы с
   `versionMismatch` на каждом вызове. Теперь такая рассинхронизация видна
   сразу, а не на первом упавшем вызове.
3. **Версия плагина против указателя.** Плагин и сервер обязаны быть из
   одного релиза.

Мосты, у которых сервер или плагин встроен в чужую программу (OBS, Roblox,
Android Studio, Ghidra), описываются честно: своей версии у них нет, и
выдумывать её нельзя.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAM_ROOT = HERE.parent.parent
TABLE_NAME = "bridge-versions.json"
# Лаунчеры лежат рядом, но не в этом файле: без этой строки сверка не сможет
# сравнить таблицу с константами в коде и объявит всё «согласованным».
sys.path.insert(0, str(HERE / "launchers"))


def table_path(base: Path | None = None) -> Path:
    """Путь к таблице: рядом с реестром, где он и лежит.

    Если реестра рядом нет (тест на битый файл, чужой каталог), ищутся
    обычные папки — иначе «таблицы нет» никогда не отличить от «не там
    искали».
    """
    root = Path(base) if base is not None else PROGRAM_ROOT
    candidates = []
    try:
        import mcp_registry  # noqa: PLC0415 — нужен только здесь

        candidates.append(mcp_registry.registry_path(root).parent / TABLE_NAME)
    except ImportError:
        pass
    candidates.append(root / "данные" / TABLE_NAME)
    candidates.append(root / TABLE_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


@dataclass
class Need:
    """Что нужно мосту: три строки и честная причина, если чего-то нет."""

    bridge: str = ""
    program: str = ""
    server: str = ""
    plugin: str = ""
    server_pinned: bool = False
    server_in: str = ""
    note: str = ""
    known: bool = True

    def lines(self) -> list[str]:
        out = [f"программа: {self.program or 'версия не важна'}",
               f"MCP-сервер: {self.server or '—'}"]
        if self.server_in:
            out[1] += f" (закреплено в {self.server_in})"
        elif not self.server_pinned:
            out[1] += " — версия не закреплена"
        out.append(f"плагин: {self.plugin or 'не нужен'}")
        if self.note:
            out.append(self.note)
        return out


def load(base: Path | None = None) -> tuple[dict | None, str]:
    """Прочитать таблицу. Битый JSON — причина словами, а не исключение."""
    path = table_path(base)
    if not path.is_file():
        return None, f"таблицы версий нет: ожидался файл {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return None, f"таблица версий не читается ({path.name}): {exc}"
    bridges = data.get("bridges")
    if not isinstance(bridges, dict) or not bridges:
        return None, f"в таблице версий нет ни одного моста: {path}"
    return data, ""


def for_bridge(server_id: str, base: Path | None = None) -> Need:
    """Что нужно конкретному мосту. Отсутствие записи — тоже ответ."""
    data, note = load(base)
    if data is None:
        return Need(bridge=str(server_id), known=False, note=note)
    entry = (data.get("bridges") or {}).get(str(server_id))
    if not isinstance(entry, dict):
        return Need(bridge=str(server_id), known=False,
                    note=(f"в таблице версий нет моста «{server_id}» — "
                          f"программа не знает, что ему нужно. Добавь запись"))
    program = entry.get("program") or {}
    server = entry.get("mcp_server") or {}
    plugin = entry.get("plugin")
    plugin_text = ""
    plugin_note = ""
    if isinstance(plugin, dict):
        version = str(plugin.get("version") or "").strip()
        kind = str(plugin.get("kind") or "").strip()
        family = str(plugin.get("family") or "").strip()
        plugin_note = str(plugin.get("note") or "")
        if kind == "built-in":
            plugin_text = f"встроен в программу ({version or 'версия не заявлена'})"
        elif kind == "manual":
            plugin_text = f"ставится вручную{(' ' + version) if version else ''}"
        elif family:
            plugin_text = f"{family}{(' ' + version) if version else ' — по указателю'}"
        else:
            plugin_text = "плагин не нужен"
    server_note = str(server.get("note") or "")
    return Need(
        bridge=str(server_id),
        program=str(program.get("text") or ""),
        server=str(server.get("spec") or ""),
        plugin=plugin_text,
        server_pinned=bool(server.get("pinned")),
        server_in=str(server.get("pinned_in") or ""),
        note=" ".join(part for part in (server_note, plugin_note) if part),
    )


def _code_value(name: str) -> str:
    """Значение константы из кода лаунчеров. Пусто — константы нет."""
    if not name.startswith("bridge_common."):
        return ""
    try:
        import bridge_common  # noqa: PLC0415 — нужен только здесь
    except ImportError:
        return ""
    return str(getattr(bridge_common, name.split(".", 1)[1], "") or "")


def audit(base: Path | None = None) -> tuple[bool, str]:
    """Сверка таблицы с реестром, с кодом и с указателями плагинов.

    Три несогласия ловятся здесь, а не при первом упавшем вызове:
    нет записи для моста, запись есть лишняя, версия в коде разошлась с
    таблицей или с указателем плагина.
    """
    data, note = load(base)
    if data is None:
        return False, note
    try:
        import mcp_registry  # noqa: PLC0415 — нужен только здесь
        import plugin_index  # noqa: PLC0415 — и тут
    except ImportError as exc:
        return False, f"модули программы не импортируются ({exc})"

    problems: list[str] = []
    bridges = data.get("bridges") or {}
    ids = [str(s.id) for s in mcp_registry.load_servers(PROGRAM_ROOT if base is None else Path(base))]
    for server_id in ids:
        if server_id not in bridges:
            problems.append(f"{server_id}: в таблице версий нет записи")
    for server_id in bridges:
        if server_id not in ids:
            problems.append(f"{server_id}: запись есть, а моста в реестре нет")

    for server_id, entry in bridges.items():
        if not isinstance(entry, dict):
            problems.append(f"{server_id}: запись не объект")
            continue
        server = entry.get("mcp_server") or {}
        pinned_in = str(server.get("pinned_in") or "")
        spec = str(server.get("spec") or "")
        if server.get("pinned") and pinned_in.startswith("bridge_common."):
            actual = _code_value(pinned_in)
            if actual and actual != spec:
                problems.append(
                    f"{server_id}: в коде {pinned_in} = «{actual}», "
                    f"а в таблице «{spec}» — разъедутся при первом же вызове")
        plugin = entry.get("plugin")
        if isinstance(plugin, dict) and str(plugin.get("family") or ""):
            family = str(plugin["family"])
            if family == "android-studio":
                continue  # девять полос, конкретную выбирает программа
            picked, why = plugin_index.latest_for(family)
            if picked is None:
                problems.append(f"{server_id}: указатель {family} не читается — {why}")
                continue
            want = str(plugin.get("version") or "").strip()
            if want and want != picked.version:
                problems.append(
                    f"{server_id}: в таблице плагин {want}, в указателе "
                    f"{family} — {picked.version}")
            if want and picked.server:
                from_server = plugin_index.server_version(picked)
                if from_server and from_server != want:
                    problems.append(
                        f"{server_id}: сервер {from_server} и плагин {want} — "
                        f"разные релизы, мост включаться не будет")
    if problems:
        return False, ("; ".join(problems[:3])
                       + (f" (ещё {len(problems) - 3})" if len(problems) > 3 else ""))
    return True, (f"таблица версий согласована с реестром, кодом и указателями: "
                  f"{len(bridges)} мостов")
