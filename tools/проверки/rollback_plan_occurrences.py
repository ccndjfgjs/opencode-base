"""Проверяет пункт 4: ловит ли plan_diff_git.py изменение числа вхождений.

До сих пор изменение числа вхождений показывалось только для пустых
строк. Если скрипт ловит это лишь на пустых, то потеря повторяющейся
строки пройдёт молча — ровно как с `ln not in carried`, где проверки были
зелёные по случайной причине.

Проба: в копии плана удаляется ОДИН из двух одинаковых `---` внутри
блока задачи 3. Ни одна строка не появляется и не исчезает целиком, но
число вхождений `---` меняется с двух на одно.

Ожидание: скрипт это отметит. Если нет — потеря повтора невидима.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
SCRIPT = "tools/проверки/plan_diff_git.py"
REL = "документы/2026-10-05-план-указатели-знаний.md"


def find_repo(start: Path) -> Path:
    """Репозиторий ищется вверх. Задавать его вручную нельзя: путь с
    именем учётки работал бы на одной машине, а проба клонирует именно
    репозиторий — из папки программы в Downloads клонировать нечего."""
    cur = start.resolve()
    for _ in range(8):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise SystemExit(
        "ПРЕДУСЛОВИЕ НЕ ВЫПОЛНЕНО: репозиторий не найден вверх по дереву. "
        "Скрипт запускается из копии рядом с .git.")


REPO = find_repo(PROG)


def run(tree: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, SCRIPT], cwd=tree,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, p.stdout + p.stderr


def make_test_repo(dest: Path) -> Path:
    """Пробный репозиторий вручную.

    `git clone` репозитория целиком не годится: в дереве знаний есть
    пути длиннее предела Windows, и клонирование падает на
    `unable to create file`. Нужен только план и скрипт сверки — их и
    кладём, с настоящим git внутри.
    """
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "документы").mkdir(exist_ok=True)
    (dest / "tools" / "проверки").mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROG / REL, dest / REL)
    shutil.copy2(PROG / SCRIPT, dest / SCRIPT)
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"], ["add", "-A"],
                ["commit", "-q", "-m", "проба"]):
        p = subprocess.run(["git", "-C", str(dest)] + cmd,
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"git {cmd[0]}: {p.stderr[:200]}")
    return dest


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="вхождения-"))
    try:
        clean = make_test_repo(base / "чистый")
        code0, out0 = run(clean)
        base_n = out0.count("изменилось число вхождений")
        print(f"пробный репозиторий: код {code0}, "
              f"строк «изменилось число вхождений»: {base_n}")

        tree = make_test_repo(base / "убрано")
        plan = tree / REL
        t = plan.read_text(encoding="utf-8")
        # Повторяющаяся строка в плане — разделитель `---`, их 11 штук по
        # всему файлу. Замена ОДНОГО из них на другую строку меняет число
        # вхождений, не добавляя и не убирая ни одной строки целиком.
        # Первые две попытки искали литерал `"---"` в коде примера, а потом
        # разделители внутри задачи 3: там их меньше двух, и обе пробы
        # падали, ничего не измерив.
        lines = t.split("\n")
        idxs = [i for i, ln in enumerate(lines) if ln.strip() == "---"]
        if len(idxs) < 2:
            raise SystemExit("разделителей `---` в плане меньше двух")
        victim = idxs[1]
        print(f"  разделителей `---` в плане: {len(idxs)}, "
              f"меняем второй (строка {victim + 1})")
        lines[victim] = "--- заменён пробой, разделителей стало меньше"
        plan.write_text("\n".join(lines), encoding="utf-8")
        print()
        print("поломка: ОДИН разделитель `---` заменён на другую строку")
        code, out = run(tree)
        n = out.count("изменилось число вхождений")
        print(f"  код {code}")
        print(f"  строк «изменилось число вхождений»: {n} (в чистой {base_n})")
        seen = [ln.strip() for ln in out.split("\n") if "вхождени" in ln]
        for s in seen[:5]:
            print("   ", s[:104])
        if n > base_n:
            print()
            print("ИТОГ: скрипт ЛОВИТ изменение числа вхождений — потеря")
            print("повторяющейся строки не проходит молча.")
            return 0
        print()
        print("ИТОГ: НЕ ЛОВИТ — потеря повтора невидима, тот же дефект.")
        return 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())