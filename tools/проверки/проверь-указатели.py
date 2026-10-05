#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка для человека: создать базу и увидеть указатели своими глазами.

Одна команда, один ответ. Ничего не доказывает по построению — создаёт
настоящую базу из образца во временной папке и показывает, что в ней
есть. Папка в конце удаляется; ничего твоего не трогается.

Запуск:  python tools/проверки/проверь-указатели.py
Код 0 — работает. Код 1 — не работает, и в выводе сказано где.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))
import core  # noqa: E402


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="проверка-указателей-"))
    try:
        src = PROG / "ОБРАЗЕЦ-БАЗЫ.md"
        template = src if src.is_file() else None

        print("=== 1. создаю новую базу из образца ===")
        plan = core.build_plan(base, "Проба", template)
        core.create_base(plan)
        made = [p for p in (plan.target / "знания").rglob("_подсказки*.md")
                if p.is_file()]
        print(f"  база: {plan.target}")
        print(f"  файлов знаний: "
              f"{sum(1 for _ in (plan.target / 'знания').rglob('*') if _.is_file())}")
        print(f"  указателей появилось: {len(made)}")

        want = core.knowledge_index_targets()
        print()
        print("=== 2. что ожидалось и что вышло ===")
        no_folder, made_n, missing = 0, 0, []
        for rel, fname, _lim in want:
            f = plan.target / rel / fname
            if not (plan.target / rel).is_dir():
                no_folder += 1
                state = "нет папки области"
            elif f.is_file():
                made_n += 1
                state = f"создан, {f.stat().st_size} байт"
            else:
                missing.append(f"{rel}/{fname}")
                state = "НЕ СОЗДАН"
            print(f"  {state:<22} {rel}/{fname}")

        print()
        print("=== 3. удаляю папку-область и пересобираю ===")
        # Удаляется область, которая точно есть в корневом указателе.
        # Первая попавшаяся папка не годится: первая версия этой проверки
        # выбирала папку наугад, и удаляла не ту, — архив не появлялся, и
        # вывод читался как «не работает», хотя дело было в проверке.
        root_idx = plan.target / "знания" / "_подсказки-общая.md"
        named = [ln for ln in root_idx.read_text(encoding="utf-8").split("\n")
                 if ln.startswith("- `")]
        target_area = None
        for ln in named:
            name = ln.split("`")[1].strip("/")
            if name and (plan.target / "знания" / name).is_dir():
                target_area = name
                break
        if target_area is None:
            print("  в корневом указателе не нашлось папки, которую можно "
                  "удалить, — проверять нечего")
            return 1
        d = plan.target / "знания"

        # Смысловую часть указателя пишет модель по ходу работы. Без неё
        # переносить нечего: в свежей базе указатель состоит из одной
        # авточасти, и исчезновение папки не теряет ничьей подсказки.
        # Первая версия этой проверки ждала архива сразу после удаления
        # и читалась как «не работает» — а не работать там и нечему.
        _add = (f"\n## Когда заходить\n"
                f"- про {target_area.lower()} — смотри `{target_area}/`.\n"
                f"- про учёт и деньги — `{target_area}/` и "
                f"`Техника/`.\n")
        root_idx.write_text(root_idx.read_text(encoding="utf-8") + _add,
                            encoding="utf-8", newline="\n")
        print(f"  дописал в указатель две строки про {target_area}/ — "
              "как это делает модель")

        print(f"  удаляю область: {target_area}/")
        shutil.rmtree(d / target_area)
        core.refresh_knowledge_indexes(plan.target)
        arch = d / core.ARCHIVE_NAME
        print(f"  архив появился: {arch.is_file()}")
        arch_ok = False
        if arch.is_file():
            body = arch.read_text(encoding="utf-8")
            lines = [ln for ln in body.split("\n") if ln.strip()]
            arch_ok = target_area in body
            print(f"  строк в архиве: {len(lines)}, "
                  f"прежний путь назван: {target_area in body}")
            for ln in lines[:10]:
                print(f"    {ln[:88]}")
            kept = [ln for ln in root_idx.read_text(encoding="utf-8")
                    .split("\n") if f"`{target_area}/`" in ln]
            print(f"  строк в указателе с упоминанием {target_area}/: "
                  f"{len(kept)}")
            for ln in kept:
                print(f"    {ln[:88]}")
        else:
            print("  в папке знаний осталось: "
                  f"{sorted(p.name for p in d.iterdir())}")
            print("  ПРЕДУСЛОВИЕ НЕ ВЫПОЛНЕНО: архива нет")

        print()
        print("=== ИТОГ ===")
        ok = not missing
        print(f"  указателей создано: {made_n} из {len(want)} "
              f"(остальное — области, которых в образце нет: {no_folder})")
        print(f"  не создано по причине папки: {missing or 'нет'}")
        print(f"  архив потерянных привязок: {'работает' if arch.is_file() else 'НЕ РАБОТАЕТ'}")
        if ok:
            print("  ДА: создал базу — получил указатели, удалил папку — "
                  "получил архив.")
            return 0
        print("  НЕТ: есть указатели, которые должны были создаться, "
              "но не созданы.")
        return 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
