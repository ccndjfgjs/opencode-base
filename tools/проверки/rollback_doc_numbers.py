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
BREAKS = [
    ("имя файла", "`_подсказки-безопасность.md`", "`_подсказки-безопасности.md`",
     "проверка 6"),
    ("число строк", "одиннадцать строк «записан»", "девять строк «записан»",
     "проверка 5"),
    ("число указателей", "одиннадцати указателей", "девяти указателей",
     "проверка 5"),
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
    lines: list[str] = ["=== откат проверок 5 и 6 ===", ""]
    ok = True

    code0, rep0 = run_check(PLAN)
    lines.append("1. текущий документ")
    lines.append(f"   код {code0} (ожидаем 0 — расхождений нет)")
    if code0 != 0:
        ok = False
        lines.append(f"   расхождения: {problems(rep0)}")

    text = PLAN.read_text(encoding="utf-8")
    broken = text
    missing: list[str] = []
    for _what, good, bad, _probe in BREAKS:
        if good not in broken:
            missing.append(good)
            continue
        broken = broken.replace(good, bad)
    if missing:
        lines.append("")
        lines.append(f"НЕЛЬЗЯ ДОКАЗАТЬ: в документе нет строк {missing} — "
                     "правки документа изменились, скрипт устарел")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
        return 2

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8", newline="") as fh:
        tmp = Path(fh.name)
        fh.write(broken)
    try:
        code1, rep1 = run_check(tmp)
        lines.append("")
        lines.append("2. копия с внесёнными правками")
        for what, _g, _b, probe in BREAKS:
            lines.append(f"   сломано: {what} — ждём {probe}")
        lines.append(f"   код {code1} (ожидаем 1)")
        caught = problems(rep1)
        for c in caught:
            lines.append(f"   поймано: {c}")
        if code1 != 1:
            ok = False
        if len(caught) < 2:
            ok = False
            lines.append("   ВНИМАНИЕ: поймано меньше двух расхождений — "
                         "одна из проверок молчит")
    finally:
        tmp.unlink(missing_ok=True)

    code2, rep2 = run_check(PLAN)
    lines.append("")
    lines.append("3. исходный документ после прогона")
    lines.append(f"   код {code2} (ожидаем 0)")
    lines.append(f"   отчёт не изменился: {rep2 == rep0}")
    if code2 != 0 or rep2 != rep0:
        ok = False

    lines.append("")
    lines.append(f"ИТОГ: {'откат доказан' if ok else 'ОТКАТ НЕ ДОКАЗАН'}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    OUT = HERE / "отчёт-откат-doc_numbers.txt"
    sys.exit(main())