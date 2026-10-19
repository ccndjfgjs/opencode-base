"""Кто именно запускает внешние программы — ловушка на subprocess.Popen.

Временный файл, в самопроверку не входит.

Ловить окна перечислением не вышло: они появляются и исчезают за
доли секунды, между двумя замерами их может не быть. Поэтому ловушка
ставится ниже: на самый нижний вызов, через который проходит любой
запуск. Записывает команду и — главное — есть ли у запуска флаг
скрытия окна.

Так видно и то, что окно уже успело исчезнуть, и то, какой именно
модуль виноват: стек вызовов печатается вместе с командой.
"""
import os
import subprocess
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
PROG = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))

#: Каждый запуск: (команда, есть ли скрытие окна, откуда вызвали)
LOG: list = []

_real_popen = subprocess.Popen


class TracedPopen(_real_popen):
    def __init__(self, args, *a, **k):
        argv = args if isinstance(args, str) else " ".join(map(str, args or []))
        hiding = ("startupinfo" in k or "creationflags" in k
                  or "close_fds" in k and False)
        stack = [f.name for f in traceback.extract_stack()[:-1]]
        # Три последние кадра — там, откуда звали по-настоящему.
        where = " ← ".join(reversed(stack[-4:]))
        LOG.append((argv[:110], hiding, where))
        print(f"  ЗАПУСК: {argv[:90]}")
        print(f"          скрытие окна: {'да' if hiding else 'НЕТ'}")
        print(f"          откуда: {where}")
        super().__init__(args, *a, **k)


subprocess.Popen = TracedPopen

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import main as app_main  # noqa: E402

w = app_main.MainWindow()
w.setAttribute(__import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.WidgetAttribute.WA_DontShowOnScreen, True)
w.resize(880, 620)
caps = w.caps_tab

TARGET = sys.argv[1] if len(sys.argv) > 1 else "obs"
row = next((i for i, s in enumerate(caps.reg_servers) if s.id == TARGET), -1)
caps.reg_table.setCurrentCell(row, 0)
print(f"строка {TARGET} = {row}; окно кнопки: {caps.btn_reg_auto.text()}")


class FakeDialog:
    @staticmethod
    def exec():
        return 1  # Accepted

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def password():
        return "TestPass123"

    @staticmethod
    def messages():
        return []

    @staticmethod
    def save_path():
        return None


app_main.ObsPasswordDialog = FakeDialog

print()
print("=== нажимаю «Настроить автоматически» ===")


def done():
    from PyQt6.QtCore import QTimer
    app.quit()


from PyQt6.QtCore import QTimer  # noqa: E402
QTimer.singleShot(25_000, done)

caps._reg_auto()
app.exec()

print()
print(f"=== ВСЕГО ЗАПУСКОВ: {len(LOG)} ===")
for argv, hiding, where in LOG:
    flag = "скрыто" if hiding else "ОТКРЫВАЕТ ОКНО"
    print(f"[{flag}] {argv}")
    print(f"            {where}")
print()
print("журнал программы:")
try:
    print("  " + caps.log.toPlainText()[:500].replace("\n", "\n  "))
except Exception as exc:
    print("  не прочитан:", exc)
print("ГОТОВО")