"""Живая проверка кнопки «Развернуть» у OmniRoute.

Запуск: python tools/dbapp/test_omniroute_button.py

Задача кнопки простая: выбрать строку OmniRoute, нажать «Развернуть» и
посмотреть, что она написала. Поэтому проверка делает ровно это — в
настоящем окне программы, настоящей кнопкой, настоящим нажатием.

Ничего не ставится в настройки opencode и ничего не пишется в настоящие
файлы: кнопка «Развернуть» только ставит пакет в папку моста рядом с
программой. Если пакет уже стоит, честный ответ — «уже развёрнут», и
проверка считает это верным, а не провалом.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("OPENCODE_NO_AUTO_INSTALL", "1")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import main as app_main  # noqa: E402
import ui  # noqa: E402


def read_log(tab) -> str:
    """Читает текст из окна журнала: журнал — это QPlainTextEdit."""
    view = getattr(tab, "log", None)
    if view is None:
        return ""
    for name in ("toPlainText", "text", "plainText"):
        method = getattr(view, name, None)
        if callable(method):
            try:
                return str(method())
            except TypeError:
                continue
    return ""


def main() -> int:
    app = QApplication.instance() or QApplication(["check-omniroute"])
    ui.apply_dark_theme(app)
    window = app_main.MainWindow()
    tab = window.caps_tab

    # Настоящие настройки opencode проверке не отдаём: кнопки автонастройки
    # в других разделах пишут по-настоящему.
    import shutil
    import tempfile

    copy_dir = Path(tempfile.mkdtemp(prefix="check-omniroute-"))
    real = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if real.is_file():
        shutil.copy2(real, copy_dir / "opencode.jsonc")
    else:
        (copy_dir / "opencode.jsonc").write_text('{"mcp": {}}\n', encoding="utf-8")
    tab.dest_edit.setText(str(copy_dir))

    rows = [srv.id for srv in tab.reg_servers]
    print("строк в таблице:", len(rows))
    if "omniroute" not in rows:
        print("ПРОВАЛ: строки omniroute нет в таблице:", rows)
        return 1
    index = rows.index("omniroute")
    print(f"строка omniroute под номером {index}")

    tab.reg_table.setCurrentCell(index, 0)
    tab._reg_show_detail()
    print("кнопка «Развернуть» активна:", tab.btn_or_deploy.isEnabled())

    if not tab.btn_or_deploy.isEnabled():
        print("ПРОВАЛ: кнопка не активна — нажать её нельзя, вот и "
              "«не разворачивает»")
        return 1

    # Нажатие по-настоящему. `_start` крутит работу в отдельном потоке,
    # и ждать надо ДО КОНЦА потока, а не «пока в журнале что-то появится».
    #
    # Почему это важно, измерено 19.10.2026. Первая версия ждала появления
    # строки в журнале и выходила раньше, чем `npm install` отработал.
    # Поток ещё жил, процесс завершался — и Qt падал с кодом
    # 0xC0000409 («QThread уничтожен, пока работает»). Выглядело это как
    # поломка программы, а поломка была в проверке.
    #
    # И второе: ждать надо ПО ВРЕМЕНИ, а не по числу повторов. Первая
    # правка крутила `processEvents` 3600 раз без паузы — это секунды, а
    # не 30 минут, и проверка рапортовала «поток не закончился» на
    # только что завершившейся работе.
    import time

    tab.btn_or_deploy.click()
    deadline = time.monotonic() + 30 * 60
    while time.monotonic() < deadline:
        app.processEvents()
        worker = getattr(tab, "_worker", None)
        if worker is None or not worker.isRunning():
            break
        time.sleep(0.2)
    else:
        print("ПРОВАЛ: поток не закончился за 30 минут")
    for _ in range(40):
        app.processEvents()

    text = read_log(tab)
    print()
    print("--- журнал после нажатия ---")
    for line in text.splitlines()[-14:]:
        print("   ", line[:170])
    print("----------------------------")

    if "OmniRoute" not in text:
        print("ПРОВАЛ: в журнале нет ни слова про OmniRoute — кнопка молчит")
        return 1
    print("ИТОГ: кнопка нажата, журнал ответил")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
