"""Окно управления базой: создать новую или подключить существующую.

Запуск:
    python tools/dbapp/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import core  # type: ignore[import-not-found]
    import ui  # type: ignore[import-not-found]
    import opencode_caps  # type: ignore[import-not-found]
else:  # запуск как модуль
    from . import core, ui, opencode_caps

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------- рабочий поток


class ScrollPage(QScrollArea):
    """Вкладка с прокруткой.

    Без неё, если содержимое не помещается в окно, Qt сжимает элементы
    и накладывает их друг на друга — получается «каша» из подписей.
    Прокрутка это решает: содержимое держит свои размеры, а лишнее
    уходит вниз под колесо мыши.
    """

    def __init__(self, inner: QWidget, parent=None) -> None:
        super().__init__(parent)
        self.setWidget(inner)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # колесо мыши должно крутить содержимое, а не «залипать» на краях
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        inner.setAutoFillBackground(False)
        # страницу запрещаем сжимать: её высота — это её настоящая высота.
        # Иначе Qt подгоняет её под окно и рисует элементы друг поверх друга.
        inner.setMinimumHeight(inner.sizeHint().height())
        inner.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self._inner = inner

    def showEvent(self, event) -> None:  # noqa: D102
        """Пересчитываем нужную высоту при каждом показе вкладки."""
        super().showEvent(event)
        self.refresh_height()

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self.refresh_height()

    def refresh_height(self) -> None:
        """Держит минимальную высоту страницы по её содержимому."""
        layout = self._inner.layout()
        if layout is None:
            return
        need = layout.minimumSize().height()
        hint = layout.sizeHint().height()
        value = max(need, hint)
        if self._inner.minimumHeight() != value:
            self._inner.setMinimumHeight(value)


class Worker(QThread):
    """Выполняет длинную работу в стороне, чтобы окно не замирало."""

    line = pyqtSignal(str, str)

    def __init__(self, func, parent=None) -> None:
        super().__init__(parent)
        self._func = func
        self.result = None

    def run(self) -> None:  # noqa: D102
        try:
            self.result = self._func(self._progress)
        except Exception as exc:  # показываем причину, а не падаем
            self.line.emit(f"Ошибка: {exc}", "error")
            self.result = exc

    def _progress(self, text: str) -> None:
        self.line.emit(text, "info")


# ---------------------------------------------------------------- подсказки


def подсказка_где_база(folder: Path) -> str:
    """Объясняет, почему папка не подошла и где искать настоящую базу.

    Пустая папка — самая частая причина. Тогда ищем базы рядом:
    может, выбрана папка-родитель, а база лежит внутри.
    """
    try:
        внутри = [d for d in folder.iterdir() if d.is_dir()]
    except OSError:
        внутри = []

    найдены = []
    for d in внутри[:40]:
        try:
            if (d / core.REQUIRED_FILES[0]).is_file():
                найдены.append(d.name)
        except OSError:
            continue

    если_пусто = not any(folder.iterdir()) if folder.is_dir() else False
    хвост = ""
    if len(найдены) == 1:
        хвост = (
            f"\n\nПохоже, база лежит внутри этой папки — "
            f"выберите вложенную папку «{найдены[0]}»."
        )
    elif найдены:
        хвост = (
            "\n\nВнутри этой папки есть готовые базы: "
            + ", ".join(f"«{n}»" for n in найдены[:5])
            + ". Выберите одну из них."
        )
    elif если_пусто:
        хвост = (
            "\n\nПапка пустая. Нужно выбрать ту папку, которую создала "
            "программа: в ней должны лежать файлы "
            + ", ".join(core.REQUIRED_FILES)
            + "."
        )
    else:
        хвост = (
            "\n\nГотовых баз внутри нет. Проверьте, что выбран именно тот "
            "путь, который был указан при создании: в базе обязаны лежать "
            "файлы " + ", ".join(core.REQUIRED_FILES) + "."
        )
    return f"Не похоже на базу: нет файла {core.REQUIRED_FILES[0]}." + хвост


# ---------------------------------------------------------------- вкладка 1


class CreateTab(ScrollPage):
    """Создание новой пустой базы и подключение её к программе."""

    base_ready = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        self._plan: core.CreationPlan | None = None
        self._worker: Worker | None = None
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    # ---- сборка окна

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        outer.addWidget(
            ui.label(
                "Новая база создаётся как обычная папка с файлами — "
                "так же, как та, с которой вы работаете сейчас.",
                kind="dim",
                wrap=True,
            )
        )

        # --- шаг 1: где создать
        box_path = QGroupBox("1. Где создать базу")
        path_layout = QVBoxLayout(box_path)

        self.parent_edit = QLineEdit()
        self.parent_edit.setPlaceholderText(
            "Папка, внутри которой появится новая база"
        )
        default_parent = Path.home() / "Documents"
        if not default_parent.is_dir():
            default_parent = Path.home()
        self.parent_edit.setText(str(default_parent))
        btn_pick_parent = QPushButton("Обзор…")
        btn_pick_parent.clicked.connect(self._pick_parent)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Папка-родитель:"))
        row1.addWidget(self.parent_edit, 1)
        row1.addWidget(btn_pick_parent)
        path_layout.addLayout(row1)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("например: Моя-база")
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Имя новой базы:  "))
        row2.addWidget(self.name_edit, 1)
        path_layout.addLayout(row2)

        self.name_hint = ui.label(
            "Имя станет именем папки. Пробелы и буквы любого языка разрешены; "
            "нельзя только  < > : \" / \\ | ? *",
            kind="dim",
            wrap=True,
        )
        path_layout.addWidget(self.name_hint)

        self.path_preview = ui.label("", kind="dim", wrap=True)
        path_layout.addWidget(self.path_preview)
        outer.addWidget(box_path)

        # --- шаг 2: чем наполнить
        box_content = QGroupBox("2. Чем наполнить новую базу")
        content_layout = QVBoxLayout(box_content)

        self.radio_blank = QRadioButton("Пустая база")
        self.radio_template = QRadioButton("Скопировать содержимое существующей")
        self.radio_blank.setChecked(True)

        content_layout.addWidget(self.radio_blank)
        self.blank_hint = ui.label(
            "Личные файлы будут пустыми. Знания, скиллы, конфиг и обход блокировок придут автоматически из главной базы.",
            kind="dim",
            wrap=True,
        )
        content_layout.addWidget(self.blank_hint)
        content_layout.addWidget(self.radio_template)

        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText("Папка существующей базы с файлами")
        self.template_edit.setEnabled(False)
        self.btn_pick_template = QPushButton("Обзор…")
        self.btn_pick_template.setEnabled(False)
        self.btn_pick_template.clicked.connect(self._pick_template)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Откуда взять:"))
        row3.addWidget(self.template_edit, 1)
        row3.addWidget(self.btn_pick_template)
        content_layout.addLayout(row3)

        self.template_hint = ui.label("", kind="dim", wrap=True)
        content_layout.addWidget(self.template_hint)

        self.copy_skills = QCheckBox("Перенести скиллы из образца")
        self.copy_skills.setChecked(True)
        self.copy_skills.setEnabled(False)
        content_layout.addWidget(self.copy_skills)
        outer.addWidget(box_content)

        # --- шаг 3: куда подключить
        box_attach = QGroupBox("3. Подключить к OpenCode")
        attach_layout = QVBoxLayout(box_attach)

        self.attach_check = QCheckBox("Подключить базу к программе сразу")
        self.attach_check.setChecked(True)
        attach_layout.addWidget(self.attach_check)

        self.program_list = QListWidget()
        self.program_list.setMinimumHeight(150)
        attach_layout.addWidget(self.program_list)

        self.program_hint = ui.label("", kind="dim", wrap=True)
        attach_layout.addWidget(self.program_hint)

        note = ui.label(
            "Конфликтов с уже открытыми проектами не будет: "
            "база копируется в папку настроек программы, "
            "папки ваших проектов не затрагиваются, "
            "а прежние файлы памяти уходят в _previous-version.\n"
            "Для OpenCode дополнительно ставится плагин памяти и настройки — "
            "именно они заставляют программу читать базу и её скиллы.",
            kind="dim",
            wrap=True,
        )
        attach_layout.addWidget(note)
        outer.addWidget(box_attach)

        # --- шаг 4: ярлык
        box_link = QGroupBox("4. Ярлык на новую базу")
        link_layout = QVBoxLayout(box_link)

        self.link_check = QCheckBox("Создать ярлык, открывающий эту базу")
        self.link_check.setChecked(True)
        link_layout.addWidget(self.link_check)

        self.link_place = QComboBox()
        for ident, title in core.SHORTCUT_PLACES:
            self.link_place.addItem(title, ident)
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Где разместить:"))
        row4.addWidget(self.link_place, 1)
        link_layout.addLayout(row4)

        self.link_custom_label = QLabel("Своя папка:   ")
        self.link_custom_edit = QLineEdit()
        self.link_custom_edit.setPlaceholderText("Своя папка для ярлыка")
        self.link_custom_edit.setVisible(False)
        self.btn_pick_link = QPushButton("Обзор…")
        self.btn_pick_link.setVisible(False)
        self.link_custom_label.setVisible(False)
        self.btn_pick_link.clicked.connect(self._pick_link_folder)

        row5 = QHBoxLayout()
        row5.addWidget(self.link_custom_label)
        row5.addWidget(self.link_custom_edit, 1)
        row5.addWidget(self.btn_pick_link)
        link_layout.addLayout(row5)

        self.link_hint = ui.label("", kind="dim", wrap=True)
        link_layout.addWidget(self.link_hint)
        outer.addWidget(box_link)

        # --- кнопка и отчёт
        buttons = QHBoxLayout()
        self.btn_preview = QPushButton("Проверить")
        self.btn_preview.clicked.connect(self._preview)
        self.btn_create = QPushButton("Создать базу")
        self.btn_create.setObjectName("primary")
        self.btn_create.setEnabled(False)
        self.btn_create.clicked.connect(self._create)
        self.btn_open = QPushButton("Открыть папку")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_result)
        buttons.addWidget(self.btn_preview)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_open)
        buttons.addWidget(self.btn_create)
        outer.addLayout(buttons)

        self.log = ui.LogView()
        self.log.setMinimumHeight(170)
        outer.addWidget(self.log)

        self._created: Path | None = None

        # Слежение за полями подключаем только здесь — когда созданы все
        # элементы, на которые реагируют обработчики. Если подключить
        # раньше, обработчик сработает на ещё не созданном поле и уронит
        # программу без всякого сообщения.
        self.name_edit.textChanged.connect(self._name_changed)
        self.parent_edit.textChanged.connect(self._name_changed)
        self.radio_blank.toggled.connect(self._mode_changed)
        self.template_edit.textChanged.connect(self._check_template)
        self.attach_check.toggled.connect(self._attach_toggled)
        self.program_list.itemSelectionChanged.connect(self._program_changed)
        self.link_check.toggled.connect(self._link_toggled)
        self.link_place.currentIndexChanged.connect(self._link_place_changed)
        self._fill_programs()
        self._mode_changed()
        self._link_toggled()

        # раскладываем и фиксируем настоящую высоту страницы — иначе
        # Qt сожмёт её и элементы наедут друг на друга
        outer.activate()
        self.refresh_height()

    def _fill_programs(self) -> None:
        from PyQt6.QtGui import QColor

        for program in core.PROGRAMS:
            installed = program.is_installed()
            mark = "установлена" if installed else "не найдена"
            if not program.can_attach():
                mark += ", базу не читает"
            text = f"{program.title} — {program.hint}  [{mark}]"
            item = QListWidgetItem(text)
            item.setData(1000, program.ident)
            if not installed:
                item.setForeground(QColor(ui.TEXT_DIM))
            self.program_list.addItem(item)
        # выбираем первую установленную
        for index in range(self.program_list.count()):
            ident = self.program_list.item(index).data(1000)
            if core.PROGRAMS_BY_ID[ident].is_installed():
                self.program_list.setCurrentRow(index)
                break

    # ---- реакции

    def _program_changed(self) -> None:
        """Показывает, куда попадёт база и увидит ли её программа."""
        program = self._selected_program()
        if program is None:
            self.program_hint.setText("")
            return
        if not program.can_attach():
            self.program_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.program_hint.setText(
                f"{program.title}: {program.ability_note()} "
                "Подключить базу к этой программе нельзя — файлы туда "
                "не переносятся."
            )
            return
        text = f"Куда: {program.config_dir()}. {program.ability_note()}"
        if program.supports_skills:
            self.program_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
        else:
            self.program_hint.setStyleSheet(f"color: {ui.WARN};")
            text += " Навыки не переносятся: программа их не читает."
        self.program_hint.setText(text)

    def _pick_parent(self) -> None:
        start = self.parent_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Где создать базу", start)
        if chosen:
            self.parent_edit.setText(chosen)

    def _pick_template(self) -> None:
        start = self.template_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Выберите существующую базу", start
        )
        if chosen:
            self.template_edit.setText(chosen)
            self._check_template()

    def _mode_changed(self) -> None:
        use_template = self.radio_template.isChecked()
        self.template_edit.setEnabled(use_template)
        self.btn_pick_template.setEnabled(use_template)
        self.copy_skills.setEnabled(use_template)
        if use_template:
            self._check_template()
        else:
            self.template_hint.setText("")
        self._name_changed(self.name_edit.text())

    def _check_template(self) -> None:
        raw = self.template_edit.text().strip()
        if not raw:
            self.template_hint.setText("")
            return
        folder = Path(raw)
        if not folder.is_dir():
            self.template_hint.setStyleSheet(f"color: {ui.WARN};")
            self.template_hint.setText("Такой папки нет. Проверьте путь.")
            return
        info = core.base_info(folder)
        if info["is_base"]:
            self.template_hint.setStyleSheet(f"color: {ui.OK};")
            self.template_hint.setText(
                f"Подходит: скиллов {info['skills']}, "
                f"размер {core.human_size(int(info['size']))}. "
                "Новая база будет такой же, плюс ваши имя и путь."
            )
        else:
            self.template_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.template_hint.setText(_подсказка_где_база(folder))

    def _attach_toggled(self) -> None:
        on = self.attach_check.isChecked()
        self.program_list.setEnabled(on)
        self.program_hint.setEnabled(on)

    # ---- ярлык

    def _link_toggled(self) -> None:
        on = self.link_check.isChecked()
        self.link_place.setEnabled(on)
        self._link_place_changed()

    def _link_place_changed(self) -> None:
        """Своя папка нужна только для пункта «Своя папка…»."""
        on = self.link_check.isChecked()
        own = on and self.link_place.currentData() == "custom"
        # поле показываем только когда оно нужно — иначе оно путает
        self.link_custom_label.setVisible(own)
        self.link_custom_edit.setVisible(own)
        self.btn_pick_link.setVisible(own)

        if not on:
            self.link_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            self.link_hint.setText("Ярлык создаваться не будет.")
            return

        where = self._link_folder()
        if where is None:
            self.link_hint.setStyleSheet(f"color: {ui.WARN};")
            self.link_hint.setText("Выберите папку для ярлыка.")
            return

        name = self.name_edit.text().strip() or "имя базы"
        self.link_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
        self.link_hint.setText(
            f"Появится файл «{core.safe_link_name(name)}.lnk» в папке:\n{where}\n"
            "Двойной щелчок по нему открывает папку базы в Проводнике."
        )

    def _link_folder(self) -> Path | None:
        """Папка для ярлыка или None, если выбрать нельзя."""
        base = Path(self.parent_edit.text().strip() or ".") / (
            self.name_edit.text().strip() or "база"
        )
        try:
            return core.resolve_shortcut_folder(
                self.link_place.currentData() or "",
                base,
                self.link_custom_edit.text(),
            )
        except core.NameError_:
            return None

    def _pick_link_folder(self) -> None:
        start = self.link_custom_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Где разместить ярлык", start
        )
        if chosen:
            self.link_custom_edit.setText(chosen)
            self._link_place_changed()

    def _name_changed(self, text: str) -> None:
        parent = self.parent_edit.text().strip()
        try:
            name = core.validate_name(text)
        except core.NameError_ as exc:
            self.name_edit.setProperty("bad", "true" if text.strip() else "false")
            self.name_edit.style().unpolish(self.name_edit)
            self.name_edit.style().polish(self.name_edit)
            self.name_hint.setText(str(exc).replace("\n", " "))
            self.name_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.path_preview.setText("")
            self.btn_create.setEnabled(False)
            self._plan = None
            return

        self.name_edit.setProperty("bad", "false")
        self.name_edit.style().unpolish(self.name_edit)
        self.name_edit.style().polish(self.name_edit)
        self.name_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
        self.name_hint.setText(
            "Имя станет именем папки. Пробелы и буквы любого языка разрешены; "
            "нельзя только  < > : \" / \\ | ? *"
        )
        self.path_preview.setText(f"База появится здесь:  {Path(parent) / name}")
        self.btn_create.setEnabled(True)
        self._plan = None

    # ---- действия

    def _selected_program(self) -> core.Program | None:
        item = self.program_list.currentItem()
        if item is None:
            return None
        return core.PROGRAMS_BY_ID.get(item.data(1000))

    def _make_plan(self, *, quiet: bool = False) -> core.CreationPlan | None:
        parent = Path(self.parent_edit.text().strip() or str(Path.home()))
        template = None
        if self.radio_template.isChecked():
            raw = self.template_edit.text().strip()
            if not raw:
                if not quiet:
                    self._warn("Не выбрана папка-образец.")
                return None
            template = Path(raw)
            if not (template / core.REQUIRED_FILES[0]).is_file():
                if not quiet:
                    self._warn(
                        f"В папке-образце нет файла {core.REQUIRED_FILES[0]}."
                    )
                return None
        try:
            if not parent.is_dir():
                parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if not quiet:
                self._warn(f"Папка-родитель недоступна:\n{exc}")
            return None
        try:
            return core.build_plan(parent, self.name_edit.text(), template)
        except core.NameError_ as exc:
            if not quiet:
                self._warn(str(exc))
            return None
        except OSError as exc:
            if not quiet:
                self._warn(f"Не удалось проверить место:\n{exc}")
            return None

    def _preview(self) -> None:
        plan = self._make_plan()
        if not plan:
            return
        self._plan = plan
        self.log.clear_log()
        self.log.add("Проверка пройдена. Будет создано:", "ok")
        self.log.add(f"  папка: {plan.target}", "dim")
        for folder in plan.dirs:
            self.log.add(f"  + {folder}", "dim")
        for name in plan.files:
            self.log.add(f"  файл: {name}", "dim")
        for warning in plan.warnings:
            self.log.add(f"Внимание: {warning}", "warn")

        if self.link_check.isChecked():
            where = self._link_folder()
            if where is None:
                self.log.add(
                    "Ярлык: папка не выбрана — он не будет создан.", "warn"
                )
            else:
                label = core.safe_link_name(plan.name)
                self.log.add(f"Ярлык: {where / (label + '.lnk')}", "info")
        else:
            self.log.add("Ярлык создаваться не будет.", "dim")

        if self.attach_check.isChecked():
            program = self._selected_program()
            if program:
                self.log.add(
                    f"Затем база будет подключена к «{program.title}» "
                    f"({program.config_dir()}).",
                    "info",
                )
                if not program.supports_skills:
                    self.log.add(
                        f"{program.title} скиллы не читает — они останутся "
                        "только в папке базы.",
                        "warn",
                    )
            else:
                self.log.add("Программа не выбрана — подключение пропустится.", "warn")

    def _warn(self, text: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Не получилось")
        box.setText(text)
        box.exec()

    def _create(self) -> None:
        plan = self._make_plan()
        if not plan:
            return
        self._plan = plan

        attach = self.attach_check.isChecked()
        program = self._selected_program() if attach else None
        if attach and program is None:
            self._warn("Программа для подключения не выбрана.")
            return

        # второй шанс отказаться, если папка уже занята посторонним
        if plan.warnings:
            answer = QMessageBox.question(
                self,
                "Папка не пустая",
                "\n\n".join(plan.warnings) + "\n\nПродолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.log.clear_log()
        self.btn_create.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.btn_open.setEnabled(False)

        # запоминаем выбор про ярлык до запуска работы: во время работы
        # поля окна читать нельзя
        link_on = self.link_check.isChecked()
        link_place = self.link_place.currentData() or ""
        link_custom = self.link_custom_edit.text()
        link_name = plan.name

        def job(progress):
            core.create_base(plan, progress)
            attached = None
            if attach and program is not None:
                progress(f"Подключение к «{program.title}»…")
                attached = core.attach_base(plan.target, program, progress)
                # запоминаем, к какой программе подключили — пригодится
                # при повторном подключении этой же базы
                try:
                    core.remember_base(plan.target, program.ident)
                except Exception:
                    pass

            if link_on:
                progress("Создание ярлыка…")
                link = core.create_base_shortcut(
                    plan.target, link_place, link_custom, link_name
                )
                if link.ok:
                    progress(f"Ярлык создан: {link.link}")
                else:
                    progress(f"Ярлык не создан: {link.error}")
                if attached is None:
                    return core.AttachResult(
                        ok=link.ok,
                        messages=[],
                        errors=[] if link.ok else [link.error],
                    )
                if not link.ok:
                    attached.errors.append(link.error)
                    attached.ok = False
                return attached
            return attached

        self._worker = Worker(job, self)
        self._worker.line.connect(self._on_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_line(self, text: str, tag: str) -> None:
        self.log.add(text, tag)

    def _on_done(self) -> None:
        self.btn_preview.setEnabled(True)
        self.btn_create.setEnabled(True)
        result = self._worker.result if self._worker else None
        plan = self._plan

        if isinstance(result, Exception):
            self.log.add(f"Прервано: {result}", "error")
            self.btn_open.setEnabled(False)
            self._warn(f"Создание прервано:\n{result}")
            return

        if plan is None:
            return
        self._created = plan.target
        self.btn_open.setEnabled(True)
        self.base_ready.emit(str(plan.target))

        if isinstance(result, core.AttachResult):
            if result.errors:
                self.log.add("Готово, но с замечаниями:", "warn")
                for error in result.errors:
                    self.log.add(f"  {error}", "error")
                self._warn(
                    "База создана, но подключить удалось не всё:\n\n"
                    + "\n".join(result.errors)
                )
            else:
                self.log.add("Готово: база создана и подключена.", "ok")
                self._inform_done(plan.target, result)
        else:
            self.log.add("Готово: база создана.", "ok")
            self._inform_done(plan.target, None)

    def _inform_done(self, target: Path, result: core.AttachResult | None) -> None:
        text = f"База создана:\n{target}"
        if self.link_check.isChecked():
            where = self._link_folder()
            if where is not None:
                label = core.safe_link_name(target.name)
                link = where / f"{label}.lnk"
                if link.is_file():
                    text += (
                        f"\n\nЯрлык на рабочем месте:\n{link}"
                        "\nДвойной щелчок по нему откроет папку базы."
                    )
                else:
                    text += "\n\nЯрлык создать не удалось."
        if result and result.skills_dir:
            text += f"\n\nСкиллы подключены в:\n{result.skills_dir}"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("База создана")
        box.setText(text)
        box.exec()

    def _open_result(self) -> None:
        if self._created and self._created.is_dir():
            core.open_in_explorer(self._created)


# ---------------------------------------------------------------- вкладка 2


class ImportTab(ScrollPage):
    """Подключение уже существующей базы к программе."""

    def __init__(self, parent=None) -> None:
        self._worker: Worker | None = None
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)
        outer.addWidget(
            ui.label(
                "Ваша база остаётся на месте. Её содержимое копируется "
                "в папку настроек программы; прежние файлы памяти "
                "сохраняются в _previous-version.",
                kind="dim",
                wrap=True,
            )
        )

        box_source = QGroupBox("1. Какую базу подключить")
        source_layout = QVBoxLayout(box_source)

        # --- список баз, созданных этой программой
        self.mine_list = QListWidget()
        self.mine_list.setMinimumHeight(120)
        self.mine_list.setMaximumHeight(160)
        source_layout.addWidget(
            ui.label("Созданные вами базы — выберите из списка:", kind="dim")
        )
        source_layout.addWidget(self.mine_list)

        row_mine = QHBoxLayout()
        self.btn_scan = QPushButton("Сканировать")
        self.btn_scan.clicked.connect(self._scan_bases)
        self.btn_refresh_mine = QPushButton("Обновить список")
        self.btn_refresh_mine.clicked.connect(self._fill_mine)
        self.btn_forget_mine = QPushButton("Убрать из список")
        self.btn_forget_mine.setEnabled(False)
        self.btn_forget_mine.clicked.connect(self._forget_mine)
        self.btn_delete_mine = QPushButton("Удалить базу")
        self.btn_delete_mine.setEnabled(False)
        self.btn_delete_mine.setObjectName("danger")
        self.btn_delete_mine.clicked.connect(self._delete_mine)
        row_mine.addWidget(self.btn_scan)
        row_mine.addWidget(self.btn_refresh_mine)
        row_mine.addWidget(self.btn_forget_mine)
        row_mine.addWidget(self.btn_delete_mine)
        row_mine.addStretch(1)
        source_layout.addLayout(row_mine)

        self.mine_hint = ui.label("", kind="dim", wrap=True)
        source_layout.addWidget(self.mine_hint)

        source_layout.addWidget(
            ui.label("…или укажите папку вручную:", kind="dim")
        )
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Папка с файлами базы")
        btn_browse = QPushButton("Обзор…")
        btn_browse.clicked.connect(self._pick_source)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Папка базы:"))
        row1.addWidget(self.source_edit, 1)
        row1.addWidget(btn_browse)
        source_layout.addLayout(row1)
        self.source_hint = ui.label("", kind="dim", wrap=True)
        source_layout.addWidget(self.source_hint)
        outer.addWidget(box_source)
        # подключаем слежение за полем только после того, как созданы
        # и поле, и подсказка, и кнопка — иначе обработчик сработает
        # раньше времени и уронит программу
        self.source_edit.textChanged.connect(self._check_source)

        box_target = QGroupBox("2. Подключение к OpenCode")
        target_layout = QVBoxLayout(box_target)
        self.target_list = QListWidget()
        self.target_list.setMinimumHeight(170)
        target_layout.addWidget(self.target_list)
        self.target_hint = ui.label("", kind="dim", wrap=True)
        target_layout.addWidget(self.target_hint)
        outer.addWidget(box_target)

        # --- шаг 3: какие навыки (скиллы) взять в работу
        self.box_skills = QGroupBox("3. Какие навыки подключить")
        skills_layout = QVBoxLayout(self.box_skills)
        skills_layout.addWidget(
            ui.label(
                "Навык — это умение, которое ассистент подхватывает "
                "автоматически. Отметьте нужные. Неотмеченные уберутся "
                "из программы, но сохранятся в _previous-version — "
                "выбор всегда можно переиграть.",
                kind="dim",
                wrap=True,
            )
        )
        self.skills_list = QListWidget()
        self.skills_list.setMinimumHeight(180)
        self.skills_list.setMaximumHeight(230)
        skills_layout.addWidget(self.skills_list)

        row_skills = QHBoxLayout()
        self.btn_skills_all = QPushButton("Отметить все")
        self.btn_skills_all.clicked.connect(lambda: self._set_all_skills(True))
        self.btn_skills_none = QPushButton("Снять все")
        self.btn_skills_none.clicked.connect(lambda: self._set_all_skills(False))
        row_skills.addWidget(self.btn_skills_all)
        row_skills.addWidget(self.btn_skills_none)
        row_skills.addStretch(1)
        skills_layout.addLayout(row_skills)

        self.skills_hint = ui.label("", kind="dim", wrap=True)
        skills_layout.addWidget(self.skills_hint)
        outer.addWidget(self.box_skills)

        buttons = QHBoxLayout()
        self.btn_run = QPushButton("Подключить")
        self.btn_run.setObjectName("primary")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run)
        self.btn_disconnect = QPushButton("Отключить от opencode")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self._disconnect)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_disconnect)
        buttons.addWidget(self.btn_run)
        outer.addLayout(buttons)

        self.log = ui.LogView()
        self.log.setMinimumHeight(170)
        outer.addWidget(self.log)

        # Слежение за списком подключаем здесь, когда созданы и список,
        # и подсказка, и кнопка. Если подключить раньше, обработчик
        # обратится к ещё не созданной кнопке и уронит программу молча.
        self.target_list.itemSelectionChanged.connect(self._target_changed)
        self._fill_targets()

        # список созданных баз — тоже только здесь: обработчик трогает
        # и кнопку «убрать», и поле пути
        self.mine_list.itemSelectionChanged.connect(self._mine_chosen)
        self.btn_refresh_mine.clicked.connect(self._fill_mine)
        self.btn_forget_mine.clicked.connect(self._forget_mine)
        self._fill_mine()

        # список навыков: отметки меняют подсказку и доступность кнопки
        self.skills_list.itemChanged.connect(self._skills_changed)
        self._fill_skills()

        # фиксируем настоящую высоту страницы, чтобы Qt её не сжимал
        outer.activate()
        self.refresh_height()

    def _fill_targets(self) -> None:
        from PyQt6.QtGui import QColor

        for program in core.PROGRAMS:
            installed = program.is_installed()
            mark = "установлена" if installed else "не найдена"
            if not program.can_attach():
                mark += ", базу не читает"
            text = (
                f"{program.title} — {program.hint}  "
                f"[{mark}]"
            )
            item = QListWidgetItem(text)
            item.setData(1000, program.ident)
            if not installed:
                item.setForeground(QColor(ui.TEXT_DIM))
            self.target_list.addItem(item)
        for index in range(self.target_list.count()):
            ident = self.target_list.item(index).data(1000)
            if core.PROGRAMS_BY_ID[ident].is_installed():
                self.target_list.setCurrentRow(index)
                break
        self._target_changed()

    def _scan_bases(self) -> None:
        """Сканирует рабочий стол и подпапки в поисках баз по файлу-идентификатору."""
        from PyQt6.QtGui import QColor

        self.mine_list.clear()
        found = core.scan_bases()
        for base in found:
            name = base.name
            marker = base / ".opencode-base.json"
            if marker.is_file():
                try:
                    import json
                    data = json.loads(marker.read_text(encoding="utf-8"))
                    name = str(data.get("name") or base.name)
                except (OSError, ValueError):
                    pass
            text = f"{name}  —  {base}"
            row = QListWidgetItem(text)
            row.setData(1000, str(base))
            row.setToolTip(str(base))
            self.mine_list.addItem(row)

        if not found:
            self.mine_hint.setText(
                "Базы не найдены. Создайте базу на первой вкладке — она появится "
                "здесь сама."
            )
        else:
            self.mine_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            self.mine_hint.setText(f"Найдено баз: {len(found)}")

    def _fill_mine(self) -> None:
        """Показывает базы, созданные этой программой."""
        from PyQt6.QtGui import QColor

        keep = self.source_edit.text().strip()
        self.mine_list.clear()
        main_base = core.current_base("opencode")
        main_key = str(main_base).lower() if main_base is not None else None
        entries = core.read_bases()
        for item in entries:
            folder = Path(str(item.get("path", "")))
            name = str(item.get("name") or folder.name)
            when = str(item.get("when", ""))[:10]
            text = f"{name}  —  {folder}"
            if when:
                text += f"   (создана {when})"
            if main_key and str(folder).lower() == main_key:
                text += "   ← основная"
            row = QListWidgetItem(text)
            row.setData(1000, str(folder))
            row.setToolTip(str(folder))
            self.mine_list.addItem(row)

        if not entries:
            self.mine_hint.setText(
                "Пока пусто. Создайте базу на первой вкладке — она появится "
                "здесь сама, и путь подставится без поисков."
            )
        else:
            self.mine_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            main_txt = f" Основная сейчас: {main_base.name}." if main_base else ""
            self.mine_hint.setText(
                f"Найдено баз: {len(entries)}.{main_txt} Выберите одну — путь "
                "подставится сам. Отмеченная «← основная» — действующая база."
            )

        # возвращаем прежний выбор, если он был; иначе — основную базу,
        # чтобы подключение не уводило программу в сторону
        restored = False
        for index in range(self.mine_list.count()):
            if self.mine_list.item(index).data(1000) == keep:
                self.mine_list.setCurrentRow(index)
                restored = True
                break
        if not restored and main_key:
            for index in range(self.mine_list.count()):
                if str(self.mine_list.item(index).data(1000)).lower() == main_key:
                    self.mine_list.setCurrentRow(index)
                    break
        has_item = self.mine_list.currentItem() is not None
        self.btn_forget_mine.setEnabled(has_item)
        self.btn_delete_mine.setEnabled(has_item)

    def _mine_chosen(self) -> None:
        """Подставляет путь выбранной базы в поле."""
        item = self.mine_list.currentItem()
        has_item = item is not None
        self.btn_forget_mine.setEnabled(has_item)
        self.btn_delete_mine.setEnabled(has_item)
        if item is None:
            return
        chosen = str(item.data(1000) or "")
        if chosen and chosen != self.source_edit.text().strip():
            self.source_edit.setText(chosen)
        # переносим фокус на список программ — следующий шаг по порядку
        if self.target_list.count():
            self.target_list.setFocus()

    def _forget_mine(self) -> None:
        """Убирает базу из списка. Сама папка не трогается."""
        item = self.mine_list.currentItem()
        if item is None:
            return
        folder = Path(str(item.data(1000) or ""))
        if not folder.name:
            return
        answer = QMessageBox.question(
            self,
            "Убрать из списка",
            f"Убрать «{folder.name}» из списка?\n\n"
            f"Сама папка останется на месте:\n{folder}\n"
            "Ничего не удаляется — база просто исчезнет из подсказок.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        core.forget_base(folder)
        self._fill_mine()

    def _delete_mine(self) -> None:
        """Полностью удаляет базу с диска и из списка."""
        item = self.mine_list.currentItem()
        if item is None:
            return
        folder = Path(str(item.data(1000) or ""))
        if not folder.name:
            return
        answer = QMessageBox.question(
            self,
            "Удалить базу навсегда",
            f"Удалить базу «{folder.name}» НАВСЕГДА?\n\n"
            f"Папка будет удалена с диска:\n{folder}\n\n"
            "Это действие НЕОБРАТИМО. Бэкап не будет создан автоматически.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        ok, message = core.delete_base(folder)
        if ok:
            self.log.add(message, "ok")
        else:
            self.log.add(message, "error")
        self._fill_mine()

    def _disconnect(self) -> None:
        """Полностью отключает выбранную базу от opencode."""
        folder_text = self.source_edit.text().strip()
        if not folder_text:
            self._warn("Сначала выберите базу в поле пути.")
            return
        folder = Path(folder_text)
        if not folder.is_dir():
            self._warn(f"Такой папки нет:\n{folder}")
            return

        # Проверяем, что это действительно база
        info = core.base_info(folder)
        if not info["is_base"]:
            self._warn("Выбранная папка не является базой.")
            return

        # Проверяем, что она сейчас основная
        main_base = core.current_base("opencode")
        if main_base is None or str(main_base).lower() != str(folder).lower():
            answer = QMessageBox.question(
                self,
                "База не основная",
                f"База «{folder.name}» сейчас не подключена к opencode.\n\n"
                "Отключать нечего. Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            answer = QMessageBox.question(
                self,
                "Отключить базу от opencode",
                f"Это полностью отключит базу «{folder.name}» от opencode:\n\n"
                "• Удалятся instructions, мосты ncp/pc и права из opencode.jsonc\n"
                "• Удалится memory-base-path.txt\n"
                "• Удалятся скиллы этой базы из ~/.config/opencode/skills/\n"
                "• Конфиг NCP-моста сбросится (если ведёт на эту базу)\n\n"
                "Сама папка базы на диске НЕ ТРОНУТА.\n\n"
                "Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.log.add(f"Отключение базы: {folder}")
        self.btn_disconnect.setEnabled(False)
        self.btn_run.setEnabled(False)

        def job(progress):
            progress(f"Отключаем {folder.name} от opencode…")
            return core.disconnect_base(folder, "opencode")

        self._worker = Worker(job, self)
        self._worker.line.connect(self.log.add)
        self._worker.finished.connect(self._on_disconnected)
        self._worker.start()

    def _on_disconnected(self) -> None:
        self.btn_disconnect.setEnabled(True)
        self.btn_run.setEnabled(True)
        result = self._worker.result if self._worker else None
        if isinstance(result, Exception):
            self.log.add(f"Прервано: {result}", "error")
            return
        if not isinstance(result, tuple) or len(result) != 2:
            self.log.add("Отключить не удалось.", "error")
            return
        messages, errors = result
        for m in messages:
            self.log.add(m, "ok")
        for e in errors:
            self.log.add(e, "error")
        if not errors:
            self.log.add("База отключена. Перезапустите opencode.", "ok")
        else:
            self.log.add("Есть ошибки — проверьте вручную.", "warn")
        # Обновляем состояние подсказки
        self._check_source()
        self._refresh_run()

    def _pick_source(self) -> None:
        start = self.source_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Выберите базу", start)
        if chosen:
            self.source_edit.setText(chosen)
            self._check_source()

    def _check_source(self) -> None:
        raw = self.source_edit.text().strip()
        if not raw:
            self.source_hint.setText("")
            self.btn_run.setEnabled(False)
            return
        folder = Path(raw)
        if not folder.is_dir():
            self.source_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.source_hint.setText("Такой папки нет.")
            self.btn_run.setEnabled(False)
            return
        info = core.base_info(folder)
        if not info["is_base"]:
            self.source_hint.setStyleSheet(f"color: {ui.ERROR};")
            подсказка = self._подсказка_где_база(folder)
            self.source_hint.setText(подсказка)
            self.btn_run.setEnabled(False)
            return
        files = ", ".join(str(f) for f in info["files"])
        marker = info["marker"] or {}
        created = f" Создана: {marker['created'][:10]}." if marker.get("created") else ""
        main_base = core.current_base("opencode")
        main_note = ""
        if main_base is not None and str(main_base).lower() == str(folder).lower():
            main_note = "\nЭта база сейчас основная."
        self.source_hint.setStyleSheet(f"color: {ui.OK};")
        self.source_hint.setText(
            f"База найдена. Скиллов: {info['skills']}. "
            f"Размер: {core.human_size(int(info['size']))}.{created}{main_note}\n"
            f"Файлы: {files}"
        )
        # сменилась база — перечитываем её навыки в шаге 3
        if hasattr(self, "skills_list"):
            self._fill_skills()
        self._refresh_run()

    def _подсказка_где_база(self, folder: Path) -> str:
        return подсказка_где_база(folder)

    # ---- шаг 3: навыки

    def _fill_skills(self) -> None:
        """Наполняет список навыками из выбранной базы.

        Все отмечены по умолчанию: обычный случай — перенести весь набор.
        Снимать нужно только то, что не нужно.

        Выбор помнится, но только внутри одной базы: при смене базы
        набор навыков другой, и переносить прежние галочки было бы
        неверно. Поэтому запоминаем не «галочки», а путь базы, для
        которой они поставлены.
        """
        from PyQt6.QtGui import QColor

        raw = self.source_edit.text().strip()
        folder = Path(raw) if raw else None

        # Для новой базы — всё отмечено заново; для той же самой
        # сохраняем то, что пользователь уже расставил.
        same_base = (
            getattr(self, "_skills_base", None) is not None
            and folder is not None
            and str(folder) == self._skills_base
        )
        chosen_before = set(self._chosen_skills()) if same_base else None

        self.skills_list.blockSignals(True)
        self.skills_list.clear()
        self._skills_data = []
        self._skills_base = str(folder) if folder else None

        entries = core.list_skills(folder) if folder and folder.is_dir() else []

        for skill in entries:
            title = skill["title"]
            desc = skill["description"]
            text = f"{title}"
            if desc:
                short = desc if len(desc) <= 120 else desc[:117].rstrip() + "…"
                text += f"\n{short}"
            row = QListWidgetItem(text)
            row.setData(1000, skill["name"])
            row.setToolTip(desc or title)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # тот же набор, что был, — возвращаем прежние отметки;
            # новая база — отмечаем всё
            keep = True if chosen_before is None else (skill["name"] in chosen_before)
            row.setCheckState(
                Qt.CheckState.Checked if keep else Qt.CheckState.Unchecked
            )
            if not desc:
                row.setForeground(QColor(ui.TEXT_DIM))
            self.skills_list.addItem(row)
            self._skills_data.append(skill)

        self.skills_list.blockSignals(False)
        self._skills_changed()

    def _chosen_skills(self) -> list[str]:
        names: list[str] = []
        if not hasattr(self, "skills_list"):
            return names
        for index in range(self.skills_list.count()):
            row = self.skills_list.item(index)
            if row.checkState() == Qt.CheckState.Checked:
                names.append(str(row.data(1000)))
        return names

    def _set_all_skills(self, on: bool) -> None:
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.skills_list.blockSignals(True)
        for index in range(self.skills_list.count()):
            self.skills_list.item(index).setCheckState(state)
        self.skills_list.blockSignals(False)
        self._skills_changed()

    def _skills_changed(self) -> None:
        """Обновляет подсказку под списком навыков и доступность кнопки."""
        total = self.skills_list.count()
        chosen = len(self._chosen_skills())

        if total == 0:
            raw = self.source_edit.text().strip()
            folder = Path(raw) if raw else None
            if not raw:
                self.skills_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
                self.skills_hint.setText(
                    "Сначала выберите базу в шаге 1 — здесь появятся "
                    "её навыки."
                )
            elif folder and (folder / "skills").is_dir():
                self.skills_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
                self.skills_hint.setText(
                    "В этой базе навыков нет — наполните папку skills, "
                    "и они появятся здесь."
                )
            else:
                self.skills_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
                self.skills_hint.setText("Навыков не найдено.")
        elif chosen == total:
            self.skills_hint.setStyleSheet(f"color: {ui.OK};")
            self.skills_hint.setText(f"Отмечены все {total} — перенесутся все.")
        elif chosen == 0:
            self.skills_hint.setStyleSheet(f"color: {ui.WARN};")
            self.skills_hint.setText(
                f"Не отмечено ни одного из {total}. Ничего не перенесётся, "
                "а прежние навыки уйдут в _previous-version."
            )
        else:
            self.skills_hint.setStyleSheet(f"color: {ui.OK};")
            self.skills_hint.setText(
                f"Отмечено {chosen} из {total}. Остальные уберутся "
                "из программы."
            )
        self._refresh_run()

    def _target_changed(self) -> None:
        item = self.target_list.currentItem()
        if item is None:
            self.target_hint.setText("")
            self._refresh_run()
            return
        program = core.PROGRAMS_BY_ID.get(item.data(1000))
        if program is None:
            self._refresh_run()
            return
        if not program.can_attach():
            self.target_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.target_hint.setText(
                f"{program.title}: {program.ability_note()} "
                "Подключить базу к этой программе нельзя — файлы туда "
                "не переносятся. Выберите другую программу."
            )
            self._refresh_run()
            return
        text = f"Куда: {program.config_dir()}. {program.ability_note()}"
        if program.supports_skills:
            self.target_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
        else:
            self.target_hint.setStyleSheet(f"color: {ui.WARN};")
            text += " Навыки не переносятся: программа их не читает."
        self.target_hint.setText(text)
        self._refresh_run()

    def _refresh_run(self) -> None:
        """Кнопка «Подключить» доступна, когда выбран путь и программа.

        Навыки намеренно не блокируют кнопку: «ни одного навыка» —
        это допустимый выбор, программа предупредит об этом отдельно.
        А программа, которая файлы с диска не читает, кнопку выключает:
        подключать к ней нечего, база всё равно останется незамеченной.

        Кнопка «Отключить от opencode» доступна, когда выбранная база
        сейчас является основной для opencode.
        """
        item = self.target_list.currentItem()
        program = core.PROGRAMS_BY_ID.get(item.data(1000)) if item else None
        ready = (
            program is not None
            and program.can_attach()
            and bool(self.source_edit.text().strip())
        )
        self.btn_run.setEnabled(ready)

        # Кнопка отключения — только если выбранная база сейчас основная для opencode
        folder_text = self.source_edit.text().strip()
        disconnect_ready = False
        if folder_text and program and program.ident == "opencode":
            main_base = core.current_base("opencode")
            if main_base is not None and str(main_base).lower() == str(Path(folder_text)).lower():
                disconnect_ready = True
        self.btn_disconnect.setEnabled(disconnect_ready)

    def _run(self) -> None:
        item = self.target_list.currentItem()
        if item is None:
            return
        program = core.PROGRAMS_BY_ID.get(item.data(1000))
        base = Path(self.source_edit.text().strip())
        if program is None or not base.is_dir():
            return

        chosen = self._chosen_skills()

        # Если навыков нет вовсе, а в базе они есть — предупреждаем,
        # что подключение уберёт прежние. Спрашиваем один раз.
        if program.supports_skills and self.skills_list.count() and not chosen:
            answer = QMessageBox.question(
                self,
                "Ни одного навыка",
                "Не отмечен ни один навык.\n\n"
                "Ничего не перенесётся, а прежние навыки уйдут "
                "в _previous-version (восстановить можно).\n\n"
                "Продолжить подключение?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.log.clear_log()
        self.btn_run.setEnabled(False)

        def job(progress):
            return core.attach_base(base, program, progress, skills=chosen)

        self._worker = Worker(job, self)
        self._worker.line.connect(self.log.add)
        self._worker.finished.connect(self._done)
        self._worker.start()

    def _done(self) -> None:
        self.btn_run.setEnabled(True)
        result = self._worker.result if self._worker else None
        if isinstance(result, Exception):
            self.log.add(f"Прервано: {result}", "error")
            return
        if not isinstance(result, core.AttachResult):
            return
        if result.errors:
            self.log.add("Готово, но с замечаниями:", "warn")
            for error in result.errors:
                self.log.add(f"  {error}", "error")
        else:
            self.log.add("Готово: база подключена.", "ok")


# ---------------------------------------------------------------- вкладка 3


class BridgeTab(ScrollPage):
    """Мост NCP — маленькая программа, через которую нейросеть получает
    доступ к библиотеке: спросить состояние, найти запись, сохранить.

    Место, куда его положить, выбирает человек. Ни одного вписанного
    пути здесь нет и быть не должно: иначе мост не заработает на другом
    компьютере, а ради этого он и делается.
    """

    def __init__(self, parent=None) -> None:
        self._worker: Worker | None = None
        self._what = ""
        self._result: core.BridgeResult | None = None
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    # ---- сборка окна

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        outer.addWidget(
            ui.label(
                "Здесь создаётся ОТДЕЛЬНАЯ копия моста в выбранной папке. "
                "Для opencode это обычно не нужно: мост уже лежит в базе, "
                "а подключается он галочкой «Подключить мост памяти» "
                "на вкладке «opencode».",
                kind="dim",
                wrap=True,
            )
        )

        # --- шаг 1: куда положить
        box_where = QGroupBox("1. Куда положить мост")
        where_layout = QVBoxLayout(box_where)

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Папка, в которой появится мост")
        self.folder_edit.setText(str(core.bridge_default_dir()))
        btn_pick_folder = QPushButton("Обзор…")
        btn_pick_folder.clicked.connect(self._pick_folder)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Папка моста:   "))
        row1.addWidget(self.folder_edit, 1)
        row1.addWidget(btn_pick_folder)
        where_layout.addLayout(row1)

        where_layout.addWidget(
            ui.label(
                "Место любое: файлы моста не привязаны к пути. Если папки "
                "нет — она будет создана. В чужую непустую папку программа "
                "писать не станет.",
                kind="dim",
                wrap=True,
            )
        )

        self.where_hint = ui.label("", kind="dim", wrap=True)
        where_layout.addWidget(self.where_hint)
        outer.addWidget(box_where)

        # --- шаг 2: к какой библиотеке
        box_lib = QGroupBox("2. К какой библиотеке подключить")
        lib_layout = QVBoxLayout(box_lib)

        self.library_edit = QLineEdit()
        self.library_edit.setPlaceholderText("Папка базы или папка библиотеки")
        self.library_edit.setText(str(core.library_dir(core.app_root())))
        btn_pick_lib = QPushButton("Обзор…")
        btn_pick_lib.clicked.connect(self._pick_library)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Библиотека:   "))
        row2.addWidget(self.library_edit, 1)
        row2.addWidget(btn_pick_lib)
        lib_layout.addLayout(row2)

        self.library_hint = ui.label("", kind="dim", wrap=True)
        lib_layout.addWidget(self.library_hint)
        outer.addWidget(box_lib)

        # --- шаг 3: куда подключить
        box_prog = QGroupBox("3. Куда подключить")
        prog_layout = QVBoxLayout(box_prog)

        prog_layout.addWidget(
            ui.label(
                "Мост один и тот же. Для opencode — готовые кнопки "
                "на вкладке «opencode». Для Харнеса — YAML-оверлей ниже: "
                "сохрани его и примени как dsh --patch <файл>.",
                kind="dim",
                wrap=True,
            )
        )

        self.radio_open = QRadioButton("Для opencode (JSON)")
        self.radio_harness = QRadioButton("Для Харнеса (YAML-оверлей)")
        self.radio_open.setChecked(True)
        row_prog = QHBoxLayout()
        row_prog.addWidget(QLabel("Показать настройки:"))
        row_prog.addWidget(self.radio_open)
        row_prog.addWidget(self.radio_harness)
        row_prog.addStretch(1)
        prog_layout.addLayout(row_prog)

        self.program_hint = ui.label("", kind="dim", wrap=True)
        prog_layout.addWidget(self.program_hint)

        prog_layout.addWidget(QLabel("Настройки моста — их можно скопировать:"))
        self.snippet = ui.LogView()
        self.snippet.setMinimumHeight(110)
        prog_layout.addWidget(self.snippet)

        row_save = QHBoxLayout()
        self.btn_save_overlay = QPushButton("Сохранить YAML для Харнеса")
        self.btn_save_overlay.clicked.connect(self._save_overlay)
        row_save.addStretch(1)
        row_save.addWidget(self.btn_save_overlay)
        prog_layout.addLayout(row_save)
        outer.addWidget(box_prog)

        # --- кнопки
        buttons = QHBoxLayout()
        self.btn_create = QPushButton("Создать мост")
        self.btn_create.setObjectName("primary")
        self.btn_create.clicked.connect(self._create)
        self.btn_check = QPushButton("Проверить")
        self.btn_check.clicked.connect(self._check)
        self.btn_open = QPushButton("Открыть папку")
        self.btn_open.clicked.connect(self._open)
        buttons.addWidget(self.btn_create)
        buttons.addWidget(self.btn_check)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_open)
        outer.addLayout(buttons)

        self.log = ui.LogView()
        self.log.setMinimumHeight(170)
        outer.addWidget(self.log)

        # Связи — только здесь, когда все элементы уже созданы. Если
        # подключить раньше, обработчик сработает на несуществующем поле
        # и уронит программу без всякого сообщения.
        self.folder_edit.textChanged.connect(self._refresh)
        self.library_edit.textChanged.connect(self._refresh)
        self.radio_open.toggled.connect(self._bridge_target_changed)
        self._refresh()

        outer.activate()
        self.refresh_height()

    # ---- подсказки и состояние

    def _refresh(self) -> None:
        """Показывает, что уже есть на месте, а чего не хватает."""
        folder_text = self.folder_edit.text().strip()
        if folder_text:
            folder = Path(folder_text)
            status = core.bridge_status(folder)
            if status.exists:
                text = "В этой папке мост уже есть — файлы будут обновлены."
                if status.library:
                    text += f"\nОн подключён к библиотеке:\n{status.library}"
                if status.problem:
                    text += f"\nЗамечание: {status.problem}"
                self.where_hint.setStyleSheet(f"color: {ui.OK};")
            elif status.problem:
                self.where_hint.setStyleSheet(f"color: {ui.WARN};")
                text = status.problem
            else:
                self.where_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
                text = "Папки пока нет — она будет создана при первом создании моста."
            self.where_hint.setText(text)
        else:
            self.where_hint.setText("")

        lib_text = self.library_edit.text().strip()
        if lib_text:
            library = core.resolve_library(Path(lib_text))
            if core.library_ready(library.parent):
                self.library_hint.setStyleSheet(f"color: {ui.OK};")
                self.library_hint.setText(
                    f"Библиотека найдена:\n{library}\n"
                    "Записи, индекс и журнал — здесь."
                )
            else:
                self.library_hint.setStyleSheet(f"color: {ui.ERROR};")
                self.library_hint.setText(
                    "Библиотеки по этому пути нет.\n"
                    "Проверьте путь или выберите базу заново."
                )
        else:
            self.library_hint.setText("")

        python = core.find_python()
        if python is None:
            self.program_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.program_hint.setText(
                "Python не найден. Мост создастся, но запускать его будет "
                "нечем. Поставьте Python 3.8 или новее с сайта python.org — "
                "при установке отметьте галочку «Add Python to PATH»."
            )
        else:
            self.program_hint.setStyleSheet(f"color: {ui.OK};")
            self.program_hint.setText(
                f"Python для запуска моста:\n{python}\n"
                "Подключение к opencode — готовыми кнопками на вкладке "
                "«opencode»."
            )

    def _bridge_target_changed(self) -> None:
        """Переключает текст настроек между opencode и Харнесом."""
        result = getattr(self, "_result", None)
        if result is not None and result.python and result.server_py:
            self._show_snippet(result.python, result.server_py)

    def _show_snippet(self, python, server_py) -> None:
        if self.radio_harness.isChecked():
            self.snippet.setPlainText(
                core.harness_overlay_snippet(python, server_py)
            )
        else:
            self.snippet.setPlainText(
                core.mcp_snippet(python, server_py)
            )

    def _save_overlay(self) -> None:
        """Сохраняет YAML-оверлей для Харнеса рядом с мостом."""
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self._warn("Сначала выбери папку моста.")
            return
        folder = Path(folder_text)
        server_py = folder / core.BRIDGE_SERVER
        if not server_py.is_file():
            self._warn("В этой папке моста пока нет — сначала нажми «Создать мост».")
            return
        python = core.find_python()
        if python is None:
            self._warn("Python не найден — нечем заполнить команду запуска.")
            return
        target = folder / "ncp-cordis-overlay.yml"
        try:
            target.write_text(
                core.harness_overlay_snippet(python, server_py), encoding="utf-8"
            )
        except OSError as exc:
            self._warn(f"Не записался файл:\n{exc}")
            return
        self.snippet.setPlainText(
            core.harness_overlay_snippet(python, server_py)
        )
        self.log.add(f"Оверлей сохранён: {target}", "ok")
        self.log.add("Примени как: dsh --patch " + str(target), "info")

    # ---- выбор папок

    def _pick_folder(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Куда положить мост", start
        )
        if chosen:
            self.folder_edit.setText(chosen)

    def _pick_library(self) -> None:
        start = self.library_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Выберите базу или папку библиотеки", start
        )
        if chosen:
            self.library_edit.setText(chosen)

    # ---- подготовка извне (после создания базы)

    def prepare(self, library: Path | None = None) -> None:
        """Подставляет путь к только что созданной базе."""
        if library is not None:
            self.library_edit.setText(str(library))
        found = core.find_bridges()
        if found:
            self.folder_edit.setText(str(found[0]))
        self._refresh()

    # ---- запуск работы

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.btn_create,
            self.btn_check,
            self.btn_open,
        ):
            button.setEnabled(not busy)

    def _start(self, job, what: str) -> None:
        self._what = what
        self.log.clear_log()
        self._set_busy(True)
        self._worker = Worker(job, self)
        self._worker.line.connect(self.log.add)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _finished(self) -> None:
        self._set_busy(False)
        result = self._worker.result if self._worker else None
        if isinstance(result, Exception):
            self.log.add(f"Прервано: {result}", "error")
            return
        if self._what == "create":
            self._on_created(result)
        elif self._what == "check":
            self._on_checked(result)
        self._refresh()

    # ---- создание

    def _create(self) -> None:
        folder_text = self.folder_edit.text().strip()
        library_text = self.library_edit.text().strip()
        if not folder_text:
            self._warn("Не выбрана папка, куда положить мост.")
            return
        if not library_text:
            self._warn("Не выбрана библиотека, к которой подключать мост.")
            return

        folder = Path(folder_text)
        library = core.resolve_library(Path(library_text))

        def job(progress):
            return core.create_bridge(folder, library, progress=progress)

        self._start(job, "create")

    def _on_created(self, result) -> None:
        if not isinstance(result, core.BridgeResult):
            self.log.add("Работа завершилась непонятным итогом.", "error")
            return
        self._result = result
        if result.python and result.server_py:
            self._show_snippet(result.python, result.server_py)
        if result.errors:
            self.log.add("Готово, но с замечаниями:", "warn")
            for error in result.errors:
                self.log.add(f"  {error}", "error")
            self._warn("Мост создан, но не всё удалось:\n\n" + "\n\n".join(result.errors))
            return
        self.log.add("Готово: мост создан и проверен.", "ok")
        if result.folder:
            self.log.add(f"Папка моста:\n{result.folder}", "info")
        self._inform(result)

    def _inform(self, result: core.BridgeResult) -> None:
        text = f"Мост создан и проверен:\n{result.folder}"
        if result.python:
            text += f"\n\nPython для запуска:\n{result.python}"
        if self.radio_harness.isChecked():
            text += (
                "\n\nДля Харнеса: сохрани YAML кнопкой ниже и примени как "
                "dsh --patch <файл>."
            )
        else:
            text += (
                "\n\nПодключить мост к opencode — готовыми кнопками "
                "на вкладке «opencode»."
            )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Мост создан")
        box.setText(text)
        box.exec()

    # ---- проверка

    def _check(self) -> None:
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self._warn("Сначала выберите папку моста.")
            return
        folder = Path(folder_text)

        def job(progress):
            progress("Проверяем мост на временной копии библиотеки…")
            return core.bridge_selftest(folder)

        self._start(job, "check")

    def _on_checked(self, result) -> None:
        if not isinstance(result, tuple):
            self.log.add("Проверить не удалось.", "error")
            return
        ok, output = result
        for line in output.splitlines():
            self.log.add(line, "ok" if ok else "error")
        self.log.add(
            "Проверка пройдена." if ok else "Проверка не прошла.",
            "ok" if ok else "error",
        )

    # ---- прочее

    def _open(self) -> None:
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self._warn("Сначала выберите папку моста.")
            return
        folder = Path(folder_text)
        if not folder.is_dir():
            self._warn(f"Такой папки пока нет:\n{folder}")
            return
        core.open_in_explorer(folder)

    def _warn(self, text: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Не получилось")
        box.setText(text)
        box.exec()


class CapsTab(ScrollPage):
    """Возможности базы для opencode — установка по выбору.

    Ставит в настройки opencode команду /голос, мост ПК, мост памяти
    и 12 агентов. Убранная галочка при нажатии «Убрать» снимает
    только наше, чужое не трогает.
    """

    TITLES = {
        "voice": "Команда /голос — говорить в микрофон",
        "pc": "Мост ПК — файлы, программы, скриншоты (всё через спрос)",
        "ncp": "Мост NCP — память, библиотека, 7 инструментов",
        "agents": "12 агентов — поиск, план, код, проверка и другие",
        "antiblock": "Обход блокировок — запуск OpenCode через прокси, пул обновляется сам",
    }

    def __init__(self, parent=None) -> None:
        self._worker: Worker | None = None
        self._what = ""
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    # ---- сборка окна

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        outer.addWidget(
            ui.label(
                "Ставит возможности этой базы прямо в opencode — только "
                "отмеченное. Настоящие настройки лежат в папке opencode, "
                "перед правкой делается копия.",
                kind="dim",
                wrap=True,
            )
        )

        # --- шаг 1: что поставить
        box_what = QGroupBox("1. Что поставить в opencode")
        what_layout = QVBoxLayout(box_what)
        self.checks: dict[str, QCheckBox] = {}
        for name, _title in opencode_caps.CAPS:
            box = QCheckBox(self.TITLES.get(name, name))
            box.setChecked(True)
            what_layout.addWidget(box)
            self.checks[name] = box
        try:
            nagents = len(list((core.app_root() / "tools" / "agents").glob("*.md")))
            if nagents:
                self.checks["agents"].setText(
                    f"{nagents} агентов — поиск, план, код, проверка и другие"
                )
        except OSError:
            pass
        outer.addWidget(box_what)

        # --- шаг 2: куда
        box_where = QGroupBox("2. Куда ставится")
        where_layout = QVBoxLayout(box_where)
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Папка настроек opencode")
        try:
            self.dest_edit.setText(str(opencode_caps.opencode_dir()))
        except Exception:
            self.dest_edit.setText("")
        btn_pick_dest = QPushButton("Обзор…")
        btn_pick_dest.clicked.connect(self._pick_dest)
        row = QHBoxLayout()
        row.addWidget(QLabel("Папка opencode:   "))
        row.addWidget(self.dest_edit, 1)
        row.addWidget(btn_pick_dest)
        where_layout.addLayout(row)
        self.state_hint = ui.label("", kind="dim", wrap=True)
        where_layout.addWidget(self.state_hint)
        outer.addWidget(box_where)

        # --- шаг 3: провайдеры моделей (новых пресетов)
        box_prov = QGroupBox("3. Провайдеры моделей (новые пресеты)")
        prov_layout = QVBoxLayout(box_prov)
        prov_layout.addWidget(
            ui.label(
                "Провайдеры, которых нет среди встроенных в opencode. "
                "Ключи не спрашиваем и не храним: задай их сам через "
                "/connect в opencode или переменными окружения.",
                kind="dim",
                wrap=True,
            )
        )
        self.pchecks: dict[str, QCheckBox] = {}
        for name, (title, _key, _block) in opencode_caps.PROVIDER_PRESETS.items():
            box = QCheckBox(title)
            box.setChecked(False)
            prov_layout.addWidget(box)
            self.pchecks[name] = box
        outer.addWidget(box_prov)

        # --- шаг 4: обход блокировок — состав набора
        box_ab = QGroupBox("4. Обход блокировок — что именно поставить")
        ab_layout = QVBoxLayout(box_ab)
        ab_layout.addWidget(
            ui.label(
                "Работает только вместе с галочкой «Обход блокировок» выше. "
                "Прокси отдаётся только запущенному через ярлык OpenCode, "
                "остальные программы идут напрямую.",
                kind="dim",
                wrap=True,
            )
        )
        self.achecks: dict[str, QCheckBox] = {}
        for key, title in (
            ("facade", "Переводчик и запуск (фасад 127.0.0.1:17890 + ярлык-запуск)"),
            ("lists", "Бесплатные списки (SOCKS5-пул + VLESS-подписки + автообновление раз в сутки)"),
            ("dns", "Защищённый DNS (DoH: Google/Cloudflare/Quad9/AdGuard) — запасной способ обхода"),
            ("command", "Команда /обход внутри OpenCode"),
            ("shortcut", "Ярлык «OpenCode (обход)» с иконкой программы на рабочий стол"),
        ):
            box = QCheckBox(title)
            box.setChecked(True)
            ab_layout.addWidget(box)
            self.achecks[key] = box
        row_ab = QHBoxLayout()
        self.btn_ab_check = QPushButton("Проверить подключение")
        self.btn_ab_dns = QPushButton("Проверить DNS")
        row_ab.addWidget(self.btn_ab_check)
        row_ab.addWidget(self.btn_ab_dns)
        row_ab.addStretch(1)
        ab_layout.addLayout(row_ab)
        outer.addWidget(box_ab)

        # --- шаг 5: навыки поштучно
        box_skills = QGroupBox("5. Навыки — какие поставить в opencode")
        skills_layout = QVBoxLayout(box_skills)
        skills_layout.addWidget(
            ui.label(
                "Отметь нужные: отмеченные скопируются целиком, неотмеченные "
                "уйдут в _previous-version — выбор всегда можно переиграть. "
                "После установки перезапусти opencode.",
                kind="dim",
                wrap=True,
            )
        )
        self.caps_skills_list = QListWidget()
        self.caps_skills_list.setMinimumHeight(180)
        self.caps_skills_list.setMaximumHeight(230)
        skills_layout.addWidget(self.caps_skills_list)

        row_skills = QHBoxLayout()
        self.btn_skills_all = QPushButton("Отметить все")
        self.btn_skills_none = QPushButton("Снять все")
        self.btn_skills_reload = QPushButton("Обновить список")
        self.btn_skills_put = QPushButton("Поставить отмеченные")
        self.btn_skills_drop = QPushButton("Убрать отмеченные")
        row_skills.addWidget(self.btn_skills_all)
        row_skills.addWidget(self.btn_skills_none)
        row_skills.addWidget(self.btn_skills_reload)
        row_skills.addStretch(1)
        row_skills.addWidget(self.btn_skills_put)
        row_skills.addWidget(self.btn_skills_drop)
        skills_layout.addLayout(row_skills)

        self.caps_skills_hint = ui.label("", kind="dim", wrap=True)
        skills_layout.addWidget(self.caps_skills_hint)
        outer.addWidget(box_skills)

        # --- кнопки
        buttons = QHBoxLayout()
        self.btn_install = QPushButton("Поставить отмеченное")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self._install)
        self.btn_remove = QPushButton("Убрать отмеченное")
        self.btn_remove.clicked.connect(self._remove)
        self.btn_refresh = QPushButton("Обновить состояние")
        self.btn_refresh.clicked.connect(self._refresh)
        buttons.addWidget(self.btn_install)
        buttons.addWidget(self.btn_remove)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_refresh)
        outer.addLayout(buttons)

        self.log = ui.LogView()
        self.log.setMinimumHeight(170)
        outer.addWidget(self.log)

        # Связи — только здесь, когда все элементы уже созданы.
        self.dest_edit.textChanged.connect(self._refresh)
        self.btn_ab_check.clicked.connect(self._check_antiblock)
        self.btn_ab_dns.clicked.connect(self._check_dns)
        self.btn_skills_all.clicked.connect(lambda: self._set_all_caps_skills(True))
        self.btn_skills_none.clicked.connect(lambda: self._set_all_caps_skills(False))
        self.btn_skills_reload.clicked.connect(lambda: self._fill_caps_skills())
        self.btn_skills_put.clicked.connect(self._install_skills)
        self.btn_skills_drop.clicked.connect(self._remove_skills)
        self.caps_skills_list.itemChanged.connect(self._caps_skills_changed)
        self._fill_caps_skills()
        self._refresh()

        outer.activate()
        self.refresh_height()

    # ---- состояние

    def _selection(self) -> set[str]:
        return {name for name, box in self.checks.items() if box.isChecked()}

    def _pselection(self) -> set[str]:
        return {name for name, box in self.pchecks.items() if box.isChecked()}

    def _antiblock_opts(self) -> dict[str, bool]:
        """Галочки шага 4 — состав набора обхода блокировок."""
        return {key: box.isChecked() for key, box in self.achecks.items()}

    def _check_antiblock(self) -> None:
        """Кнопка «Проверить подключение»: слушает ли фасад свой порт."""
        try:
            import antiblock  # noqa: PLC0415 — рядом лежит

            ok, text = antiblock.check_connection()
        except Exception as exc:
            ok, text = False, f"Проверка не запустилась: {exc}"
        self.log.add(text, "ok" if ok else "warn")

    def _check_dns(self) -> None:
        """Кнопка «Проверить DNS»: резолвит домен через защищённый DNS."""
        self.btn_ab_dns.setEnabled(False)
        try:
            import antiblock  # noqa: PLC0415 — рядом лежит

            ok, text = antiblock.check_dns(proxy_url="")
        except Exception as exc:
            ok, text = False, f"Проверка DNS не запустилась: {exc}"
        finally:
            self.btn_ab_dns.setEnabled(True)
        self.log.add(text, "ok" if ok else "warn")

    # ---- навыки поштучно

    def _fill_caps_skills(self) -> None:
        """Список навыков базы: все отмечены, как при подключении."""
        self.caps_skills_list.blockSignals(True)
        self.caps_skills_list.clear()
        for skill in core.list_skills(self._base()):
            desc = skill["description"]
            text = skill["title"]
            if desc:
                short = desc if len(desc) <= 120 else desc[:117].rstrip() + "…"
                text += f"\n{short}"
            row = QListWidgetItem(text)
            row.setData(1000, skill["name"])
            row.setToolTip(desc or skill["title"])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)
            self.caps_skills_list.addItem(row)
        self.caps_skills_list.blockSignals(False)
        self._caps_skills_changed()

    def _chosen_caps_skills(self) -> list[str]:
        names: list[str] = []
        for index in range(self.caps_skills_list.count()):
            row = self.caps_skills_list.item(index)
            if row.checkState() == Qt.CheckState.Checked:
                names.append(str(row.data(1000)))
        return names

    def _set_all_caps_skills(self, on: bool) -> None:
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.caps_skills_list.blockSignals(True)
        for index in range(self.caps_skills_list.count()):
            self.caps_skills_list.item(index).setCheckState(state)
        self.caps_skills_list.blockSignals(False)
        self._caps_skills_changed()

    def _caps_skills_changed(self) -> None:
        total = self.caps_skills_list.count()
        chosen = len(self._chosen_caps_skills())
        if total == 0:
            self.caps_skills_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            self.caps_skills_hint.setText("В базе навыков нет — нечего ставить.")
        elif chosen == total:
            self.caps_skills_hint.setStyleSheet(f"color: {ui.OK};")
            self.caps_skills_hint.setText(f"Отмечены все: {chosen}.")
        elif chosen == 0:
            self.caps_skills_hint.setStyleSheet(f"color: {ui.WARN};")
            self.caps_skills_hint.setText(
                "Ничего не отмечено: «Поставить» переносить нечего, "
                "«Убрать» спрячет все навыки программы в _previous-version."
            )
        else:
            self.caps_skills_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            self.caps_skills_hint.setText(f"Отмечено: {chosen} из {total}.")

    def _install_skills(self) -> None:
        dest = self._dest()
        if dest is None:
            self.log.add("Не выбрана папка opencode.", "error")
            return
        chosen = self._chosen_caps_skills()
        base = self._base()

        def job(progress):
            return core.sync_selected_skills(base, dest, chosen, progress)

        self._start(job, "skills")

    def _remove_skills(self) -> None:
        dest = self._dest()
        if dest is None:
            self.log.add("Не выбрана папка opencode.", "error")
            return
        chosen = self._chosen_caps_skills()
        base = self._base()

        def job(progress):
            # Убрать = поставить пустой набор: всё уедет в _previous-version.
            kept = [n for n in self._all_caps_skill_names() if n not in set(chosen)]
            return core.sync_selected_skills(base, dest, kept, progress)

        self._start(job, "skills")

    def _all_caps_skill_names(self) -> list[str]:
        return [s["name"] for s in core.list_skills(self._base())]

    def _dest(self) -> Path | None:
        text = self.dest_edit.text().strip()
        if not text:
            return None
        return Path(text)

    def _refresh(self) -> None:
        dest = self._dest()
        if dest is None or not dest.is_dir():
            self.state_hint.setStyleSheet(f"color: {ui.WARN};")
            self.state_hint.setText("Папки пока нет — при установке будет создана.")
            return
        try:
            status = opencode_caps.caps_status(dest)
            pstatus = opencode_caps.providers_status(dest)
        except Exception as exc:
            self.state_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.state_hint.setText(f"Не прочиталось: {exc}")
            return
        inside = [self.TITLES[n] for n in status if status[n]]
        inside += [title for name, (title, _k, _b) in opencode_caps.PROVIDER_PRESETS.items()
                   if pstatus.get(name)]
        if inside:
            self.state_hint.setStyleSheet(f"color: {ui.OK};")
            self.state_hint.setText("Уже стоит:\n- " + "\n- ".join(inside))
        else:
            self.state_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            self.state_hint.setText("Наших возможностей здесь пока нет.")

    # ---- выбор папки

    def _pick_dest(self) -> None:
        start = self.dest_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Папка настроек opencode", start
        )
        if chosen:
            self.dest_edit.setText(chosen)

    # ---- запуск работы

    def _set_busy(self, busy: bool) -> None:
        for button in (self.btn_install, self.btn_remove, self.btn_refresh,
                       self.btn_skills_put, self.btn_skills_drop,
                       self.btn_skills_reload):
            button.setEnabled(not busy)

    def _start(self, job, what: str) -> None:
        self._what = what
        self.log.clear_log()
        self._set_busy(True)
        self._worker = Worker(job, self)
        self._worker.line.connect(self.log.add)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _finished(self) -> None:
        self._set_busy(False)
        result = self._worker.result if self._worker else None
        if isinstance(result, Exception):
            self.log.add(f"Прервано: {result}", "error")
            return
        messages, errors = result
        for line in messages:
            self.log.add(line, "ok")
        if errors:
            self.log.add("Готово, но с замечаниями:", "warn")
            for line in errors:
                self.log.add(f"  {line}", "error")
        else:
            self.log.add("Готово.", "ok")
        self._refresh()

    def _base(self) -> Path:
        return core.app_root()

    def _install(self) -> None:
        dest = self._dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        selection = self._selection()
        pselection = self._pselection()
        if not selection and not pselection:
            self._warn("Ничего не отмечено — отметьте хотя бы одну галочку.")
            return
        base = self._base()

        def job(progress):
            m1, e1 = ([], [])
            m2, e2 = ([], [])
            if selection:
                m1, e1 = opencode_caps.install_caps(
                    base, dest, selection, progress=progress,
                    antiblock_opts=self._antiblock_opts(),
                )
            if pselection:
                m2, e2 = opencode_caps.install_providers(dest, pselection, progress=progress)
            return (m1 + m2, e1 + e2)

        self._start(job, "install")

    def _remove(self) -> None:
        dest = self._dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        selection = self._selection()
        pselection = self._pselection()
        if not selection and not pselection:
            self._warn("Ничего не отмечено — отметьте хотя бы одну галочку.")
            return

        def job(progress):
            m1, e1 = ([], [])
            m2, e2 = ([], [])
            if selection:
                m1, e1 = opencode_caps.remove_caps(dest, selection, progress=progress)
            if pselection:
                m2, e2 = opencode_caps.remove_providers(dest, pselection, progress=progress)
            return (m1 + m2, e1 + e2)

        self._start(job, "remove")

    def _warn(self, text: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Не получилось")
        box.setText(text)
        box.exec()


# ---------------------------------------------------------------- вкладка «Инструкция»


class HelpTab(ScrollPage):
    """Детальная инструкция: как пользоваться программой."""

    def __init__(self, parent=None) -> None:
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = ui.label(text, kind="title")
        label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {ui.ACCENT};")
        return label

    @staticmethod
    def _step(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {ui.TEXT};")
        return label

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(8)

        outer.addWidget(ui.label("Как пользоваться программой", kind="title"))

        outer.addWidget(self._section("1. Что такое эта программа"))
        outer.addWidget(self._step(
            "Это конструктор баз данных для OpenCode. Она создаёт новые базы по "
            "встроенному шаблону, подключает их к OpenCode и помогает управлять "
            "обходом блокировок. Сама базы не хранит — они лежат отдельно на "
            "вашем компьютере (папка DataBases на рабочем столе)."
        ))

        outer.addWidget(self._section("2. Первый запуск"))
        outer.addWidget(self._step(
            "При первом запуске программа создаёт папку DataBases на рабочем "
            "столе и показывает окно-приветствие. Дальше новые базы можно "
            "складывать туда же — программа сама будет находить их кнопкой "
            "«Сканировать»."
        ))

        outer.addWidget(self._section("3. Создать новую базу"))
        outer.addWidget(self._step(
            "Первая вкладка «Создать новую базу»:\n"
            "1) выберите папку, где создать базу (по умолчанию — DataBases);\n"
            "2) введите имя базы (латиницей или русским);\n"
            "3) нажмите «Создать» — программа развернёт базу со всей "
            "файловой структурой, шаблонами, скиллами и инструкциями."
        ))
        outer.addWidget(self._step(
            "База — это папка с текстовыми файлами: память, библиотека знаний, "
            "скиллы, инструкции. Скиллы при создании берутся из встроенного "
            "шаблона, вместе с индексом сценариев (skills-index.json) — "
            "нейросеть читает его и сама выбирает нужный скилл по задаче."
        ))

        outer.addWidget(self._section("4. Подключить существующую базу"))
        outer.addWidget(self._step(
            "Вторая вкладка «Подключить существующую»:\n"
            "1) нажмите «Сканировать» — программа найдёт все базы с файлом-"
            "идентификатором .opencode-base.json на рабочем столе и в DataBases;\n"
            "2) выбазу из списка или укажите папку вручную через «Обзор…»;\n"
            "3) нажмите «Подключить» — файлы базы скопируются в настройки "
            "OpenCode, прежние файлы уйдут в _previous-version."
        ))

        outer.addWidget(self._section("5. Мост NCP"))
        outer.addWidget(self._step(
            "Третья вкладка «Мост NCP — создать»: создаёт переводчик между "
            "OpenCode и библиотекой знаний NCP. Мост умеет 7 операций: "
            "ncp_status (состояние), ncp_search (поиск), ncp_save (сохранить "
            "запись), ncp_read (прочитать), ncp_update (изменить), "
            "ncp_checkpoint (контрольная точка), ncp_reindex (пересобрать "
            "индекс). Путь к библиотеке подставляется автоматически."
        ))

        outer.addWidget(self._section("6. Возможности для OpenCode (вкладка «opencode»)"))
        outer.addWidget(self._step(
            "Здесь ставятся в настройки OpenCode только отмеченные возможности:\n"
            "— команда /голос (голосовой ввод);\n"
            "— мост ПК (файлы, скриншоты, список программ);\n"
            "— мост памяти NCP (7 инструментов);\n"
            "— 12 агентов (поиск, план, код, проверка и другие);\n"
            "— обход блокировок (запуск OpenCode через прокси)."
        ))

        outer.addWidget(self._section("7. Обход блокировок"))
        outer.addWidget(self._step(
            "Обход работает только для запущенного через ярлык OpenCode.\n"
            "Каналы по приоритету:\n"
            "1) V2Ray — свой Xray (узлы из встроенных VLESS-подписок, выбирается "
            "быстрейший);\n"
            "2) публичные прокси (список обновляется автоматически, источников 6);\n"
            "3) защищённый DNS (DoH: Google, Cloudflare, Quad9, AdGuard, Yandex, "
            "NextDNS, CleanBrowsing, Mullvad).\n"
            "Фасад сам выбирает канал по скорости и пишет подробный лог в окно "
            "запуска: видно, через что идёт трафик и что отвалилось."
        ))

        outer.addWidget(self._section("8. Темы (вкладка «Темы»)"))
        outer.addWidget(self._step(
            "Папка themes/ в конструкторе и в базе. Заготовка темы OpenCode — "
            "Markdown-файл с полями: цвета, шрифт, размер. Скопируйте заготовку, "
            "заполните своими значениями и попросите ассистента применить тему."
        ))

        outer.addWidget(self._section("9. Перенос на другой компьютер"))
        outer.addWidget(self._step(
            "Скопируйте папку базы целиком, установите Python с PyQt6, запустите "
            "«Управление-базой.cmd». Программа сама найдёт базу, подключит мосты "
            "и настроит OpenCode. Ничего вручную прописывать не нужно."
        ))

        outer.addWidget(self._section("10. Если что-то не работает"))
        outer.addWidget(self._step(
            "— OpenCode не видит базу → проверьте memory-base-path.txt и "
            "перезапустите OpenCode;\n"
            "— обход не подключается → запустите ярлык «OpenCode (обход)», "
            "посмотрите лог в окне;\n"
            "— мост NCP не отвечает → проверьте library_path в "
            "tools/ncp-bridge/config.json;\n"
            "— программа не открывается → нужен Python 3 с пакетом PyQt6."
        ))


# ---------------------------------------------------------------- вкладка «Темы»


class ThemesTab(ScrollPage):
    """Темы оформления OpenCode — папка в корне главной базы.

    Показывает файлы тем (Markdown-заготовки) из папки themes/ главной
    базы и даёт открыть её в проводнике. Сами темы сюда не применяются:
    вкладка — это просмотр и место, откуда удобно взять заготовку.
    """

    def __init__(self, parent=None) -> None:
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    @staticmethod
    def themes_dir() -> Path:
        """Папка тем в корне главной базы."""
        return core.program_root() / "themes"

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        outer.addWidget(
            ui.label(
                "Темы оформления OpenCode. Выберите тему и нажмите «Применить» — "
                "она скопируется в настройки OpenCode и вступит в силу после "
                "перезапуска.",
                kind="dim",
                wrap=True,
            )
        )

        box = QGroupBox("Доступные темы")
        box_layout = QVBoxLayout(box)
        self.list_ = QListWidget()
        box_layout.addWidget(self.list_, 1)
        hint = ui.label(
            "Встроенные темы — из конструктора. Свои — из папки themes/ базы.",
            kind="dim",
            wrap=True,
        )
        box_layout.addWidget(hint)
        outer.addWidget(box, 1)

        row = QHBoxLayout()
        self.btn_apply = QPushButton("Применить")
        self.btn_apply.clicked.connect(self._apply_theme)
        self.btn_open = QPushButton("Открыть папку тем")
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_refresh = QPushButton("Обновить список")
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        outer.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        """Обновляет список тем: встроенные (конструктор) + свои (база)."""
        self.list_.clear()
        seen: set[str] = set()
        for folder in (core.program_root() / "themes", core.app_root() / "themes"):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.json")):
                if path.stem in seen:
                    continue
                seen.add(path.stem)
                try:
                    import json
                    data = json.loads(path.read_text(encoding="utf-8"))
                    # Новый формат: имеет defs и theme
                    if "defs" in data and "theme" in data:
                        name = path.stem
                        mode = "dark"  # новый формат поддерживает и dark, и light
                    # Старый формат: имеет name, mode, colors
                    else:
                        name = str(data.get("name") or path.stem)
                        mode = str(data.get("mode") or "dark")
                except (OSError, ValueError):
                    name, mode = path.stem, "dark"
                item = QListWidgetItem(f"{name}  ({mode})")
                item.setData(1000, str(path))
                item.setToolTip(str(path))
                self.list_.addItem(item)
        if not self.list_.count():
            self.list_.addItem("(тем нет — добавьте JSON-файл в папку themes)")

    def _apply_theme(self) -> None:
        item = self.list_.currentItem()
        if item is None:
            self._warn("Сначала выберите тему из списка.")
            return
        path = Path(item.data(1000))
        if not path.is_file():
            self._warn(f"Файл темы не найден:\n{path}")
            return
        ok, message = core.apply_theme(path)
        if ok:
            QMessageBox.information(self, "Тема применена", message)
        else:
            self._warn(message)

    def _open_folder(self) -> None:
        folder = self.themes_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if not folder.is_dir():
            self._warn(f"Папку тем не удалось создать:\n{folder}")
            return
        core.open_in_explorer(folder)

    def _warn(self, text: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Не получилось")
        box.setText(text)
        box.exec()


# ---------------------------------------------------------------- окно


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Управление базой")
        self.setMinimumSize(720, 560)
        self.resize(880, 900)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(ui.label("Управление базой", kind="title"))
        layout.addWidget(
            ui.label(
                "База — это папка с текстовыми файлами памяти, правил и скиллов.",
                kind="dim",
            )
        )

        tabs = QTabWidget()
        self.tabs = tabs
        self.create_tab = CreateTab()
        self.import_tab = ImportTab()
        self.bridge_tab = BridgeTab()
        self.caps_tab = CapsTab()
        self.themes_tab = ThemesTab()
        self.help_tab = HelpTab()
        tabs.addTab(self.create_tab, "Создать новую базу")
        tabs.addTab(self.import_tab, "Подключить существующую")
        tabs.addTab(self.bridge_tab, "Мост NCP — создать")
        tabs.addTab(self.caps_tab, "opencode")
        tabs.addTab(self.themes_tab, "Темы")
        tabs.addTab(self.help_tab, "Инструкция")
        layout.addWidget(tabs, 1)

        self.create_tab.base_ready.connect(self._suggest_import)
        self.create_tab.base_ready.connect(self._suggest_bridge)

    def _suggest_bridge(self, path: str) -> None:
        """После создания базы предлагает завести мост NCP.

        Смысл: без моста программа библиотеку не видит — она умеет
        работать только со своими файлами. Лучше сказать об этом сразу,
        пока человек ещё здесь, чем потом искать причину.
        """
        if not path:
            return
        base = Path(path)
        if not core.library_ready(base):
            return

        # путь к новой библиотеке подставляем в любом случае: пригодится,
        # даже если сейчас человек откажется
        self.bridge_tab.prepare(core.library_dir(base))

        if core.find_bridges():
            # мост уже есть — молча готовим вкладку, спрашивать не о чем
            return

        answer = QMessageBox.question(
            self,
            "Нужен мост NCP",
            "База создана.\n\n"
            "Чтобы нейросеть увидела библиотеку, нужен мост NCP — "
            "маленькая программа-переводчик между программой и папкой "
            "с записями. Без него библиотека остаётся просто файлами, "
            "которые никто не читает.\n\n"
            "Создать мост сейчас?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.tabs.setCurrentIndex(2)

    def _suggest_import(self, path: str) -> None:
        """После создания предлагаем сразу подключить эту же базу.

        Смысл всей затеи: создали базу на первой вкладке — она сразу
        подставлена на второй, искать путь руками не нужно.
        """
        if not path:
            return
        folder = Path(path)
        if not folder.is_dir():
            return

        # обновляем список созданных баз и выделяем в нём новую
        self.import_tab._fill_mine()
        chosen = None
        for index in range(self.import_tab.mine_list.count()):
            item = self.import_tab.mine_list.item(index)
            stored = str(item.data(1000) or "")
            if not stored:
                continue
            try:
                same = Path(stored).resolve() == folder.resolve()
            except OSError:
                same = stored.lower() == str(folder).lower()
            if same:
                chosen = index
                break
        if chosen is not None:
            self.import_tab.mine_list.setCurrentRow(chosen)

        # путь всё равно подставляем: список мог оказаться пустым
        if self.import_tab.source_edit.text().strip() != str(folder):
            self.import_tab.source_edit.setText(str(folder))
        self.import_tab._check_source()

        self.tabs.setCurrentIndex(1)
        self.import_tab.mine_hint.setStyleSheet(f"color: {ui.OK};")
        self.import_tab.mine_hint.setText(
            "База создана. Она уже выбрана — осталось отметить программу "
            "и нажать «Подключить»."
        )


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Управление базой")
    ui.apply_dark_theme(app)

    if not core.first_run_done():
        folder = core.ensure_data_bases_folder()
        from ui_first_run import FirstRunDialog

        dlg = FirstRunDialog(folder)
        dlg.exec()
        core.mark_first_run_done()

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
