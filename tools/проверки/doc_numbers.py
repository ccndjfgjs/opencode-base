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
     создаваемыми при реализации;
  5) число указателей, названное в прозе, совпадает с тем, что даёт функция
     `knowledge_index_targets()` — её код берётся из самого документа и
     выполняется на настоящих `KNOWLEDGE_*` из `core.py`.

Про (5). Проверка ловит одно конкретное утверждение — «сколько указателей»,
а не все числа подряд: числа подряд она уже ловила лишнее, и от этого
отказались. Считает не руками и не `Select-String`, а исполнением функции
из документа, потому что перебор дважды насчитал неверно: 36 совпадений
вместо 28 и файл материала, принятый за файл указателя.

Если функцию из документа извлечь или выполнить не удалось — проверка
пишет «не проверено» и не придумывает число. Молчаливая подстановка хуже
отсутствия проверки.

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

#: Слова, которыми в прозе называют число указателей. «областей» здесь нет
#: намеренно: «девять областей» — верное утверждение об областях, а не об
#: указателях, и проверка не должна его считать расхождением.
WORDS = {
    "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10,
    "одиннадцать": 11, "одиннадцати": 11,
}


def code_blocks(lines: list[str]) -> list[str]:
    """Все блоки ```python ... ``` из документа."""
    blocks: list[str] = []
    inside = False
    buf: list[str] = []
    for row in lines:
        if row.strip().startswith("```python"):
            inside, buf = True, []
            continue
        if inside and row.strip() == "```":
            blocks.append("\n".join(buf))
            inside = False
            continue
        if inside:
            buf.append(row)
    return blocks


def count_targets_from_doc(text: str) -> tuple[int | None, str]:
    """Сколько указателей даёт функция, написанная в документе.

    Возвращает (число, отчёт). Число None означает «не удалось посчитать»,
    и тогда вызывающий не имеет права ничего утверждать о количестве.
    """
    blocks = [b for b in code_blocks(text.splitlines())
              if "def knowledge_index_targets(" in b]
    if len(blocks) != 1:
        return None, (f"блоков с knowledge_index_targets в документе "
                      f"{len(blocks)}, ожидался один — не проверено")
    block = blocks[0]
    if not re.search(r"^KNOWLEDGE_AREAS\s*=", block, re.M):
        # блок опирается на импорт из core.py — добавляем его вручную
        block += "\nKNOWLEDGE_AREAS = KNOWLEDGE_AREAS\n"
    sys.path.insert(0, str(PROG / "tools" / "dbapp"))
    try:
        import core  # noqa: PLC0415
    except Exception as exc:                      # noqa: BLE001
        return None, f"не импортировался core.py: {exc}"
    ns = {name: getattr(core, name, None) for name in
          ("KNOWLEDGE_AREAS", "KNOWLEDGE_SUBDIRS", "KNOWLEDGE_SUBSUBDIRS")}
    if ns["KNOWLEDGE_AREAS"] is None:
        return None, "в core.py нет KNOWLEDGE_AREAS — не проверено"
    try:
        exec(compile(block, "<из документа>", "exec"), ns)  # noqa: S102
        targets = ns["knowledge_index_targets"]()
    except Exception as exc:                      # noqa: BLE001
        return None, f"функция из документа не выполнилась: {exc}"
    ns["__targets"] = targets
    return len(targets), "выполнена на настоящих KNOWLEDGE_* из core.py"


def valid_names(text: str) -> set[str] | None:
    """Имена файлов, которые даёт функция из документа, — для проверки 6."""
    blocks = [b for b in code_blocks(text.splitlines())
              if "def knowledge_index_targets(" in b]
    if len(blocks) != 1:
        return None
    sys.path.insert(0, str(PROG / "tools" / "dbapp"))
    try:
        import core  # noqa: PLC0415
    except Exception:                             # noqa: BLE001
        return None
    ns = {name: getattr(core, name, None) for name in
          ("KNOWLEDGE_AREAS", "KNOWLEDGE_SUBDIRS", "KNOWLEDGE_SUBSUBDIRS")}
    if ns["KNOWLEDGE_AREAS"] is None:
        return None
    block = blocks[0]
    if not re.search(r"^KNOWLEDGE_AREAS\s*=", block, re.M):
        block += "\nKNOWLEDGE_AREAS = KNOWLEDGE_AREAS\n"
    try:
        exec(compile(block, "<из документа>", "exec"), ns)  # noqa: S102
        return {f for _r, f, _l in ns["knowledge_index_targets"]()}
    except Exception:                             # noqa: BLE001
        return None


#: Слова, по которым видно, что имя в документе названо как неправильный
#: пример, а не как задание. План прямо пишет «получилось бы … вместо …»,
#: и такое имя обязано там остаться, иначе исчезнет объяснение.
COUNTER_MARK = ("вместо", "получилось бы", "вышло бы", "нельзя", "отменено")

#: Маски, а не имена: их в списке быть не может.
PLACEHOLDERS = ("*", "<", ">")

