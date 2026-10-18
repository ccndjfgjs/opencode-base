"""Проверки таблицы версий мостов: что нужно каждому мосту и как это сверяется.

Запуск: python tools/dbapp/test_bridge_versions.py

Главное здесь — не «всё согласовано», а «сверка ловит расхождение». Если
проверка только радуется, она ничего не охраняет: сдвинь версию в таблице —
и посмотри, скажет ли она об этом.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bridge_versions as bv  # noqa: E402
import mcp_registry  # noqa: E402

PROGRAM_ROOT = HERE.parent.parent
TMP = Path(tempfile.gettempdir()) / "opencode" / "проверка-версий-мостов"

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


def fake_program(mutate=None) -> Path:
    """Копия программы с реестром и таблицей: на ней сверка и проверяется."""
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    data_dir = TMP / "данные"
    data_dir.mkdir(parents=True, exist_ok=True)
    registry = mcp_registry.registry_path(PROGRAM_ROOT)
    shutil.copy2(registry, data_dir / registry.name)
    table = json.loads(bv.table_path(PROGRAM_ROOT).read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(table)
    (data_dir / bv.TABLE_NAME).write_text(
        json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return TMP


def main() -> int:
    # === 1. Таблица читается и описывает все мосты ===
    data, note = bv.load(PROGRAM_ROOT)
    check(data is not None, f"таблица версий читается: {note}")
    if data is None:
        print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
        return 1

    servers = mcp_registry.load_servers(PROGRAM_ROOT)
    ids = {str(s.id) for s in servers}
    bridges = set(data.get("bridges") or {})
    missing = sorted(ids - bridges)
    extra = sorted(bridges - ids)
    check(not missing,
          f"у каждого моста реестра есть запись ({len(ids)} шт.)"
          + (f" — нет: {missing}" if missing else ""))
    check(not extra, f"лишних записей нет" + (f" — лишние: {extra}" if extra else ""))

    # === 2. Что нужно конкретному мосту ===
    unity = bv.for_bridge("unity", PROGRAM_ROOT)
    check(unity.known and "10.3.0" in unity.server,
          f"для Unity названа версия сервера: {unity.server}")
    check("unity-mcp" in unity.plugin and "10.3.0" in unity.plugin,
          f"и версия плагина: {unity.plugin}")
    check(bool(unity.lines()) and len(unity.lines()) >= 3,
          f"строк получилось столько, сколько нужно: {len(unity.lines())}")
    unreal = bv.for_bridge("unreal", PROGRAM_ROOT)
    check("встроенный сервер плагина" in unreal.server
          and "0.6.0-beta-f" in unreal.plugin,
          f"у Unreal сервер внутри плагина, версия одна: {unreal.server} / "
          f"{unreal.plugin}")
    check("не проверен" in " ".join(unreal.lines()),
          f"и порт по умолчанию помечен непроверенным: {unreal.lines()[-1][:90]}")
    roblox = bv.for_bridge("roblox-studio", PROGRAM_ROOT)
    check("встроен" in roblox.plugin or not roblox.plugin,
          f"у Roblox плагина нет и сказано честно: {roblox.plugin}")
    unpinned = bv.for_bridge("windows-admin", PROGRAM_ROOT)
    check(not unpinned.server_pinned and "не закреплена" in unpinned.lines()[1],
          f"незакреплённая версия названа честно: {unpinned.lines()[1]}")

    # === 3. Незнакомый мост — тоже ответ ===
    stranger = bv.for_bridge("такого-моста", PROGRAM_ROOT)
    check(not stranger.known and "нет моста" in stranger.note,
          f"незнакомый мост не выдумывает версий: {stranger.note[:60]}")

    # === 4. Сверка на настоящей программе ===
    ok, why = bv.audit(PROGRAM_ROOT)
    check(ok, f"настоящая таблица согласована с кодом и указателями: {why}")

    # === 5. Сверка ЛОВИТ расхождение ===
    # Это главная часть: если сверка только радуется, она ничего не охраняет.

    def break_version(table):
        table["bridges"]["unity"]["mcp_server"]["spec"] = "mcpforunityserver==99.9.9"

    ok_bad, why_bad = bv.audit(fake_program(break_version))
    check(not ok_bad and "unity" in why_bad,
          f"разошлась версия в таблице и в коде — сверка сказала: {why_bad[:90]}")

    def break_plugin(table):
        table["bridges"]["unreal"]["plugin"]["version"] = "0.6.0-beta-e"

    ok_bad2, why_bad2 = bv.audit(fake_program(break_plugin))
    check(not ok_bad2 and "unreal" in why_bad2,
          f"плагин разошёлся с указателем — сверка сказала: {why_bad2[:90]}")

    def drop_bridge(table):
        table["bridges"].pop("godot", None)

    ok_bad3, why_bad3 = bv.audit(fake_program(drop_bridge))
    check(not ok_bad3 and "godot" in why_bad3,
          f"мост без записи о версиях — сверка сказала: {why_bad3[:90]}")

    def add_stranger(table):
        table["bridges"]["мост-призрак"] = table["bridges"]["unity"]

    ok_bad4, why_bad4 = bv.audit(fake_program(add_stranger))
    check(not ok_bad4 and "мост-призрак" in why_bad4,
          f"запись без моста в реестре — сверка сказала: {why_bad4[:90]}")

    # === 6. Битая таблица — причина словами, а не исключение ===
    broken_dir = TMP / "битая"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / bv.TABLE_NAME).write_text("{ не json", encoding="utf-8")
    data_bad, note_bad = bv.load(broken_dir)
    check(data_bad is None and "не читается" in note_bad,
          f"битый файл назван словами: {note_bad[:60]}")
    empty_dir = TMP / "пустая"
    empty_dir.mkdir(parents=True, exist_ok=True)
    (empty_dir / bv.TABLE_NAME).write_text('{"bridges": {}}', encoding="utf-8")
    data_empty, note_empty = bv.load(empty_dir)
    check(data_empty is None and "ни одного моста" in note_empty,
          f"пустая таблица — тоже отказ: {note_empty[:60]}")

    shutil.rmtree(TMP, ignore_errors=True)
    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
