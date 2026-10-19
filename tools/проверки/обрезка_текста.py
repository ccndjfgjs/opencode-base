"""Меряем обрезку текста в двух режимах Qt: обычном и offscreen.

Запуск: python tools/проверки/обрезка_текста.py

Зачем. 19.10.2026 самопроверка переведена в offscreen, и после этого три
проверки «текст не срезан» стали падать: подписи навыков не влезают в
свою кнопку. Но падает ли из-за offscreen или из-за настоящей ошибки
вёрстки — по отчёту не видно: offscreen считает ширину текста иначе.

Поэтому здесь одно и то же измеряется в обоих режимах и сравнивается:
если в обычном режиме текст влезает, а в offscreen нет — это артефакт
измерения, и падать нечему. Если и в обычном не влезает — ошибка
настоящая, и её надо чинить.

Проверка ничего не сохраняет и ничего не меняет.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))

MODE = sys.argv[1] if len(sys.argv) > 1 else "offscreen"
if MODE == "offscreen":
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
else:
    os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("OPENCODE_NO_AUTO_INSTALL", "1")

from PyQt6.QtWidgets import QApplication, QAbstractButton, QGroupBox  # noqa: E402

import main as app_main  # noqa: E402
import ui  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication(["probe"])
    ui.apply_dark_theme(app)
    window = app_main.MainWindow()
    window.showNormal()
    for _ in range(8):
        app.processEvents()

    print(f"режим: {MODE}")
    print(f"размер окна: {window.width()}x{window.height()}")
    app_font = app.font()
    print(f"шрифт программы: {app_font.family()} {app_font.pointSize()}")
    fm = app.fontMetrics()
    print("horizontalAdvance('rtk — поставить плагин') =",
          fm.horizontalAdvance("rtk — поставить плагин"))

    bad = []
    for index in range(window.tabs.count()):
        page = window.tabs.widget(index)
        if not hasattr(page, "refresh_height"):
            continue
        window.tabs.setCurrentIndex(index)
        for _ in range(3):
            app.processEvents()
        page.refresh_height()
        for _ in range(3):
            app.processEvents()
        for widget in page._inner.findChildren(QWidget):
            if not widget.isVisible() or widget.height() <= 0:
                continue
            if isinstance(widget, QAbstractButton):
                text = widget.text()
            elif isinstance(widget, QGroupBox):
                text = widget.title()
            else:
                continue
            if not text:
                continue
            need = widget.fontMetrics().horizontalAdvance(text)
            if need > widget.width() + 1:
                bad.append((window.tabs.tabText(index), text[:28],
                            need, widget.width()))
    print(f"обрезанных подписей: {len(bad)}")
    for item in bad[:8]:
        print("   ", item)
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