#: Имя, которое переименовываем по решению от 05.10.
OLD_NAME = "_подсказки-программисту.md"


def wrong_names(lines: list[str], valid: set[str]) -> list[tuple[str, int, str]]:
    """Имена указателей в документе, которых нет в списке функции.

    Возвращает (имя, строка, почему). Пустые маски и имена, названные как
    неправильный пример, пропускаются: ругаться на них — ложное замечание.
    """
    bad: list[tuple[str, int, str]] = []
    for i, row in enumerate(lines, 1):
        marked = any(m in row for m in COUNTER_MARK)
        for tok in re.findall(r"_подсказки-[^\s`|)\],]*\.md", row):
            if tok in valid or tok == OLD_NAME:
                continue
            if any(p in tok for p in PLACEHOLDERS):
                continue
            if marked:
                continue          # назван как «не надо так»
            bad.append((tok, i, "нет такого имени в списке функции"))
    return bad


def said_counts(lines: list[str]) -> dict[int, list[int]]:
    """Какие числа указателей названы в прозе, с номерами строк.

    Ловит только утверждения о числе указателей: «N указателей», «N строк
    «записан»», «N указателей знаний».
    """
    found: dict[int, list[int]] = {}
    for i, row in enumerate(lines, 1):
        for m in re.finditer(r"(\d+)\s+указател\w*", row):
            found.setdefault(int(m.group(1)), []).append(i)
        for m in re.finditer(r"(\d+)\s+строк\s+«записан»", row):
            found.setdefault(int(m.group(1)), []).append(i)
        for word, num in WORDS.items():
            if re.search(rf"\b{word}\s+указател\w*", row):
                found.setdefault(num, []).append(i)
                break
            # «девять строк «записан»» — тоже утверждение о числе
            # указателей, просто написанное словом, а не цифрой. Без этой
            # строки расхождение в плане прошло бы молча.
            if re.search(rf"\b{word}\s+строк\s+«записан»", row):
                found.setdefault(num, []).append(i)
                break
    return found


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
    if not checks:
        # В плане таблицы проверок нет — там проверки это пункты задач.
        # Ругаться на её отсутствие бессмысленно: это не расхождение чисел,
        # а другой жанр документа.
        out_lines.append("таблицы проверок в документе нет — проверка 1 и 2 "
                         "неприменимы, это не замечание")
        rows: list[int] = []
    elif len(checks) != 1:
        problems.append(f"таблиц проверок найдено {len(checks)}, ожидалась одна")
        rows = []
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
    if not checks:
        # сверять не с чем: таблицы в документе нет, а число 10 относится
        # к проверкам селфтеста, а не к таблице этого документа
        out_lines.append("  сверять не с чем — таблицы проверок нет, "
                         "это не замечание")
    elif said != {len(rows)}:
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

    # --- 5. число указателей: проза против функции из документа
    out_lines.append("")
    said_idx = said_counts(lines)
    computed, how = count_targets_from_doc(text)
    out_lines.append("=== сколько указателей (проверка 5) ===")
    if computed is None:
        out_lines.append(f"  НЕ ПРОВЕРЕНО: {how}")
        # молча подставлять число здесь было бы хуже, чем не проверять вовсе
    elif not said_idx:
        out_lines.append("  в документе нет утверждений о числе указателей — "
                         "нечего сверять")
        out_lines.append(f"  (по функции из документа получается {computed})")
    else:
        out_lines.append(f"  по функции из документа: {computed} — {how}")
        for num in sorted(said_idx):
            where = ", ".join(f"строка {n}" for n in said_idx[num])
            out_lines.append(f"  в прозе сказано {num}: {where}")
        wrong = {n: v for n, v in said_idx.items() if n != computed}
        if wrong:
            problems.append(f"число указателей в прозе {sorted(wrong)}, "
                            f"а по функции {computed}")
        else:
            out_lines.append(f"  и это сходится: {computed}")

    # --- 6. имена указателей: каждое имя из документа есть в списке функции
    out_lines.append("")
    good = valid_names(text)
    out_lines.append("=== имена указателей (проверка 6) ===")
    if good is None:
        out_lines.append("  НЕ ПРОВЕРЕНО: список имён получить не удалось")
    else:
        seen: dict[str, list[int]] = {}
        for ln in lines:
            for tok in re.findall(r"_подсказки-[^\s`|)\],]*\.md", ln):
                seen.setdefault(tok, []).append(lines.index(ln) + 1)
        typos = wrong_names(lines, good)
        out_lines.append(f"  разных имён в документе: {len(seen)}")
        out_lines.append(f"  ошибочных: {len(typos)}")
        for tok, num, why in typos[:8]:
            out_lines.append(f"    {tok} — строка {num}: {why}")
        if typos:
            problems.append(f"имена указателей не из списка функции: "
                            f"{sorted({t for t, _n, _w in typos})}")
        else:
            out_lines.append("  и все они есть в списке функции")

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