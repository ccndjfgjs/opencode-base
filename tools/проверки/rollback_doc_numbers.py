# -*- coding: utf-8 -*-
"""Откат для проверок 5 и 6 в doc_numbers.py.

Проверку, которая ни разу не падала, нельзя считать проверкой. Здесь
доказывается обратное: в копию документа вносятся правки, каждая из
которых ломает своё утверждение, и проверки обязаны каждую поймать.

Скрипт повторный: он не ждёт, что исходный документ сломан. Сначала
проверяет текущее состояние, потом ломает копию, потом убеждается, что
исходный документ не тронут.

Настоящий документ не меняет: работает на копии во временном файле.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE.parent.parent / "документы" / "2026-10-05-план-указатели-знаний.md"
DOC_NUMBERS = HERE / "doc_numbers.py"

#: Что ломаем и что обязано сработать.
DOCS = HERE.parent.parent / "документы"
PLAN = DOCS / "2026-10-05-план-указатели-знаний.md"
SPEC = DOCS / "2026-10-04-указатели-знаний-дизайн.md"

#: (документ, что ломаем, на что, номер проверки). Поломка ищется только в
#: своём документе: строка «уровень 1: 9 областей» есть в плане, а строка
#: «| 1 | 9 областей:» — в спецификации, и искать одно вместо другого
#: бессмысленно.
BREAKS = [
    (PLAN, "имя файла", "`_подсказки-безопасность.md`",
     "`_подсказки-безопасности.md`", "имена указателей не из списка"),
    (PLAN, "число строк", "одиннадцать строк «записан»",
     "девять строк «записан»", "число указателей в прозе"),
    (PLAN, "число указателей", "одиннадцати указателей",
     "девяти указателей", "число указателей в прозе"),
    (PLAN, "вилка в числе областей", "уровень 1: 9 областей",
     "уровень 1: 9–12 областей", "вилка вместо числа областей"),
    (SPEC, "вилка в числе областей", "9 областей: «тема → область»",
     "9–12 областей: «тема → область»", "вилка вместо числа областей"),
]


def run_check(doc: Path) -> tuple[int, str]:
    """Гоняет doc_numbers.py и возвращает код и текст отчёта."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as fh:
        out = Path(fh.name)
    try:
        proc = subprocess.run(
            [sys.executable, str(DOC_NUMBERS), str(doc), str(out)],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return proc.returncode, out.read_text(encoding="utf-8")
    finally:
        out.unlink(missing_ok=True)


def problems(rep: str) -> list[str]:
    """Строки раздела «ИТОГ замечаний», то есть сами расхождения.

    Формат отчёта — две начальные пробела, а не дефис: doc_numbers.py
    печатает замечания как ``  текст``. Сначала тут был дефис, и скрипт
    молча считал, что поймал ноль расхождений, хотя код возвращал 1.
    """
    out: list[str] = []
    grab = False
    for ln in rep.splitlines():
        if ln.startswith("ИТОГ замечаний"):
            grab = True
            continue
        if grab:
            if ln.startswith("  ") and ln.strip():
                out.append(ln.strip())
            elif ln.strip():
                break
    return out


def main() -> int:
    lines: list[str] = ["=== откат проверок 5, 6 и 7 ===", ""]
    ok = True

    # --- 1. текущее состояние обоих документов
    for doc in (PLAN, SPEC):
        code, rep = run_check(doc)
        lines.append(f"1. {doc.name}")
        lines.append(f"   код {code} (ожидаем 0 — расхождений нет)")
        if code != 0:
            ok = False
            lines.append(f"   расхождения: {problems(rep)}")

    # --- 2. каждая поломка обязана ломать свой документ
    for target in (PLAN, SPEC):
        lines.append("")
        lines.append(f"2. поломки в {target.name}")
        mine = [b for b in BREAKS if b[0] == target]
        text = target.read_text(encoding="utf-8")
        broken = text
        missing: list[str] = []
        for _d, _what, good, bad, _probe in mine:
            if good not in broken:
                missing.append(good)
                continue
            broken = broken.replace(good, bad)
        if missing:
            lines.append(f"   НЕЛЬЗЯ ДОКАЗАТЬ: нет строк {missing} — "
                         "правки изменились, скрипт устарел")
            ok = False
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8", newline="") as fh:
            tmp = Path(fh.name)
            fh.write(broken)
        try:
            code1, rep1 = run_check(tmp)
            caught = problems(rep1)
            lines.append(f"   код {code1} (ожидаем 1)")
            for c in caught:
                lines.append(f"   поймано: {c}")
            if code1 != 1:
                ok = False
            # Сверка поимённая, а не по числу: две поломки про числа
            # указателей законно дают одно сообщение, и требование
            # «столько-то расхождений» искажало бы результат.
            for _d, what, _g, _b, expect in mine:
                hit = any(expect in c for c in caught)
                mark = "поймана" if hit else "ПРОПУЩЕНА"
                if not hit:
                    ok = False
                lines.append(f"   {what}: ждали «{expect}» — {mark}")
        finally:
            tmp.unlink(missing_ok=True)

    # --- 3. исходные документы не тронуты
    lines.append("")
    lines.append("3. исходные документы после прогона")
    for doc in (PLAN, SPEC):
        code, _ = run_check(doc)
        lines.append(f"   {doc.name}: код {code} (ожидаем 0)")
        if code != 0:
            ok = False

    lines.append("")
    lines.append(f"ИТОГ: {'откат доказан' if ok else 'ОТКАТ НЕ ДОКАЗАН'}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    OUT = HERE / "отчёт-откат-doc_numbers.txt"
    sys.exit(main())