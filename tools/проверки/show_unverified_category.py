"""Показывает вывод сверки на поломке, где категория «непроверяемых блоков»
непуста. Пункт 3: «покажи строку, где эта категория названа, а не только код 1».

Поломка: в плане появляется блок, где на одной глубине смешаны 4 и 8
пробелов. Такой блок не является файлом, и обёртка его не исправляет —
в категорию «не проверено» он попасть не может.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
SCRIPT = "tools/проверки/plan_matches_code.py"
FENCE = chr(96) * 3


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="непроверяемые-"))
    try:
        tree = base / "дерево"
        shutil.copytree(PROG, tree, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git"))
        plan = tree / "документы" / "2026-10-05-план-указатели-знаний.md"
        t = plan.read_text(encoding="utf-8")
        t += f"\n{FENCE}python\nif True:\n    x = 1\n        y = 2\n{FENCE}\n"
        plan.write_text(t, encoding="utf-8")

        print("=== поломка: блок со смешанными уровнями отступа ===")
        p = subprocess.run([sys.executable, SCRIPT], cwd=tree,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        for ln in p.stdout.split("\n"):
            if ("НЕ ПРОВЕРЕН" in ln or "непроверяемых" in ln
                    or "ВНИМАНИЕ" in ln or "ослабление" in ln
                    or "ИТОГ" in ln):
                print("  " + ln.strip())
        print(f"  код возврата: {p.returncode}")
        return 0 if p.returncode != 0 else 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())