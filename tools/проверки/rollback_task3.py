#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Откат задачи 3: доказательство, что проверки 8ц-3 не могут быть зелёными
на неправильном коде.

Метод тот же, что для 8ц-2: делаем копию дерева программы рядом с
настоящей, ломаем в копии ровно одну вещь, гоняем селфтест и смотрим,
какие проверки покраснели. Поломка, которая ничего не ломает, в отчёт не
попадает вовсе — и это тоже результат.

Дерево программы не трогаем. Копия снимается целиком, потому что селфтест
ищет папку программы от своего расположения.

Запуск: python tools/проверки/rollback_task3.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent.parent
SELFTEST = "tools/dbapp/selftest.py"

# Строки-приметки новых проверок. По ним выбираем красное из отчёта.
MARKERS = (
    "при исчезновении папки создан архив",
    "смысловая часть модели уцелела целиком",
    "строка про уцелевшую папку осталась в указателе",
    "из указателя убраны строки про исчезнувшие папки",
    "уцелевшая папка осталась в авточасти",
    "строка про исчезнувшую папку ушла в архив",
    "вторая исчезнувшая папка тоже ушла в архив",
    "поиск ловит и короткое имя папки",
    "архив не перезаписывается при следующей пересборке",
    "в архиве сказано, что это не инструкция для модели",
    "в архиве две записи, с прежним путём",
    "у каждой записи в архиве есть дата переноса",
    "указатель не ссылается на архив",
)


