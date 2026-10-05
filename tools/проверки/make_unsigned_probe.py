# -*- coding: utf-8 -*-
"""Готовит пробную копию селфтеста: подписываемый файл заменён на
неподписанный.

Цель проверки: убедиться, что неудача внешнего зонда даёт «не проверено»,
а не «сбой». Раньше она давала «сбой», и прогон краснел из-за состояния
машины, а не из-за кода.

Ничего настоящего не трогает: работает на копии во временной папке.
"""

import sys
from pathlib import Path

PROG = Path(r"C:\Users\Dedy_Sher\Downloads\opencode-base-main")
SRC = PROG / "tools" / "dbapp" / "selftest.py"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("selftest-nezakon.py")

OLD = '_node = Path(r"C:\\Program Files\\nodejs\\node.exe")'
NEW = (f'_node = Path(r"{PROG}\\ПРАВИЛА-ИИ.md")'
       "   # файл есть, но подписи нет")

text = SRC.read_text(encoding="utf-8")
if OLD not in text:
    print("НЕ НАЙДЕНО: строка с node.exe в селфтесте изменилась")
    raise SystemExit(2)

OUT.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
print(f"пробная копия: {OUT}")
print(f"  размер: {OUT.stat().st_size} байт")
print(f"  подставлено: {NEW[:70]}")