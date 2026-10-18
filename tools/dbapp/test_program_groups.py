"""Проверки раскладки мостов по группам.

Запуск: python tools/dbapp/test_program_groups.py

Проверяется не «красиво ли», а три вещи, которые ломаются чаще всего:
у каждого моста есть группа, у каждой группы есть объяснение, и мост без
причины в «Прочее» не попадает молча.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mcp_registry  # noqa: E402
import program_groups as pg  # noqa: E402

PROGRAM_ROOT = HERE.parent.parent

passed = 0
failed = 0


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


@dataclass
class FakePlugin:
    finder: str = ""
    name: str = ""
    button: str = ""


@dataclass
class FakeInstall:
    program: str = ""
    method: str = ""
    winget_id: str = ""
    plugin: FakePlugin | None = None


@dataclass
class FakeServer:
    id: str = ""
    program_install: FakeInstall | None = None
    raw: dict = field(default_factory=dict)


def fake(server_id: str, winget: str = "", finder: str = "") -> FakeServer:
    install = None
    if winget or finder:
        install = FakeInstall(winget_id=winget,
                              plugin=FakePlugin(finder=finder) if finder else None)
    return FakeServer(id=server_id, program_install=install)


def main() -> int:
    # === 1. Правила по данным ===
    check(pg.place(fake("что-то", winget="Unity.UnityHub")).group == "engines",
          "издатель Unity кладёт мост в «Движки и игры»")
    check(pg.place(fake("что-то", winget="OBSProject.OBSStudio")).group == "record",
          "издатель OBS — в «Запись и стриминг»")
    check(pg.place(fake("что-то", winget="Spotify.Spotify")).group == "media",
          "издатель Spotify — в «Творчество и медиа»")
    check("издатель" in pg.place(fake("что-то", winget="Adobe.CreativeCloud")).rule,
          "и объяснение называет издателя")

    # === 2. Плагин важнее издателя ===
    # У Unity издатель Unity, у Unreal — EpicGames, но оба моста про движки
    # должны узнаваться по плагину: он и есть первичный признак.
    plugin_rule = pg.place(fake("что-то", winget="EpicGames.EpicGamesLauncher",
                                finder="unreal"))
    check(plugin_rule.group == "engines" and "указателя движка" in plugin_rule.rule,
          f"плагин движка важнее издателя: {plugin_rule.rule}")
    editor_rule = pg.place(fake("что-то", finder="ghidra-mcp"))
    check(editor_rule.group == "editors",
          f"расширение чужой программы — редакторы: {editor_rule.rule}")

    # === 3. Без сигнала — честный отказ, а не догадка ===
    stranger = pg.place(fake("мост-без-сигнала"))
    check(stranger.group == "other" and "ни одно правило" in stranger.rule,
          f"мост без сигналов попадает в «Прочее» и это видно: {stranger.rule}")
    excel = pg.place(fake("excel"))
    check(excel.group == "office" and excel.rule.startswith("явный список"),
          f"а Excel попадает в «Офис и работа» из явного списка: {excel.rule}")

    # === 4. Настоящий реестр: у всех 24 есть группа и объяснение ===
    servers = mcp_registry.load_servers(PROGRAM_ROOT)
    items = pg.placements(servers)
    check(len(items) == len(servers),
          f"все {len(servers)} мостов получили место")
    no_rule = [item.bridge for item in items if not item.rule.strip()]
    check(not no_rule, "и у каждого есть объяснение" + (f" — нет: {no_rule}" if no_rule else ""))
    # Мост в «Прочее» без явной причины — это потерявшийся мост.
    silent_other = [item.bridge for item in items
                    if item.group == "other" and not item.rule.startswith("явный список")]
    check(not silent_other,
          "в «Прочее» нет моста без явной причины"
          + (f" — потерялись: {silent_other}" if silent_other else ""))
    # На настоящем реестре «Прочее» обязана быть пустой: каждая группа
    # не должна таить потерявшийся мост, который никто не опознал.
    leftover = [item.bridge for item in items if item.group == "other"]
    check(not leftover,
          "«Прочее» на настоящем реестре пуста"
          + (f" — неопознанные: {leftover}" if leftover else ""))
    titled = {item.bridge: item.title for item in items}
    for bridge, title in (("unity", "Движки и игры"), ("unreal", "Движки и игры"),
                          ("godot", "Движки и игры"), ("roblox-studio", "Движки и игры"),
                          ("android-studio", "Редакторы и студии"),
                          ("ghidra-mcp", "Редакторы и студии"),
                          ("blender", "Редакторы и студии"),
                          ("obs", "Запись и стриминг"),
                          ("excel", "Офис и работа"),
                          ("spotify", "Творчество и медиа"),
                          ("windows-admin", "Машина, эмуляторы и система"),
                          ("dbhub", "Служебные мосты")):
        check(titled.get(bridge) == title,
              f"{bridge} -> {titled.get(bridge)} (ожидалось «{title}»)")
    # Четыре CLI ИИ-агентов — служебные мосты: это мосты к чужой программе,
    # которая не ставится как обычное приложение. Проверяется отдельно,
    # потому что решение принималось без человека и может быть переиграно.
    for bridge in ("chatgpt", "codex", "cursor", "claude"):
        check(titled.get(bridge) == "Служебные мосты",
              f"{bridge} -> {titled.get(bridge)}")

    # === 5. Группы идут по порядку и без пустых ===
    grouped = pg.groups(items)
    order = [key for key, _t in pg.GROUPS]
    keys = [key for key, _t, _items in grouped]
    check(keys == [key for key in order if key in keys],
          f"порядок групп сохранён: {keys}")
    check(all(rows for _key, _title, rows in grouped),
          "и пустых групп в списке нет")
    covered = sum(len(rows) for _key, _title, rows in grouped)
    check(covered == len(servers),
          f"в группах все мосты, ничего не потеряно: {covered} из {len(servers)}")

    # === 6. Общая программа не выдаёт себя за чужую группу ===
    # Node.js нужен шести мостам из шести групп. Если взять группу первого
    # моста, он встанет в «Движки и игры» — и это будет правдоподобная
    # неправда: он не движок. Общие программы стоят отдельно.
    class Card:
        def __init__(self, key, servers):
            self.key = key
            self.servers = servers

    placed = pg.by_bridge(servers)
    node = pg.place_card(Card("node", ["obs", "excel", "unreal", "spotify"]), placed)
    check(node.group == "shared" and "групп" in node.rule,
          f"программа на несколько групп уходит в «Общие программы»: {node.rule}")
    check(not any(key in node.rule for key in ("engines", "record", "media",
                                               "office", "bridges", "devices")),
          f"и группы названы по-человечески, а не ключами: {node.rule}")
    one = pg.place_card(Card("obs-studio", ["obs"]), placed)
    check(one.group == "record" and "obs" in one.rule,
          f"а программа одного моста стоит в его группе: {one.rule}")
    ghost = pg.place_card(Card("призрак", ["такого-моста"]), placed)
    check(ghost.group == "other" and "нет мостов" in ghost.rule,
          f"программа без мостов попадает в «Прочее» с причиной: {ghost.rule}")
    xray = pg.place_card(Card("xray-core", []), placed)
    check(xray.group != "other" and xray.rule,
          f"а обход блокировок, у которого мостов нет вовсе, — не «Прочее»: "
          f"{xray.group}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