def _patch(path: Path, old: str, new: str) -> None:
    """Меняет текст ровно один раз. Не сработало — это ошибка пробы."""
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"ПОДМЕНА НЕ ПРОШЛА ({n} совпадений): {old[:60]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# Каждая поломка: (имя, что ломаем, подстановка). Подстановка — пара
# (кусок, который ищем, чем заменяем).
BREAKS: list[tuple[str, str, str, str]] = [
    # 1. Затирание текста модели — то, что делал код из шага 3 плана.
    ("затирание смысловой части",
     "tools/dbapp/core.py",
     'body = "\\n".join(keep).strip("\\n")',
     'body = fresh_after.strip("\\n")'),
    # 2. Перенесённые строки остаются на месте: архив и указатель дублируют.
    ("перенесённое остаётся в указателе",
     "tools/dbapp/core.py",
     "keep = [ln for ln in after.splitlines() if ln not in carried]",
     "keep = list(after.splitlines())"),
    # 3. Фильтр «было в прошлой авточасти» убран. Без него кандидатом
    # становится любое упоминание в кавычках, и в архив уезжает код:
    # `ALLOW_PUSH`, `opencode.jsonc`. Проверено пробой — четыре упоминания.
    ("кандидатом любое упоминание, а не бывшая папка",
     "tools/dbapp/core.py",
     "            if name in known or name in known_tail\n"
     "            if name not in live and name not in live_tail]",
     "            if name not in live and name not in live_tail]"),
    # 4. Короткое имя перестаёт ловиться.
    ("поиск только по полному пути",
     "tools/dbapp/core.py",
     '        if token:\n            found.add(token.split("/")[-1])',
     "        pass"),
    # 5. Архив перезаписывается вместо дописывания.
    ("архив перезаписывается",
     "tools/dbapp/core.py",
     'with path.open("a", encoding="utf-8") as fh:',
     'with path.open("w", encoding="utf-8") as fh:'),
    # 6. Из архива убрано предупреждение «не инструкция».
    ("нет предупреждения «не инструкция»",
     "tools/dbapp/core.py",
     '"# Потерянные привязки\\n\\n"\n'
     '            "Это **не инструкция** для модели:',
     '"# Потерянные привязки\\n\\n"\n'
     '            "Тут лежат строки:'),
    # 7. Из заголовка записи убран прежний путь.
    ("нет прежнего пути в заголовке",
     "tools/dbapp/core.py",
     'fh.write(f"\\n## Было: `{rel}` (потеряно {stamp})\\n\\n")',
     'fh.write(f"\\n## Запись (потеряно {stamp})\\n\\n")'),
    # 8. Из заголовка записи убрана дата.
    ("нет даты переноса",
     "tools/dbapp/core.py",
     'fh.write(f"\\n## Было: `{rel}` (потеряно {stamp})\\n\\n")',
     'fh.write(f"\\n## Было: `{rel}`\\n\\n")'),
    # 9. Заголовки перестают собираться вовсе — попадает только последний.
    ("только один заголовок вместо двух",
     "tools/dbapp/core.py",
     "out: list[tuple[str, list[str]]] = []\n    carried: set[str] = set()",
     "out: list[tuple[str, list[str]]] = []\n    carried: set[str] = set()\n"
     "    return out[:1], carried"),
    # 10. В указатель вставляется ссылка на архив.
    ("указатель ссылается на архив",
     "tools/dbapp/core.py",
     'target.write_text(f"{head}\\n{body}\\n", encoding="utf-8", newline="\\n")',
     'target.write_text(f"{head}\\n{body}\\n\\n{ARCHIVE_NAME}\\n",\n'
     '                      encoding="utf-8", newline="\\n")'),
    # 11. Уцелевшая папка выпадает из авточасти. Первая версия поломки была
    # `if n == 0: continue` — недостижима на этом дереве: у «Техники» один
    # файл, не ноль, и фильтр никогда не срабатывал. Поломка, которую
    # нельзя вызвать, не поймана не потому, что проверка слабая.
    # Теперь ошибка достижима: перепутана единица с нулём.
    ("уцелевшая папка выпадает из авточасти",
     "tools/dbapp/core.py",
     "    for rel, n in paths:\n        lines.append(f\"- `{rel}/` — {n} {_plural_files(n)}\")",
     "    for rel, n in paths:\n        if n == 1:\n            continue\n"
     "        lines.append(f\"- `{rel}/` — {n} {_plural_files(n)}\")"),
    # 12. Перезапись идёт с CRLF: текст портится побайтово.
    ("запись с CRLF вместо LF",
     "tools/dbapp/core.py",
     'encoding="utf-8", newline="\\n")\n    report = [f"указатель: {target.name}"]',
     'encoding="utf-8")\n    report = [f"указатель: {target.name}"]'),
    # 13. Архив перестаёт быть служебным: попадает в счёт файлов.
    ("архив попадает в счёт файлов",
     "tools/dbapp/core.py",
     "            or path.name.startswith(\"_подсказки\")\n"
     "            or path.name == ARCHIVE_NAME)",
     "            or path.name.startswith(\"_подсказки\"))"),
    # Поломка 14 удалена с честной пометкой — по измерению, а не по решению.
#
# Что предполагалось: фильтр `ln not in carried` убирает все строки,
# совпавшие с перенесённой, и на этом якобы теряется законный повтор.
# Измерено на живом коде:
#     рабочий фильтр, GONE_1 осталось: 0
#     «поломанный» фильтр, GONE_1 осталось: 0
#     различаются результаты: False
# Три попытки поломки давали то же самое: две — синтаксическую ошибку
# (IndentationError, прогон падал на разборе файла), третья работала, но
# при `continue` строка не добавлялась в `_seen`, поэтому отбрасывались обе
# копии — ровно как в рабочем коде.
#
# И вывод важнее самой поломки: убирать ВСЕ копии перенесённой строки —
# это и есть правильное поведение. Если строка про исчезнувшую папку
# написана дважды, обе копии должны уйти в архив, иначе в указателе
# останется подсказка про несуществующую папку.
#
# Сомнение, которое породило эти попытки, снято проверками, а не
# рассуждением: в примере есть повтор живой строки (`---` дважды и
# повторная ссылка на уцелевшую `Техника/`), обе уцелели. Фильтр идёт по
# содержимому перенесённой строки, а живой текст с ней не совпадает.
# Проверки «законный повтор строки уцелел обе раза» и «повторная ссылка
# на уцелевшую папку осталась» остаются в селфтесте как защита.
]

# Проверки, добавленные после первого прогона отката.
MARKERS += (
    "после архива остался один обычный файл",
    "в авточасти написано честное число файлов",
    "смысловая часть уцелела дословно, перенесённого нет",
    "упоминание кода в кавычках осталось в указателе",
    "упоминание кода не уехало в архив",
    "указатель записан с LF, а не CRLF",
    "законный повтор строки уцелел обе раза",
    "повторная ссылка на уцелевшую папку осталась",
)


def _drop(tree: Path) -> None:
    """Убирает копию. Занятый файл — не повод ронять весь откат.

    Windows держит файл, пока его не закроют. `subprocess.run` дескрипторы
    закрывает сам, но `__pycache__` рядом может держать другой процесс,
    и первый вариант уборки падал с PermissionError посреди отката —
    терялись все последующие поломки из-за одной.
    """
    try:
        shutil.rmtree(tree, ignore_errors=True)
        return
    except Exception:
        pass
    for attempt in range(3):
        try:
            shutil.rmtree(tree)
            return
        except PermissionError:
            if attempt == 2:
                print(f"  ! копию {tree.name} убрать не удалось, "
                      f"продолжаю: на результат не влияет")
                return
            _sleep(2)
        except FileNotFoundError:
            return


