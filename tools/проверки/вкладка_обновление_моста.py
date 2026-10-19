"""Живая проверка вкладки «Обновление» для моста OmniRoute.

Временный файл, в самопроверку не входит.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
PROG = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))

from PyQt6.QtCore import Qt, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import update_tab  # noqa: E402
import omniroute  # noqa: E402

t = update_tab.UpdateTab()
t.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
t.resize(880, 620)

print("ДО нажатия")
print("  стоит:", t.lbl_or.text().replace("\n", " | ")[:120])
print("  «Обновить мост» активна:", t.btn_or_update.isEnabled())

print()
print("нажимаю «Проверить» — жду ответ GitHub…")
t.btn_or_check.click()

deadline = [0]


def poll():
    deadline[0] += 500
    if t._worker is not None and deadline[0] < 120_000:
        QTimer.singleShot(500, poll)
        return
    print()
    print("ПОСЛЕ нажатия")
    print("  журнал:", t.lbl_step.text()[:220])
    print("  стоит:", t.lbl_or.text().replace("\n", " | ")[:140])
    print("  «Проверить» снова активна:", t.btn_or_check.isEnabled())
    print("  «Обновить мост» активна:", t.btn_or_update.isEnabled())
    print("  найденная версия:", getattr(t, "_or_remote", ""))
    app.quit()


QTimer.singleShot(500, poll)
app.exec()
print("ГОТОВО")