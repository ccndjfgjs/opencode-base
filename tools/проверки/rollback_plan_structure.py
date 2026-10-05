#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Показывает, что скрипт структуры плана действительно падает.

Проверка «план и код совпадают» и скрипт, который следит за числом блоков,
легко превращаются в зелёный шум: они ничего не ловят, если никто не
проверял их на поломке. Здесь ломаем копию плана тремя способами и смотрим
код возврата каждой.
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
FENCE = chr(96) * 3

# (имя, что делаем с копией плана, ждём ли ненулевой код)
CASES = [
    # Первая проба проверяла не тот скрипт: число блоков считает
    # fix_task3_steps.py, а plan_matches_code.py ищет только функции — лишний
    # блок ему не мешает, и код остаётся 0. Отсюда «2 из 4».
    ("съеден блок python — сверка плана и кода (plan_matches_code)",
     "drop_block", "tools/проверки/plan_matches_code.py"),
    ("в функции опечатка — сверка плана и кода (plan_matches_code)",
     "typo", "tools/проверки/plan_matches_code.py"),
    ("смешаны уровни отступа — сверка плана и кода (plan_matches_code)",
     "mixed_indent", "tools/проверки/plan_matches_code.py"),
    # Дальше — поломки, которые обязана ловить СВЕРКА, а не инструмент
    # починки. Прежняя проба гоняла их на fix_task3_steps и conclude
    # «скрипт красный» — но это говорило о починке, а не о том, что сверка
    # охраняет план. Обе идут на сверку.
    #
    # Шаг 2 добавлен потому, что шаг без кода: убрать его — число блоков
    # не меняется, и сверка молчала бы. Счёт шагов её этому и учит.
    ("убран шаг 3 задачи 3 — сверка плана и кода",
     "drop_step", "tools/проверки/plan_matches_code.py"),
    ("убран шаг 2 задачи 3 — сверка плана и кода",
     "drop_step2", "tools/проверки/plan_matches_code.py"),
]


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="структура-плана-"))
    try:
        clean = base / "чистый"
        shutil.copytree(PROG, clean, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git"))
        code0 = subprocess.run([sys.executable, SCRIPT], cwd=clean,
                               capture_output=True).returncode
        print(f"чистая копия: код {code0} (ожидается 0)")
        if code0 != 0:
            print("ИТОГ: база не зелёная, проба бессмысленна")
            return 1

        rows = []
        print()
        print("| # | поломка | скрипт | код | ожидали |")
        print("|---|---------|--------|-----|---------|")
        for i, (name, kind, script) in enumerate(CASES, 1):
            tree = base / f"п{i}"
            shutil.copytree(clean, tree, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc"))
            plan = tree / "документы" / "2026-10-05-план-указатели-знаний.md"
            t = plan.read_text(encoding="utf-8")
            applied = True
            if kind == "drop_block":
                a = t.index("def _split_index(")
                a = t.rindex(f"{FENCE}python\n", 0, a)
                b = t.index(f"\n{FENCE}", a) + len(f"\n{FENCE}")
                t = t[:a] + t[b:]
            elif kind == "typo":
                applied = "return len(moved)" in t
                t = t.replace("return len(moved)", "return len(moved) + 1", 1)
            elif kind == "mixed_indent":
                # Новый блок, где на одной глубине смешаны 4 и 8 пробелов.
                # Применяем всегда: поломка не зависит от содержимого плана.
                t = (t + f"\n{FENCE}python\nif True:\n    x = 1\n"
                       f"        y = 2\n{FENCE}\n")
            elif kind == "drop_step":
                a = t.index("- [ ] **Шаг 3: реализуй**")
                b = t.index("- [ ] **Шаг 4: запусти", a)
                t = t[:a] + t[b:]
            elif kind == "drop_step2":
                a = t.index("- [ ] **Шаг 2: запусти и убедись, что падает**")
                b = t.index("- [ ] **Шаг 3: реализуй**", a)
                t = t[:a] + t[b:]
            plan.write_text(t, encoding="utf-8")
            code = subprocess.run([sys.executable, script], cwd=tree,
                                  capture_output=True).returncode
            ok = code != 0 and applied
            short = script.split("/")[-1]
            rows.append((i, name, short, code, ok))
            note = "" if applied else " (поломка не применилась)"
            verdict = ("ненулевой" if ok
                       else ("0 — НЕ СРАБОТАЛО" if applied else "подмена не прошла"))
            print(f"| {i} | {name} | {short} | {code} | {verdict}{note} |")
            shutil.rmtree(tree, ignore_errors=True)

        print()
        good = sum(1 for r in rows if r[4])
        print(f"сработало: {good} из {len(CASES)}")
        if good == len(CASES):
            print(f"ИТОГ: сверка краснеет на всех {len(CASES)} поломках, "
              f"и каждая проходит через неё, а не через инструмент починки.")
            return 0
        print("ИТОГ: скрипт где-то не сработал.")
        return 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())