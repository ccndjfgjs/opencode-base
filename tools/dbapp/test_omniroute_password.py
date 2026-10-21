# -*- coding: utf-8 -*-
"""Тест panel_password без сети и без настоящей базы OmniRoute."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import omniroute  # noqa: E402


def make_base(sql_rows):
    """Временные «настройки opencode» с базой OmniRoute нужного вида."""
    root = Path(tempfile.mkdtemp())
    data = root / "omniroute-data"
    data.mkdir()
    conn = sqlite3.connect(str(data / "storage.sqlite"))
    conn.execute(
        "CREATE TABLE key_value (namespace TEXT, key TEXT, value TEXT)")
    for key, value in sql_rows:
        conn.execute(
            "INSERT INTO key_value (namespace, key, value) "
            "VALUES ('settings', ?, ?)", (key, value))
    conn.commit()
    conn.close()
    return root


# 1) пароль простым текстом — возвращается как есть
root = make_base([("password", "sk_omniroute-test")])
password, why = omniroute.panel_password(root)
assert password == "sk_omniroute-test" and why == "", (password, why)
print("1. простой текст — читается")

# 2. JSON-обёрнутый bcrypt — честный отказ
root2 = make_base([("password", json.dumps("$2b$12$" + "x" * 53))])
password, why = omniroute.panel_password(root2)
assert password == "" and "хэшем" in why, (password, why)
print("2. хэш — отказ словами")

# 3. базы нет — отказ словами
root3 = Path(tempfile.mkdtemp())
password, why = omniroute.panel_password(root3)
assert password == "" and "ещё не создан" in why, why
print("3. базы нет — отказ словами")

# 4. json-обёрнутый простой пароль — разворачивается
root4 = make_base([("password", json.dumps("мой-пароль"))])
password, why = omniroute.panel_password(root4)
assert password == "мой-пароль" and why == "", (password, why)
print("4. JSON-обёртка разворачивается")

# --- 5. файл с паролем программы: «Пароль» показывает его, а не базу
root5 = Path(tempfile.mkdtemp())
(root5 / "omniroute-data").mkdir()
(root5 / "omniroute-data" / "panel-password.txt").write_text(
    "сгенерированный-пароль", encoding="utf-8")
got, why5 = omniroute.panel_password(root5)
assert got == "сгенерированный-пароль" and why5 == "", (got, why5)
print("5. файл с паролем программы — читается первым")

# --- 6. ensure_panel_password: файл приоритетнее, хэш не трогается
root6 = make_base([("password", json.dumps("$2b$12$" + "x" * 53))])
assert omniroute.ensure_panel_password(root5) == "сгенерированный-пароль"
assert omniroute.ensure_panel_password(root6) == ""
assert omniroute.ensure_panel_password(root3) != ""
assert (root6 / "omniroute-data" / "panel-password.txt").is_file() is False
print("6. ensure_panel_password: файл повторно используется, хэш не трогается")
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
