#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ставит в план задачи 3 шаг 2 (красное состояние) и шаг 3 (код).

Смешавшиеся блоки: прежние версии этого скрипта искали границы по первой
обратной кавычке-тройке и по маркеру «Шаг 1: …», а он встречается в
каждой задаче. В итоге шаг 3 и шаг 2 исчезали из плана дважды.

Здесь границы явные: вставляем строго между последней строкой блока шага 1
и заголовком шага 4, внутри задачи 3. Проверяем результат счётом: шаг 2
один раз, шаг 3 один раз, тест один, код один.
"""
from pathlib import Path
import re
import sys

# Пути относительные от расположения скрипта. Абсолютный путь стоял здесь
# до измерения: в пробе отката скрипт правил НАСТОЯЩИЙ план вместо копии,
# и три поломки выглядели «не сработавшими» — на деле починка уезжала в
# оригинал, а проба честно показывала, что копия не тронута.
HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
PLAN = PROG / "документы" / "2026-10-05-план-указатели-знаний.md"
SELFTEST = PROG / "tools" / "dbapp" / "selftest.py"
CORE = PROG / "tools" / "dbapp" / "core.py"
FENCE = chr(96) * 3

# Ожидаемое число блоков ```python в плане. Задано числом и в этом скрипте,
# и в plan_matches_code.py: значение одно, иначе инструмент починки и
# проверка будут ждать разного.
EXPECTED_BLOCKS = 12

STEP2 = """- [ ] **Шаг 2: запусти и убедись, что падает**

Запуск: `python tools/dbapp/selftest.py`
Ожидание: `AttributeError: ... 'write_knowledge_index'`, код 1.

Красное состояние обязательно: без него нечем считать зелёное состояние
доказательством. Раньше шаг был в плане, а при правках плана потерялся —
и проверки появлялись сразу зелёными.

"""

STEP3_HEAD = "- [ ] **Шаг 3: реализуй**\n\n"


def code_body() -> str:
    core = CORE.read_text(encoding="utf-8-sig")
    parts = []
    for name in ("_split_index", "_referenced_paths", "_orphaned_lines",
                 "append_archive", "write_knowledge_index"):
        m = re.search(rf"^def {re.escape(name)}\(.*?(?=\n\n\n|\Z)",
                      core, re.S | re.M)
        if not m:
            raise SystemExit(f"нет функции {name}")
        parts.append(m.group(0).rstrip())
    return "\n\n\n".join(parts)


def main() -> int:
    text = PLAN.read_text(encoding="utf-8")
    task = text.index("## Задача 3:")
    task_end = text.index("## Задача 4а:")
    seg = text[task:task_end]

    # Уже на месте — ничего не вставляем, только перепроверяем.
    if "**Шаг 2: запусти" not in seg:
        anchor = seg.index("- [ ] **Шаг 4: запусти")
        seg = seg[:anchor] + STEP2 + seg[anchor:]
        task_end = task + len(seg)

    if "**Шаг 3: реализуй**" not in seg:
        anchor = seg.index("- [ ] **Шаг 4: запусти")
        block = STEP3_HEAD + f"{FENCE}python\n" + code_body() + f"\n{FENCE}\n\n"
        seg = seg[:anchor] + block + seg[anchor:]
    else:
        # Шаг 3 есть, а блока кода внутри нет. Удаляем пустое место ДО
        # вставки: иначе «старым блоком» оказывается только что вставленный
        # и следующая же строка его съедает. Порядок найден пробой — блоков
        # после починки оставалось 11 вместо 12.
        s3 = seg.find("**Шаг 3: реализуй**")
        s4 = seg.find("- [ ] **Шаг 4: запусти", s3)
        if s3 >= 0 and s4 > s3 and "def _split_index(" not in seg[s3:s4]:
            old_fence = seg.find(f"{FENCE}python\n", s3)
            if 0 <= old_fence < s4:
                old_end = seg.index(f"\n{FENCE}", old_fence) + len(f"\n{FENCE}\n")
                seg = seg[:old_fence] + seg[old_end:]
            s4 = seg.find("- [ ] **Шаг 4: запусти", s3)
            block = (STEP3_HEAD + f"{FENCE}python\n" + code_body()
                     + f"\n{FENCE}\n\n")
            seg = seg[:s4] + block + seg[s4:]

    # Обновляем тест в шаге 1 — по границам блока, а не по маркеру.
    s = SELFTEST.read_text(encoding="utf-8")
    a = s.index("    # ---- 8ц-3. Пересборка")
    b = s.index("shutil.rmtree(_k3, ignore_errors=True)", a) + len(
        "shutil.rmtree(_k3, ignore_errors=True)")
    body = "\n".join(ln[8:] if ln.startswith("            ") else ln
                     for ln in s[a:b].split("\n")).rstrip("\n")
    f_open = seg.index(f"{FENCE}python\n")
    f_body = f_open + len(f"{FENCE}python\n")
    f_close = seg.index(f"\n{FENCE}", f_body)
    seg = seg[:f_body] + body + "\n" + seg[f_close:]

    PLAN.write_text(text[:task] + seg + text[task_end:], encoding="utf-8")

    final = PLAN.read_text(encoding="utf-8")
    ft = final.index("## Задача 3:")
    fe = final.index("## Задача 4а:")
    fs = final[ft:fe]
    checks = {
        "шаг 2": fs.count("**Шаг 2: запусти"),
        "шаг 3": fs.count("**Шаг 3: реализуй**"),
        "тест 8ц-3": fs.count("8ц-3. Пересборка"),
        "код _split_index": fs.count("def _split_index("),
        "шаг 4": fs.count("**Шаг 4: запусти"),
    }
    print("в задаче 3 плана:")
    for k, v in checks.items():
        want = 1
        print(f"  {k}: {v} (ждать {want})")
    bad = any(v != 1 for v in checks.values())

    # Число блоков во всём плане. Без этой проверки инструмент рапортовал об
    # успехе, оставив план с неверным числом блоков: шаги все на месте,
    # а сверка потом краснела. Молчаливый полууспех хуче явного отказа.
    n_blocks = final.count(f"{FENCE}python\n")
    print(f"блоков python во всём плане: {n_blocks} (ждать "
          f"{EXPECTED_BLOCKS})")
    if n_blocks != EXPECTED_BLOCKS:
        bad = True

    print("ИТОГ:", "структура верна" if not bad else "НАРУШЕНА")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())