#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Показывает, что изменилось в плане против последнего закоммиченного.

Зачем. Структурная проверка видит, что блоки и шаги на месте, но не видит
их содержимое. Две содержательные строки из блока «Файлы» задачи 4а были
потеряны при ручном восстановлении, и ни счёт шагов, ни счёт блоков этого
не заметили — поймал только diff. Значит diff должен идти перед каждым
коммитом обязательно.

План хранится в git, поэтому эталон всегда под рукой: HEAD.

Что делает. Берёт план из `git show HEAD:<путь>`, сравнивает с рабочей
копией и печатает различия по разделам. Ничего не меняет и ничего не
блокирует: различия бывают намеренными, и решает человек.

Запуск: python tools/проверки/plan_diff_git.py
"""
from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
REL = "документы/2026-10-05-план-указатели-знаний.md"
PLAN = PROG / REL


def find_repo(start: Path) -> Path | None:
    """Ищет корень репозитория вверх. Без этого сравнение не работало
    бы из папки программы в Downloads: там .git нет вовсе, и скрипт
    честно отвечал «сравнивать не с чем», хотя версия плана в репозитории
    лежит."""
    cur = start.resolve()
    for _ in range(8):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


REPO = find_repo(PROG)


def head_version() -> str | None:
    if REPO is None:
        return None
    p = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{REL}"],
                       capture_output=True)
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", errors="replace")


def split_sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    cur = "(шапка)"
    buf: list[str] = []
    for ln in text.split("\n"):
        if ln.startswith("## "):
            out[cur] = buf
            cur = ln
            buf = [ln]
        else:
            buf.append(ln)
    out[cur] = buf
    return out


def main() -> int:
    if not PLAN.is_file():
        print(f"ПЛАНА НЕТ: {PLAN}")
        return 1
    head = head_version()
    if head is None:
        if REPO is None:
            # Предусловие не выполнено. Молчать или отвечать «сравнивать не
            # с чем» здесь нельзя: это тот же класс, что с первым тестовым
            # пушем — работа продолжается, а проверка молча ничего не
            # сделала. Предусловие не выполнено — падаем.
            print("ПРЕДУСЛОВИЕ НЕ ВЫПОЛНЕНО: репозиторий не найден вверх "
                  "по дереву.")
            print("Скрипт запускается из копии рядом с .git. Запускать из "
                  "папки программы в Downloads бессмысленно: там git нет.")
            return 1
        print("В git нет ни одной версии плана — сравнивать не с чем.")
        print("Это нормально для самого первого коммита плана.")
        return 0

    now = PLAN.read_text(encoding="utf-8")
    a = split_sections(head)
    b = split_sections(now)

    print(f"=== {REL}")
    print(f"  в HEAD:  {len(head.splitlines())} строк, {len(a)} разделов")
    print(f"  сейчас:  {len(now.splitlines())} строк, {len(b)} разделов")
    print()
    print("=== что считается разделом ===")
    print("  раздел = заголовок «## »; их столько же, сколько заголовков")
    print("  такого уровня, а задач среди них девять. Число ниже — разделы,")
    print("  не задачи, иначе счёт не сойдётся с числом заголовков.")
    print()
    print("=== по разделам ===")
    print("  Пустые строки считаются ОТДЕЛЬНО. Иначе счёт не сходится, и")
    print("  это была найденная причина: пустая строка уже есть в HEAD, так")
    print("  что «новой» она не считается, но длину добавляет. Три таких")
    print("  строки и давали расхождение +3 в задаче 4а.")
    print(f"  {'раздел':46} {'в HEAD':>7} {'сейчас':>7} {'сдвиг':>7} "
          f"{'новых':>6} {'пропало':>8} {'пустых+':>8}")
    order = list(a.keys())
    for k in b:
        if k not in order:
            order.append(k)
    t_head = t_now = t_new = t_gone = t_bl = 0
    lost: list[tuple[str, str]] = []
    occ_changed: list[str] = []
    for k in order:
        la, lb = a.get(k, []), b.get(k, [])
        # Число вхождений каждой строки. Без этого потеря повторяющейся
        # строки невидима: заменить один `---` из одиннадцати — и ни одна
        # строка не пропадёт и не появится, а повтор уже не тот. Та же
        # blindness, что была с повтором в смысловой части.
        ca, cb = Counter(la), Counter(lb)
        for line in set(ca) | set(cb):
            if ca.get(line, 0) != cb.get(line, 0):
                occ_changed.append(
                    f"{k[:28]}: {ca.get(line, 0)} -> {cb.get(line, 0)}  "
                    f"{line.strip()[:52]!r}")
        shift = len(lb) - len(la)
        # Мультимножество, а не вхождение: две одинаковые новые строки —
        # это две строки. Подсчёт по вхождению терял единицу, и счёт
        # переставал сходиться ровно тогда, когда в плане появлялись
        # две одинаковые строки подряд. Измерено: `continue` добавился
        # дважды, скрипт показал 118 новых вместо 119 и «НЕ СХОДИТСЯ».
        #
        # Пустые строки из мультимножества исключены: они считаются
        # отдельным слагаем `blank`, иначе они посчитаны дважды. Проверено
        # счётом: с исключением 136 − 19 + 6 = 123, что равно сдвигу.
        new = [x for x in (cb - ca).elements() if x.strip()]
        gone = [x for x in (ca - cb).elements() if x.strip()]
        # Прирост числа пустых строк считаем отдельно: без него сдвиг
        # не равен «новых минус пропавших» и скрипт сам себе не верит.
        blank = (sum(1 for x in lb if not x.strip())
                 - sum(1 for x in la if not x.strip()))
        t_head += len(la)
        t_now += len(lb)
        t_new += len(new)
        t_gone += len(gone)
        t_bl += blank
        for g in gone:
            lost.append((k, g))
        if shift or new or gone or k not in a:
            print(f"  {k[:46]:46} {len(la):7} {len(lb):7} "
                  f"{shift:+7} {len(new):6} {len(gone):8} {blank:+8}")
    print()
    print(f"  ИТОГ: в HEAD {t_head} строк, сейчас {t_now}, "
          f"сдвиг {t_now - t_head:+d}")
    print(f"  новых {t_new}, пропало {t_gone}, пустых добавилось {t_bl}")
    check = t_new - t_gone + t_bl
    print(f"  проверка счёта: {t_new} − {t_gone} + {t_bl} = {check}, "
          f"а сдвиг {t_now - t_head:+d} → "
          f"{'СХОДИТСЯ' if check == t_now - t_head else 'НЕ СХОДИТСЯ'}")
    print()
    if occ_changed:
        print(f"ВНИМАНИЕ: изменилось число вхождений строк ({len(occ_changed)}).")
        print("Повтор исчез или утроился: ни одна строка не пропала целиком,")
        print("поэтому счёт выше этого не показывает.")
        for ln in occ_changed[:20]:
            print(f"  ~ {ln}")
    print()
    if t_gone:
        # Разрешение живёт в .git рядом с хуком, а не в репозитории:
        # намеренная замена строки — разовое решение, а не свойство кода.
        permit = REPO / ".git" / "разрешение-потерь-плана"
        print("ВНИМАНИЕ: пропавшие строки:")
        allowed: set[str] = set()
        if permit.is_file():
            allowed = {x.strip() for x in
                       permit.read_text(encoding="utf-8").split("\n")
                       if x.strip()}
        unallowed: list[tuple[str, str]] = []
        for k, x in lost:
            mark = ""
            if x.strip() in allowed:
                mark = "  (разрешено)"
            else:
                unallowed.append((k, x))
            print(f"  - {k[:30]}: {x.strip()[:76]}{mark}")
        if unallowed:
            print()
            print(f"НЕ РАЗРЕШЕНО пропавших строк: {len(unallowed)}")
            print("Это настоящая потеря содержимого — такого раньше не было.")
            print("Коммит заблокирован. Если потеря намеренная, перечисли")
            print("строки в файле-разрешении (по одной в строке, без отступа):")
            print(f"  {permit}")
            return 1
        print()
        print(f"Все пропавшие строки перечислены в разрешении, потерь необъяснённых: 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())