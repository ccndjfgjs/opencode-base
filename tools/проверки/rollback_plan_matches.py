#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Откат скрипта `plan_matches_code.py`: доказательство, что он краснеет.

Зачем это нужно. После синхронизации плана с кодом проверка зелена по
построению: обе стороны скопированы друг из друга. Такая проверка ничего не
доказывает, пока не проверено, что она способна упасть. Здесь ровно это и
проверяется — поломки вносятся в копию плана, а скрипт запускается на ней.

Поломки настоящие: каждая меняет содержание так, что расхождение
невозможно не заметить. Ни одна не трогает файл настоящего плана.

Пути относительные от расположения скрипта.

Запуск: python tools/проверки/rollback_plan_matches.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent

SCRIPT = "tools/проверки/plan_matches_code.py"

# (имя, что ищем, чем заменяем, ожидаем ли ненулевой код)
BREAKS: list[tuple[str, str, str]] = [
    ("в функции плана опечатка",
     '    return text[:b], text[b:e + len(INDEX_END)], text[e + len(INDEX_END):]',
     '    return text[:b], text[b:e + len(INDEX_BEGIN)], text[e + len(INDEX_END):]'),
    ("из функции плана выброшена строка",
     '    known_tail = {k.split("/")[-1] for k in known}',
     '    known_tail = set()'),
    ("в функции плана сменилось имя",
     "def append_archive(folder: Path, moved: list[tuple[str, list[str]]],",
     "def append_archive2(folder: Path, moved: list[tuple[str, list[str]]],"),
    ("в плане функция заменена на прочерк",
     "    if not moved:\n        return 0\n    path = folder / ARCHIVE_NAME",
     "    if not moved:\n        return 0\n    path = None  # было ARCHIVE_NAME"),
    # В плане тест лежит фрагментом с отступом 8, а в селфтесте — 16.
    # Первая подмена искала 16 пробелов и не нашла ничего: поломка не
    # применилась, а не «проверка мимо». Отступы взяты из плана измерением.
    ("тест в плане искажён",
     "        check(core.ARCHIVE_NAME not in _after,",
     "        check(core.ARCHIVE_NAME in _after,"),
    ("тест в плане урезан",
     '              "указатель не ссылается на архив")',
     '              "указатель ссылается на архив, и это ошибка")'),
    # Строка поменялась, когда у теста появилась помеченная строка:
    # дословное сравнение строилось по началу строки, а сама пометка
    # проверялась отдельно. Поломка со старым текстом не применилась и
    # рапортовала «не поймана» — то есть проверка была мёртвой.
    ("тест в плане потерял проверку дословности",
     '        check("\\n".join(_norm_sem) == _expect,',
     '        check("\\n".join(_norm_sem) != _expect,'),
]


def _patch(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"ПОДМЕНА НЕ ПРОШЛА ({n} совпадений): {old[:60]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def run(tree: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, SCRIPT], cwd=tree, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="откат-плана-"))
    try:
        # Базовая копия: она обязана быть зелёной, иначе проверять нечего.
        clean = base / "чистый"
        shutil.copytree(PROG, clean, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git"))
        code0, out0 = run(clean)
        print("чистая копия (ожидаем 0):", code0)
        tail0 = [ln for ln in out0.splitlines() if ln.startswith("ИТОГ")]
        for ln in tail0:
            print("   ", ln)
        if code0 != 0:
            print("ИТОГ: база не зелёная — сначала приведи план и код к "
                  "одинаковому виду.")
            print(out0[-1500:])
            return 1

        ok = 0
        misses: list[str] = []
        print()
        print("| # | поломка | код | что поймала проверка |")
        print("|---|---------|-----|---------------------|")
        rows: list[tuple[int, str, int, str, bool]] = []
        for i, (name, old, new) in enumerate(BREAKS, 1):
            tree = base / f"поломка{i}"
            shutil.copytree(clean, tree, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc"))
            plan = tree / "документы" / "2026-10-05-план-указатели-знаний.md"
            try:
                _patch(plan, old, new)
            except SystemExit as exc:
                print(f"  {i}. {name}: {exc}")
                misses.append(name)
                rows.append((i, name, -1, "поломка не применилась", False))
                continue
            code, out = run(tree)
            red = [ln.strip() for ln in out.splitlines()
                   if "РАСХОДИТСЯ" in ln or "НЕ НАЙДЕН" in ln
                   or "НЕТ В ПЛАНЕ" in ln]
            first = red[0][:64] if red else "(причина не распознана)"
            caught = code != 0
            if caught:
                ok += 1
            else:
                misses.append(name)
            rows.append((i, name, code, first, caught))
            shutil.rmtree(tree, ignore_errors=True)

        print()
        for i, name, code, first, caught in rows:
            mark = "поймана" if caught else "НЕ ПОЙМАНА"
            print(f"| {i} | {name} | {code} | {mark}: {first} |")

        print()
        print(f"чистый план: код {code0} (ожидается 0)")
        print(f"поймано: {ok} из {len(BREAKS)}")
        if misses:
            print("не поймано:")
            for m in misses:
                print(f"  - {m}")
        print()
        if ok == len(BREAKS):
            print("ИТОГ: откат доказан — проверка умеет краснеть, и у всех "
                  "поломок код возврата 1.")
            return 0
        print("ИТОГ: откат НЕ доказан.")
        return 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())