#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Проверяет, что навыки во всех копиях одинаковые.

Навыки живут сразу в нескольких местах, и они молча расходятся: мастер,
папка программы, живая база человека и та папка, из которой opencode
на самом деле читает навыки. Никто об этом не узнаёт, пока навык молча
не перестанет срабатывать.

Скрипт ничего не меняет. Только говорит.

    python tools\\dbapp\\check_skills_sync.py
    python tools\\dbapp\\check_skills_sync.py "C:\\путь\\к\\репозиторию"

Код возврата 0 — все копии совпадают, 1 — есть расхождения, 2 — не разобрался.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402  — путь к модулю настраивается строкой выше

LINE = "=" * 68


def _opencode_root() -> Path | None:
    """Копия, из которой opencode читает навыки на самом деле."""
    try:
        folder = core.PROGRAMS_BY_ID["opencode"].config_dir()
    except (AttributeError, KeyError):
        return None
    return folder if (folder / "skills").is_dir() else None


def collect(master: Path, extra: list[str]) -> list[tuple[str, Path | None, str]]:
    """Кого сравнивать с мастером: живая база, настройки, всё из аргументов.

    Третий элемент — чего ждём от копии. В папку настроек opencode плагин
    везёт только папки навыков: ни индекса, ни описания туда не едет, и
    требовать их — значит ругаться на пустое.
    """
    found: list[tuple[str, Path | None, str]] = []

    live = core.app_root()
    found.append(("живая база", None if live == master else live, "full"))

    settings = _opencode_root()
    found.append(("настройки opencode",
                  None if settings is None or settings == master else settings,
                  "skills-only"))

    for raw in extra:
        path = Path(raw).expanduser()
        found.append((f"из аргументов: {path}",
                      path if (path / "skills").is_dir() else None, "full"))
    return found


def describe(res: dict) -> list[str]:
    """Расхождения по-человечески. Пусто — копии совпадают."""
    return core.skills_findings(res)


def main() -> int:
    master = core.program_root()
    print(LINE)
    print(" Проверка копий навыков")
    print(LINE)
    print(f" Мастер: {master}")
    if not (master / "skills").is_dir():
        print("\n В папке программы нет skills/. Не с чем сравнивать.")
        return 2

    extra = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not extra:
        print(" Копии проверяю те, что программа знает сама. Репозиторий")
        print(" она не знает — путь к нему можно дать аргументом.")

    pairs = collect(master, extra)
    problems = 0
    unknown = 0
    number = 0

    for label, other, expect in pairs:
        number += 1
        title = f"[{number}] {label}"
        if other is None:
            print(f"\n{title} — не найдена, пропускаю")
            unknown += 1
            continue

        res = core.compare_skills(master, other, expect=expect)
        m_n, o_n = res["counts"]
        what = "только навыки" if expect == "skills-only" else "навыки, индекс и описания"
        print(f"\n{title} — {other}")
        print(f"    ждём: {what}")
        print(f"    навыков: {o_n} против {m_n} в мастере")

        found = describe(res)
        if found:
            problems += 1
            for item in found:
                print(f"    - {item}")
        else:
            print("    расхождений нет")

        if res["index_bytes_differ"] and not (
                res["index_missing"] or res["index_extra"]
                or res["index_changed"]):
            print("    записи индекса одинаковые, разошлись байты — "
                  "это разрядка, не беда")
        if res["manual"]:
            print("    (эти навыки правили руками — так и должно быть, "
                  "трогать их нельзя)")

    print(f"\n{LINE}")
    if problems:
        print(f" ИТОГ: расхождения в {problems} копии из "
              f"{len(pairs) - unknown}")
    else:
        print(f" ИТОГ: все {len(pairs) - unknown} копии совпадают с мастером")
    if unknown:
        print(f" не нашлось копий: {unknown}")
    print(LINE)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
