#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Откат подключения: create_base, подключение базы, правила знаний.

Задачи 4, 5 и 6. Пятнадцать новых проверок селфтеста без своих поломок
недоказанны: зелёная проверка, которую ничто не роняет, не отличается от
мёртвой. Здесь каждая поломка — настоящая порча кода, а проверка должна
покраснеть.

Проба идёт в копии, а не в настоящей папке программы: правило «пробы
только в пробном репозитории» нарушалось с коммитом, и пачка проб
уезжала в оригинал.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
SELFTEST = "tools/dbapp/selftest.py"


def _patch(path: Path, old: str, new: str) -> None:
    """Меняет текст ровно один раз. Не сработало — ошибка пробы."""
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"ПОДМЕНА НЕ ПРОШЛА ({n} совпадений): {old[:70]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


BREAKS: list[tuple[str, str, str, str]] = [
    # 1. Пересборка не делает ничего. Раньше указатели знаний не появлялись
    #    нигде, и это выглядело как «функция есть, пользы нет».
    ("пересборка указателей ничего не делает",
     "tools/dbapp/core.py",
     '    messages: list[str] = []\n'
     '    stamp = datetime.now().strftime("%Y-%m-%d")\n'
     '    made = 0',
     '    return []\n'
     '    messages: list[str] = []\n'
     '    stamp = datetime.now().strftime("%Y-%m-%d")\n'
     '    made = 0'),
    # 2. Папки создаются молча. У человека может не быть области «Деньги»,
    #    и заводить её без спроса — значит врать о структуре базы.
    ("пересборка выдумывает отсутствующие папки",
     "tools/dbapp/core.py",
     '        if not folder.is_dir():\n'
     '            messages.append(f"{rel}/{fname}: нет папки, указатель не создан")\n'
     '            continue',
     '        if not folder.is_dir():\n'
     '            folder.mkdir(parents=True, exist_ok=True)'),
    # 3. О несуществующих папках молчат. Тогда человек не видит, чего у него
    #    нет, и считает базу полной.
    ("о несуществующих папках не сказано",
     "tools/dbapp/core.py",
     '            messages.append(f"{rel}/{fname}: нет папки, указатель не создан")',
     '            pass'),
    # 4. create_base пересборку не зовёт — то есть исходная беда.
    ("создание базы не зовёт пересборку указателей",
     "tools/dbapp/core.py",
     '    # Указатели знаний — тоже часть новой базы: без них знания лежат, а\n'
     '    # карты к ним нет, и модель не знает, куда смотреть.\n'
     '    for message in refresh_knowledge_indexes(target):\n'
     '        say(message)',
     '    pass  # пересборка указателей не вызвана'),
    # 5. Подключение существующей базы пересборку не зовёт.
    ("подключение базы не зовёт пересборку указателей",
     "tools/dbapp/core.py",
     '        # Существующая база тоже должна получить указатели: их могло не\n'
     '        # быть вовсе, а знания в ней уже есть. Иначе перенос потерянных\n'
     '        # привязок в архив так и не включался бы на живой базе.\n'
     '        for message in refresh_knowledge_indexes(base):\n'
     '            say(message)',
     '        pass  # пересборка указателей не вызвана'),
    # 6. Правила знаний называют не все указатели. Модель пошла бы открывать
    #    то, чего в базе нет, — а это ровно то, из-за чего пришлось завести
    #    одиннадцать файлов вместо двух.
    #    Первый вариант поломки возвращал пустой список, и селфтест падал с
    #    исключением раньше, чем напечатал первую красную строку: код 1 при
    #    нуле красных. Поломка обязана ронять проверку, а не убивать прогон.
    ("правила знаний не называют все указатели",
     "tools/dbapp/core.py",
     "    return [f\"{rel}/{fname}\" for rel, fname, _ in knowledge_index_targets()]",
     "    return [f\"{rel}/{fname}\" for rel, fname, _ "
     "in knowledge_index_targets()][:2]"),
    # 7. В правилах нет предупреждения про архив: модель приняла бы
    #    список потерянных привязок за инструкцию и пошла по нему.
    ("в правилах нет предупреждения про архив",
     "tools/dbapp/core.py",
     '        "Файл `_потеряно-привязок.md` в папке области — не инструкция.\\n"',
     '        "Упоминание архива убрано.\\n"'),
    # 9. Превышение лимита проходит молча. Пока порог был числом в
    #    списке целей и разворачивался в никуда, переполнение не давало
    #    знать ни о чём. Теперь превышение попадает в отчёт, и обрезать
    #    нельзя: обрезка выбросила бы ровно то, ради чего указатель жив.
    ("о превышении лимита не сказано",
     "tools/dbapp/core.py",
     "        size = (folder / fname).stat().st_size\n"
     "        if size > _limit:",
     "        size = (folder / fname).stat().st_size\n"
     "        if False:"),
    # 8. Корневой указатель без секции «## Пути». Имена секций читает
    #    человек и модель, и «Разделы» вместо «Пути» молча ломает всё, что
    #    на них завязано.
    ("в корневом указателе нет секции ## Пути",
     "tools/dbapp/core.py",
     '        "## Пути",',
     '        "## Разделы",'),
]


def run(tree: Path) -> tuple[int, list[str]]:
    proc = subprocess.run([sys.executable, SELFTEST], cwd=tree,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=3600)
    red = [ln.strip() for ln in (proc.stdout or "").split("\n")
           if ln.startswith("[СБОЙ")]
    return proc.returncode, red


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="откат-подключения-"))
    clean = base / "чисто"
    print("чистая копия снята, прогон на ней:")
    shutil.copytree(PROG, clean, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git"))
    code0, red0 = run(clean)
    print(f"  код {code0}; красных {len(red0)}")
    if red0:
        for r in red0[:5]:
            print("   ", r[:110])
        print("  ПРЕДУСЛОВИЕ НЕ ВЫПОЛНЕНО: чистая копия красная, "
              "откат нечего ломать.")
        shutil.rmtree(base, ignore_errors=True)
        return 1

    caught = 0
    seen_red: set[str] = set()
    print()
    print("поломки по одной:")
    for i, (name, rel, old, new) in enumerate(BREAKS, 1):
        tree = base / f"поломка-{i}"
        shutil.copytree(clean, tree, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc"))
        try:
            _patch(tree / rel, old, new)
        except SystemExit as exc:
            print(f"{i:2}. {name}: ПОДМЕНА НЕ ПРОШЛА — {exc}")
            continue
        code, red = run(tree)
        own = [r for r in red if r.split(":", 1)[0] not in seen_red]
        seen_red.update(r.split(":", 1)[0] for r in red)
        ok = code != 0 and red
        caught += 1 if ok else 0
        print(f"{i:2}. {name}: {'поймана' if ok else 'НЕ ПОЙМАНА'} "
              f"({len(red)} красных, код {code}, своих {len(own)})")
        for r in red[:3]:
            print(f"        красная: {r[:96]}")
        shutil.rmtree(tree, ignore_errors=True)

    shutil.rmtree(base, ignore_errors=True)
    print()
    print(f"поймано: {caught} из {len(BREAKS)}")
    print("ИТОГ:", "откат доказан" if caught == len(BREAKS)
          else "откат НЕ доказан")
    return 0 if caught == len(BREAKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
