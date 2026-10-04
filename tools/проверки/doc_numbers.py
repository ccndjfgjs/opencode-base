# -*- coding: utf-8 -*-
"""Проверка документов: числа в тексте против того, что есть в самом тексте.

Заведена после того, как число проверок в спецификации разошлось с числом
строк в её таблице трижды подряд: восемь, девять, снова девять при десяти
строках. Глазами это ловится плохо — три правки подряд и все в одном месте.
Значит, сверять надо кодом.

Что проверяет:
  1) таблица проверок: нумерация сплошная с единицы;
  2) числа проверок, названные в прозе, совпадают с числом строк таблицы;
  3) нет одинаковых строк подряд;
  4) упомянутые пути существуют — кроме тех, что документ сам называет
     создаваемыми при реализации.

Запуск без аргументов: python doc_numbers.py [документ] [отчёт]
По умолчанию проверяется спецификация указателей знаний.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
DEFAULT_DOC = PROG / "документы" / "2026-10-04-указатели-знаний-дизайн.md"
DEFAULT_OUT = HERE / "отчёт-doc_numbers.txt"


def collect_tables(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Таблица — это заголовок, разделитель и следующие подряд строки на «|».

    Раньше строки вида «| N |» искались подряд по всему документу, и таблица
    проверок считалась трижды неверно: цеплялась за таблицу уровней из §3, за
    добавленную рядом таблицу уровней указателя и обрывалась на вставленном
    тексте между строками. Три раза виновата была проверка, а не документ.
    """
    tables: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        if (lines[i].strip().startswith("|") and i + 1 < len(lines)
                and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip())):
            header = lines[i].strip()
            body: list[str] = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                body.append(lines[j].strip())
                j += 1
            tables.append((header, body))
            i = j
        else:
            i += 1
    return tables


def main() -> int:
    doc = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOC
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    if not doc.is_file():
        print(f"нет документа: {doc}")
        return 1

    text = doc.read_text(encoding="utf-8")
    lines = text.splitlines()
    out_lines: list[str] = [f"документ: {doc.name}", f"строк: {len(lines)}", ""]
    problems: list[str] = []

    # --- 1 и 2. таблица проверок и числа в прозе
    tables = collect_tables(lines)
    out_lines.append(f"таблиц в документе: {len(tables)}")
    checks = [body for head, body in tables if "№" in head]
    if len(checks) != 1:
        problems.append(f"таблиц проверок найдено {len(checks)}, ожидалась одна")
        rows: list[int] = []
    else:
        rows = [int(m.group(1)) for ln in checks[0]
                if (m := re.match(r"^\| (\d+) \| ", ln))]
    out_lines.append(f"строк в таблице проверок: {len(rows)}")
    out_lines.append(f"  номера: {', '.join(str(n) for n in rows)}")
    if rows and rows != list(range(1, len(rows) + 1)):
        problems.append(f"нумерация сбита: {rows}")
    elif rows:
        out_lines.append("  нумерация сплошная с единицы")

    words = {8: "Восемь", 9: "Девять", 10: "Десять", 11: "Одиннадцать",
             12: "Двенадцать"}
    said: set[int] = set()
    for ln in lines:
        for m in re.finditer(r"(\d+)\s+быстрых проверок", ln):
            said.add(int(m.group(1)))
        for num, word in words.items():
            if re.match(rf"^{word}, все", ln.strip()):
                said.add(num)
    out_lines.append("")
    out_lines.append(f"числа проверок, названные в прозе: {sorted(said) or '—'}")
    if said != {len(rows)}:
        problems.append(f"в прозе {sorted(said)}, а строк в таблице {len(rows)}")
    else:
        out_lines.append("  и они сходятся с таблицей")

    # --- 3. одинаковые строки подряд
    out_lines.append("")
    dups = [i + 1 for i in range(1, len(lines))
            if lines[i].strip() and lines[i] == lines[i - 1]]
    out_lines.append(f"одинаковых строк подряд: {len(dups)}")
    if dups:
        problems.append(f"повторы на строках {dups[:5]}")

    # --- 4. упомянутые пути
    out_lines.append("")
    will_create: set[str] = set()
    for m in re.finditer(r"`([^`]+\.(?:md|json))`[^\n]*созда", text):
        will_create.add(m.group(1).replace("/", "\\"))
    missing: set[str] = set()
    for m in re.finditer(r"`([^`/\\]+\.(?:md|json))`", text):
        if "/" not in m.group(1):
            continue                    # одиночное имя — не путь
        rel = m.group(1).replace("/", "\\")
        if rel in will_create:
            continue                    # его положим при реализации
        if not (PROG / rel).exists():
            missing.add(rel)
    out_lines.append(f"упомянутых путей нет на диске: {len(missing)}")
    for rel in sorted(missing):
        out_lines.append(f"  {rel}")
    out_lines.append(f"создаваемых при реализации: {len(will_create)}"
                     + (f" — {', '.join(sorted(will_create))}"
                        if will_create else ""))
    if missing:
        problems.append(f"нет файлов: {sorted(missing)}")

    out_lines.append("")
    out_lines.append(f"ИТОГ замечаний: {len(problems)}")
    for p in problems:
        out_lines.append(f"  {p}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"отчёт: {out}")
    print(f"замечаний: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())