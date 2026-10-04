# -*- coding: utf-8 -*-
"""Откат для проверок 5 и 6 в doc_numbers.py.

Проверку, которая ни разу не падала, нельзя считать проверкой. Здесь
доказывается обратное: правим копию плана — проверки зеленеют, возвращаем
исходный текст — краснеют.

Работает на копии в памяти. Настоящий план не трогает.
"""

import io
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
PLAN = PROG / "документы" / "2026-10-05-план-указатели-знаний.md"
DOC_NUMBERS = HERE / "doc_numbers.py"

#: Что и куда правим. Первое — имя файла, второе и третье — числа в прозе.
FIXES = [
    ("`_подсказки-безопасности.md`", "`_подсказки-безопасность.md`",
     "имя файла, строка 505"),
    ("девять строк «записан»", "одиннадцать строк «записан»",
     "число строк в ожидании задачи 5"),
    ("у всех девяти указателей", "у всех одиннадцати указателей",
     "число указателей в задаче 6"),
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
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        return proc.returncode, out.read_text(encoding="utf-8")
    finally:
        out.unlink(missing_ok=True)


def main() -> int:
    original = PLAN.read_text(encoding="utf-8")
    lines_out: list[str] = ["=== откат проверок 5 и 6 ===", ""]

    code, rep = run_check(PLAN)
    lines_out.append("1. исходный план")
    lines_out.append(f"   код {code} (ожидаем 1 — в плане есть расхождения)")
    lines_out.append(f"   замечаний: "
                     f"{[l.strip() for l in rep.splitlines() if l.startswith('  ') and ('указател' in l)][:2]}")

    # --- применяем все три правки к копии
    fixed = original
    for old, new, _why in FIXES:
        if old not in fixed:
            lines_out.append(f"   ВНИМАНИЕ: не найдено «{old}» — правка не применилась")
            fixed = None
            break
        fixed = fixed.replace(old, new)
    if fixed is None:
        OUT.write_text("\n".join(lines_out), encoding="utf-8")
        print("\n".join(lines_out))
        return 2

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8", newline="") as fh:
        tmp = Path(fh.name)
        fh.write(fixed)
    try:
        code2, rep2 = run_check(tmp)
        lines_out.append("")
        lines_out.append("2. копия плана с тремя правками")
        for _o, n, why in FIXES:
            lines_out.append(f"   правка: {why}")
        lines_out.append(f"   код {code2} (ожидаем 0 — расхождений не осталось)")
        check5 = [l.strip() for l in rep2.splitlines() if "сходится" in l]
        check6 = [l.strip() for l in rep2.splitlines() if "все они есть" in l]
        lines_out.append(f"   проверка 5: {check5 or '—'}")
        lines_out.append(f"   проверка 6: {check6 or '—'}")

        # --- и возвращаем обратно: то же самое состояние обязано падать снова
        code3, rep3 = run_check(PLAN)
        lines_out.append("")
        lines_out.append("3. возврат к исходному (файл не меняли, но проверяем "
                         "повторно)")
        lines_out.append(f"   код {code3} (ожидаем 1 — те же расхождения)")
        lines_out.append(f"   отчёт совпал с первым: {rep3 == rep}")

        ok = (code == 1 and code2 == 0 and code3 == 1 and rep3 == rep
              and bool(check5) and bool(check6))
        lines_out.append("")
        lines_out.append(f"ИТОГ: {'откат доказан' if ok else 'ОТКАТ НЕ ДОКАЗАН'}")
    finally:
        tmp.unlink(missing_ok=True)

    OUT.write_text("\n".join(lines_out), encoding="utf-8")
    print("\n".join(lines_out))
    return 0 if ok else 1


if __name__ == "__main__":
    OUT = HERE / "отчёт-откат-doc_numbers.txt"
    sys.exit(main())