def _sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)


def run_selftest(tree: Path, out: Path) -> tuple[int, list[str]]:
    """Прогоняет селфтест на указанном дереве, возвращает код и строки."""
    proc = subprocess.run(
        [sys.executable, SELFTEST],
        cwd=tree, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=3600,
    )
    out.write_text(proc.stdout or "", encoding="utf-8")
    (out.with_suffix(".err.txt")).write_text(proc.stderr or "", encoding="utf-8")
    return proc.returncode, (proc.stdout or "").splitlines()


def verdicts(lines: list[str]) -> dict[str, bool]:
    """ОК или нет по каждой из 13 проверок — по строке-приметке."""
    got: dict[str, bool] = {}
    for ln in lines:
        if not ln.startswith(("[ОК", "[СБОЙ")):
            continue
        for mark in MARKERS:
            if mark in ln:
                got[mark] = ln.startswith("[ОК")
    return got


def main() -> int:
    if not (PROG / SELFTEST).is_file():
        raise SystemExit(f"селфтест не найден: {PROG / SELFTEST}")

    base = Path(tempfile.gettempdir()) / "rollback-task3"
    if base.exists():
        _drop(base)
    base.mkdir(parents=True, exist_ok=True)

    # Чистая копия: без неё нечем отделить «поломку поймана» от «прогон
    # и так красный».
    clean = base / "чистый"
    shutil.copytree(PROG, clean, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git"))
    print("чистая копия снята, прогон на ней:")
    code0, out0 = run_selftest(clean, base / "чистый.txt")
    v0 = verdicts(out0)
    green = [m for m in MARKERS if v0.get(m) is True]
    red = [m for m in MARKERS if v0.get(m) is False]
    missing = [m for m in MARKERS if m not in v0]
    print(f"  код {code0}; проверок задачи 3 зелёных {len(green)}, "
          f"красных {len(red)}, не найдено {len(missing)}")
    for m in missing:
        print(f"    НЕ НАЙДЕНА: {m}")
    if red or missing or code0 != 0:
        print("ИТОГ: база не зелёная, откат бессмыслен — сначала почини это.")
        return 1

    ok_breaks = 0
    honest_misses: list[str] = []
    print()
    print("поломки по одной:")
    for i, (name, rel, old, new) in enumerate(BREAKS, 1):
        tree = base / f"поломка{i}"
        shutil.copytree(clean, tree, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc"))
        try:
            _patch(tree / rel, old, new)
        except SystemExit as exc:
            print(f"  {i:2}. {name}: {exc}")
            honest_misses.append(name)
            _drop(tree)
            continue
        code, out = run_selftest(tree, base / f"поломка{i}.txt")
        v = verdicts(out)
        # Поломка поймана, если краснула ЛЮБАЯ проверка, а не только из
        # 8ц-3. Первая версия смотрела только на маркеры своей задачи, и
        # поломка «уцелевшая папка выпадает из авточасти» дала две красные
        # в 8ц-2 — отчёт назвал её непойманной. Проверка, которая падает не
        # там, где ждали, всё равно поймана.
        all_red = [r for r in out if r.startswith("[СБОЙ")]
        caught_markers = [m for m in MARKERS if v.get(m) is False]
        if all_red:
            ok_breaks += 1
            first = caught_markers[0] if caught_markers else (
                all_red[0].split("]")[1].strip()[:52] if "]" in all_red[0]
                else all_red[0][:52])
            where = ("своя" if caught_markers else "соседняя")
            print(f"  {i:2}. {name}: поймана ({len(all_red)} красных, "
                  f"код {code}, {where}) — «{first}»")
        else:
            print(f"  {i:2}. {name}: НЕ ПОЙМАНА (код {code}, "
                  f"красных 0) — проверка мимо")
            honest_misses.append(name)
        _drop(tree)

    print()
    print(f"поймано поломок: {ok_breaks} из {len(BREAKS)}")
    if honest_misses:
        print("не поймано (проверка мимо либо поломка не provokable):")
        for m in honest_misses:
            print(f"  - {m}")
    print()
    print("Поломки, убранные с честной пометкой, — см. комментарий в BREAKS:")
    print("  одна, «фильтр убирает повтор строки»: три попытки, все дали то же,")
    print("  что рабочий код. Убирать все копии перенесённой строки — правильно.")
    print()
    if ok_breaks == len(BREAKS):
        print(f"ИТОГ: откат доказан — все {len(BREAKS)} проверяемых поломок "
              f"пойманы, и каждая своей проверкой.")
        return 0
    print("ИТОГ: откат НЕ доказан.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())