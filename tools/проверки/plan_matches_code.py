#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сверяет код внутри плана с рабочим кодом.

Зачем. План — не документ для чтения, а инструкция к исполнению. Код в нём
обязан быть рабочим: иначе следующий заход по плану скопирует в core.py то,
что не запустится. Именно так и вышло: в плане долго стояло
`body = fresh_after or ...`, и этот код оттуда и пришёл в задачу 3.

Проверок тут три, и все три обязаны уметь краснеть:

1. каждый блок python в плане разбирается как код;
2. функции задачи 3 в плане совпадают с рабочими;
3. тест раздела 8ц-3 в плане совпадает с рабочим.

Оговорка про полезность. Сверка ловит расхождение кода и плана, но не
доказывает, что код верен: после синхронизации она зелена по построению.
Защита от устаревания, не замена откату. Проверка, что она способна краснеть,
живёт в `rollback_plan_matches.py`.

Пути относительные от расположения скрипта: так он работает и на
конструкторе в Downloads, и на репозиторий, и на чужой машине.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
PLAN = PROG / "документы" / "2026-10-05-план-указатели-знаний.md"
CORE = PROG / "tools" / "dbapp" / "core.py"
SELFTEST = PROG / "tools" / "dbapp" / "selftest.py"

FENCE = chr(96) * 3

FUNCS = ("_split_index", "_referenced_paths", "_orphaned_lines",
         "append_archive", "write_knowledge_index")

# Число блоков ```python в плане. Задано числом: вычислять его из того же
# плана бессмысленно — съеденный блок уменьшит и ожидаемое.
EXPECTED_BLOCKS = 12

# Число шагов в задаче 3. Проверять только блоки мало: шаг 2 не содержит
# кода, и его пропажа не меняет числа блоков. Считается числом, не из
# плана: вычислять ожидаемое из того же файла бессмысленно.
EXPECTED_STEPS = 5


def blocks(text: str) -> list[tuple[int, str]]:
    """Блоки ```python с номером первой строки. Номер нужен, чтобы
    показать, где лежит блок, а не только что он есть."""
    out: list[tuple[int, str]] = []
    pos = 0
    while True:
        start = text.find(f"{FENCE}python\n", pos)
        if start < 0:
            return out
        line_no = text.count("\n", 0, start) + 1
        body_start = start + len(f"{FENCE}python\n")
        end = text.find(f"\n{FENCE}", body_start)
        if end < 0:
            return out
        out.append((line_no, text[body_start:end + 1]))
        pos = end + 1


def _norm(s: str) -> str:
    """Схлопывает переносы, чтобы разница в разбивке строк не считалась
    расхождением. Содержательные различия остаются видимыми."""
    return re.sub(r"[ \t]*\n[ \t]*", "\n", s).strip()


def _grab_func(text: str, name: str) -> str | None:
    """Тело функции целиком, по границам — две пустые строки."""
    m = re.search(rf"^def {re.escape(name)}\(.*?(?=\n\n\n|\Z)",
                  text, re.S | re.M)
    return m.group(0).rstrip() if m else None


def check_blocks(bs: list[tuple[int, str]]) -> int:
    """Разбирается ли каждый блок. Возвращает число непроверяемых."""
    print(f"=== 1. блоки {FENCE}python разбираются как код ({len(bs)}) ===")
    # Ожидаемое число блоков задано числом, а не вычисляется: иначе съеденный
    # блок уменьшит и ожидаемое, и оба пройдут. Съедание блока кода задачи 3
    # случалось дважды и оба раза маскировалось словами «регулярка не находит».
    print(f"  ожидается блоков: {EXPECTED_BLOCKS}")
    if len(bs) != EXPECTED_BLOCKS:
        print(f"  ЧИСЛО БЛОКОВ РАСХОДИТСЯ: {len(bs)} вместо "
              f"{EXPECTED_BLOCKS}")
    skipped = 0
    for line_no, b in bs:
        first = next((ln.strip() for ln in b.split("\n")
                      if ln.strip() and not ln.strip().startswith("#")), "?")
        # Фрагмент из тела функции не является файлом: он начинается с
        # отступа. Такой оборачиваем в def — тогда отступ законен. Но если
        # внутри смешаны уровни отступа или есть пропуск, обёртка не поможет,
        # и это разбирается отдельно: такие блоки перечисляются как
        # непроверяемые, а не как ошибки.
        indented = b[:1].isspace()
        wrapped = f"def _фрагмент():\n{b}" if indented else b
        where = "фрагмент" if indented else "целиком"
        try:
            ast.parse(wrapped)
            print(f"  строка {line_no:5}  ок ({where:8}) {first[:48]}")
        except SyntaxError as exc:
            skipped += 1
            print(f"  строка {line_no:5}  НЕ ПРОВЕРЕН ({where:8}) "
                  f"строка {exc.lineno}: {exc.msg}")
            print(f"                          начало: {first[:48]}")
    if skipped:
        print(f"  непроверяемых блоков: {skipped}. Они не фрагменты тела")
        print("  функции целиком — это куски с пропусками или смесью")
        print("  уровней отступа, и разбирать их в отрыве от контекста нечем.")
    return skipped


