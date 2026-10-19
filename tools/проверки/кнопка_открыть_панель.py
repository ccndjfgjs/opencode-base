"""Живая проверка кнопки «Открыть панель»: в окне и в трее.

Временный файл, в самопроверку не входит.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

app = QApplication.instance() or QApplication([])

import main as app_main  # noqa: E402
import tray_panel  # noqa: E402
import omniroute  # noqa: E402

w = app_main.MainWindow()
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
w.resize(880, 620)

print("готово окно")
caps = w.caps_tab
print("строка реестра:", caps.reg_table.rowCount(), "строк")
btn = getattr(caps, "btn_or_open", None)
print("кнопка «Открыть панель» есть:", btn is not None)
if btn is not None:
    print("  подпись:", btn.text())
    print("  активна сейчас:", btn.isEnabled(), "(строка не выбрана — верно False)")

    # выбираем строку omniroute
    for i, s in enumerate(caps.reg_servers):
        if s.id == "omniroute":
            caps.reg_table.setCurrentCell(i, 0)
            break
    print("  активна у строки OmniRoute:", btn.isEnabled())
    tip = btn.toolTip()
    print("  подсказка:", tip[:100])

    # живая проверка панели
    ok, note = omniroute.panel_ready(omniroute.find_settings_dir())
    print("живая панель:", ok, "|", note[:100])

print()
print("=== панель трея ===")
panel = tray_panel.TrayPanel(w)
sections = {s.title: s for s in panel._sections}
print("разделы:", sorted(sections))
for title, sec in sections.items():
    for e in sec.entries:
        if "omniroute" in e.name.lower():
            print(f"  строка: {e.name[:50]}")
            print(f"  состояние: {e.state[:70]}")
            print(f"  кнопки: {[c for c, _ in e.actions]}")
print()
print("PANEL_URLS:", {k: v() for k, v in tray_panel.PANEL_URLS.items()})
print("ГОТОВО")