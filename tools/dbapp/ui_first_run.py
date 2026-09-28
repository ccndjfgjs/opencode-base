"""Окно первого запуска: создаёт DataBases и объясняет, куда класть базы."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import ui


WELCOME_TEXT = (
    "Программа-конструктор баз данных для OpenCode.\n\n"
    "Она создаёт новые базы по шаблону и подключает их к программе. "
    "Сама базы не хранит — они лежат у вас на компьютере."
)

DATA_BASES_INFO = (
    "Папка для баз данных уже создана:\n"
    "{path}\n\n"
    "Сюда программа будет предлагать складывать новые базы. "
    "На вкладке «Подключить существующую» кнопка «Сканировать» "
    "быстро находит все базы из этой папки."
)


class FirstRunDialog(QDialog):
    """Окно первого запуска — в тёмной теме программы."""

    def __init__(self, base_folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.base_folder = base_folder
        self._build()

    def _build(self) -> None:
        self.setWindowTitle("Первый запуск — Конструктор баз OpenCode")
        self.setMinimumWidth(520)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        title = QLabel("Конструктор баз данных")
        title.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #4c9aff;"
        )
        outer.addWidget(title)

        body = QLabel(WELCOME_TEXT)
        body.setWordWrap(True)
        body.setStyleSheet("font-size: 13px; color: #e6e6e8;")
        outer.addWidget(body)

        box = QWidget()
        box.setStyleSheet(
            "background: #26272b; border: 1px solid #3a3b41; "
            "border-radius: 8px; padding: 16px;"
        )
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(10)

        box_title = QLabel("Папка для баз данных")
        box_title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #e6e6e8; border: none;"
        )
        box_layout.addWidget(box_title)

        path_label = QLabel(str(self.base_folder))
        path_label.setWordWrap(True)
        path_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; "
            "color: #9a9ba1; border: none;"
        )
        box_layout.addWidget(path_label)

        info = QLabel(DATA_BASES_INFO.format(path=self.base_folder))
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 13px; color: #e6e6e8; border: none;")
        box_layout.addWidget(info)

        outer.addWidget(box)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok = QPushButton("Начать работу")
        ok.setObjectName("primary")
        ok.setMinimumWidth(170)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        outer.addLayout(btn_row)