def check_funcs(core: str, bs: list[tuple[int, str]]) -> int:
    print()
    print("=== 2. функции плана совпадают с рабочими ===")
    bad = 0
    for name in FUNCS:
        real = _grab_func(core, name)
        if real is None:
            print(f"  {name}: НЕТ В core.py — это дефект кода")
            bad += 1
            continue
        where = []
        ok = False
        for line_no, b in bs:
            got = _grab_func(b, name)
            if got is None:
                continue
            where.append(line_no)
            if _norm(got) == _norm(real):
                ok = True
        if ok:
            print(f"  {name}: совпадает (блок на строке {where[0]})")
        else:
            bad += 1
            if where:
                print(f"  {name}: РАСХОДИТСЯ (блок на строке {where[0]})")
                for a, c in _first_diff(real, _grab_func(
                        next(b for ln, b in bs if ln == where[0]), name)):
                    print(f"      в core.py: {a!r}")
                    print(f"      в плане:   {c!r}")
                    break
            else:
                print(f"  {name}: НЕТ В ПЛАНЕ (ищем `def {name}(` в "
                      f"{len(bs)} блоках)")
    return bad


def _first_diff(real: str, plan: str) -> list[tuple[str, str]]:
    rl, pl = _norm(real).split("\n"), _norm(plan).split("\n")
    for i in range(max(len(rl), len(pl))):
        a = rl[i] if i < len(rl) else "<нет строки>"
        c = pl[i] if i < len(pl) else "<нет строки>"
        if a != c:
            return [(a, c)]
    return []


def check_test(selftest: str, bs: list[tuple[int, str]]) -> int:
    print()
    print("=== 3. тест 8ц-3 в плане совпадает с рабочим ===")
    s = selftest.index("    # ---- 8ц-3. Пересборка")
    e = selftest.index("shutil.rmtree(_k3, ignore_errors=True)", s)
    real = "\n".join(
        ln[8:] if ln.startswith("            ") else ln
        for ln in selftest[s:e].split("\n")).rstrip()
    for line_no, b in bs:
        if "8ц-3" in b and real in b:
            print(f"  совпадает (блок на строке {line_no})")
            return 0
    for line_no, b in bs:
        if "8ц-3" not in b:
            continue
        print("  РАСХОДИТСЯ")
        for a, c in _first_diff(real, b) or []:
            print(f"    в selftest: {a!r}")
            print(f"    в плане:    {c!r}")
        return 1
    print("  НЕ НАЙДЕН блок с тестом 8ц-3")
    return 1


def main() -> int:
    plan = PLAN.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8-sig")
    selftest = SELFTEST.read_text(encoding="utf-8")
    bs = blocks(plan)

    skipped = check_blocks(bs)
    bad = check_funcs(core, bs)
    bad += check_test(selftest, bs)
    if len(bs) != EXPECTED_BLOCKS:
        bad += 1
    # Шаги задачи 3 — отдельный счёт, см. пункт 4 ниже.
    t3 = plan.index("## Задача 3:")
    t3_end = plan.find("## Задача 4", t3 + 1)
    plan_task = plan[t3:t3_end if t3_end > 0 else len(plan)]
    n_steps = len(re.findall(r"^- \[ \] \*\*Шаг \d+", plan_task, re.M))
    if n_steps != EXPECTED_STEPS:
        bad += 1

    print()
    # Число шагов задачи 3. Шаг без кода (например шаг 2 — «запусти и
    # убедись, что падает») при пропаже не меняет числа блоков, и сверка
    # молчала бы. Отдельная проверка это закрывает.
    plan_steps = re.findall(r"^- \[ \] \*\*Шаг \d+", plan_task, re.M)
    print(f"=== 4. шаги задачи 3: {len(plan_steps)} (ждать {EXPECTED_STEPS}) ===")
    if len(plan_steps) != EXPECTED_STEPS:
        print(f"  ЧИСЛО ШАГОВ РАСХОДИТСЯ: {len(plan_steps)} вместо "
              f"{EXPECTED_STEPS}")

    print()
    print("ИТОГ:", "плана и кода не расходится" if bad == 0
          else f"расхождений {bad}")
    if skipped:
        # Непустая категория «не проверено» — это ослабление, и молчать
        # о нём нельзя: блок, который перестал разбираться, выглядит так
        # же, как блок, который просто не проверялся. Краснеем.
        print(f"ВНИМАНИЕ: {skipped} блоков не проверены (см. пункт 1). "
              f"Это ослабление проверки.")
        return 1
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())