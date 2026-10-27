"""Окно управления базой: создать новую или подключить существующую.

Запуск:
    python tools/dbapp/main.py
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import core  # type: ignore[import-not-found]
    import ui  # type: ignore[import-not-found]
    import mcp_registry  # type: ignore[import-not-found]
    import mcp_categories  # type: ignore[import-not-found]
    import opencode_caps  # type: ignore[import-not-found]
    import android_studio  # type: ignore[import-not-found]
    import bridge_versions  # type: ignore[import-not-found]
    import bridges  # type: ignore[import-not-found]
    import browsers  # type: ignore[import-not-found]
    import caveman  # type: ignore[import-not-found]
    import dbhub  # type: ignore[import-not-found]
    import editor_plugins  # type: ignore[import-not-found]
    import engine_setup  # type: ignore[import-not-found]
    import lmarena  # type: ignore[import-not-found]
    import auto_improve  # type: ignore[import-not-found]
    import greenlight  # type: ignore[import-not-found]
    import qwen_review  # type: ignore[import-not-found]
    import omniroute  # type: ignore[import-not-found]
    import pxpipe  # type: ignore[import-not-found]
    import rtk  # type: ignore[import-not-found]
    import program_cards  # type: ignore[import-not-found]
    import program_groups  # type: ignore[import-not-found]
    import programs  # type: ignore[import-not-found]
    import kinocut_install  # type: ignore[import-not-found]
    import telegram_check  # type: ignore[import-not-found]
    import winget_install  # type: ignore[import-not-found]
else:  # запуск как модуль
    from . import (core, ui, mcp_categories, mcp_registry, opencode_caps,
                   android_studio,
                   auto_improve, bridge_versions, bridges, browsers, caveman,
                   dbhub, editor_plugins, engine_setup, greenlight, lmarena,
                   kinocut_install, omniroute, program_cards, program_groups,
                   programs, pxpipe, qwen_review, rtk, telegram_check,
                   winget_install)

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QFrame,
    QGridLayout,
    QWidget,
)


# ---------------------------------------------------------------- рабочий поток


#: Высота строки списка навыков в пикселях и запас на рамку. Строки у нас
#: ровно две — название и короткое описание, — поэтому высота постоянная.
#: Константа, а не `sizeHintForRow`: спрашивать у виджета смысла нет, когда
#: высота строки известна и не меняется.
SKILL_ROW_PX = 26
SKILL_LIST_PAD_PX = 10


def fit_skills_height(lst) -> None:
    """Растянуть список навыков так, чтобы все были видны сразу.

    Подпись под списком говорит «Отмечены все: 32», а сам список показывал
    14 — и выглядело так, будто двух третей навыков в нём нет. Внутренняя
    прокрутка списка вводила в заблуждение: человек видел часть и считал,
    что остальных не дали. Теперь прокручивается страница целиком, а
    список показывает все навыки разом.

    Функция на уровне модуля, а не метод класса: списки живут в разных
    вкладках — `CreateTab` и `CapsTab`, — и метод одного из них из другого
    был бы недоступен.
    """
    count = lst.count()
    if count == 0:
        return
    needed = SKILL_ROW_PX * count + SKILL_LIST_PAD_PX
    target = min(needed, 1000)
    lst.setMinimumHeight(target)
    lst.setMaximumHeight(target)


def fit_rows_height(lst, limit: int = 700) -> None:
    """Растянуть список на все строки — без прокрутки внутри.

    Высота строки спрашивается у самого списка, а не берётся из
    константы: она зависит от шрифта, масштаба экрана и переносов в
    тексте, и зашитое число на другом экране врёт. Так вышло у списка
    агентов: константа обещала 26 px, а строка в две строки занимала
    42, и список показывал четыре агента из тринадцати.

    `limit` — потолок на случай совсем длинного списка: тогда он
    прокручивается внутри, но это уже честная простыня, а не окошко
    в четыре строки.
    """
    count = lst.count()
    if count == 0:
        return
    row = lst.sizeHintForRow(0)
    if row <= 0:
        return
    target = min(row * count + SKILL_LIST_PAD_PX, limit)
    if target == lst.maximumHeight() == lst.minimumHeight():
        return
    lst.setMinimumHeight(target)
    lst.setMaximumHeight(target)


class FittedList(QListWidget):
    """Список, который растягивается на все строки сам.

    `fit_rows_height` до показа окна считает высоту строки по ещё не
    применённому стилю: QSS задаёт полям пунктов 8 px, а до полировки
    их в расчёте нет, и выходит 42 вместо 52. Список получался на
    130 px ниже содержимого — внутри появлялась прокрутка, ровно та,
    от которой уходили (проверено на живой сборке 22.10.2026).

    Поэтому высота пересчитывается ещё и при показе. Сторож на
    сравнение с текущей высотой не даёт раскладке зациклиться:
    setMinimumHeight поднимает resizeEvent, и без него список звал бы
    сам себя бесконечно.
    """

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        fit_rows_height(self)

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        fit_rows_height(self)


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
        # Страницу запрещаем сжимать по высоте: её высота — это её
        # настоящая высота. Иначе Qt подгоняет её под окно и рисует
        # элементы друг поверх друга.
        inner.setMinimumHeight(inner.sizeHint().height())
        inner.setMinimumWidth(0)
        # По ширине страница обязана ужиматься вместе с окном. Раньше
        # стояло Preferred, и это означало «хочу шириной со своё
        # содержимое»: при окне 895 внутренний виджет был 825 при
        # просмотре 665, и подписи уезжали за правый край наравне с
        # рамкой, а их концы просто пропадали. По горизонтали здесь
        # та же политика Minimum, что и по высоте: содержимое может
        # стать любой ширины, лишнее уходит в перенос строк.
        inner.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
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
        """Держит минимальную высоту страницы по её содержимому.

        Заодно ограничивает ширину. Без этого страница брала ширину
        по своему содержимому и оказывалась шире окна: измерено, при
        окне 895 просмотр был 665, а внутренний виджет 825. Ряды с
        длинными подписями и таблицами уезжали за правый край, и
        концы подписей просто пропадали. Максимальная ширина заставляет
        Qt сжать содержимое до его минимумов, а горизонтальной
        прокрутки у страницы нет намеренно.
        """
        limit = self.viewport().width()
        if limit > 0 and self._inner.maximumWidth() != limit:
            self._inner.setMaximumWidth(limit)
        self._wrap_rows_later()
        self._fit_wrapped()
        layout = self._inner.layout()
        if layout is None:
            return
        layout.activate()
        need = layout.minimumSize().height()
        hint = layout.sizeHint().height()
        value = max(need, hint)
        if self._inner.minimumHeight() != value:
            self._inner.setMinimumHeight(value)

    def _wrap_rows_later(self) -> None:
        """Переносит ряды кнопок, но не сейчас, а следующим тактом.

        Перестроение раскладки прямо во время сборки окна роняет Qt на
       мертвь: проверено, окно падало с 0xC0000409 ещё на создании.
        Поэтому работа уходит в отдельный такт цикла событий, когда
        раскладки уже никто не считает, и делается один раз на страницу
        — иначе она переписывала бы саму себя при каждой смене ширины.
        """
        if getattr(self, "_rows_wrapped", False):
            return
        self._rows_wrapped = True

        def do_wrap() -> None:
            try:
                ui.wrap_button_rows(self._inner)
                self.refresh_height()
            except Exception:  # noqa: BLE001
                # Не сломанный ряд — не повод ронять программу: остаётся
                # как было, лишь часть подписей при узком окне срежется.
                self._rows_wrapped = False

        QTimer.singleShot(0, do_wrap)

    def _fit_wrapped(self) -> None:
        """Растягивает переносимые подписи под их текст.

        Qt не пересчитывает высоту подписи с переносом строк, когда
        страницу сжали по ширине: слова переносятся на новую строку,
        а рамка подписи остаётся от прежней ширины — и последняя
        строка обрезается пополам, прямо посреди букв. Измерено на
        вкладке «Программы»: 16 подписей, самая короткая имела высоту
        6 пикселей при нужных 36, то есть текст не был виден вообще.

        Считать высоту надо у каждой подписи по её собственной
        ширине, потому что длина текста разная, и после обрезки надо
        пересчитать раскладку — иначе высота страницы будет посчитана
        по старым, обрезанным подписям.

        Минимальная высота, а не фиксированная: при расширении окна
        строки снова встанут в одну, и подпись сама станет ниже.
        """
        for label in self._inner.findChildren(QLabel):
            if not label.wordWrap() or label.width() <= 0:
                continue
            needed = label.heightForWidth(label.width())
            # heightForWidth не всегда считает явные переносы «\n»:
            # последняя строка такого текста срезалась пополам. Считаем
            # строки сами и берём высоту с запасом.
            lines = label.text().count("\n") + 1
            if lines > 1:
                by_lines = lines * label.fontMetrics().lineSpacing() + 4
                needed = max(needed, by_lines)
            if needed > 0 and label.minimumHeight() != needed:
                label.setMinimumHeight(needed)


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


class QwenCheckModels(QThread):
    """Проверка доступности моделей провайдера — в стороне от окна.

    Отдельный поток, а не общий Worker: у проверки свой прогресс
    («Проверено X из Y») и свой результат — справочник состояний,
    который рисуется в своей области карточки Qwen, а не в общем
    журнале. Обработчик кнопки только запускает поток:
    check_provider_models зовётся здесь, в run(), и GUI-поток
    не блокируется.
    """

    progress = pyqtSignal(str)

    def __init__(self, dest, provider_id: str, parent=None) -> None:
        super().__init__(parent)
        self._dest = dest
        self._provider = provider_id
        self.result: object = None

    def run(self) -> None:  # noqa: D102
        try:
            self.result = qwen_review.check_provider_models(
                self._dest, self._provider,
                progress=lambda text: self.progress.emit(text))
        except Exception as exc:  # noqa: BLE001 — причина в окно, а не падение
            self.result = exc


#: Отвязанные воркеры: окно закрылось, а проверка доживает своя.
#: Пока поток работает, ссылку обязан кто-то держать — иначе Python
#: соберёт QThread прямо под работающим потоком, и процесс упадёт.
_QW_DETACHED_WORKERS: list = []


def _qw_detached_worker_finished() -> None:
    """Отвязанная проверка кончила сама — программе можно выходить."""
    app = QApplication.instance()
    if app is not None:
        app.quit()


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
        outer.setContentsMargins(18, 16, 18, 16)
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
        # По умолчанию — та самая папка DataBases, которую программа создаёт
        # при первом запуске. Раньше здесь стояли «Документы», из-за чего
        # базы уезжали мимо папки, которую же программа и рекомендует.
        # Если создать не вышло (нет прав) — берём домашнюю папку.
        try:
            default_parent = core.ensure_data_bases_folder()
        except OSError:
            default_parent = Path.home()
        if not default_parent.is_dir():
            default_parent = Path.home()
        self.parent_edit.setText(str(default_parent))
        btn_pick_parent = QPushButton("Обзор…")
        btn_pick_parent.clicked.connect(self._pick_parent)

        row1 = QHBoxLayout()
        label_parent = QLabel("Папка-родитель:")
        label_parent.setMinimumWidth(130)
        row1.addWidget(label_parent)
        row1.addWidget(self.parent_edit, 1)
        row1.addWidget(btn_pick_parent)
        path_layout.addLayout(row1)

        # Решение человека о чувствительных данных. По умолчанию
        # выключено: без прямой просьбы секретное не пишется.
        self.chk_sensitive = QCheckBox(
            "Разрешить в этой базе пароли и ключи"
        )
        self.chk_sensitive.setToolTip(
            "Сними галочку — нейросеть не будет записывать пароли, ключи "
            "и токены даже по просьбе, а предложит хранилище. "
            "По умолчанию выключено."
        )
        # Чекбокс про секреты стоит внизу блока, а не между путём и
        # именем: по смыслу он про настройку базы, а не про имя папки.

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("например: Моя-база")
        row2 = QHBoxLayout()
        label_name = QLabel("Имя новой базы:")
        label_name.setMinimumWidth(130)
        row2.addWidget(label_name)
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
        path_layout.addSpacing(4)
        path_layout.addWidget(ui.line())
        path_layout.addWidget(self.chk_sensitive)
        path_layout.addWidget(ui.label(
            "Без разрешения нейросеть не запишет в базу пароли, ключи и "
            "токены — даже по прямой просьбе.", kind="dim", wrap=True))
        outer.addWidget(box_path)

        # --- шаг 2: память этой базы. Строго один тип, хранилище одно.
        box_memory = QGroupBox("2. Память этой базы")
        memory_layout = QVBoxLayout(box_memory)

        memory_layout.addWidget(ui.label(
            "Хранилище памяти у базы одно. От него зависит, куда ассистент "
            "складывает заметки между сессиями. Остальная структура базы "
            "у всех типов одинаковая.",
            kind="dim",
            wrap=True,
        ))

        self.memory_radio: dict[str, QRadioButton] = {}
        self.memory_install_radio: dict[str, QRadioButton] = {}
        self.memory_extra: dict[str, ui.label] = {}

        # Три карточки-радио: NCP, Obsidian, Hindsight. Каждая несёт
        # data - тип памяти, подпись и подсказку про цену. Кнопки живут в
        # разных ячейках (свои карточки), поэтому связываем их группой —
        # иначе Qt не считает их взаимоисключающими.
        self.memory_group = QButtonGroup(self)
        cards = self._memory_cards_text()
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for idx, (mem, title, desc) in enumerate(cards):
            rb = QRadioButton(title)
            rb.setObjectName(f"memory-{mem}")
            rb.setProperty("memory", mem)
            self.memory_group.addButton(rb)
            self.memory_radio[mem] = rb
            hint = ui.label(desc, kind="dim", wrap=True)
            self.memory_extra[mem] = hint
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(10, 6, 10, 6)
            cell_layout.setSpacing(2)
            cell_layout.addWidget(rb)
            cell_layout.addWidget(hint)
            row = idx // 1
            grid.addWidget(cell, row, 0)
        memory_layout.addLayout(grid)

        # Выбор способа установки Hindsight: uv или docker. Показывается
        # только когда выбрана память hindsight (иначе мешает).
        self.hindsight_install_box = QWidget()
        hi_layout = QVBoxLayout(self.hindsight_install_box)
        hi_layout.setContentsMargins(0, 0, 0, 0)
        hi_layout.addWidget(ui.label(
            "Как поставить Hindsight (программа сделает это сама):",
            kind="dim",
            wrap=True,
        ))
        self.radio_hindsight_uv = QRadioButton(
            "uv — отдельный модуль"
        )
        self.radio_hindsight_docker = QRadioButton(
            "Docker — официальный образ"
        )
        self.radio_hindsight_uv.setChecked(True)
        hi_layout.addWidget(self.radio_hindsight_uv)
        hi_layout.addWidget(self.radio_hindsight_docker)
        self.hindsight_install_box.setVisible(False)
        memory_layout.addWidget(self.hindsight_install_box)

        # Кнопки управления службой Hindsight для уже созданной базы.
        self.hindsight_buttons_box = QWidget()
        hb_layout = QHBoxLayout(self.hindsight_buttons_box)
        hb_layout.setContentsMargins(0, 0, 0, 0)
        hb_layout.setSpacing(8)
        self.btn_hindsight_start = QPushButton("Запустить Hindsight")
        self.btn_hindsight_start.clicked.connect(self._hindsight_start)
        self.btn_hindsight_stop = QPushButton("Остановить")
        self.btn_hindsight_stop.clicked.connect(self._hindsight_stop)
        self.btn_hindsight_check = QPushButton("Проверить")
        self.btn_hindsight_check.clicked.connect(self._hindsight_check)
        hb_layout.addWidget(self.btn_hindsight_start)
        hb_layout.addWidget(self.btn_hindsight_check)
        hb_layout.addWidget(self.btn_hindsight_stop)
        hb_layout.addStretch(1)
        self.hindsight_status_label = ui.label("", kind="dim", wrap=True)
        hb_layout.addWidget(self.hindsight_status_label)
        self.hindsight_buttons_box.setVisible(False)
        memory_layout.addWidget(self.hindsight_buttons_box)

        # Разделитель
        memory_layout.addSpacing(2)
        memory_layout.addWidget(ui.line())
        self.memory_hint = ui.label("", kind="dim", wrap=True)
        memory_layout.addWidget(self.memory_hint)
        outer.addWidget(box_memory)

        # --- шаг 3: чем наполнить
        box_content = QGroupBox("3. Чем наполнить новую базу")
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
        content_layout.addSpacing(8)

        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText("Папка существующей базы с файлами")
        self.template_edit.setEnabled(False)
        self.btn_pick_template = QPushButton("Обзор…")
        self.btn_pick_template.setEnabled(False)
        self.btn_pick_template.clicked.connect(self._pick_template)

        row3 = QHBoxLayout()
        label_source = QLabel("Откуда взять:")
        label_source.setMinimumWidth(130)
        row3.addWidget(label_source)
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

        # --- шаг 4: куда подключить
        box_attach = QGroupBox("4. Подключить к OpenCode")
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

        # --- шаг 5: ярлык
        box_link = QGroupBox("5. Ярлык на новую базу")
        link_layout = QVBoxLayout(box_link)

        self.link_check = QCheckBox("Создать ярлык, открывающий эту базу")
        self.link_check.setChecked(True)
        link_layout.addWidget(self.link_check)

        self.link_place = QComboBox()
        for ident, title in core.SHORTCUT_PLACES:
            self.link_place.addItem(title, ident)
        row4 = QHBoxLayout()
        label_place = QLabel("Где разместить:")
        label_place.setMinimumWidth(130)
        row4.addWidget(label_place)
        row4.addWidget(self.link_place, 1)
        link_layout.addLayout(row4)

        self.link_custom_label = QLabel("Своя папка:")
        self.link_custom_label.setMinimumWidth(130)
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
        self.btn_obsidian = QPushButton("Открыть в Obsidian")
        self.btn_obsidian.setEnabled(False)
        self.btn_obsidian.clicked.connect(self._open_obsidian)
        # Кнопки живут в нижней панели окна, а не в прокрутке: раньше
        # «Создать базу» уезжала за экран вместе с длинной страницей.
        self.footer = QWidget()
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 6, 0, 0)
        footer_layout.setSpacing(8)
        footer_layout.addWidget(self.btn_preview)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.btn_open)
        footer_layout.addWidget(self.btn_obsidian)
        footer_layout.addWidget(self.btn_create)

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
        for mem, rb in self.memory_radio.items():
            rb.toggled.connect(self._memory_toggled)
        self.radio_hindsight_uv.toggled.connect(self._hindsight_install_changed)
        self.radio_hindsight_docker.toggled.connect(self._hindsight_install_changed)
        self._load_memory_prefs()
        self._fill_programs()
        self._mode_changed()
        self._link_toggled()

        # раскладываем и фиксируем настоящую высоту страницы — иначе
        # Qt сожмёт её и элементы наедут друг на друга
        outer.activate()
        self.refresh_height()

    # ---- память этой базы: выбор типа и управление Hindsight

    def _memory_cards_text(self) -> list[tuple[str, str, str]]:
        """Три карточки выбора типа памяти: (id, заголовок, подпись)."""
        return [
            (
                "ncp",
                "NCP — библиотека записей (стандарт)",
                "Папка «библиотека» с поиском и мост NCP. "
                "Инструменты ncp_* / memory_*. Рекомендуется.",
            ),
            (
                "obsidian",
                "Obsidian — хранилище заметок",
                "Сама база открывается и читается в Obsidian. "
                "Папки «библиотека» нет, мост NCP не ставится.",
            ),
            (
                "hindsight",
                "Hindsight — банк памяти",
                "Внешний банк памяти Hindsight. Папки «библиотека» нет, "
                "мост ходит на http://127.0.0.1:8888/mcp/<банк>/.",
            ),
        ]

    def _load_memory_prefs(self) -> None:
        """Тип памяти и способ установки — как в прошлый раз."""
        import memory_prefs

        memory, install = memory_prefs.load()
        rb = self.memory_radio.get(memory)
        if rb is not None:
            rb.setChecked(True)
        else:
            default = self.memory_radio.get(core.MEMORY_DEFAULT)
            if default is not None:
                default.setChecked(True)
        if install == "docker":
            self.radio_hindsight_docker.setChecked(True)
        else:
            self.radio_hindsight_uv.setChecked(True)
        self._memory_refresh()

    def _memory_toggled(self) -> None:
        import memory_prefs

        memory = self._selected_memory()
        install = self._selected_hindsight_install()
        error = memory_prefs.save(memory, install)
        self._memory_refresh(error)

    def _hindsight_install_changed(self) -> None:
        import memory_prefs

        memory = self._selected_memory()
        install = self._selected_hindsight_install()
        error = memory_prefs.save(memory, install)
        self._memory_refresh(error)

    def _selected_memory(self) -> str:
        for mem, rb in self.memory_radio.items():
            if rb.isChecked():
                return mem
        return core.MEMORY_DEFAULT

    def _selected_hindsight_install(self) -> str:
        if self.radio_hindsight_docker.isChecked():
            return "docker"
        return "uv"

    def _memory_refresh(self, error: str | None = None) -> None:
        """Показывает/скрывает блоки под выбранным типом памяти и пишет
        подсказку. Честно: отсутствие Obsidian или Docker называется вслух."""
        memory = self._selected_memory()
        install = self._selected_hindsight_install()

        # блок выбора способа установки и кнопок Hindsight — только для
        # hindsight
        self.hindsight_install_box.setVisible(memory == "hindsight")
        self.hindsight_buttons_box.setVisible(memory == "hindsight")

        # подсказка внизу блока памяти
        if error:
            self.memory_hint.setText(error)
            return
        if memory == "hindsight":
            if install == "docker":
                self.memory_hint.setText(
                    "Docker: ~9 ГБ на диске, нужен работающий Docker Desktop. "
                    "Установку сделает программа."
                )
            else:
                self.memory_hint.setText(
                    "uv: ~2–3 ГБ на диске и ~1,5–2 ГБ оперативной памяти "
                    "в момент запуска. Установку сделает программа."
                )
        elif memory == "obsidian":
            import obsidian_base
            if obsidian_base.find_obsidian() is None:
                self.memory_hint.setText(obsidian_base.missing_obsidian_text())
            else:
                self.memory_hint.setText(
                    "Obsidian найден. Будет создана совместимая база с "
                    "кнопкой «Открыть в Obsidian» под созданной базой."
                )
        else:
            self.memory_hint.setText(
                "Стандартное хранилище. Мост NCP подключается автоматически."
            )
            self.hindsight_status_label.setText("")
        self._hindsight_status()

    def _hindsight_status(self) -> None:
        """Живой статус Hindsight для кнопок. Молчания здесь быть не может."""
        if self._selected_memory() != "hindsight":
            self.hindsight_status_label.setText("")
            self.btn_hindsight_start.setEnabled(True)
            self.btn_hindsight_stop.setEnabled(False)
            return
        import hindsight_base

        try:
            status = hindsight_base.status_text()
        except Exception as exc:
            status = f"Не удалось проверить: {exc}"
        self.hindsight_status_label.setText(status)
        running = "работает" in status
        self.btn_hindsight_start.setEnabled(not running)
        self.btn_hindsight_stop.setEnabled(running)

    def _hindsight_start(self) -> None:
        import hindsight_base

        install = self._selected_hindsight_install()
        try:
            ok, log = hindsight_base.install(
                lambda s: self.log.add(s, "info"), method=install,
            )
            if not ok and log:
                self._warn("\n".join(log[-3:]))
        except Exception as exc:
            self._warn(f"Не удалось поставить Hindsight:\n{exc}")
            return
        self._hindsight_status()

    def _hindsight_stop(self) -> None:
        import hindsight_base

        try:
            note = hindsight_base.stop()
            self.log.add(note, "info")
        except Exception as exc:
            self._warn(f"Не удалось остановить Hindsight:\n{exc}")
        self._hindsight_status()

    def _hindsight_check(self) -> None:
        import hindsight_base

        try:
            note = hindsight_base.status_text()
        except Exception as exc:
            note = f"Не удалось проверить: {exc}"
        self.hindsight_status_label.setText(note)
        running = "работает" in note
        self.btn_hindsight_start.setEnabled(not running)
        self.btn_hindsight_stop.setEnabled(running)

    def _open_obsidian(self) -> None:
        """Открывает хранилище официальным адресом, а не командой.

        Отказ называет причину: нет папки, нет программы или Obsidian
        не открыл адрес. Молчаливого «открыто» здесь быть не может.
        """
        import obsidian_base

        target = self._created
        if target is None or not Path(target).is_dir():
            self._warn("База не создана, открывать нечего.")
            return
        ok, note = obsidian_base.open_vault(Path(target))
        self.log.add(note, "ok" if ok else "warn")
        if not ok:
            self._warn(note)

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
        # Пустое поле — ещё не ошибка. Красное «Имя не может быть пустым»
        # горело сразу при открытии вкладки, хотя человек ничего не вводил.
        # Показываем его только после попытки проверить или создать базу.
        if not text.strip() and not getattr(self, "_name_tried", False):
            self.name_edit.setProperty("bad", "false")
            self.name_edit.style().unpolish(self.name_edit)
            self.name_edit.style().polish(self.name_edit)
            self.name_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            self.name_hint.setText(
                "Имя станет именем папки. Пробелы и буквы любого языка "
                "разрешены; нельзя только  < > : \" / \\ | ? *"
            )
            self.path_preview.setText("")
            self.btn_create.setEnabled(False)
            self._plan = None
            return
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
        # С этого момента пустое имя — ошибка, и её видно красным.
        self._name_tried = True
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
            return core.build_plan(
                parent, self.name_edit.text(), template,
                allow_sensitive=self.chk_sensitive.isChecked(),
                memory=self._selected_memory(),
                hindsight_install=self._selected_hindsight_install(),
            )
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

        memory = plan.memory
        self.log.add(
            f"Память базы: {core.MEMORY_TITLES.get(memory, memory)}", "info"
        )
        if memory == "obsidian":
            import obsidian_base
            if obsidian_base.find_obsidian() is None:
                self.log.add(obsidian_base.missing_obsidian_text(), "warn")
            else:
                self.log.add(
                    "Obsidian: будет создана совместимая база (Главная.md), "
                    "чужие заметки не перезаписываются.",
                    "info",
                )
        elif memory == "hindsight":
            bank = ""
            try:
                bank = core.bank_slug(plan.name)
            except Exception:
                bank = "банк"
            self.log.add(
                f"Hindsight: банк «{bank}» на http://127.0.0.1:8888/mcp/{bank}/. "
                + ("Способ: Docker." if plan.hindsight_install == "docker"
                   else "Способ: uv."),
                "info",
            )

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
        self.btn_obsidian.setEnabled(False)

        # запоминаем выбор про ярлык до запуска работы: во время работы
        # поля окна читать нельзя
        link_on = self.link_check.isChecked()
        link_place = self.link_place.currentData() or ""
        link_custom = self.link_custom_edit.text()
        link_name = plan.name
        # То же с типом памяти: решение принято до запуска, во время
        # работы поля окна недоступны.
        memory = plan.memory
        self._obsidian_extra = {"notes": [], "errors": [], "wanted": memory == "obsidian"}

        def job(progress):
            core.create_base(plan, progress)
            if memory == "obsidian":
                import obsidian_base
                notes, errors = obsidian_base.apply(
                    plan.target, obsidian=True, agent=False,
                )
                self._obsidian_extra = {
                    "notes": notes, "errors": errors, "wanted": True,
                }
                for line in notes:
                    progress(line)
                for line in errors:
                    progress(line)
            if memory == "hindsight":
                progress("Установка Hindsight…")
                try:
                    import hindsight_base
                    ok, log = hindsight_base.install(
                        progress, method=plan.hindsight_install or "uv",
                    )
                    if not ok:
                        self._obsidian_extra = {
                            "notes": [], "errors": log[-3:], "wanted": False,
                        }
                except Exception as exc:
                    self._obsidian_extra = {
                        "notes": [], "errors": [f"Hindsight: {exc}"], "wanted": False,
                    }
                    progress(f"Hindsight: {exc}")
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
            self.btn_obsidian.setEnabled(False)
            self._warn(f"Создание прервано:\n{result}")
            return

        if plan is None:
            return
        self._created = plan.target
        self.btn_open.setEnabled(True)
        extra = getattr(self, "_obsidian_extra", None) or {}
        self.btn_obsidian.setEnabled(bool(extra.get("wanted")) and plan.target.is_dir())
        self.base_ready.emit(str(plan.target))

        extra = getattr(self, "_obsidian_extra", None) or {}
        memory_errors = list(extra.get("errors") or [])
        if isinstance(result, core.AttachResult):
            if result.errors or memory_errors:
                self.log.add("Готово, но с замечаниями:", "warn")
                for error in result.errors:
                    self.log.add(f"  {error}", "error")
                for error in memory_errors:
                    self.log.add(f"  {error}", "error")
                parts = []
                if result.errors:
                    parts.append("Подключить удалось не всё:\n" + "\n".join(result.errors))
                if memory_errors:
                    parts.append("Память базы:\n" + "\n".join(memory_errors))
                self._warn("База создана, но не всё прошло:\n\n" + "\n\n".join(parts))
            else:
                self.log.add("Готово: база создана и подключена.", "ok")
                self._inform_done(plan.target, result)
        else:
            if memory_errors:
                self.log.add("База создана, память — с замечаниями:", "warn")
                self._warn("База создана, но память:\n\n" + "\n".join(memory_errors))
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
        outer.setContentsMargins(18, 16, 18, 16)
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
        self.btn_forget_mine = QPushButton("Убрать из списка")
        self.btn_forget_mine.setEnabled(False)
        self.btn_forget_mine.clicked.connect(self._forget_mine)
        # Временные папки (Temp) попадают в список после самопроверок и
        # остаются мусором. Убираем их одной кнопкой, папки не трогаем.
        self.btn_forget_temp = QPushButton("Убрать временные")
        self.btn_forget_temp.setToolTip(
            "Убрать из списка записи, чьи папки лежат во временной папке "
            "Windows. Сами папки не удаляются"
        )
        self.btn_forget_temp.clicked.connect(self._forget_temp)
        self.btn_delete_mine = QPushButton("Удалить базу")
        self.btn_delete_mine.setEnabled(False)
        self.btn_delete_mine.setObjectName("danger")
        self.btn_delete_mine.clicked.connect(self._delete_mine)
        row_mine.addWidget(self.btn_scan)
        row_mine.addWidget(self.btn_refresh_mine)
        row_mine.addWidget(self.btn_forget_mine)
        row_mine.addWidget(self.btn_forget_temp)
        row_mine.addStretch(1)
        source_layout.addLayout(row_mine)

        self.mine_hint = ui.label("", kind="dim", wrap=True)
        source_layout.addWidget(self.mine_hint)

        # Опасное действие — отдельно от безопасных и справа: случайно
        # нажать «Удалить базу» рядом с «Обновить список» слишком просто.
        danger_row = QHBoxLayout()
        self.chk_show_temp = QCheckBox("Показывать временные")
        self.chk_show_temp.setToolTip(
            "Записи из временной папки Windows — обычно следы самопроверок")
        self.chk_show_temp.toggled.connect(self._fill_mine)
        danger_row.addWidget(self.chk_show_temp)
        danger_row.addStretch(1)
        danger_row.addWidget(self.btn_delete_mine)
        source_layout.addLayout(danger_row)

        # Ручной ввод — под спойлером: выбранный пункт списка и так
        # подставляет путь, и поле только дублировало его.
        self.manual_toggle = QToolButton()
        self.manual_toggle.setText("Указать папку вручную")
        self.manual_toggle.setCheckable(True)
        self.manual_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.manual_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.manual_toggle.setObjectName("cardSpoiler")
        self.manual_box = QWidget()
        manual_layout = QVBoxLayout(self.manual_box)
        manual_layout.setContentsMargins(0, 4, 0, 0)
        manual_layout.setSpacing(6)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Папка с файлами базы")
        btn_browse = QPushButton("Обзор…")
        btn_browse.clicked.connect(self._pick_source)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Папка базы:"))
        row1.addWidget(self.source_edit, 1)
        row1.addWidget(btn_browse)
        manual_layout.addLayout(row1)
        self.manual_box.setVisible(False)

        def toggle_manual(checked: bool) -> None:
            self.manual_box.setVisible(checked)
            self.manual_toggle.setArrowType(
                Qt.ArrowType.DownArrow if checked
                else Qt.ArrowType.RightArrow)

        self.manual_toggle.toggled.connect(toggle_manual)
        source_layout.addWidget(self.manual_toggle)
        source_layout.addWidget(self.manual_box)
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
        # Навыки — не здесь. Список навыков один, и он на вкладке opencode
        # (шаг «Навыки — какие поставить в opencode»): два одинаковых списка
        # в двух местах — это дублирование, в котором легко запутаться.
        # Подключение переносит все навыки базы, а отбор делается там.
        self.box_skills_hint = QGroupBox("3. Навыки")
        hint_layout = QVBoxLayout(self.box_skills_hint)
        hint_layout.addWidget(ui.label(
            "Навыки подключаются во вкладке opencode — там список с выбором, "
            "как здесь выбираются остальные возможности. Подключение базы "
            "переносит все её навыки целиком, а какие из них нужны, отмечается "
            "на вкладке opencode.",
            kind="dim", wrap=True,
        ))
        self.skills_hint = ui.label("", kind="dim", wrap=True)
        hint_layout.addWidget(self.skills_hint)
        outer.addWidget(self.box_skills_hint)

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
            short = self._short_path(str(base))
            text = f"{name}  —  {short}"
            if self._is_temp_path(str(base)):
                text += "   (временная)"
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
        if not self.chk_show_temp.isChecked():
            entries = [item for item in entries
                       if not self._is_temp_path(str(item.get("path", "")))]
        for item in entries:
            folder = Path(str(item.get("path", "")))
            name = str(item.get("name") or folder.name)
            when = str(item.get("when", ""))[:10]
            short = self._short_path(str(folder))
            text = f"{name}  —  {short}"
            if self._is_temp_path(str(folder)):
                text += "   (временная)"
            # Дату создания держим в подсказке: в строке она обрезалась
            # и мешала видеть путь.
            tip = str(folder) + (f"\nсоздана {when}" if when else "")
            if main_key and str(folder).lower() == main_key:
                text += "   ← основная"
            row = QListWidgetItem(text)
            row.setData(1000, str(folder))
            row.setToolTip(tip)
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

    @staticmethod
    def _is_temp_path(path: str) -> bool:
        """Лежит ли папка во временной папке Windows."""
        low = str(path).replace("/", "\\").lower()
        return "\\temp\\" in low or "\\tmp\\" in low

    @staticmethod
    def _short_path(path: str, limit: int = 62) -> str:
        """Путь с многоточием посередине: видны диск и имя папки.

        Слева важны диск и верхние папки, справа — сама база; середина
        («Users\\<имя>\\AppData\\Local\\Temp\\...») ничего не говорит
        и как раз её можно потерять.
        """
        text = str(path)
        if len(text) <= limit:
            return text
        tail = max(24, limit // 2)
        head = max(10, limit - tail - 1)
        return text[:head].rstrip("\\/") + "…" + text[-tail:]

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

    def _forget_temp(self) -> None:
        """Убирает из списка записи с временными папками. Файлы целы."""
        entries = core.read_bases()
        temp = [item for item in entries
                if self._is_temp_path(str(item.get("path", "")))]
        if not temp:
            QMessageBox.information(
                self, "Временных записей нет",
                "В списке нет баз из временной папки Windows — убирать нечего.")
            return
        answer = QMessageBox.question(
            self,
            "Убрать временные записи",
            f"Убрать из списка {len(temp)} записей с временными папками?\n\n"
            "Сама папка останется на месте, файлы не удаляются.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for item in temp:
            folder = Path(str(item.get("path", "")))
            if folder.name:
                core.forget_base(folder)
        self._fill_mine()
        self.mine_hint.setText(
            f"Убрано временных записей: {len(temp)}. Папки на диске целы.")

    def _delete_mine(self) -> None:
        """Полностью удаляет базу с диска и из списка."""
        item = self.mine_list.currentItem()
        if item is None:
            return
        folder = Path(str(item.data(1000) or ""))
        if not folder.name:
            return
        # Удаление необратимо, поэтому подтверждение — вводом имени:
        # одну кнопку «Да» нажимают не глядя.
        typed, ok = QInputDialog.getText(
            self,
            "Удалить базу",
            f"С диска удалится вся папка:\n{folder}\n\n"
            "Вместе с ней пропадут файлы базы: профиль, факты, проекты, "
            "библиотека и наработки.\n\n"
            f"Чтобы подтвердить, введите имя базы: {folder.name}",
        )
        if not ok or typed.strip() != folder.name:
            return
        ok, message = core.delete_base(folder, confirm=True)
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
        # Файлы переносим вручную, по три в строку: одна общая строка
        # «Файлы: …» на широком списке уезжала за правый край панели,
        # и хвост списка просто пропадал.
        names = [str(f) for f in info["files"]]
        chunks = [", ".join(names[i:i + 3]) for i in range(0, len(names), 3)]
        files = ",\n".join(chunks)
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
            f"Файлы:\n{files}"
        )
        self._refresh_run()

    def _подсказка_где_база(self, folder: Path) -> str:
        return подсказка_где_база(folder)

    # ---- шаг 3: навыки

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
            text += " Навыки перенесутся все, отбор — на вкладке opencode."
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

        # Навыки при подключении переносятся все, что есть в базе: отбор
        # делается на вкладке opencode, где список один. Раньше здесь был
        # второй такой же список — два одинаковых места путали.
        chosen: list[str] | None = None
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
        outer.setContentsMargins(18, 16, 18, 16)
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

        # --- кнопки: в нижней панели окна, чтобы «Создать мост» была
        # на виду с самого начала, а не уезжала под длинную страницу.
        self.footer = QWidget()
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 6, 0, 0)
        footer_layout.setSpacing(8)
        self.btn_create = QPushButton("Создать мост")
        self.btn_create.setObjectName("primary")
        self.btn_create.clicked.connect(self._create)
        self.btn_check = QPushButton("Проверить")
        self.btn_check.clicked.connect(self._check)
        self.btn_open = QPushButton("Открыть папку")
        self.btn_open.clicked.connect(self._open)
        footer_layout.addWidget(self.btn_create)
        footer_layout.addWidget(self.btn_check)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.btn_open)

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


class ManualConfigDialog(QDialog):
    """Окно вставки конфигурации, которую выдаёт чужая программа.

    Нужно для серверов вроде Android Studio: программа не может
    включить сервер внутри студии, это действие в её окне. Что она
    может - принять конфигурацию, которую человек скопировал, и
    сохранить её рядом с настройками opencode.

    Смысл окна в том, что человек видит текст, который попадёт в
    настройки. Ничего не подставляется молча.
    """

    def __init__(self, server: mcp_registry.Server, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.saved_note = ""
        self.setWindowTitle(f"Включить {server.name}")
        self.setMinimumWidth(620)

        box = QVBoxLayout(self)
        box.setSpacing(8)

        known_url = str(
            (server.raw.get("connection") or {}).get("url") or ""
        ).strip()
        if known_url:
            intro = ui.label(
                f"Проще нажать «Настроить автоматически» в блоке серверов: "
                f"программа сама поставит плагин в {server.name}, включит "
                "сервер и проверит его. Это окно нужно, только если плагин "
                "уже стоит руками и осталось вписать адрес.",
                wrap=True,
            )
        else:
            intro = ui.label(
                f"{server.name} включается у себя, внутри своей программы. "
                "Отсюда включить его нельзя — это действие в её окне. "
                "Но конфигурацию принять можно: скопируй её там и вставь сюда.",
                wrap=True,
            )
        box.addWidget(intro)

        steps = server.setup_steps
        if steps:
            box.addWidget(ui.label("Как настроить:", kind="title"))
            for index, text in enumerate(steps, start=1):
                box.addWidget(ui.label(f"  {index}. {text}", wrap=True))

        box.addSpacing(4)
        # Адрес известен программе заранее, а у этого сервера токена нет
        # вовсе. Поэтому поле подставляем сами, а не просим человека
        # идти за конфигурацией, которой он не может достать: прежний
        # текст звал кнопку Copy Config, которой в студии 2026.1 нет.
        if known_url:
            box.addWidget(
                ui.label(
                    "Адрес сервера известен программе, он уже подставлен ниже. "
                    "Ничего копировать из студии не нужно. Проверь глазами и "
                    "нажми «Записать»:",
                    wrap=True,
                )
            )
        else:
            box.addWidget(
                ui.label(
                    "Вставь сюда конфигурацию целиком — вместе с адресом:",
                    wrap=True,
                )
            )

        self.text = QPlainTextEdit()
        if known_url:
            self.text.setPlainText(
                json.dumps(
                    {"mcpServers": {self.server.id: {"url": known_url}}},
                    ensure_ascii=False, indent=2,
                )
            )
        self.text.setPlaceholderText(
            '{"mcpServers": {"' + self.server.id + '": {"url": "http://localhost:.../api/mcp"}}}'
        )
        self.text.setMinimumHeight(110)
        # Моноширинный шрифт, как у окошка лога: конфигурация - это JSON,
        # и в пропорциональном шрифте её структура плохо читается.
        _font = QFont("Consolas")
        _font.setStyleHint(QFont.StyleHint.Monospace)
        self.text.setFont(_font)
        box.addWidget(self.text)

        # Подсказка — про то, что происходит с полем, поэтому стоит под
        # ним. Наверху она читалась как ещё один абзац инструкции.
        self.status = ui.label("", wrap=True)
        self.status.setObjectName("hint")
        box.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_paste = QPushButton("Вставить из буфера обмена")
        self.btn_paste.clicked.connect(self._paste)
        self.btn_clear = QPushButton("Очистить")
        self.btn_clear.clicked.connect(self.text.clear)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Записать")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(self.btn_paste)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)

        # Подсказка зависит от того, подставили мы адрес сами.
        if known_url:
            self.status.setText(
                "Адрес подставлен программой. Если сервер ещё не отвечает, "
                "нажми «Настроить автоматически» в блоке серверов — "
                "поставить плагин и включить его проще."
            )
            return
        # Сразу подсказываем про буфер, если там есть что вставить.
        clipboard = QApplication.clipboard()
        if clipboard is not None and self._looks_like_config(clipboard.text()):
            self.status.setText(
                "В буфере обмена похоже на конфигурацию этого сервера. "
                "Нажми «Вставить из буфера обмена»."
            )
        else:
            self.status.setText(
                "Поле пустое — так честнее, чем подставлять наугад. "
                "Нажми «Вставить из буфера обмена», если конфигурация "
                "уже скопирована."
            )

    def _looks_like_config(self, text: str) -> bool:
        """Похож ли текст на конфигурацию этого сервера.

        Грубая, но достаточная проверка: без неё кнопка предлагала бы
        вставить что угодно, а с ней - хотя бы не пустоту.
        """
        raw = (text or "").strip()
        if not raw or len(raw) > 20000:
            return False
        return "mcp" in raw.lower() and ("url" in raw.lower()
                                        or "http" in raw.lower())

    def _paste(self) -> None:
        clipboard = QApplication.clipboard()
        text = clipboard.text() if clipboard is not None else ""
        if not text.strip():
            self.status.setText("В буфере обмена пусто. Скопируй конфигурацию.")
            return
        self.text.setPlainText(text)
        self.status.setText(
            "Вставлено. Посмотри глазами, что это конфигурация, и нажми "
            "«Записать»."
        )

    def config_text(self) -> str:
        return self.text.toPlainText()


class ObsPasswordDialog(QDialog):
    """Окно пароля WebSocket-сервера OBS.

    Отдельное окно, а не строчка в таблице, потому что здесь есть
    решение, которое нельзя принять за человека: пароль либо уже есть,
    либо его нужно выпустить. Показываем и то, и другое, и третье —
    вписать свой.

    Куда сохранять копию — необязательно. Не выбрал путь, значит пароль
    всё равно лежит рядом с настройками, оттуда его и возьмёт лаунчер.
    Просто тогда человек не найдёт его глазами, поэтому предлагаем.
    """

    def __init__(self, current: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Пароль WebSocket-сервера OBS")
        self.setMinimumWidth(560)
        self._path: Path | None = None

        box = QVBoxLayout(self)
        box.setSpacing(8)

        box.addWidget(ui.label(
            "Мост OBS подключается к OBS по паролю. Программа умеет "
            "выпустить его сама, но ты можешь вписать свой. Пароль не "
            "попадёт в opencode.jsonc: он лежит отдельным файлом, "
            "потому что конфиг открыт и переносится между компьютерами.",
            wrap=True,
        ))

        row = QHBoxLayout()
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setPlaceholderText(
            "Пароль, 8–20 символов, с буквами и цифрами"
        )
        if current:
            self.field.setText(current)
        row.addWidget(self.field, 1)
        self.btn_gen = QPushButton("Сгенерировать")
        self.btn_gen.clicked.connect(self._generate)
        self.btn_show = QPushButton("Показать")
        self.btn_show.setCheckable(True)
        self.btn_show.toggled.connect(self._toggle)
        row.addWidget(self.btn_gen)
        row.addWidget(self.btn_show)
        box.addLayout(row)

        self.status = ui.label("", wrap=True)
        self.status.setObjectName("hint")
        box.addWidget(self.status)

        row2 = QHBoxLayout()
        self.btn_save = QPushButton("Сохранить копию пароля…")
        self.btn_save.clicked.connect(self._choose_path)
        row2.addWidget(self.btn_save)
        self.path_label = ui.label("", kind="dim", wrap=True)
        row2.addWidget(self.path_label, 1)
        box.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Дальше")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row3.addWidget(self.btn_cancel)
        row3.addWidget(self.btn_ok)
        box.addLayout(row3)

        self._refresh_status()

    def _generate(self) -> None:
        self.field.setText(bridges.generate_password())
        self.btn_show.setChecked(True)
        self._refresh_status()

    def _toggle(self, show: bool) -> None:
        mode = (QLineEdit.EchoMode.Normal if show
                else QLineEdit.EchoMode.Password)
        self.field.setEchoMode(mode)

    def _refresh_status(self) -> None:
        value = self.field.text()
        if not value:
            self.status.setText(
                "Пусто. Нажми «Сгенерировать» — это надёжнее, чем придумывать."
            )
        elif bridges.password_is_valid(value):
            self.status.setText("Пароль годный.")
        else:
            self.status.setText(
                f"Нужен от {bridges.OBS_PASSWORD_MIN} до "
                f"{bridges.OBS_PASSWORD_MAX} символов, со строчной буквой, "
                "заглавной и цифрой."
            )

    def _choose_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Куда сохранить пароль", "",
            "Текстовый файл (*.txt);;Все файлы (*)",
        )
        if not path:
            return
        self._path = Path(path)
        self.path_label.setText(f"Сохраню в: {self._path}")

    def password(self) -> str:
        return self.field.text().strip()

    def save_path(self) -> Path | None:
        return self._path


class EngineSetupDialog(QDialog):
    """Спрашивает только то, чего у программы нет: путь, команду или токен.

    Окно не обещает, что редактор или кабинет ответили. Для Unity и
    Roblox спрашивать нечего — здесь только проверка и кнопка вписать
    команду, если проверка прошла.
    """

    def __init__(self, server_id: str, server_name: str, note: str,
                 can_write: bool, parent=None) -> None:
        super().__init__(parent)
        self.server_id = server_id
        self.setWindowTitle(f"Настройка: {server_name}")
        self.setMinimumWidth(640)
        self.project = QLineEdit()
        self.plugin = QLineEdit()
        self.command = QPlainTextEdit()
        self.token = QLineEdit()
        self.app_id = QLineEdit()
        self.url = QLineEdit()
        # Поле модели. В патче его не было, а chatgpt до него обращался:
        # окно падало бы с AttributeError на третьей секунде. Сделано
        # здесь и проверено — тихо это оставлять нельзя.
        self.model = QLineEdit()
        # Список найденных проектов. Заполняется только там, где проект
        # можно выбрать из найденных; иначе остаётся None, и окно работает
        # как раньше — с одним полем ввода.
        self.projects = None
        # Порт встроенного сервера плагина. Спрашивается всегда: значение
        # по умолчанию взято из документации автора и на живой машине не
        # проверено, а молчаливый неверный адрес хуже явного вопроса.
        self.port = QLineEdit()

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "Программа запишет только свой файл рядом с настройками opencode "
            "и впишет команду. Плагин в редактор она не ставит. Зелёной "
            "галочки «готово» после этого не будет: живого ответа не было.",
            wrap=True,
        ))
        if note:
            box.addWidget(ui.label(note, wrap=True))

        if server_id == "unreal":
            box.addWidget(ui.label(
                "Папка проекта или файл .uproject. Плагин EngineWire должен "
                "уже лежать в Plugins/EngineWire. Старый McpAutomationBridge "
                "не подходит.",
                wrap=True,
            ))
            row = QHBoxLayout()
            self.project.setPlaceholderText(r"D:\Games\MyGame или MyGame.uproject")
            row.addWidget(self.project, 1)
            browse = QPushButton("Папка…")
            browse.clicked.connect(self._browse_project)
            file_btn = QPushButton(".uproject…")
            file_btn.clicked.connect(self._browse_uproject)
            row.addWidget(browse)
            row.addWidget(file_btn)
            box.addLayout(row)
            row2 = QHBoxLayout()
            self.plugin.setPlaceholderText("Папка плагина, если она не внутри проекта")
            row2.addWidget(self.plugin, 1)
            plug = QPushButton("Плагин…")
            plug.clicked.connect(self._browse_plugin)
            row2.addWidget(plug)
            box.addLayout(row2)
            box.addWidget(ui.label(
                "В линии 0.6 сервер MCP встроен в плагин, поэтому подключение "
                "идёт по адресу, а не через Node.js и npm. Мост отвечает, "
                "ПОКА ОТКРЫТ редактор с плагином: закрыл Unreal — адрес не "
                "слушается, и это не поломка.", wrap=True,
            ))
            row_p = QHBoxLayout()
            self.port.setPlaceholderText(str(engine_setup.UNREAL_PORT_DEFAULT))
            self.port.setToolTip(
                "Порт из документации автора, на этой машине не проверен. "
                "Если в настройках плагина стоит другой — впиши его.")
            row_p.addWidget(ui.label("Порт сервера:", kind="title"))
            row_p.addWidget(self.port, 1)
            row_p.addWidget(ui.label(
                f"по умолчанию {engine_setup.UNREAL_PORT_DEFAULT}, не проверено",
                kind="dim", wrap=True))
            box.addLayout(row_p)
        elif server_id == "godot":
            box.addWidget(ui.label(
                "Вставь JSON из дока Godot AI, кнопку «Run this manually». "
                "В команде должно быть слово attach. Адрес "
                "http://127.0.0.1:8000/mcp не подходит. Текст команды в "
                "журнал не попадёт.",
                wrap=True,
            ))
            box.addWidget(ui.label(
                "Папка проекта нужна для аддона: программа сама распакует "
                "godot-ai в корень проекта (встроенный файл, без интернета). "
                "Включить аддон потом придётся вручную: Project → Project "
                "Settings → Plugins → Godot AI.",
                wrap=True,
            ))
            row_g = QHBoxLayout()
            self.project.setPlaceholderText("папка проекта с файлом project.godot")
            row_g.addWidget(self.project, 1)
            browse_g = QPushButton("Папка:")
            browse_g.clicked.connect(self._browse_project)
            row_g.addWidget(browse_g)
            box.addLayout(row_g)
            self.command.setPlaceholderText(
                '{ "command": ["uvx", "godot-ai", "attach"] }'
            )
            self.command.setMinimumHeight(120)
            box.addWidget(self.command)
        elif server_id == "unity":
            box.addWidget(ui.label(
                "Папка проекта нужна для пакета MCP for Unity: программа "
                "впишет его в Packages/manifest.json (с копией файла и "
                "откатом), а скачает и применит редактор при открытии "
                "проекта. Редактор при этом должен быть закрыт: открытый "
                "перезапишет файл при выходе.",
                wrap=True,
            ))
            row_u = QHBoxLayout()
            self.project.setPlaceholderText("или впиши папку проекта")
            row_u.addWidget(self.project, 1)
            browse_u = QPushButton("Папка:")
            browse_u.clicked.connect(self._browse_project)
            row_u.addWidget(browse_u)
            box.addLayout(row_u)
            # Проекты ищет программа, а не человек: набирать путь руками —
            # это работа, которую можно сделать один раз и ошибиться. Выбор
            # остаётся за человеком, но из списка, а не по памяти.
            scan = editor_plugins.scan_unity_projects()
            if scan.items:
                box.addWidget(ui.label(
                    f"Найдено проектов Unity: {len(scan.items)}. Выбери нужный: "
                    "программа не угадывает за тебя.", kind="title", wrap=True,
                ))
                self.projects = QListWidget()
                for project_path, project_version in scan.items:
                    shown = project_version or "версия не записана"
                    entry = QListWidgetItem(f"{project_path.name} — {shown}")
                    entry.setData(Qt.ItemDataRole.UserRole, str(project_path))
                    entry.setToolTip(str(project_path))
                    self.projects.addItem(entry)
                self.projects.setMinimumHeight(min(140, 20 + 34 * len(scan.items)))
                box.addWidget(self.projects)
                if scan.truncated:
                    box.addWidget(ui.label(
                        f"Поиск остановлен на {scan.visited} папках — возможно, "
                        "проект лежит глубже. Укажи папку руками.", kind="dim",
                        wrap=True,
                    ))
            else:
                box.addWidget(ui.label(
                    "Проектов Unity на диске не нашлось. Их ещё нет или они "
                    "лежат не в папках пользователя и не в папках Projects, "
                    "Games, Unity на дисках — укажи нужную папку руками.",
                    kind="dim", wrap=True,
                ))
        elif server_id == "tiktok":
            box.addWidget(ui.label(
                "Access token и App ID из своего кабинета TikTok Business. "
                "В opencode.jsonc они не пишутся и в журнал не попадают.",
                wrap=True,
            ))
            self.token.setEchoMode(QLineEdit.EchoMode.Password)
            self.token.setPlaceholderText("Access token")
            token_row = QHBoxLayout()
            token_row.addWidget(self.token, 1)
            show = QPushButton("Показать")
            show.setCheckable(True)
            show.toggled.connect(self._toggle_token)
            token_row.addWidget(show)
            box.addLayout(token_row)
            self.app_id.setPlaceholderText("App ID")
            box.addWidget(self.app_id)
        elif server_id == "capcut":
            box.addWidget(ui.label(
                "У CapCut нет своего сервера MCP в интернете. Сюда вписывается "
                "адрес, который дал твой хост: https и чужой MCP, не страница "
                "capcut.com. Программа по этому адресу сейчас не ходит и ролик "
                "не экспортирует. Черновик потом открывается в CapCut.",
                wrap=True,
            ))
            self.url.setPlaceholderText("https://хост-твоего-сервера/mcp")
            box.addWidget(self.url)
            self.token.setEchoMode(QLineEdit.EchoMode.Password)
            self.token.setPlaceholderText("Токен, если хост его просит. Можно пустым")
            token_row = QHBoxLayout()
            token_row.addWidget(self.token, 1)
            show = QPushButton("Показать")
            show.setCheckable(True)
            show.toggled.connect(self._toggle_token)
            token_row.addWidget(show)
            box.addLayout(token_row)
        elif server_id == "spotify":
            box.addWidget(ui.label(
                "Client ID своего приложения Spotify. Пакет ходит в Web API, "
                "это не программа Spotify. Воспроизведение просит Premium и "
                "уже открытый Spotify. Браузер эта кнопка не открывает.",
                wrap=True,
            ))
            self.app_id.setPlaceholderText("SPOTIFY_CLIENT_ID")
            box.addWidget(self.app_id)
        elif server_id == "chatgpt":
            box.addWidget(ui.label(
                "Ключ и имя модели из кабинета OpenAI. Запросы идут только на "
                "api.openai.com. Сайт chatgpt.com не открывается. Имя модели "
                "скопируй из кабинета: программа его не выдумывает.",
                wrap=True,
            ))
            self.token.setEchoMode(QLineEdit.EchoMode.Password)
            self.token.setPlaceholderText("Ключ API, без слова Bearer")
            token_row = QHBoxLayout()
            token_row.addWidget(self.token, 1)
            show = QPushButton("Показать")
            show.setCheckable(True)
            show.toggled.connect(self._toggle_token)
            token_row.addWidget(show)
            box.addLayout(token_row)
            self.model.setPlaceholderText("Имя модели из кабинета")
            box.addWidget(self.model)
        elif server_id == "cursor":
            box.addWidget(ui.label(
                "Ключ можно оставить пустым, если вход в Cursor CLI уже сделан. "
                "В командную строку и в журнал он не попадает. --yolo не передаётся.",
                wrap=True,
            ))
            self.token.setEchoMode(QLineEdit.EchoMode.Password)
            self.token.setPlaceholderText("Ключ Cursor, можно пустым")
            token_row = QHBoxLayout()
            token_row.addWidget(self.token, 1)
            show = QPushButton("Показать")
            show.setCheckable(True)
            show.toggled.connect(self._toggle_token)
            token_row.addWidget(show)
            box.addLayout(token_row)

        self.status = ui.label("", wrap=True)
        self.status.setObjectName("hint")
        box.addWidget(self.status)

        row3 = QHBoxLayout()
        row3.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Записать и включить")
        if server_id in ("unity", "roblox-studio"):
            self.btn_ok.setText("Вписать команду")
            self.btn_ok.setEnabled(can_write)
            if not can_write:
                self.status.setText("Вписывать нечего: сначала закрой причину выше.")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._accept)
        row3.addWidget(cancel)
        row3.addWidget(self.btn_ok)
        box.addLayout(row3)

    def _toggle_token(self, show: bool) -> None:
        mode = (QLineEdit.EchoMode.Normal if show
                else QLineEdit.EchoMode.Password)
        self.token.setEchoMode(mode)

    def _browse_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Папка проекта Unreal")
        if path:
            self.project.setText(path)

    def _browse_uproject(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл проекта Unreal", "", "Unreal (*.uproject)"
        )
        if path:
            self.project.setText(path)

    def _browse_plugin(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Папка EngineWire")
        if path:
            self.plugin.setText(path)

    def _accept(self) -> None:
        if self.server_id == "unreal" and not self.project.text().strip():
            self.status.setText("Укажи папку проекта или файл .uproject.")
            return
        if self.server_id == "unity" and not self.project_path():
            # Раньше Unity отвечал словами «Папка проекта не указана»
            # уже после нажатия. Теперь окно не закрывается, пока проект
            # не выбран: пустой мост бесполезен, и человек видит это сразу.
            self.status.setText("Выбери проект из списка или укажи его папку.")
            return
        if self.server_id == "godot" and not self.command.toPlainText().strip():
            self.status.setText("Вставь команду из дока. Пустую не записываю.")
            return
        if self.server_id == "tiktok":
            if not self.token.text().strip() or not self.app_id.text().strip():
                self.status.setText("Нужны и токен, и App ID. Пустое не записываю.")
                return
        if self.server_id == "capcut" and not self.url.text().strip():
            self.status.setText("Впиши адрес MCP. Сайт CapCut сюда не подставляется.")
            return
        if self.server_id == "spotify" and not self.app_id.text().strip():
            self.status.setText("Нужен Client ID. Пустое не записываю.")
            return
        if self.server_id == "chatgpt":
            if not self.token.text().strip() or not self.model.text().strip():
                self.status.setText("Нужны и ключ, и имя модели. Пустое не записываю.")
                return
        self.accept()

    def project_path(self) -> str:
        """Папка проекта: что вписано руками или что выбрано из списка.

        Ручной ввод важнее списка: человек мог указать проект, которого
        программа не нашла, — молча заменить его найденным нельзя.
        """
        text = self.project.text().strip()
        if text:
            return text
        if self.projects is not None:
            entry = self.projects.currentItem()
            if entry is not None:
                return str(entry.data(Qt.ItemDataRole.UserRole) or "")
        return ""

    def plugin_path(self) -> str:
        return self.plugin.text().strip()

    def port_value(self) -> str:
        return self.port.text().strip()

    def command_text(self) -> str:
        return self.command.toPlainText()

    def token_value(self) -> str:
        return self.token.text().strip()

    def app_id_value(self) -> str:
        return self.app_id.text().strip()

    def url_value(self) -> str:
        return self.url.text().strip()

    def model_value(self) -> str:
        return self.model.text().strip()


class DbhubConnectionDialog(QDialog):
    """Окно подключения к базе для DBHub.

    Спрашиваем только то, без чего мост нечего запускать: как звать
    подключение, к какой базе и по какой строке. Отдельного поля под
    пароль нет намеренно: пароль берётся из строки подключения и уезжает
    в свой файл, а в конфиг попадает ссылка на переменную. Так секрет не
    остаётся в файле, который открыт и переносится между компьютерами.

    Файл подключений ведёт программа: он лежит рядом с настройками
    opencode и в репозиторий не попадает. Дописать второй источник можно
    тем же окном — список уже добавленных виден наверху.
    """

    def __init__(self, dest: Path, parent=None) -> None:
        super().__init__(parent)
        self.dest = Path(dest)
        self.messages: list[str] = []
        self.setWindowTitle("Подключение к базе для DBHub")
        self.setMinimumWidth(640)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "DBHub умеет PostgreSQL, MySQL, MariaDB, SQL Server, Oracle и "
            "SQLite. Строку подключения возьми у себя: у каждой базы она "
            "своя. Пароль, если он есть в строке, программа вынет и "
            "положит отдельным файлом рядом с настройками — в конфиге "
            "останется только ссылка на него.",
            wrap=True,
        ))

        old = dbhub.read_sources(self.dest)
        if old:
            names = ", ".join(f"{s.id} ({s.db_type})" for s in old)
            box.addWidget(ui.label(f"Уже добавлено: {names}", kind="dim", wrap=True))

        form = QVBoxLayout()
        form.setSpacing(4)

        row_name = QHBoxLayout()
        row_name.addWidget(ui.label("Имя подключения:", kind="title"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("латиницей, без пробелов: sklad, main-db")
        row_name.addWidget(self.name, 1)
        form.addLayout(row_name)

        row_type = QHBoxLayout()
        row_type.addWidget(ui.label("Тип базы:", kind="title"))
        self.db_type = QComboBox()
        for key, title, _schemes in dbhub.DB_TYPES:
            self.db_type.addItem(title, key)
        self.db_type.currentIndexChanged.connect(self._refresh_example)
        row_type.addWidget(self.db_type, 1)
        form.addLayout(row_type)

        row_dsn = QHBoxLayout()
        row_dsn.addWidget(ui.label("Строка подключения:", kind="title"))
        self.dsn = QLineEdit()
        row_dsn.addWidget(self.dsn, 1)
        form.addLayout(row_dsn)
        box.addLayout(form)

        row_limits = QHBoxLayout()
        self.readonly = QCheckBox("Только чтение")
        self.readonly.setChecked(True)
        self.readonly.setToolTip(
            "Запросы на изменение данных будут отклонены. Снять галочку — "
            "значит разрешить серверу менять базу"
        )
        row_limits.addWidget(self.readonly)
        row_limits.addSpacing(16)
        row_limits.addWidget(ui.label("Строк в ответе:", kind="title"))
        self.max_rows = QSpinBox()
        self.max_rows.setRange(10, 100000)
        self.max_rows.setValue(dbhub.DEFAULT_MAX_ROWS)
        self.max_rows.setSingleStep(100)
        self.max_rows.setToolTip(
            "Сколько строк сервер отдаст в одном ответе. Ограничение "
            "касается execute_sql: без него один неосторожный запрос "
            "вернёт таблицу целиком"
        )
        row_limits.addWidget(self.max_rows)
        row_limits.addStretch(1)
        box.addLayout(row_limits)

        self.example = ui.label("", kind="dim", wrap=True)
        box.addWidget(self.example)

        self.status = ui.label("", wrap=True)
        box.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Записать")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)

        self._refresh_example()

    def _current_type(self) -> str:
        return str(self.db_type.currentData() or "")

    def _refresh_example(self) -> None:
        key = self._current_type()
        example = dbhub.DSN_EXAMPLES.get(key, "")
        self.dsn.setPlaceholderText(example)
        self.example.setText(
            f"Пример для этой базы: {example}. Такой адрес — образец формы, "
            "а не настоящий: подставь свой хост, базу и пользователя."
            if example else ""
        )

    def _save(self) -> None:
        messages, errors = dbhub.add_source(
            self.dest, self.name.text(), self._current_type(),
            self.dsn.text(), self.readonly.isChecked(), self.max_rows.value(),
        )
        if errors:
            # Окно не закрывается: человек должен видеть, что именно не так,
            # и поправить хотя бы то, что поправимо с клавиатуры.
            self.status.setText("Не записано. " + " ".join(errors))
            return
        self.messages = messages
        self.accept()


class BrowserChoiceDialog(QDialog):
    """Окно выбора браузера для моста Playwright MCP.

    Спрашиваем то, без чего мост не запустить: каким браузером водит
    нейросеть, куда класть его профиль и показывать ли окно. Меню браузеров
    у Playwright своё и не совпадает с тем, что стоит у человека: Chrome и
    Edge берутся по каналу, Яндекс.Браузер — только по пути к browser.exe,
    а Firefox — не тот, что стоит у человека, а своя сборка Playwright.
    Про последнее окно говорит прямо, а не ставит галочку «Firefox»,
    за которой ничего нет.

    Выбор ложится файлом рядом с настройками opencode. В самих настройках
    остаётся только команда лаунчера: смена браузера их не переписывает.
    """

    def __init__(self, dest: Path, parent=None) -> None:
        super().__init__(parent)
        self.dest = Path(dest)
        self.messages: list[str] = []
        self.setWindowTitle("Браузер для нейросети")
        self.setMinimumWidth(700)
        self.choice = browsers.read_choice(self.dest)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "Нейросеть будет открывать страницы в выбранном браузере. По "
            "умолчанию у неё свой профиль, поэтому твои вкладки и входы в "
            "своих аккаунтах она не увидит. Режим «мои сессии» — только "
            "явным выбором и только с расширением Playwright.",
            wrap=True,
        ))

        row_browser = QHBoxLayout()
        row_browser.addWidget(ui.label("Браузер:", kind="title"))
        self.browser_box = QComboBox()
        for item in browsers.BROWSERS:
            self.browser_box.addItem(item.title, item.key)
        index = self.browser_box.findData(self.choice.browser)
        if index >= 0:
            self.browser_box.setCurrentIndex(index)
        self.browser_box.currentIndexChanged.connect(self._refresh)
        row_browser.addWidget(self.browser_box, 1)
        box.addLayout(row_browser)

        self.browser_hint = ui.label("", kind="dim", wrap=True)
        box.addWidget(self.browser_hint)

        row_path = QHBoxLayout()
        row_path.addWidget(ui.label("Путь к browser.exe:", kind="title"))
        self.path = QLineEdit(self.choice.executable)
        self.path.setPlaceholderText(
            "для Яндекс.Браузера: ...\\Yandex\\YandexBrowser\\Application\\browser.exe"
        )
        self.path.textChanged.connect(self._refresh)
        row_path.addWidget(self.path, 1)
        self.btn_browse = QPushButton("Обзор…")
        self.btn_browse.clicked.connect(self._browse)
        row_path.addWidget(self.btn_browse)
        box.addLayout(row_path)

        row_profile = QHBoxLayout()
        row_profile.addWidget(ui.label("Профиль:", kind="title"))
        self.profile_box = QComboBox()
        for key, title in browsers.PROFILE_MODES:
            self.profile_box.addItem(title, key)
        index = self.profile_box.findData(self.choice.profile)
        if index >= 0:
            self.profile_box.setCurrentIndex(index)
        self.profile_box.currentIndexChanged.connect(self._refresh)
        row_profile.addWidget(self.profile_box, 1)
        box.addLayout(row_profile)

        row_token = QHBoxLayout()
        row_token.addWidget(ui.label("Токен расширения:", kind="title"))
        self.token_field = QLineEdit(browsers.read_token(self.dest))
        self.token_field.setPlaceholderText(
            "Вставь токен из расширения Playwright — и Chrome перестанет "
            "спрашивать одобрение"
        )
        self.token_field.setObjectName("password")
        self.token_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_field.textChanged.connect(self._refresh)
        row_token.addWidget(self.token_field, 1)
        self.btn_token_paste = QPushButton("Вставить")
        self.btn_token_paste.setToolTip(
            "Токен из буфера обмена. Нажми «Вставить токен», когда в буфере "
            "будет токен из расширения Playwright"
        )
        self.btn_token_paste.clicked.connect(self._fill_token)
        row_token.addWidget(self.btn_token_paste)
        self.btn_token_show = QPushButton("Показать")
        self.btn_token_show.setCheckable(True)
        self.btn_token_show.toggled.connect(self._toggle_token)
        row_token.addWidget(self.btn_token_show)
        box.addLayout(row_token)

        self.token_status = ui.label("", wrap=True)
        box.addWidget(self.token_status)

        self.headless = QCheckBox("Скрыть окно браузера — работать без него")
        self.headless.setChecked(self.choice.headless)
        self.headless.setToolTip(
            "С окном видно, что делает нейросеть, и можно вмешаться. Без "
            "окна работа идёт незаметно"
        )
        self.headless.stateChanged.connect(self._refresh)
        box.addWidget(self.headless)

        self.download = QCheckBox(
            "Скачать сборку Firefox для Playwright, около 90 МБ"
        )
        self.download.setChecked(self.choice.download_firefox)
        self.download.setToolTip(
            "Твой Firefox не подойдёт: Playwright водит только свою сборку. "
            "Скачивание идёт командой npx playwright install firefox"
        )
        box.addWidget(self.download)

        self.command_hint = ui.label("", kind="dim", wrap=True)
        box.addWidget(self.command_hint)

        self.status = ui.label("", wrap=True)
        box.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Записать")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)

        self._refresh()

    def _current_key(self) -> str:
        return str(self.browser_box.currentData() or "chrome")

    def _current_profile(self) -> str:
        return str(self.profile_box.currentData() or "separate")

    def _build_choice(self) -> browsers.Choice:
        return browsers.Choice(
            browser=self._current_key(),
            executable=self.path.text().strip(),
            profile=self._current_profile(),
            headless=self.headless.isChecked(),
            download_firefox=self.download.isChecked(),
            checked=self.choice.checked,
        )

    def _browse(self) -> None:
        start = self.path.text().strip()
        if not start:
            found = browsers.installed_path(self._current_key())
            start = str(found) if found else ""
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Где лежит browser.exe", start,
            "Программы (*.exe);;Все файлы (*)",
        )
        if chosen:
            self.path.setText(chosen)

    def _refresh(self) -> None:
        key = self._current_key()
        item = browsers.browser(key)
        profile = self._current_profile()
        self.browser_hint.setText(
            item.note + " " + browsers.hint(key, self._build_choice())
        )
        # Путь нужен только там, где браузер запускается по файлу. У
        # остальных он бы только путал: Playwright их и так найдёт.
        needs_path = item.kind == "path"
        self.path.setEnabled(needs_path)
        self.btn_browse.setEnabled(needs_path)
        self.download.setEnabled(
            item.kind == "playwright" and browsers.playwright_firefox_dir() is None
        )
        self.headless.setEnabled(profile != "sessions")
        sessions = profile == "sessions"
        self.token_field.setVisible(sessions)
        self.btn_token_show.setVisible(sessions)
        self.btn_token_paste.setVisible(sessions)
        if sessions:
            if not self.token_field.text().strip():
                self.token_status.setText(
                    "Токен не нужен: Chrome спросит одобрение при "
                    "подключении, и достаточно один раз нажать «да». "
                    "Вставь токен, если не хочешь вопроса каждый раз."
                )
            else:
                self.token_status.setText("Токен вставлен: будет без запроса одобрения.")
        self.command_hint.setText(
            "Запуск: " + " ".join(browsers.command(self.dest, self._build_choice()))
            + ". Профиль: "
            + str(browsers.profile_dir(self.dest, key))
        )

    def _toggle_token(self, show: bool) -> None:
        mode = (QLineEdit.EchoMode.Normal if show
                else QLineEdit.EchoMode.Password)
        self.token_field.setEchoMode(mode)

    def _fill_token(self) -> None:
        self.token_field.setText(
            QApplication.clipboard().text().strip()
            if QApplication.clipboard() else ""
        )
        self._refresh()

    def _save(self) -> None:
        messages, errors = browsers.write_choice(self.dest, self._build_choice())
        if errors:
            # Окно не закрывается: человек должен видеть, что именно не так,
            # и поправить это здесь же.
            self.status.setText("Не записано. " + " ".join(errors))
            return
        # Токен сохраняем только в режиме «мои сессии» (поле вовсе скрыто
        # в других профилях, но защитимся и проверкой). Поле — источник
        # правды: пустое поле означает «токен не нужен», и файл очищается.
        if self._current_profile() == "sessions":
            _saved, _note = browsers.write_token(self.dest,
                                                 self.token_field.text().strip())
            self.token_status.setText(_note)
            if not _saved:
                self.status.setText("Токен не записался: " + self.token_status.text())
                return
        self.messages = messages
        self.accept()


class LmarenaWarningDialog(QDialog):
    """Предупреждения моста LMArena — до первого запуска.

    Мост работает через веб-сервис арены, а не через её официальный API,
    и запросы уходят на публичную площадку. Поэтому мост выключен по
    умолчанию, а это окно показывается каждый раз перед тем, как его
    поднять или вписать в настройки: согласие должно быть осознанным, а
    не «я когда-то нажал галочку». Текст предупреждений держится в
    lmarena.WARNINGS — там же, откуда его берут скилл и самопроверка.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Мост LMArena: что важно знать")
        self.setMinimumWidth(680)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "Мост LMArena — программа к сервису Arena (arena.ai). Он "
            "включается только по явному согласию и по умолчанию выключен. "
            "Перед первым запуском прочитай, на что идёшь:",
            wrap=True,
        ))
        for number, warning in enumerate(lmarena.WARNINGS, start=1):
            box.addWidget(ui.label(f"{number}. {warning}", wrap=True))

        box.addWidget(ui.label(
            "Нажми «Согласен» — и дальше программа сделает ровно то, что "
            "написано на кнопке. «Отмена» не делает ничего.",
            kind="dim",
            wrap=True,
        ))

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Согласен")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)


class PxpipeWarningDialog(QDialog):
    """Предупреждение pxpipe — до запуска прокси и до галочки.

    pxpipe переписывает часть запроса картинками, и это сжатие с потерями:
    по тестам автора часть моделей плохо различает символы, а точные
    строки, ключи и код — как раз из символов. Галочка по умолчанию снята,
    а это окно показывается и перед её включением, и перед каждым запуском
    прокси: согласие должно быть осознанным, а не «я когда-то нажал
    галочку». Текст держится в pxpipe.WARNING — там же, откуда его берут
    скилл и самопроверка.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("pxpipe: что важно знать")
        self.setMinimumWidth(700)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "pxpipe — сторонний прокси автора teamchong (лицензия MIT). "
            "Запросы opencode пойдут через него, и часть запроса он "
            "превратит в картинки. Включается только по явному согласию "
            "и по умолчанию выключен. Прочитай, на что идёшь:",
            wrap=True,
        ))
        # Абзацы текста автора свёрнуты в строки: переносы в константе стоят
        # для читаемости кода, а не для окна — окно переносит само.
        for _part in pxpipe.WARNING.split("\n\n"):
            _text = " ".join(line.strip() for line in _part.splitlines()
                             if line.strip())
            if _text:
                box.addWidget(ui.label(_text, wrap=True))
        box.addWidget(ui.label(
            "Нажми «Согласен» — и дальше программа сделает ровно то, что "
            "написано на кнопке. «Отмена» не делает ничего.",
            kind="dim",
            wrap=True,
        ))

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Согласен")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)


class QwenReviewDialog(QDialog):
    """Что проверять вторым ревьюером: папка проекта и база сравнения.

    Дальше — обычная проверка: изменения берутся командой `git diff`,
    ревьюер идёт в режиме «только чтение» и файлы не правит.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Qwen Code: ревью изменений")
        self.setMinimumWidth(720)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "Второй ревьюер прочитает `git diff` проекта и вернёт замечания. "
            "Код изменений уйдёт выбранному провайдеру — это тратит токены. "
            "Ревьюер файлы не правит: он работает в режиме «только чтение».",
            wrap=True,
        ))

        row_project = QHBoxLayout()
        row_project.addWidget(QLabel("Папка проекта:   "))
        self.project = QLineEdit()
        self.project.setPlaceholderText("папка с кодом, где есть .git")
        self.btn_pick_project = QPushButton("Выбрать…")
        self.btn_pick_project.clicked.connect(self._pick_project)
        row_project.addWidget(self.project, 1)
        row_project.addWidget(self.btn_pick_project)
        box.addLayout(row_project)

        row_base = QHBoxLayout()
        row_base.addWidget(QLabel("С чем сравнивать:   "))
        self.base = QLineEdit()
        self.base.setPlaceholderText("пусто — рабочее дерево против индекса (git diff)")
        row_base.addWidget(self.base, 1)
        box.addLayout(row_base)
        box.addWidget(ui.label(
            "Ветку, тег или коммит можно указать вручную: например `main` — "
            "тогда видно всё, что сделано в текущей ветке поверх main.",
            kind="dim", wrap=True,
        ))

        # Режим ревью — из общего списка qwen_review.MODES, а не хардкод.
        # Выбор в комбо (once/debate/vote); спором управляет человек.
        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("Режим:   "))
        self.mode = QComboBox()
        for _mode in qwen_review.MODES:
            self.mode.addItem(str(_mode.get("name") or _mode["id"]),
                              str(_mode.get("id") or ""))
        self.mode.setToolTip(
            "«Одна проверка» — ревьюер прочитал diff и вернул замечания. "
            "«Спор» — обмен возражениями двух моделей до N раундов, решает "
            "человек. «Тройное ревью» — три обличья из панели ловят одну "
            "проблему дважды, а её повтор подтверждается двумя моделями. "
            "Спор с тройным ревью совмещать нельзя: программа откажет "
            "сама."
        )
        row_mode.addWidget(self.mode, 1)
        box.addLayout(row_mode)

        self.status = ui.label("", wrap=True)
        box.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Проверить")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._accept)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)

    def _pick_project(self) -> None:
        start = self.project.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Папка проекта", start if Path(start).is_dir() else str(Path.home())
        )
        if chosen:
            self.project.setText(chosen)

    def values(self) -> dict:
        """Выбор человека: папка проекта, база сравнения и режим."""
        return {
            "project": self.project.text().strip(),
            "base": self.base.text().strip(),
            "mode": str(self.mode.currentData() or qwen_review.MODE_ONCE),
        }

    def _accept(self) -> None:
        values = self.values()
        if not values["project"]:
            self.status.setText("Не выбрана папка проекта.")
            return
        folder = Path(values["project"])
        if not folder.is_dir():
            self.status.setText("Такой папки нет: " + values["project"])
            return
        if not (folder / ".git").exists():
            self.status.setText(
                "Это не git-репозиторий: ревьюеру нужен `git diff`. "
                "Проверь папку проекта."
            )
            return
        self.accept()


class QwenReplyDialog(QDialog):
    """Возражение основного агента для раунда спора.

    Текст пишет человек (или основной агент передаёт его сюда): ревьюер
    отвечает на доводы, и так до предела раундов. За пределом программа
    не спорит сама — решение остаётся за человеком.
    """

    def __init__(self, round_no: int, limit: int, project: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Qwen Code: возражение в споре")
        self.setMinimumWidth(760)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            f"Раунд {round_no} из {limit}. Возражение уйдёт ревьюеру вместе с "
            "ходом спора: он либо согласится, либо объяснит, почему возражение "
            "неверно. Файлы по-прежнему никто не правит.",
            wrap=True,
        ))
        self.project = QLineEdit(project)
        self.project.setReadOnly(True)
        box.addWidget(self.project)
        self.reply = QPlainTextEdit()
        self.reply.setPlaceholderText(
            "Что возразить ревьюеру: почему его замечание не подходит — "
            "с обоснованием (например: «так задумано, потому что…»)"
        )
        self.reply.setMinimumHeight(160)
        box.addWidget(self.reply)

        self.status = ui.label("", wrap=True)
        box.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Отправить возражение")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._accept)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)

    def values(self) -> str:
        """Текст возражения."""
        return self.reply.toPlainText().strip()

    def _accept(self) -> None:
        if not self.values():
            self.status.setText("Пустое возражение отправлять нечего.")
            return
        self.accept()


class QwenSetupDialog(QDialog):
    """Фразы-триггеры для скилла настройки ревьюера — что сказать агенту.

    Кнопка «Настроить через скилл» сама настройкой не занимается: она
    показывает человеку фразы, которые он говорит агенту, — и каждую
    можно скопировать в буфер. Сами команды выполняет скилл
    qwen-review-setup за пределами этого диалога.
    """

    #: Фразы-триггеры: что сказать агенту и что это даст.
    PHRASES = [
        "«настрой ревьюера» — выбрать провайдера и модель, развернуть, включить",
        "«настрой тройное ревью» — заполнить панель тремя слотами",
        "«проверь, какие модели отвечают» — живая проверка доступности",
        "«ревьюер отвечает 401» — найти причину по ключу",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настроить ревьюера — через скилл")
        self.setMinimumWidth(700)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "Настройка выбором в окне передана скиллу: агент сам читает "
            "статус, узнаёт живые модели, выбирает провайдера по числу живых "
            "моделей (ничья — спросит), разворачивает и включает. Скажи "
            "агенту любую из фраз — и он сделает остальное.",
            wrap=True,
        ))
        box.addWidget(ui.label(
            "Фразы-триггеры (скопируй и вставь агенту):",
            kind="dim", wrap=True,
        ))
        self._copy_buttons: list[QPushButton] = []
        for phrase in self.PHRASES:
            row = QHBoxLayout()
            label = ui.label(phrase, wrap=True)
            btn = QPushButton("Скопировать")
            row.addWidget(label, 1)
            row.addWidget(btn)
            box.addLayout(row)
            btn.clicked.connect(
                lambda _=False, text=phrase, b=btn: self._copy(text, b))
            self._copy_buttons.append(btn)

        self.qw_setup_status = ui.label("", wrap=True)
        box.addWidget(self.qw_setup_status)

        row_foot = QHBoxLayout()
        row_foot.addStretch(1)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.setObjectName("primary")
        self.btn_close.setDefault(True)
        self.btn_close.clicked.connect(self.accept)
        row_foot.addWidget(self.btn_close)
        box.addLayout(row_foot)

    def _copy(self, text: str, button: QPushButton) -> None:
        """Кладёт фразу в буфер обмена и говорит об этом."""
        QApplication.clipboard().setText(text)
        for _btn in self._copy_buttons:
            _btn.setText("Скопировать")
        button.setText("Скопировано ✔")
        self.qw_setup_status.setText("Фраза в буфере: " + text)


class LmarenaTokenDialog(QDialog):
    """Токен арены: вписать свежую куку `arena-auth-prod-v1`.

    Токен берётся человеком в своём браузере — README форка описывает
    именно этот путь (отправить сообщение на сайте, открыть средства
    разработки, скопировать куку, начинается с `base64-`). Программа его
    только сохраняет: файлом рядом с настройками opencode, откуда он
    уезжает в config.json моста. В настройки opencode, в журнал и в
    сообщения окна токен не попадает.
    """

    def __init__(self, dest: Path, parent=None) -> None:
        super().__init__(parent)
        self.dest = Path(dest)
        self.messages: list[str] = []
        self.setWindowTitle("Токен арены для моста LMArena")
        self.setMinimumWidth(700)

        box = QVBoxLayout(self)
        box.setSpacing(8)
        box.addWidget(ui.label(
            "Как взять токен (путь из README форка): открой сайт арены, "
            "отправь там сообщение любой модели, нажми F12, открой "
            "«Application» → «Cookies», найди куку arena-auth-prod-v1 и "
            "скопируй её значение целиком — оно начинается с base64-.",
            wrap=True,
        ))
        box.addWidget(ui.label(
            "Токен ляжет файлом " + lmarena.TOKEN_NAME + " рядом с "
            "настройками opencode и в репозиторий не попадёт. В сам мост "
            "он уезжает при «Запустить» и «Перезапустить». Свежий токен "
            "заменяет прежний: старый мог протухнуть.",
            kind="dim",
            wrap=True,
        ))

        self.token = QLineEdit()
        self.token.setPlaceholderText("base64-…")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setToolTip(
            "Значение куки. Показывается точками: это секрет, и он должен "
            "попадать в журнал как можно реже"
        )
        self.show_token = QCheckBox("Показать токен")
        self.show_token.toggled.connect(
            lambda on: self.token.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        box.addWidget(self.token)
        box.addWidget(self.show_token)

        self.status = ui.label("", wrap=True)
        box.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Сохранить")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        box.addLayout(row)

    def _save(self) -> None:
        messages, errors = lmarena.save_token(self.dest, self.token.text())
        if errors:
            self.status.setText("Не записано. " + " ".join(errors))
            return
        self.messages = messages
        self.accept()


class CapsTab(ScrollPage):
    """Возможности базы для opencode — установка по выбору.

    Ставит в настройки opencode команду /голос, мост ПК, мост памяти
    и 13 агентов. Убранная галочка при нажатии «Убрать» снимает
    только наше, чужое не трогает.
    """

    #: Подписи двойного назначения: и для галочек (берутся из
    #: opencode_caps.CAPS_CHOICES), и для строки «уже стоит» (из caps_status,
    #: где мосты тоже есть). Поэтому подписи мостов остаются, хотя самих
    #: галочек у них больше нет.
    TITLES = {
        "voice": "Команда /голос — говорить в микрофон",
        "pc": "Мост ПК — файлы, программы, скриншоты (всё через спрос)",
        "ncp": "Мост NCP — память, библиотека, 7 инструментов",
        "agents": "13 агентов — поиск, план, код, проверка и другие",
        "antiblock": "Обход блокировок — запуск OpenCode через прокси",
        "rtk": "rtk — вывод команд короче",
        "caveman": "caveman — правила краткости ответов",
        "pxpipe": "pxpipe — запросы картинками",
        "auto-improve": "auto-improve — улучшение текста",
        "greenlight": "greenlight — проверка iOS перед App Store",
        "qwen-review": "Qwen Code — второй ревьюер (вторая пара глаз)",
    }

    def __init__(self, parent=None) -> None:
        self._worker: Worker | None = None
        self._qw_check_worker: QwenCheckModels | None = None
        self._what = ""
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    # ---- сборка окна

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        outer.addWidget(
            ui.label(
                "Ставит возможности этой базы прямо в opencode — только "
                "отмеченное. Мосты ПК и NCP сюда не входят: они едут с базой "
                "и включаются кнопкой «Подключить базу». Настоящие настройки "
                "лежат в папке opencode, перед правкой делается копия.",
                kind="dim",
                wrap=True,
            )
        )

        # --- шаг 1: что поставить
        self.checks: dict[str, QCheckBox] = {}
        # Кто из возможностей — агенты: у них отдельный блок со списком
        # ниже. Определяем до блока и до цикла: и то, и другое их читает.
        agent_names = [n for n, _t in opencode_caps.CAPS_CHOICES
                       if n.startswith(opencode_caps.AGENT_PREFIX)]
        # Агенты — тот же список, что навыки ниже: QListWidget с
        # отмечаемыми строками «имя — короткое описание», кнопки «Отметить
        # все» и «Снять все», подсказка со счётом. Раньше здесь стояли
        # тринадцать отдельных галочек: список выглядел и работал не как
        # навыки, и блок уезжал за край окна. Найдено 15.10.2026 глазами на
        # живом экране.
        box_agents = QGroupBox("1. Агенты — какие поставить в opencode")
        agents_layout = QVBoxLayout(box_agents)
        agents_layout.addWidget(ui.label(
            "Агент — отдельная «голова» со своей ролью, вызывается как @имя. "
            "Отметьте нужных: отмеченные скопируются в папку agents рядом с "
            "настройками, неотмеченные — нет. Сняли отметку у того, кто уже "
            "стоит: файл уберётся, если его не правили руками.",
            kind="dim", wrap=True,
        ))
        self.caps_agents_list = FittedList()
        # Настройки — как у списка навыков: перенос строки делает core,
        # а не Qt, поэтому высота строки известна заранее.
        self.caps_agents_list.setWordWrap(False)
        self.caps_agents_list.setUniformItemSizes(False)
        self.caps_agents_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Высота — по числу агентов, а не «окошко в 230 пикселей».
        # Раньше список был ограничен 230 px, и при тринадцати агентах
        # человек видел четыре строки, полосу прокрутки и пустое место
        # под ними — блок выглядел сломанным (снимок 22.10.2026).
        # Теперь список растянут на все строки, а прокручивается
        # страница целиком, как у навыков.
        agents_layout.addWidget(self.caps_agents_list)
        for cap_name, cap_title in opencode_caps.CAPS_CHOICES:
            if not cap_name.startswith(opencode_caps.AGENT_PREFIX):
                continue
            short = cap_title.split(" — ", 1)
            title = short[0]
            desc = short[1] if len(short) > 1 else ""
            row = QListWidgetItem(core.skill_item_text(
                {"title": title, "description": desc}, width=88))
            row.setData(1000, cap_name)
            row.setToolTip(f"{title} (@{title})\n\n{desc}\n\n"
                           "Файл агента: tools/agents/… По снятию отметки "
                           "файл убирается, если его не правили руками.")
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)
            self.caps_agents_list.addItem(row)
        # Строк ровно столько, сколько агентов: высота считается по
        # настоящей высоте строки, а не по константе — шрифт и масштаб
        # экрана у всех разные, и зашитая цифра врёт на 150%.
        fit_rows_height(self.caps_agents_list)

        row_ag = QHBoxLayout()
        btn_ag_all = QPushButton("Отметить все")
        btn_ag_all.clicked.connect(lambda: self._set_all_caps_agents(True))
        btn_ag_none = QPushButton("Снять все")
        btn_ag_none.clicked.connect(lambda: self._set_all_caps_agents(False))
        row_ag.addWidget(btn_ag_all)
        row_ag.addWidget(btn_ag_none)
        row_ag.addStretch(1)
        btn_ag_put = QPushButton("Установить отмеченных")
        btn_ag_put.setToolTip(
            "Ставит только агентов: копирует отмеченные файлы в папку agents "
            "рядом с настройками opencode. Навыки и остальное не трогает"
        )
        btn_ag_put.clicked.connect(self._install)
        btn_ag_drop = QPushButton("Убрать отмеченных")
        btn_ag_drop.setToolTip(
            "Убирает файлы отмеченных агентов. Те, что правили руками, "
            "останутся — о них будет сказано в списке"
        )
        btn_ag_drop.clicked.connect(self._remove)
        row_ag.addWidget(btn_ag_put)
        row_ag.addWidget(btn_ag_drop)
        agents_layout.addLayout(row_ag)
        self.caps_agents_hint = ui.label("", kind="dim", wrap=True)
        agents_layout.addWidget(self.caps_agents_hint)
        self._caps_agents_changed()
        outer.addWidget(box_agents)

        box_what = QGroupBox("1. Что поставить в opencode")
        what_layout = QVBoxLayout(box_what)
        for name, _title in opencode_caps.CAPS_CHOICES:
            # Агенты живут в своём списке рядом, как навыки: в общем списке
            # галочек их нет.
            if name in agent_names:
                continue
            # Подпись б��рётся из TITLES, а если её там нет — из списка
            # возможностей, так что служебных имён не остаётся.
            box = QCheckBox(self._cap_title(name))
            # rtk и caveman по умолчанию выключены: у rtk нужен бинарник в
            # PATH, caveman меняет стиль ответов. Молча включать такое нельзя.
            box.setChecked(name not in opencode_caps.CAPS_OFF_BY_DEFAULT)
            if name == "rtk":
                box.setToolTip(
                    "Плагин opencode от автора rtk: команды агента пойдут "
                    "через rtk и вернут меньше текста. Сам rtk ставится по "
                    "README автора (winget install rtk-ai.rtk или готовый "
                    "архив). Программа проверит rtk живым запросом и, если "
                    "его нет или версия старая, ничего не впишет"
                )
            if name == "caveman":
                box.setToolTip(
                    "Правила коротких ответов в AGENTS.md между метками базы. "
                    "Текст правил — из tools/thirdparty/caveman, автор "
                    "JuliusBrussee (Apache-2.0). Снимается галочкой или "
                    "словами «stop caveman»"
                )
            if name == "pxpipe":
                box.setToolTip(
                    "Локальный прокси автора teamchong (MIT): часть запроса "
                    "уезжает нейросети картинкой, и в окно контекста "
                    "помещается больше. Сжатие с потерями — точные строки и "
                    "код могут быть прочитаны неверно. Галочка только "
                    "вписывает запись провайдера: сначала запусти прокси "
                    "кнопкой ниже, иначе программа ничего не впишет"
                )
                box.toggled.connect(self._px_toggled)
            if name == "auto-improve":
                box.setToolTip(
                    "Сторонний скрипт автора crimeacs (MIT): улучшает один "
                    "текстовый файл точечными правками, а оценивает их "
                    "отдельная модель-судья Gemini по рубрике. Нужны ключ "
                    "судьи (команда auto_improve.py key), git и файл внутри "
                    "git-репозитория. Цикл сам коммитит в ветку improve/<тег> "
                    "и тратит токены — включай осознанно. Кнопка «Улучшить "
                    "файл…» работает, только когда галочка отмечена"
                )
                box.toggled.connect(self._ai_toggled)
            if name == "greenlight":
                box.setToolTip(
                    "Сторонний консольный сканер автора Revyl (MIT): читает "
                    "исходники, файлы приватности и Info.plist, сверяет с "
                    "правилами Apple и выдаёт список рисков с исправлениями. "
                    "Основная проверка идёт офлайн, наружу ничего не "
                    "отправляется. Для opencode-base (PyQt6, Windows) он не "
                    "нужен — это опция для тех, кто делает приложения для "
                    "iOS. Кнопка «Проверить iOS-приложение» работает, только "
                    "когда галочка отмечена"
                )
                box.toggled.connect(self._gl_toggled)
            if name == "qwen-review":
                box.setToolTip(
                    "Второй ревьюер: сторонний консольный агент Qwen Code "
                    "(автор QwenLM, Apache-2.0). После работы основного "
                    "агента он читает `git diff` изменений и приносит "
                    "замечания — свежий взгляд второй модели. Модель "
                    "выбирается из провайдеров, уже подключённых в "
                    "opencode. Ревьюер файлы не правит и идёт в режиме "
                    "«только чтение». Это тратит токены: каждая проверка — "
                    "запрос. Отдельный режим «спор» по умолчанию выключен"
                )
                box.toggled.connect(self._qw_toggled)
            what_layout.addWidget(box)
            self.checks[name] = box

        # --- qwen-review: второй ревьюер. Настройка выбором провайдера и
        # развёртывание отдана скиллу qwen-review-setup; в окне остались
        # статус, проверка доступности и запуск проверки изменений.
        box_qw = QGroupBox("Qwen Code — второй ревьюер (вторая пара глаз)")
        qw_layout = QVBoxLayout(box_qw)
        qw_layout.addWidget(ui.label(
            "Сторонний консольный агент Qwen Code (автор QwenLM, лицензия "
            "Apache-2.0) в headless-режиме: читает `git diff` изменений и "
            "приносит замечания второй моделью. Файлы он не правит — идёт в "
            "режиме «только чтение». Модель выбирается из провайдеров, уже "
            "подключённых в opencode; ключ передаётся только в окружение "
            "запуска и в окно и журналы не попадает.",
            kind="dim", wrap=True,
        ))
        # --- режимы ревьюера: список строится из общего qwen_review.MODES,
        # а не хардкодом: добавился режим в списке — появился и здесь.
        qw_layout.addWidget(ui.label("Режимы ревьюера:", kind="dim", wrap=True))
        self.qw_modes_labels: list[QLabel] = []
        for _mode in qwen_review.MODES:
            _line = "• " + str(_mode.get("name") or "") + " — " \
                + str(_mode.get("description") or "")
            _lbl = ui.label(_line, kind="dim", wrap=True)
            qw_layout.addWidget(_lbl)
            self.qw_modes_labels.append(_lbl)
        # Настройка ушла в скилл qwen-review-setup: выбор провайдера и
        # модели, развёртывание и включение делает агент, а не кнопки
        # окна. Здесь остались кнопка-подсказка «Настроить через скилл»,
        # живая проверка доступности и запуск проверки изменений.
        row_qw_pick = QHBoxLayout()
        self.btn_qw_setup = QPushButton("Настроить через скилл")
        self.btn_qw_setup.setToolTip(
            "Фразы-триггеры для агента: «настрой ревьюера», «настрой тройное "
            "ревью», «проверь, какие модели отвечают», «ревьюер отвечает 401». "
            "Агент сам выберет провайдера и модель по числу живых моделей, "
            "развернёт и включит ревьюера"
        )
        row_qw_pick.addWidget(self.btn_qw_setup)
        row_qw_pick.addStretch(1)
        qw_layout.addLayout(row_qw_pick)
        # --- проверка доступности моделей: кнопка, под ней — прогресс и
        # список состояний ✔/✘/?. Проверка живёт в отдельном потоке
        # (QwenCheckModels): в момент нажатия кнопка гаснет, а окно
        # продолжает отвечать.
        row_qw_avail = QHBoxLayout()
        self.btn_qw_check_models = QPushButton("Проверить доступность")
        self.btn_qw_check_models.setToolTip(
            "Задаёт один минимальный вопрос каждой модели выбранного "
            "провайдера и показывает, кто отвечает (✔), кто отказал "
            "окончательно (✘ — 401, 404) и кто неизвестен (? — 429, "
            "таймаут). Это тратит токены и бьёт по API: не больше "
            "120 запросов за прогон. Результат запоминается на сутки: "
            "повторный просмотр без кнопки идёт из кэша"
        )
        row_qw_avail.addWidget(self.btn_qw_check_models)
        row_qw_avail.addStretch(1)
        qw_layout.addLayout(row_qw_avail)
        self.qw_check_progress = ui.label("", kind="dim", wrap=True)
        qw_layout.addWidget(self.qw_check_progress)
        # Список состояний моделей. Своя высота с потолком: провайдеров
        # бывают сотни моделей, и без потолка страница выросла бы на
        # экран, а с потолком список крутится внутри себя сам.
        self.qw_check_list = QListWidget()
        self.qw_check_list.setWordWrap(True)
        self.qw_check_list.setMaximumHeight(150)
        self.qw_check_list.setVisible(False)
        qw_layout.addWidget(self.qw_check_list)
        self.qw_hint = ui.label("", kind="dim", wrap=True)
        qw_layout.addWidget(self.qw_hint)
        row_qw_btns = QHBoxLayout()
        self.btn_qw_run = QPushButton("Проверить изменения…")
        self.btn_qw_run.setToolTip(
            "Берёт `git diff` проекта и отдаёт его ревьюеру. Раунды спора "
            "начинаются с этого же нажатия. Кнопка доступна только при "
            "отмеченной галочке qwen-review"
        )
        row_qw_btns.addWidget(self.btn_qw_run)
        row_qw_btns.addStretch(1)
        qw_layout.addLayout(row_qw_btns)
        # Подпись и подсказка галочки берутся из общего списка режимов
        # (qwen_review.MODES): в задаче 5 отсюда же построится окно выбора.
        # Текст прежний — разметку не ломаем, на галочку завязаны
        # _qw_toggled, _qw_debate_toggled, _qw_run и _qw_reply.
        _qw_debate_mode = qwen_review.mode_by_id(qwen_review.MODE_DEBATE) or {}
        self.qw_debate = QCheckBox(
            str(_qw_debate_mode.get("label") or "спор — ревьюер против модели"))
        self.qw_debate.setToolTip(str(_qw_debate_mode.get("description") or (
            "Отдельный режим, по умолчанию выключен. Ревьюер присылает "
            "замечания, основной агент возражает с обоснованием, ревьюер "
            "отвечает — и так не больше заданного числа раундов. Если "
            "согласия нет, программа не решает сама: она показывает оба "
            "довода и спорный фрагмент, а решает человек"
        )))
        # Текущий режим по старой галочке: пишется в _qw_debate_toggled,
        # читается оттуда же, из qwen_review.MODES.
        self._qw_mode_id = qwen_review.mode_from_flag(False)
        row_qw_debate = QHBoxLayout()
        row_qw_debate2 = QHBoxLayout()
        row_qw_debate.addWidget(self.qw_debate)
        row_qw_debate.addWidget(QLabel("   раундов:   "))
        self.qw_rounds = QSpinBox()
        self.qw_rounds.setRange(1, qwen_review.MAX_ROUNDS)
        self.qw_rounds.setValue(qwen_review.DEFAULT_ROUNDS)
        self.qw_rounds.setToolTip(
            "Сколько раундов спора разрешено. Больше — больше токенов; "
            "предел задан автором режима, поднимать его выше пяти не даём"
        )
        row_qw_debate.addWidget(self.qw_rounds)
        row_qw_debate.addStretch(1)
        self.btn_qw_reply = QPushButton("Возразить и продолжить…")
        self.btn_qw_reply.setToolTip(
            "Следующий раунд спора: возражение с обоснованием уходит "
            "ревьюеру вместе с ходом спора. Работает только при включённом "
            "«споре»"
        )
        self.btn_qw_forget = QPushButton("Забыть ход спора")
        self.btn_qw_forget.setToolTip(
            "Сбрасывает счёт раундов и доводы: следующий запуск начнётся "
            "заново. Ни файлы проекта, ни настройки не трогает"
        )
        row_qw_debate2.addWidget(self.btn_qw_reply)
        row_qw_debate2.addWidget(self.btn_qw_forget)
        row_qw_debate2.addStretch(1)
        # Ряд из галочки, счётчика и двух кнопок занимал 763 пикселя при
        # ширине окна около 830 и упирался в правый край. Теперь настройка
        # спора стоит на одной строке, а его действия — на следующей.
        qw_layout.addLayout(row_qw_debate)
        qw_layout.addLayout(row_qw_debate2)
        what_layout.addWidget(box_qw)
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
        import antiblock as _ab  # noqa: PLC0415 — рядом лежит, круга нет

        self.achecks: dict[str, QCheckBox] = {}
        # Подпись у галочки короткая, а подробности — в подсказке. Qt не
        # переносит текст внутри QCheckBox, и длинная подпись просто
        # обрезалась: измерено при минимальном окне 720, «Защищённый DNS»
        # получал 422 пикселя вместо 526 и конец пропадал. Обрезанное
        # должно оставаться достижимым — для этого подсказка.
        for key, title, tip in (
            ("facade",
             f"Переводчик и запуск (фасад 127.0.0.1:{_ab.facade_port()} "
             "+ ярлык-запуск)",
             "Поднимает переводчик на своём порту и создаёт ярлык запуска"),
            ("lists", "Бесплатные списки",
             "SOCKS5-пул и VLESS-подписки, обновляются раз в сутки сами"),
            ("dns", "Защищённый DNS",
             "DoH через Google, Cloudflare, Quad9 или AdGuard — запасной "
             "способ обхода, если прокси не помог"),
            ("command", "Команда /обход", "Команда /обход внутри OpenCode"),
            ("shortcut", "Ярлык «OpenCode (обход)»",
             "Ярлык на рабочий стол с иконкой самой программы"),
        ):
            box = QCheckBox(title)
            box.setToolTip(tip)
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
        # Строка состояния: своим каналом, запасным или не работает.
        # §20.6 плана требует говорить прямо, когда включён запасной:
        # снаружи оба канала выглядят одинаково, а на деле трафик идёт
        # через чужие машины. Молчание тут врёт.
        self.lbl_ab_state = ui.label("Обход: проверяю...", kind="dim", wrap=True)
        ab_layout.addWidget(self.lbl_ab_state)
        row_port = QHBoxLayout()
        row_port.addWidget(ui.label("Порт фасада:", kind="dim"))
        self.spin_ab_port = QSpinBox()
        self.spin_ab_port.setRange(_ab.PORT_MIN, _ab.PORT_MAX)
        self.spin_ab_port.setValue(_ab.facade_port())
        self.spin_ab_port.setToolTip(
            "Порт, на котором фасад принимает соединения. Меняйте, если "
            f"дефолтный {_ab.FACADE_PORT} занят. Стартер прочитает это сам."
        )
        row_port.addWidget(self.spin_ab_port)
        self.btn_ab_save = QPushButton("Сохранить")
        row_port.addWidget(self.btn_ab_save)
        row_port.addStretch(1)
        ab_layout.addLayout(row_port)
        self._refresh_ab_state()
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
        # Перенос делает core.skill_item_text, вставляя переносы в текст
        # явно: сворачивание длинного описания в одну строку Qt здесь
        # делает непредсказуемо, а с явными переносами высота строки
        # известна заранее и список растёт равномерно.
        self.caps_skills_list.setWordWrap(False)
        self.caps_skills_list.setUniformItemSizes(False)
        self.caps_skills_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Запас на случай пустого списка: fit_skills_height выставит свою
        # высоту по фактическому числу навыков.
        self.caps_skills_list.setMinimumHeight(300)
        self.caps_skills_list.setMaximumHeight(600)
        skills_layout.addWidget(self.caps_skills_list)

        row_skills = QHBoxLayout()
        self.btn_skills_all = QPushButton("Отметить все")
        self.btn_skills_none = QPushButton("Снять все")
        self.btn_skills_reload = QPushButton("Обновить список")
        # Проверка обновлений у авторов. Отдельная кнопка, а не
        # продолжение «Обновить список»: та просто перерисовывает
        # содержимое базы, эта ходит в сеть и сравнивает с тем, что
        # лежит у автора.
        self.btn_skills_check = QPushButton("Проверить обновления скилов")
        self.btn_skills_check.setToolTip(
            "Сравнить наши скилы с тем, что лежит у их авторов. "
            "Ничего не обновляет: показывает, у кого появилось, и "
            "разницу. Переводы не трогает — их нечем заменить "
            "автоматически.")
        self.btn_skills_put = QPushButton("Поставить отмеченные")
        self.btn_skills_drop = QPushButton("Убрать отмеченные")
        row_skills.addWidget(self.btn_skills_all)
        row_skills.addWidget(self.btn_skills_none)
        row_skills.addWidget(self.btn_skills_reload)
        row_skills.addStretch(1)
        row_skills.addWidget(self.btn_skills_put)
        row_skills.addWidget(self.btn_skills_drop)
        skills_layout.addLayout(row_skills)

        # Проверка обновлений — на своей строке. В общий ряд она не
        # помещалась: шесть кнопок в линию не влезают в ширину окна, Qt
        # растягивал их на всю ширину блока, и кнопка уезжала за край
        # экрана целиком — измерено: все шесть были по 640 пикселей при
        # окне 895. Человек её не видел вовсе.
        row_skills_check = QHBoxLayout()
        row_skills_check.addWidget(self.btn_skills_check)
        row_skills_check.addStretch(1)
        skills_layout.addLayout(row_skills_check)

        self.caps_skills_hint = ui.label("", kind="dim", wrap=True)
        skills_layout.addWidget(self.caps_skills_hint)
        outer.addWidget(box_skills)

        # --- шаг 6. Серверы MCP из реестра
        box_mcp = QGroupBox("6. Серверы MCP — что можно включить")
        mcp_layout = QVBoxLayout(box_mcp)
        mcp_layout.addWidget(
            ui.label(
                "Это не мосты: мосты едут с базой и включены всегда. Здесь "
                "сторонние серверы из реестра. Программа проверяет требования "
                "живьём и вписывает блок в настройки opencode — сама ничего "
                "не скачивает и подписки не покупает. После включения "
                "перезапусти opencode.",
                kind="dim",
                wrap=True,
            )
        )

        self.reg_servers: list[mcp_registry.Server] = []
        # Что реально показано в таблице: поиск и подменю категорий
        # фильтруют список, а кнопки блока работают с выбранной строкой.
        # Без отдельного списка «строка 3» после фильтра означала бы
        # третий сервер реестра, а не третий на экране.
        self._reg_shown: list[mcp_registry.Server] = []
        self._reg_query = ""
        self._reg_group = ""

        # Поиск стоит над таблицей, а не над всей вкладкой: он ищет
        # именно мосты, и стоять выше агентов значило бы обещать
        # фильтр по всей странице.
        search_row = QHBoxLayout()
        self.reg_search = QLineEdit()
        self.reg_search.setPlaceholderText(
            "Поиск мостов: имя, категория или описание…"
        )
        self.reg_search.setClearButtonEnabled(True)
        self.reg_search.textChanged.connect(self._reg_apply_filter)
        search_row.addWidget(self.reg_search, 1)
        self.btn_reg_check_top = QPushButton("Проверить всё")
        self.btn_reg_check_top.setObjectName("primary")
        self.btn_reg_check_top.setToolTip(
            "Живая проверка требований: запускает чужие команды, чтобы "
            "честно сказать состояние. Ничего не устанавливает и не включает"
        )
        self.btn_reg_check_top.clicked.connect(self._reg_check_all)
        search_row.addWidget(self.btn_reg_check_top)
        mcp_layout.addLayout(search_row)
        self.reg_counter = ui.label("", kind="dim")
        mcp_layout.addWidget(self.reg_counter)

        self.reg_table = QTableWidget(0, 4)
        # Заголовок «Инструментов» не помещался в свою колонку: та
        # получает остаток места, а не своё, и на снимке обрезалась
        # с двух сторон — «-трумен…». Короче и понятнее: сколько
        # инструментов даёт сервер.
        self.reg_table.setHorizontalHeaderLabels(
            ["Сервер", "Категория", "Состояние", "Инструм."]
        )
        self.reg_table.verticalHeader().setVisible(False)
        self.reg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.reg_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.reg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.reg_table.setMinimumHeight(150)
        # Потолка высоты больше нет: её считает _reg_fit_table_height по
        # числу серверов, чтобы в блок влезали все строки. Прежний
        # предел 190 пикселей показывал половину списка и заставлял
        # крутить полосу прокрутки внутри самого блока.
        # Ширины заданы явно, потому что Qt по умолчанию распределяет
        # место неудачно: снимок показал обрезанные до «Windo…» имена и
        # обрезанное до «нужно: …» состояние. Имя должно помещаться
        # целиком - по нему человека ищет в списке, - а лишнее место
        # отдаётся состоянию, потому что оно длиннее всех.
        header = self.reg_table.horizontalHeader()
        # Подписи колонок — по левому краю, как и текст в ячейках:
        # центрированные заголовки выглядели сдвинутыми относительно
        # своих колонок.
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(header.ResizeMode.Fixed)
        # Ширины считаются по содержимому при заполнении таблицы,
        # см. _reg_fit_columns. Здесь только минимумы: пока таблица
        # пустая, измерять нечего.
        for col, minimum in ((0, 160), (1, 80), (2, 120), (3, 70)):
            self.reg_table.setColumnWidth(col, minimum)
        # Прокрутка вбок появляется только когда не помещается. Раньше она
        # была выключена вовсе, и тогда таблица задавала ширину всей
        # страницы: колонка «Состояние» растягивается под длинные
        # тексты, сумма ширин доходила до 775, и на узком окне вместе
        # с ней за правый край уезжали кнопки этого же блока. Теперь
        # при обычной ширине полосы нет, а на узком окне прокручивается
        # только сама таблица, а не вся страница.
        self.reg_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        mcp_layout.addWidget(self.reg_table)

        self.reg_detail = QPlainTextEdit()
        self.reg_detail.setReadOnly(True)
        self.reg_detail.setMinimumHeight(120)
        mcp_layout.addWidget(self.reg_detail)

        row_mcp = QHBoxLayout()
        row_mcp2 = QHBoxLayout()
        self.btn_reg_check = QPushButton("Проверить всё")
        self.btn_reg_on = QPushButton("Включить")
        self.btn_reg_auto = QPushButton("Настроить автоматически")
        self.btn_reg_auto.setToolTip(
            "Описание берётся по выбранной строке: что кнопка сделает "
            "именно с этим сервером. Мосты редакторов, CapCut, Spotify, "
            "ChatGPT API, Codex и Cursor настраивают только свою часть — "
            "файл или проверку. Чужое окно не открывает ни одна строка."
        )
        self.btn_reg_auto.setEnabled(False)
        self.btn_reg_off = QPushButton("Выключить")
        self.btn_reg_src = QPushButton("Открыть источник")
        # Подключения DBHub. Кнопки стоят в общем ряду, но живут только
        # для своей строки: у остальных серверов подключений к базам нет.
        self.btn_db_add = QPushButton("Добавить подключение")
        self.btn_db_add.setToolTip(
            "DBHub: вписать базу — файл mcp-dbhub.toml рядом с настройками "
            "opencode. Пароль из строки подключения программа сохранит "
            "отдельным файлом"
        )
        self.btn_db_add.setEnabled(False)
        self.btn_db_check = QPushButton("Проверить соединение")
        self.btn_db_check.setToolTip(
            "DBHub: поднять сервер и спросить у него протоколом, отвечает ли "
            "база. Ничего не записывает — только говорит, жива ли связь"
        )
        self.btn_db_check.setEnabled(False)
        # Кнопки браузеров. Тоже живут только для своей строки: у
        # остальных серверов выбирать нечего — они запускаются командой.
        self.btn_br_choose = QPushButton("Выбрать браузер")
        self.btn_br_choose.setToolTip(
            "Браузеры: Chrome, Edge, Яндекс.Браузер или Firefox; профиль "
            "нейросети и показывать ли окно. В режиме «мои сессии» — "
            "токен расширения Playwright, чтобы не спрашивать одобрение. "
            "Выбор ляжет в mcp-browsers.json рядом с настройками opencode"
        )
        self.btn_br_choose.setEnabled(False)
        self.btn_br_check = QPushButton("Проверить браузер")
        self.btn_br_check.setToolTip(
            "Браузеры: поднять мост, открыть страницу и прочитать её "
            "заголовок. Ничего не записывает — говорит, работает ли выбранный "
            "браузер и видно ли страницу"
        )
        self.btn_br_check.setEnabled(False)
        # Кнопки OmniRoute. Своя строка и своя работа: развернуть пакет,
        # поднять сервер, перезапустить его и показать состояние. В
        # opencode ничего из этого не пишет — пишет только автонастройка.
        self.btn_or_deploy = QPushButton("Развернуть")
        self.btn_or_deploy.setToolTip(
            "OmniRoute: поставить пакет из npm в свою папку моста. Это "
            "сотни мегабайт и несколько минут; служебные папки Node.js "
            "программа не трогает"
        )
        self.btn_or_deploy.setEnabled(False)
        self.btn_or_start = QPushButton("Запустить")
        self.btn_or_start.setToolTip(
            "OmniRoute: поднять локальный сервер (панель и API на "
            "http://127.0.0.1:20128) и дождаться ответа API. Ничего не "
            "записывает в настройки opencode"
        )
        self.btn_or_start.setEnabled(False)
        self.btn_or_restart = QPushButton("Перезапустить")
        self.btn_or_restart.setToolTip(
            "OmniRoute: остановить сервер и поднять снова, затем живая "
            "проверка. Так же лечится зависший мост. Заново подключает "
            "бесплатных провайдеров без ключа"
        )
        self.btn_or_restart.setEnabled(False)
        self.btn_or_status = QPushButton("Показать статус")
        self.btn_or_status.setToolTip(
            "OmniRoute: что развёрнуто, отвечает ли API, какая версия и "
            "сколько провайдеров подключено. Ни ключей, ни токенов в "
            "ответе нет"
        )
        self.btn_or_status.setEnabled(False)
        # Кнопка «Открыть панель». OmniRoute поднимает локальный веб-сайт,
        # а открыть его из программы было нечем: человек шёл искать адрес
        # вручную, хотя программа знает его лучше него. Открывает вид,
        # а не модуль моста, поэтому одна функция на окно и на трей.
        self.btn_or_open = QPushButton("Открыть панель")
        self.btn_or_open.setToolTip(
            "OmniRoute: открыть локальную панель в браузере по адресу "
            "http://127.0.0.1:20128. Сначала живая проверка: при "
            "выключенном сервере кнопка скажет, что делать, а не "
            "откроет страницу с ошибкой"
        )
        self.btn_or_open.setEnabled(False)
        # Кнопки моста LMArena. Своя строка и своя работа: развернуть
        # окружение форка, поднять мост, перезапустить его, показать
        # состояние и положить токен арены. В opencode ничего из этого не
        # пишет — пишет только автонастройка, и только после ответа модели.
        self.btn_lm_deploy = QPushButton("Развернуть")
        self.btn_lm_deploy.setToolTip(
            "LMArena: поставить окружение моста (.venv) и его зависимости "
            "из requirements.txt в папку tools/thirdparty/lmarena. Код форка "
            "уже в репозитории; чужие папки пакетов не трогаются"
        )
        self.btn_lm_deploy.setEnabled(False)
        self.btn_lm_start = QPushButton("Запустить")
        self.btn_lm_start.setToolTip(
            "LMArena: перенести токен из файла рядом с настройками в "
            "config.json моста и поднять его на http://127.0.0.1:8000. "
            "Перед первым запуском программа покажет предупреждения"
        )
        self.btn_lm_start.setEnabled(False)
        self.btn_lm_restart = QPushButton("Перезапустить")
        self.btn_lm_restart.setToolTip(
            "LMArena: остановить мост и поднять заново — так лечится "
            "зависший мост и так же подхватывается обновлённый токен"
        )
        self.btn_lm_restart.setEnabled(False)
        self.btn_lm_status = QPushButton("Показать статус")
        self.btn_lm_status.setToolTip(
            "LMArena: что развёрнуто, отвечает ли мост, есть ли токен "
            "арены и сколько моделей он знает. Токена самого в ответе нет"
        )
        self.btn_lm_status.setEnabled(False)
        self.btn_lm_token = QPushButton("Обновить токен")
        self.btn_lm_token.setToolTip(
            "LMArena: вписать свежую куку arena-auth-prod-v1 с сайта арены. "
            "Токен ляжет файлом рядом с настройками opencode и уедет в "
            "config.json моста, а не в настройки opencode"
        )
        self.btn_lm_token.setEnabled(False)
        # Раньше все восемнадцать кнопок стояли в одном ряду: он занимал
        # 1870 пикселей, а окно показывает около 830. Страница становилась
        # вдвое шире видимой части, крайние кнопки уходили за правый край
        # на 1000 пикселей и до них нельзя было дотянуться: полоса
        # прокрутки вбок есть только в самом низу страницы, а страница
        # здесь — четыре тысячи пикселей высотой. Плюс ряд из
        # восемнадцати одинаковых кнопок без подписей читался как каша:
        # из «Развернуть» и «Запустить» не было видно, что это про арену.
        # Теперь ряд на сервер — так и было задумано в комментариях выше.
        row_mcp.addWidget(self.btn_reg_check)
        row_mcp.addWidget(self.btn_reg_on)
        self.btn_reg_all = QPushButton("Включить все")
        self.btn_reg_all.setToolTip(
            "Включить в настройках opencode сразу все серверы, которые "
            "не требуют вопросов. Те, где нужно что-то выбрать или сначала "
            "живая проверка (Android Studio, DBHub, LMArena), будут "
            "перечислены в журнале с указанием, что нажать — молча пропускать "
            "их нельзя. Повторное нажатие ничего не ломает: запись "
            "идемпотентна"
        )
        row_mcp.addWidget(self.btn_reg_all)
        self.btn_reg_off_all = QPushButton("Отключить все мосты")
        self.btn_reg_off_all.setToolTip(
            "Убрать из настроек opencode ВСЕ блоки серверов разом — вместе с "
            "мостами памяти базы ncp и pc. После этого память, навыки, агенты "
            "и чтение компьютера работать перестанут, пока их не включат "
            "заново. Нужен, чтобы взять чистую листку и оставить только "
            "нужное. Перед записью делается копия настроек, после — нужен "
            "перезапуск opencode"
        )
        row_mcp.addWidget(self.btn_reg_off_all)
        row_mcp.addWidget(self.btn_reg_off)
        row_mcp2.addWidget(self.btn_reg_auto)
        row_mcp2.addWidget(self.btn_reg_src)
        row_mcp.addStretch(1)
        row_mcp2.addStretch(1)
        mcp_layout.addLayout(row_mcp)
        mcp_layout.addLayout(row_mcp2)

        for owner, buttons in (
            ("DBHub", (self.btn_db_add, self.btn_db_check)),
            ("Браузеры", (self.btn_br_choose, self.btn_br_check)),
            ("OmniRoute", (self.btn_or_deploy, self.btn_or_start,
                           self.btn_or_restart, self.btn_or_open,
                           self.btn_or_status)),
            ("LMArena", (self.btn_lm_deploy, self.btn_lm_start,
                         self.btn_lm_restart, self.btn_lm_status,
                         self.btn_lm_token)),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            # Подпись сервера — короткая и тусклая: она только говорит,
            # чьи это кнопки. Подробности живут в подсказках кнопок, а
            # строка таблицы выше показывает, что выбрано сейчас.
            name = ui.label(owner, kind="dim")
            name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(name)
            row.addSpacing(4)
            for button in buttons:
                row.addWidget(button)
            row.addStretch(1)
            mcp_layout.addLayout(row)

        self.reg_hint = ui.label("", kind="dim", wrap=True)
        mcp_layout.addWidget(self.reg_hint)
        outer.addWidget(box_mcp)

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
        # Потолок и подсказку пустого журнала ставит сам LogView: пока
        # отчёта нет, он занимает минимум, а не всю оставшуюся страницу.
        outer.addWidget(self.log)

        # Связи — только здесь, когда все элементы уже созданы.
        self.dest_edit.textChanged.connect(self._refresh)
        self.btn_ab_check.clicked.connect(self._check_antiblock)
        self.btn_ab_dns.clicked.connect(self._check_dns)
        self.btn_ab_save.clicked.connect(self._save_ab_port)
        self.btn_skills_all.clicked.connect(lambda: self._set_all_caps_skills(True))
        self.btn_skills_none.clicked.connect(lambda: self._set_all_caps_skills(False))
        self.btn_skills_reload.clicked.connect(lambda: self._fill_caps_skills())
        self.btn_skills_check.clicked.connect(self._check_skill_updates)
        self.btn_skills_put.clicked.connect(self._install_skills)
        self.btn_skills_drop.clicked.connect(self._remove_skills)
        self.caps_skills_list.itemChanged.connect(self._caps_skills_changed)
        self.btn_reg_check.clicked.connect(self._reg_check_all)
        self.btn_reg_all.clicked.connect(self._reg_enable_all)
        self.btn_reg_on.clicked.connect(self._reg_enable)
        self.btn_reg_off_all.clicked.connect(self._reg_disable_all)
        self.btn_reg_auto.clicked.connect(self._reg_auto)
        self.btn_reg_off.clicked.connect(self._reg_disable)
        self.btn_reg_src.clicked.connect(self._reg_open_source)
        self.btn_db_add.clicked.connect(self._db_add_source)
        self.btn_db_check.clicked.connect(self._db_check)
        self.btn_br_choose.clicked.connect(self._br_choose)
        self.btn_br_check.clicked.connect(self._br_check)
        self.btn_or_deploy.clicked.connect(self._or_deploy)
        self.btn_or_start.clicked.connect(self._or_start)
        self.btn_or_restart.clicked.connect(self._or_restart)
        self.btn_or_status.clicked.connect(self._or_status)
        self.btn_or_open.clicked.connect(self._or_open_panel)
        self.btn_lm_deploy.clicked.connect(self._lm_deploy)
        self.btn_lm_start.clicked.connect(self._lm_start)
        self.btn_lm_restart.clicked.connect(self._lm_restart)
        self.btn_lm_status.clicked.connect(self._lm_status)
        self.btn_lm_token.clicked.connect(self._lm_token)
        self.btn_qw_setup.clicked.connect(self._qw_setup)
        self.btn_qw_run.clicked.connect(self._qw_run)
        self.btn_qw_reply.clicked.connect(self._qw_reply)
        self.btn_qw_forget.clicked.connect(self._qw_forget)
        self.btn_qw_check_models.clicked.connect(self._qw_check_models)
        self.qw_debate.toggled.connect(self._qw_debate_toggled)
        self.reg_table.currentCellChanged.connect(
            lambda *_: self._reg_show_detail()
        )
        self._fill_caps_skills()
        self._reg_load()
        # Проверки уходят из сборки окна. Они бьют по сети и по запуску
        # внешних программ, и из-за них главное окно открывалось через
        # несколько секунд, а Windows помечала его «не отвечает»: главный
        # поток занят, события не обрабатываются. Теперь проверки
        # выполняются сразу после показа окна — очередь событий ещё
        # пуста, поэтому окно успевает отрисоваться, а потом
        # дописываются честные ответы.
        QTimer.singleShot(0, self._startup_checks)

        outer.activate()
        self.refresh_height()

    def _startup_checks(self) -> None:
        """Проверки, которые раньше шли при сборке окна."""
        self._ai_toggled(self.checks["auto-improve"].isChecked())
        # Кнопки greenlight — по галочке greenlight: по умолчанию сканер
        # выключен и ничего не запускается.
        self._gl_toggled(self.checks["greenlight"].isChecked())
        # Второй ревьюер: по умолчанию выключен, «спор» — тоже.
        self._qw_toggled(self.checks["qwen-review"].isChecked())
        self._qw_debate_toggled(False)
        self._refresh()

    # ---- серверы MCP из реестра

    def _reg_base(self) -> Path:
        return self._base()

    def _reg_dest(self) -> Path | None:
        dest = self._dest()
        return dest

    def _reg_load(self) -> None:
        """Читает реестр и показывает серверы без проверки требований.

        Требования здесь не проверяются: каждая проверка запускает
        внешнюю программу. Пока пользователь не нажал «Проверить всё»,
        состояние показано как «не проверено» — это честнее, чем молча
        показывать пустые галочки.

        Реестр — файл программы, а база держит его копию. Копия старее
        программы — и вкладка молча показывала бы серверы, которых в
        программе уже нет, и не показывала бы новые: человек открывал
        окно и не мог подключить то, что только что перенесено. Поэтому
        перед чтением копия приводится к программе, а что именно
        изменилось — пишется в журнал вкладки.
        """
        base = self._reg_base()
        synced = core.sync_base_data(base)
        self._reg_sync_notes = list(synced)
        data = mcp_registry.load_registry(base)
        self.reg_servers = []
        for spec in data.get("servers") or []:
            if not isinstance(spec, dict):
                continue
            conn = spec.get("connection")
            self.reg_servers.append(
                mcp_registry.Server(
                    id=str(spec.get("id") or ""),
                    name=str(spec.get("name") or ""),
                    raw=spec,
                    has_connection=isinstance(conn, dict) and bool(
                        conn.get("command") or conn.get("url")
                        or conn.get("manual_config")
                    ),
                )
            )
        self._reg_paint()
        # Что обновилось из программы — говорим вслух. Молча обновившийся
        # реестр выглядит как «ничего не изменилось», а человек потом
        # гадает, откуда взялись серверы и куда делись прежние.
        notes = getattr(self, "_reg_sync_notes", []) or []
        for line in notes:
            self.log.add(f"Реестр базы: {line}", "ok")
        # Подсказка — только про то, что случилось на самом деле. Если
        # обновился один лишь файл уведомлений, писать «реестр обновлён»
        # значило бы сказать неправду.
        if any("mcp-registry.json" in line for line in notes):
            if any("меняли руками" in line for line in notes):
                self.reg_hint.setText(
                    "Реестр в базе правили руками — программа его не тронула. "
                    "Её версия лежит в .workbuddy-ai/backups/дано-программой, "
                    "показанные серверы — из твоей копии."
                )
            else:
                self.reg_hint.setText(
                    "Реестр в базе обновлён из программы — прежняя копия "
                    "отложена в .workbuddy-ai/backups."
                )
        elif notes:
            self.reg_hint.setText(
                "Файлы программы в базе обновлены, прежние копии отложены "
                "в .workbuddy-ai/backups."
            )

    def _reg_config_saved(self, server: mcp_registry.Server) -> bool:
        """Вставлена ли конфигурация для сервера, который настраивают руками.

        Из трёх ручных требований это единственное, которое программа
        может проверить сама: конфигурацию вставляет она же и хранит
        рядом с настройками. Остальные два - включён ли сервер в студии
        и запущена ли студия - проверяются только человеком.
        """
        if not server.manual_setup:
            return True
        dest = self._reg_dest()
        if dest is None:
            return False
        return mcp_registry.load_manual_config(dest, server.id) is not None

    # Серверы, у которых кнопка «Настроить автоматически» есть.
    # Первые семь настраиваются целиком, остальные — только своей частью:
    # записать файл или сказать, чего не хватает. Чужое окно кнопка не
    # открывает ни в одном случае.
    AUTO_SERVERS = ("android-studio", "obs", "android-emulator", "dbhub",
                    "browsers", "omniroute", "lmarena",
                    "unity", "unreal", "roblox-studio", "godot", "tiktok",
                    "capcut", "spotify", "chatgpt", "codex", "cursor",
                    "claude")

    def _reg_auto_possible(self, server: mcp_registry.Server | None) -> tuple[bool, str]:
        """Можно ли настроить автоматически и что этому мешает.

        У семи старых серверов кнопка делает настройку целиком. У десяти
        мостов движков и агентов — только то, что не требует чужого
        окна: записать файл или сказать, чего не хватает. У остальных
        серверов она была бы кнопкой вроде работающей.
        """
        if server is None:
            return False, (
                "Выберите строку в списке: автонастройка есть у Android "
                "Studio, OBS, Android-эмулятора, DBHub, Браузеров, "
                "OmniRoute, LMArena и у мостов движков. У LDPlayer она не "
                "нужна — ему достаточно кнопки «Включить»."
            )
        if server.id not in self.AUTO_SERVERS:
            return False, (
                f"Автонастройки для «{server.name}» нет: сервер запускается "
                "командой, достаточно кнопки «Включить»."
            )
        return True, ""

    def _reg_auto_tip(self, server: mcp_registry.Server | None) -> str:
        """Что именно сделает кнопка у выбранной строки.

        Подсказка на кнопке, а не текст в подробностях: человек
        наводит курсор до нажатия и должен видеть, откроется ли
        чужое окно. Ни одна из этих строк его не открывает.
        """
        tips = {
            "android-studio": (
                "Поставить плагин из набора, включить сервер в студии, "
                "проверить его и вписать в настройки opencode."
            ),
            "obs": (
                "Спросить пароль, включить WebSocket-сервер OBS и вписать мост. "
                "Студию программа не открывает."
            ),
            "android-emulator": (
                "Включить отладку, подключить эмулятор по adb и вписать мост."
            ),
            "dbhub": (
                "Проверить живую связь с базой и вписать мост. Без "
                "подключения к базе скажет, что делать."
            ),
            "browsers": (
                "Открыть страницу, прочитать заголовок и вписать мост. "
                "Браузер выбирается кнопкой рядом."
            ),
            "omniroute": (
                "Развернуть мост, запустить, дождаться ответа API и вписать "
                "провайдеров."
            ),
            "lmarena": (
                "Спросить у модели ответ через арену и только потом вписать "
                "мост. Не ответила — в настройки не пишется ничего."
            ),
            "unity": (
                "Выбрать проект из найденных, прописать в него пакет "
                "MCP for Unity и вписать мост в настройки opencode. "
                "Сам пакет скачает редактор при открытии проекта: он "
                "должен быть закрыт. Редактор программа не открывает."
            ),
            "unreal": (
                "Спросить проект и порт, поставить EngineWire и вписать адрес "
                "его сервера. Node.js и npm не нужны: сервер внутри плагина. "
                "Проверяет адрес живым запросом. Редактор не открывает — без "
                "открытого Unreal с плагином мост молчит."
            ),
            "roblox-studio": (
                "Проверить mcp.bat и вписать мост в настройки opencode. "
                "Плагина нет: сервер встроенный, включается галочкой в самой "
                "студии. Студию программа не открывает."
            ),
            "godot": (
                "Принять команду attach, поставить аддон в проект и вписать "
                "мост в настройки opencode. Включение аддона — галочкой в "
                "самом Godot. Редактор не открывает."
            ),
            "tiktok": (
                "Записать токен в mcp-tiktok.txt, не в журнал и не в "
                "opencode.jsonc. Кабинет не открывает."
            ),
            "capcut": (
                "Записать твой https-адрес MCP. На capcut.com не ходит, "
                "редактор не открывает и ролик не экспортирует."
            ),
            "spotify": (
                "Записать Client ID. В аккаунт не входит и трек не включает. "
                "Нужны Premium и открытый Spotify."
            ),
            "chatgpt": (
                "Записать ключ и имя модели. На сайт chatgpt.com не ходит "
                "и живой запрос не делает."
            ),
            "codex": (
                "Проверить команду codex. Пароль не спрашивает. По умолчанию "
                "только чтение."
            ),
            "cursor": (
                "Проверить команду agent и записать ключ, если он нужен. "
                "--yolo не передаёт."
            ),
            "claude": (
                "Проверить команду claude и её версию: ограничения моста "
                "требуют 2.1.259 или новее. Вход делает человек сам, "
                "мост запускает только проверку."
            ),
        }
        if server is None:
            return "Сначала выберите строку."
        return tips.get(server.id, "Для этой строки автонастройки нет.")

    def _reg_engine_setup(self, server: mcp_registry.Server, dest: Path) -> None:
        """Записывает только свой файл и вписывает команду. Готовым не считает.

        Окно спрашивает ровно то, чего у программы нет: путь, команду или
        токен. Значение секрета ни в журнал, ни в подсказку не идёт.
        """
        note = ""
        can_write = True
        if server.id == "unity":
            can_write, note = engine_setup.unity_ready()
        elif server.id == "roblox-studio":
            can_write, note = engine_setup.roblox_ready()
        elif server.id == "claude":
            can_write, note = engine_setup.claude_ready()
        elif server.id == "codex":
            can_write, note = engine_setup.codex_ready()
        elif server.id == "cursor":
            can_write, note = engine_setup.cursor_ready()
        # Подключение моста — единственное место, где CLI ставится сама.
        # Проверки состояния выше только читают: поставить программу оттуда
        # нельзя, иначе прогон самопроверки ставил бы её на машину.
        if (not can_write and server.id in engine_setup.AUTO_INSTALL
                and engine_setup.auto_install_allowed()):
            installed, note = engine_setup.install_cli(server.id)
            can_write = installed
        dialog = EngineSetupDialog(server.id, server.name, note, can_write, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        mirror = ""
        if server.id == "unreal":
            ok, note = engine_setup.save_unreal(
                dest, dialog.project_path(), dialog.plugin_path()
            )
            port_ok, port_note = engine_setup.save_unreal_port(dest, dialog.port_value())
            if ok and not port_ok:
                ok, note = False, port_note
            elif ok and port_note:
                note = f"{note} {port_note}"
            mirror = engine_setup.UNREAL_NAME
        elif server.id == "unity":
            ok, note = engine_setup.save_project(
                dest, engine_setup.UNITY_NAME, dialog.project_path()
            )
        elif server.id == "godot":
            # Папка проекта нужна аддону, команда attach — серверу. Обе
            # части нужны, поэтому спрашиваются обе, а пишутся отдельно.
            ok_project, note_project = engine_setup.save_project(
                dest, engine_setup.GODOT_PROJECT_NAME, dialog.project_path()
            )
            ok, note = engine_setup.save_godot(dest, dialog.command_text())
            if ok and not ok_project:
                ok, note = False, note_project
            elif ok:
                note = note + " " + note_project
            mirror = engine_setup.GODOT_NAME
        elif server.id == "tiktok":
            ok, note = engine_setup.save_tiktok(
                dest, dialog.token_value(), dialog.app_id_value()
            )
            mirror = engine_setup.TIKTOK_NAME
        elif server.id == "capcut":
            ok, note = engine_setup.save_capcut(
                dest, dialog.url_value(), dialog.token_value()
            )
        elif server.id == "spotify":
            ok, note = engine_setup.save_spotify(dest, dialog.app_id_value())
            mirror = engine_setup.SPOTIFY_NAME
        elif server.id == "chatgpt":
            ok, note = engine_setup.save_chatgpt(
                dest, dialog.token_value(), dialog.model_value()
            )
            mirror = engine_setup.CHATGPT_NAME
        elif server.id == "cursor":
            ok, note = engine_setup.save_cursor(dest, dialog.token_value())
            mirror = engine_setup.CURSOR_NAME
        elif server.id in ("unity", "roblox-studio", "codex"):
            ok = can_write
        else:
            self._warn("Этот мост отсюда не настраивается.")
            return
        if not ok:
            self._warn(note)
            return
        if mirror:
            extra = engine_setup.mirror_for_launcher(dest, mirror)
            if extra:
                note = note + " " + extra
        self.log.add(note, "ok")
        # Плагин ставится отдельно и в фоне: это распаковка архива и правка
        # файлов чужой программы, а модальное окно на это время замерзает.
        if server.id in editor_plugins.HANDLERS:
            self._start_plugin_setup(server, dest)
        # Roblox — единственный мост, у которого настраивать нечего: файл
        # запуска создаёт сама студия, команда задана в реестре, отдельного
        # файла настроек нет. Кнопка проверяла, писала одну строку в журнал —
        # и всё, а человек видел «ничего не поднялось».
        elif server.id == "roblox-studio":
            self._start_enable(server, dest)

    def _start_enable(self, server: mcp_registry.Server, dest: Path) -> None:
        """Вписать мост в настройки opencode — последний шаг своей кнопки.

        Отдельный метод, а не повтор в двух местах: и Roblox, и мосты с
        плагином в конце делают одно и то же.
        """
        self._start(
            lambda progress: mcp_registry.enable(dest, server, progress=progress),
            "registry",
        )

    def _start_plugin_setup(self, server: mcp_registry.Server, dest: Path) -> None:
        """Поставить плагин моста и вписать сам мост — в фоне, одной кнопкой.

        Отдельный поток нужен по трём причинам: распаковка архива и запись в
        чужую папку занимают секунды, а модальное окно на это время не
        отвечает; результат может быть отказом, и отказ должен попасть в
        журнал текстом, а не уронить окно; и мост записывается после
        плагина, а не отдельной кнопкой — плагин без моста бесполезен, а
        мост без плагина не поднимется, и человек решал, что сломалось.
        """
        worker = Worker(self._plugin_setup_job(server, dest), self)
        worker.line.connect(lambda text, kind: self.log.add(text, kind))
        worker.finished.connect(lambda w=worker: self._plugin_setup_done(w))
        self._worker = worker
        worker.start()

    @staticmethod
    def _plugin_setup_job(server: mcp_registry.Server, dest: Path):
        """Работа для фонового потока: плагин, потом запись моста.

        Отдельным методом и без Qt — чтобы проверка могла вызвать её сама и
        убедиться, что мост действительно вписывается, а не только плагин
        ставится. Мост записывается лишь после успеха: нечего включать
        то, что не установилось.
        """
        def job(progress):
            ok, note = editor_plugins.auto_setup(server.id, progress=progress)
            messages, errors = ([], [])
            if ok:
                messages, errors = mcp_registry.enable(dest, server, progress=progress)
            return (ok, note), messages, errors
        return job

    def _plugin_setup_done(self, worker) -> None:
        """Что вышло после установки плагина и записи моста."""
        result = getattr(worker, "result", None)
        if not (isinstance(result, tuple) and len(result) == 3):
            self.log.add("Установка плагина закончилась, подробности в журнале.",
                         "ok")
            return
        (ok, note), messages, errors = result
        self.log.add(str(note), "ok" if ok else "warn")
        for line in messages:
            self.log.add(line, "ok")
        for line in errors:
            self.log.add(line, "error")
        if not ok:
            return
        if errors:
            self.log.add(
                "Плагин поставлен, но мост в настройки вписан не полностью — "
                "смотри строки выше.", "warn",
            )
        else:
            self.log.add(
                "Мост вписан в настройки opencode. Перезапусти opencode — "
                "серверы читаются при старте.", "ok",
            )

    def _reg_state_text(self, server: mcp_registry.Server) -> str:
        """Состояние для колонки. Короткое - иначе таблица разъезжается.

        Полный список требований человек видит в подробностях под
        таблицей. Здесь достаточно понять, что мешает, и то, что
        остальное не упёрлось в ту же строку понасметку.
        """
        if server.installed:
            return "включён"
        if server.id == "browsers":
            # У браузеров до выбора нечего проверять: без файла выбора
            # живая проверка возьмёт Chrome по умолчанию, а человек мог
            # хотеть Яндекс.Браузер. Честнее сказать, что ждём выбора.
            dest = self._reg_dest()
            if dest is None or not browsers.config_path(dest).is_file():
                return "нужно: выбрать браузер"
        if not server.requirements:
            return "не проверено"
        if not server.has_connection:
            return "нет команды"
        if server.missing:
            first = server.missing[0]
            rest = len(server.missing) - 1
            tail = f" и ещё {rest}" if rest > 0 else ""
            return f"не хватает: {first.what}{tail}"
        if server.id == "telegram":
            # Конфигурация проверяется чтением файла: без этого строка
            # говорила бы «можно включить» и до, и после заполнения.
            # «Готово» не пишем: действительность сессии без входа в
            # аккаунт не проверяется, и обещать её нельзя.
            dest = self._reg_dest()
            if dest is None:
                return "нужно: папка настроек"
            result = telegram_check.check(
                Path(dest) / telegram_check.FILE_NAME, Path(dest))
            return result.short()
        if server.manual_setup:
            # Конфигурацию программа в состоянии проверить может, иначе
            # строка врала бы "нужно" даже после того, как человек всё
            # вставил. А вот то, работает ли студия, - не может.
            if not self._reg_config_saved(server):
                return "нужно: конфигурация из студии"
            return "можно включить, толк не гарантирован"
        first = server.blocking_manual
        if first:
            rest = len(first) - 1
            tail = f" и ещё {rest}" if rest > 0 else ""
            return f"нужно: {first[0].what}{tail}"
        return "можно включить"

    @staticmethod
    def _reg_state_color(text: str) -> str:
        """Цвет строки состояния. Один и тот же для таблицы и подсказок."""
        low = str(text).lower()
        if low.startswith("включён") or low.startswith("можно включить"):
            return ui.OK
        if low.startswith("не проверено"):
            return ui.TEXT_DIM
        if (low.startswith("нужно") or low.startswith("не хватает")
                or "нет команды" in low):
            return ui.WARN
        return ui.TEXT

    def _reg_fit_columns(self) -> None:
        """Раздаёт ширины колонок по тому, что в них реально лежит.

        Зачем. Трижды ширины двигали вручную, и каждый раз находился
        либо обрезанный текст, либо лишняя полоса прокрутки: сумма
        ширин упирается в ширину таблицы, а строки в реестре меняются.
        Поэтому измеряем то, что написано, и выдаём каждой колонке
        ровно столько, сколько нужно, а остаток отдаём последней.

        Текст известен на этот момент - ячейки уже заполнены, поэтому
        измерять можно точно, а не гадать по длине строки.
        """
        table = self.reg_table
        if table.rowCount() <= 0:
            return
        # Последняя колонка - число инструментов. Её текст всегда
        # короткий, поэтому меряем её последней и с тем же запасом:
        # иначе при нехватке места Qt отдаёт ей остаток, и она
        # схлопывается в ноль - колонка пропадает совсем.
        raw: list[int] = []
        for col in range(table.columnCount()):
            need = 0
            for row in range(table.rowCount()):
                item = table.item(row, col)
                if item is None:
                    continue
                need = max(need, QFontMetrics(item.font())
                           .horizontalAdvance(item.text()))
            header_item = table.horizontalHeaderItem(col)
            if header_item is not None:
                need = max(need, QFontMetrics(header_item.font())
                           .horizontalAdvance(header_item.text()))
            # Имя моста бывает в целую строку («Kinocut (монтаж видео для
            # агентов: FFmpeg, субтитры, вертикалки, квитанции)»). Без
            # потолка колонка съедала всю ширину, и таблица уезжала
            # вбок; длинное имя лучше перенести на вторую строку.
            if col == 0:
                need = min(need, 240)
            # Категория и состояние — короткие слова, длиннее этой
            # подписи быть не должны: запас на перенос не нужен ни тем,
            # ни другим, а раздутая колонка грабит имя моста.
            if col == 1:
                need = min(need, 90)
            if col == 2:
                need = min(need, 120)
            # Число инструментов — всегда короткая цифра (или «—»). Текст
            # длиннее этой подписи в такое поле попасть не может: либо его
            # раздуло в реестре (было: 406 символов пояснения в «числе»
            # ghidra-mcp — колонка улетала на 2400 пикселей), либо это
            # ошибка. Не даём колонке съесть ширину всей таблицы.
            if col == 3:
                need = min(need, 110)
            raw.append(need)

        # «не проверено» — самое длинное значение колонки состояния, и
        # без запаса оно обрезалось до «не …». Запас берём у имени:
        # имя и так переносится, а состояние — нет.
        if len(raw) >= 4:
            take = min(40, max(0, raw[0] - 220))
            raw[0] -= take
            raw[1] += 10
            raw[2] += 14
            raw[3] += 10

        # Отступы делятся, а не задаются с потолка. Меряю от того,
        # что действительно есть, а не от того, что предполагаю:
        # viewport не равен ширине таблицы. На снимке получилось так,
        # что ширины в сумме 621, таблица 592 - и Qt подрезал правую
        # колонку, потому что вертикальной полосы в блоке не было,
        # а я её вычитал. Значит считать надо от реальной ширины
        # минус настоящая полоса, если она показана.
        shown = table.verticalScrollBar().isVisible()
        available = table.viewport().width()
        if shown:
            available -= table.verticalScrollBar().width()
        columns = max(1, len(raw))
        spare = available - sum(raw)
        if spare < 0:
            # Не помещается - режем отступы, но не текст: обрезанное
            # состояние хуже, чем тесные края.
            padding = 2
        else:
            padding = min(28, max(8, spare // columns))
        for col, need in enumerate(raw):
            # +6 — внутренние поля ячейки из QSS: без них заголовок
            # «Категория» обрезался до «Категори».
            if col != 3:
                table.setColumnWidth(col, need + padding + 6)
        # Последняя колонка («Инструм.») берёт остаток после трёх первых.
        # Так таблица заполняет свой просмотр на любой ширине окна без
        # горизонтальной прокрутки: числа инструментов — короткие, им
        # лишние пиксели не нужны, а имени они портят картину.
        table.horizontalHeader().setStretchLastSection(True)
        # Минимум ширины разрывает круг. Qt считает ширину таблицы как
        # сумму ширин колонок, а я считаю колонки от ширины таблицы.
        # Без этого minima Qt сжимает таблицу под блок, сумма ширин
        # остаётся прежней, проверки проходят - а последняя колонка
        # молча уезжает за край. На снимке это выглядело как
        # обрезанный заголовок «Инструм.». Проверено: с минимумом
        # таблица рисуется целиком, без него - обрезается.
        #
        # Но минимум не шире просмотра вкладки: страница по ширине не
        # прокручивается, и при узком окне таблица с минимумом 750+
        # раздвигала её — на 680x560 страница не помещалась на 195
        # пикселей, а правый край таблицы просто обрезался, и
        # доскроллить до последних колонок было нельзя. Уступаем:
        # таблица сжимается до просмотра, и её собственная полоса
        # прокрутки (ScrollBarAsNeeded) отдаёт остальное человеку.
        total = sum(table.columnWidth(c)
                    for c in range(table.columnCount())) + 4
        # 80 пикселей - поля страницы, рамка и поля блока вокруг таблицы:
        # их минимум тоже входит в минимум раскладки страницы.
        limit = self.viewport().width() - 80
        if limit >= 240 and total > limit:
            total = limit
        table.setMinimumWidth(total)

    def _reg_visible(self) -> list[mcp_registry.Server]:
        """Серверы после поиска и фильтра категории, по алфавиту.

        Порядок алфавитный, а не как в реестре: при семидесяти с лишним
        мостах искать «Spotify» глазами в случайном порядке бессмысленно.
        Фильтр идёт по имени, id, лицензии, категории, описанию и
        способу установки — то есть по всему, что человек помнит.
        """
        query = self._reg_query.strip().lower()
        group = self._reg_group
        out: list[mcp_registry.Server] = []
        for server in self.reg_servers:
            category = mcp_categories.group_of(server.id)
            if group and category != group:
                continue
            if query:
                raw = server.raw if isinstance(server.raw, dict) else {}
                haystack = " ".join((
                    server.name, server.id, server.license,
                    mcp_categories.title(category),
                    str(raw.get("why") or ""),
                    str(raw.get("install") or ""),
                    str(raw.get("requires") or ""),
                )).lower()
                if query not in haystack:
                    continue
            out.append(server)
        out.sort(key=lambda item: item.name.lower())
        return out

    def _reg_update_counter(self) -> None:
        """Строка «показано N из M» — иначе фильтр молчит о себе."""
        total = len(self.reg_servers)
        shown = len(self._reg_shown)
        parts = [f"Показано {shown} из {total}"]
        if self._reg_group:
            parts.append("категория: " + mcp_categories.title(self._reg_group))
        if self._reg_query.strip():
            parts.append(f"поиск: «{self._reg_query.strip()}»")
        self.reg_counter.setText(" · ".join(parts))

    def _reg_apply_filter(self, text: str) -> None:
        """Поиск по мере набора: перерисовать список и ничего не трогать."""
        self._reg_query = str(text or "")
        self._reg_paint()

    def set_bridge_category(self, group_id: str) -> None:
        """Категория из подменю сайдбара. Пустая строка — все мосты."""
        self._reg_group = str(group_id or "")
        self._reg_paint()

    def bridge_category(self) -> str:
        """Какая категория выбрана сейчас (для подсветки в сайдбаре)."""
        return self._reg_group

    def _reg_paint(self) -> None:
        servers = self._reg_visible()
        self._reg_shown = servers
        self.reg_table.setRowCount(len(servers))
        for row, server in enumerate(servers):
            category = mcp_categories.short_title(
                mcp_categories.group_of(server.id))
            self.reg_table.setItem(row, 0, QTableWidgetItem(server.name))
            self.reg_table.setItem(row, 1, QTableWidgetItem(category))
            state_text = self._reg_state_text(server)
            state_item = QTableWidgetItem(state_text)
            # Цвет состояния — единственный цветной текст в таблице:
            # зелёный «включён», жёлтый «нужно…», серый «не проверено».
            state_item.setForeground(QColor(self._reg_state_color(state_text)))
            self.reg_table.setItem(row, 2, state_item)
            tools_text = str(server.tools_count or "").strip()
            tools_item = QTableWidgetItem(tools_text or "—")
            if server.tools_note and tools_item.text() != "—":
                tools_item.setToolTip(server.tools_note)
            if not tools_text:
                tools_item.setForeground(QColor(ui.TEXT_DIM))
                tools_item.setToolTip(
                    "Число инструментов появится после проверки сервера")
            self.reg_table.setItem(row, 3, tools_item)
        self._reg_update_counter()
        self._reg_fit_columns()
        self._reg_fit_table_height()
        if servers and self.reg_table.currentRow() < 0:
            self.reg_table.setCurrentCell(0, 0)
        self._reg_show_detail()

    def _reg_fit_table_height(self) -> None:
        """Высота таблицы — по числу серверов, чтобы были видны все.

        Раньше высота была ограничена 190 пикселями, и при двенадцати
        серверах в блок влезало пять с половиной строк: список крутился
        внутри самого блока, половина серверов не была видна без
        прокрутки в этом крутике, а сам блок выглядел недоделанным —
        пустое место под таблицей и обрезанная строка на краю.
        """
        table = self.reg_table
        if table.rowCount() <= 0:
            return
        table.resizeRowsToContents()
        header = table.horizontalHeader().height()
        body = sum(table.rowHeight(row) for row in range(table.rowCount()))
        needed = header + body + 2 * table.frameWidth() + 2
        table.setMinimumHeight(needed)
        table.setMaximumHeight(needed)

    def _reg_current(self) -> mcp_registry.Server | None:
        row = self.reg_table.currentRow()
        if 0 <= row < len(self._reg_shown):
            return self._reg_shown[row]
        return None

    def _reg_show_detail(self) -> None:
        server = self._reg_current()
        # Кнопка жива только там, где у неё есть настоящее действие.
        # Для остальных строк нажатие было бы враньём, поэтому гасим
        # её, а не ждём ошибки по нажатию.
        possible, _ = self._reg_auto_possible(server)
        self.btn_reg_auto.setEnabled(possible)
        self.btn_reg_auto.setToolTip(self._reg_auto_tip(server))
        # Кнопки подключений — только у DBHub: больше ни один сервер
        # не ходит в базы, и «Добавить подключение» у него означало бы
        # пустую кнопку.
        is_db = server is not None and server.id == "dbhub"
        self.btn_db_add.setEnabled(is_db)
        self.btn_db_check.setEnabled(
            is_db and bool(dbhub.read_sources(self._reg_dest() or Path()))
        )
        # Кнопки браузеров — только у своей строки: у остальных серверов
        # выбирать нечего, они запускаются командой.
        is_br = server is not None and server.id == "browsers"
        self.btn_br_choose.setEnabled(is_br)
        self.btn_br_check.setEnabled(is_br)
        # Кнопки OmniRoute — только у своей строки: у остальных серверов
        # разворачивать, запускать и перезапускать нечего.
        is_or = server is not None and server.id == "omniroute"
        self.btn_or_deploy.setEnabled(is_or)
        self.btn_or_start.setEnabled(is_or)
        self.btn_or_restart.setEnabled(is_or)
        self.btn_or_status.setEnabled(is_or)
        self.btn_or_open.setEnabled(is_or)
        # Кнопки LMArena — только у своей строки: у остальных серверов нет
        # ни окружения форка, ни токена арены.
        is_lm = server is not None and server.id == "lmarena"
        self.btn_lm_deploy.setEnabled(is_lm)
        self.btn_lm_start.setEnabled(is_lm)
        self.btn_lm_restart.setEnabled(is_lm)
        self.btn_lm_status.setEnabled(is_lm)
        self.btn_lm_token.setEnabled(is_lm)
        if is_db:
            sources = dbhub.read_sources(self._reg_dest() or Path())
            if sources:
                names = ", ".join(s.id for s in sources)
                self.reg_hint.setText(
                    f"Подключения DBHub: {names}. «Проверить соединение» "
                    "поднимает сервер и спрашивает протоколом, отвечает ли "
                    "база. «Настроить автоматически» делает то же и вписывает "
                    "сервер в настройки opencode."
                )
            else:
                self.reg_hint.setText(
                    "Подключений к базам пока нет: у DBHub без них нечего "
                    "проверять и нечего включать. Начни с «Добавить подключение»."
                )
        elif is_br:
            dest = self._reg_dest() or Path()
            choice = browsers.read_choice(dest)
            chosen = browsers.config_path(dest).is_file()
            head = ("Выбрано: " + browsers.description(choice) + ". "
                    if chosen else
                    "Браузер ещё не выбран: пока не выберешь, проверять "
                    "нечего. ")
            self.reg_hint.setText(
                head
                + "«Проверить браузер» открывает страницу и читает заголовок — "
                "это и есть доказательство, что браузер работает. «Настроить "
                "автоматически» делает то же и вписывает сервер в настройки "
                "opencode."
            )
        elif is_lm:
            token = ("токен арены уже вписан" if lmarena.token_present(
                self._reg_dest() or Path()) else
                "токена арены пока нет — без него моделей не будет")
            self.reg_hint.setText(
                "Порядок: «Развернуть» (окружение моста и зависимости), "
                "«Обновить токен» (кука arena-auth-prod-v1 с сайта арены — "
                f"{token}), «Запустить» (мост на http://127.0.0.1:8000), "
                "«Показать статус», затем «Настроить автоматически»: она "
                "спросит у модели ответ и только потом впишет мост и "
                "провайдера с моделями арены в настройки opencode. Мост "
                "выключен по умолчанию и включается после предупреждений."
            )
        elif is_or:
            self.reg_hint.setText(
                "Порядок: «Развернуть» (пакет из npm в папку моста), "
                "«Запустить» (панель и API на http://127.0.0.1:20128), "
                "«Открыть панель» (тот же адрес в браузере — только при "
                "живом сервере), «Показать статус», затем «Настроить "
                "автоматически»: она подключит бесплатных провайдеров без "
                "ключа и впишет мост в настройки opencode. Что-то зависнет "
                "— «Перезапустить». Обновить версию — во вкладке "
                "«Обновление», блок «Мост OmniRoute»."
            )
        elif server is not None and server.id == "telegram":
            # Подробности проверки конфигурации: человек видит, чего не
            # хватает, ещё до включения. Значения не печатаются — только
            # имена полей. «Готово» не пишем: сессия не проверялась.
            dest = self._reg_dest()
            if dest is None:
                self.reg_hint.setText(
                    "Папка настроек opencode не выбрана — проверять "
                    "конфигурацию негде."
                )
            else:
                result = telegram_check.check(
                    Path(dest) / telegram_check.FILE_NAME, Path(dest))
                head = {
                    telegram_check.MISSING: "Конфигурация не готова",
                    telegram_check.BAD_FORMAT:
                        "Формат конфигурации неверный",
                    telegram_check.PARTIAL:
                        "Имя сессии допустимо, содержимое не проверялось",
                    telegram_check.FORMAT_OK:
                        "Формат верный, сессия не проверялась",
                }[result.level]
                parts = [head + "."]
                if result.problems:
                    parts.append(" ".join(f"• {item};"
                                          for item in result.problems))
                if result.notes:
                    parts.append(" ".join(result.notes))
                parts.append(
                    "Проверка только читает файл: ни сети, ни входа в "
                    "аккаунт, ни вывода значений."
                )
                self.reg_hint.setText(" ".join(parts))
        else:
            self.reg_hint.clear()
        if server is None:
            self.reg_detail.setPlainText("Выберите сервер, чтобы увидеть подробности.")
            return
        raw = server.raw
        lines = [f"{server.name} — {server.license}"]
        conn = raw.get("connection") or {}
        target = conn.get("url") or " ".join(conn.get("command") or [])
        if target:
            lines.append(f"Команда: {target}")
        if server.id == "browsers":
            # Что именно запустится — видно прямо здесь: браузер, профиль и
            # окно живут в файле выбора, и без этой строки человек не понял
            # бы, что уйдёт в npx.
            dest = self._reg_dest() or Path()
            choice = browsers.read_choice(dest)
            br = browsers.browser(choice.browser)
            lines.append("")
            lines.append(f"Выбрано: {browsers.description(choice)}")
            lines.append("Запуск: " + " ".join(browsers.command(dest, choice)))
            lines.append(f"Профиль: {browsers.profile_dir(dest, br.key)}")
            lines.append(browsers.hint(br.key, choice))
        # Нужные версии сервера и плагина — прямо здесь, а не внутри кода:
        # расхождение между ними выглядит как «мост сломан», и человек
        # должен видеть, какие версии задуманы, ещё до установки.
        _need = bridge_versions.for_bridge(server.id)
        if _need.known:
            lines.append("")
            lines.append("Что нужно этому мосту:")
            for _line in _need.lines():
                lines.append(f"  {_line}")
        else:
            lines.append("")
            lines.append(_need.note)
        if server.id == "omniroute":
            # Состояние моста словами: развёрнут ли, отвечает ли API,
            # какая версия и сколько провайдеров. Здесь же адрес панели:
            # куда идти человеку за ключами провайдеров.
            dest = self._reg_dest() or Path()
            lines.append("")
            lines.append(omniroute.status_text(dest))
            lines.append(f"Панель и API: http://{omniroute.DEFAULT_HOST}:{omniroute.DEFAULT_PORT}")
            lines.append(f"Папка данных: {omniroute.data_dir(dest)}")
            lines.append(
                "Ключи провайдеров лежат в папке данных и в настройки "
                "opencode не попадают."
            )
        if raw.get("why"):
            lines.append("")
            lines.append(str(raw["why"]))
        for key, title in (
            ("exclusive_access", "Особенность"),
            ("telemetry", "Телеметрия"),
            ("auth", "Вход"),
        ):
            if raw.get(key):
                lines.append("")
                lines.append(f"{title}: {raw[key]}")
        if raw.get("requires"):
            lines.append("")
            lines.append("Требуется:")
            for req in raw["requires"]:
                lines.append(f"  • {req.get('what')}"
                             + (f" — {req['note']}" if req.get("note") else ""))
        if raw.get("safety"):
            lines.append("")
            lines.append(f"Безопасность: {raw['safety']}")

        # Шаги показываем всем, у кого они есть, а не только серверу
        # с ручной конфигурацией. Иначе OBS, эмулятор и десять новых
        # мостов молчали, хотя текст в реестре уже лежал.
        steps = server.setup_steps
        if steps:
            lines.append("")
            lines.append("Как настроить — по шагам:")
            for index, step in enumerate(steps, start=1):
                lines.append(f"  {index}. {step}")
        if server.manual_setup and raw.get("only_while_running"):
            lines.append("")
            lines.append(
                f"Пока студия закрыта: {raw['only_while_running']}"
            )
        if raw.get("ready_here_note") and not server.ready_here:
            lines.append("")
            lines.append(f"Сейчас: {raw['ready_here_note']}")

        if raw.get("verdict"):
            lines.append("")
            lines.append(f"Итог: {raw['verdict']}")
        lines.append("")
        lines.append(f"Источник: {server.source}")
        self.reg_detail.setPlainText("\n".join(lines))
        self._reg_fit_detail_height()

    def _reg_fit_detail_height(self) -> None:
        """Высота поля описания — под сам текст, а не под старый минимум.

        Поле было ограничено 120 пикселями, а описание сервера занимает
        больше: текст обрывался на полуслове, и последняя строка
        читалась как «...действия откажут» без конца.

        Высоту текста у Qt здесь взять нечем: document.size() у этого поля
        отдаёт не пиксели, а число строк, и даже после отрисовки, поэтому
        перенос меряем сами по метрикам шрифта. Считаем по словам, а не
        делением длины на ширину, — иначе длинное слово «разъехалось» бы
        на две строки и поле выросло бы лишнего.
        """
        box = self.reg_detail
        width = box.viewport().width()
        if width < 50:
            return
        metrics = box.fontMetrics()
        lines = 0
        for paragraph in box.toPlainText().split("\n"):
            words = paragraph.split()
            if not words:
                lines += 1
                continue
            current = 0
            for word in words:
                advance = metrics.horizontalAdvance(word)
                if current and current + 1 + advance > width:
                    lines += 1
                    current = advance
                else:
                    current += advance + (1 if current else 0)
            lines += 1
        # Запас сверх расчёта: наш перенос по словам чуть занижает реальный —
        # Qt переносит ещё и по границам символов в длинных кусках вроде
        # команды npm. Лучше лишние двадцать процентов пустоты внизу, чем
        # обрезанная последняя строка и полоса прокрутки.
        needed = int(lines * metrics.lineSpacing() * 1.2) + 2 * box.frameWidth() + 10
        # Нижняя граница: короткое описание не должно оставлять под
        # собой пустоту — на пустое место в этом блоке и жаловались.
        needed = max(needed, 150)
        box.setMinimumHeight(needed)
        box.setMaximumHeight(needed)

    def _reg_bulk_reason(self, server: mcp_registry.Server) -> str:
        """Что мешает включить сервер вместе со всеми. Пусто — можно.

        Правила те же, что и у кнопки «Включить» для одной строки: часть
        серверов перед записью обязана что-то спросить или проверить
        живьём. Пропускать их молча нельзя — человек потом не поймёт,
        почему сервер из списка не включился.
        """
        if server.manual_setup:
            return ("нужен выбор — программа спросит его сама, "
                    "поэтому в общий список он не входит")
        if server.id == "dbhub":
            return ("нужна живая проверка связи с базой: выбери его строку "
                    "и нажми «Включить»")
        if server.id == "lmarena":
            return ("нужен токен арены и ответ модели: выбери его строку "
                    "и нажми «Настроить автоматически»")
        return ""

    def _reg_disable_all(self) -> None:
        """Отключает все мосты разом, вместе с мостами памяти базы.

        Действие общее и необратимое без копии, поэтому сначала вопрос с
        прямым перечислением того, что пропадёт. Молча отключить память
        было бы хуже, чем не отключать вовсе: человек узнал бы об этом
        по тому, что его забыло.
        """
        dest = self._reg_dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        question = (
            "Из настроек opencode уйдут ВСЕ серверы — вместе с мостами "
            "памяти базы ncp и pc.\n\n"
            "Пока их не включат заново, перестанут работать: память базы, "
            "навыки, агенты и чтение компьютера.\n\n"
            "Копия настроек будет сделана до записи, вернуть можно из неё. "
            "Отключить?"
        )
        answer = QMessageBox.question(
            self,
            "Отключить все мосты?",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def job(progress):
            return mcp_registry.disable_all(dest)

        self._start(job, "registry")

    def _reg_enable_all(self) -> None:
        """Включает вместе все серверы, где для этого не надо ничего спрашивать."""
        dest = self._reg_dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        base = self._reg_base()
        if base is None:
            self._warn("Не выбрана папка базы с реестром.")
            return

        def job(progress):
            servers = mcp_registry.load_servers(base)
            mcp_registry.mark_installed(servers, dest)
            self.reg_servers = servers
            enabled: list[str] = []
            skipped: list[str] = []
            errors: list[str] = []
            for server in servers:
                reason = self._reg_bulk_reason(server)
                if reason:
                    skipped.append(f"пропущен {server.name}: {reason}")
                    continue
                try:
                    _messages, errs = mcp_registry.enable(
                        dest, server, progress=progress)
                except Exception as exc:  # noqa: BLE001 — сервер не должен ронять всех
                    errors.append(f"{server.name}: {exc}")
                    continue
                if errs:
                    errors.append(f"{server.name}: " + "; ".join(errs))
                    continue
                if server.installed:
                    enabled.append(f"{server.name}: уже был включён")
                else:
                    enabled.append(f"{server.name}: включён")
            self._reg_paint()
            lines = [f"Готово: {len(enabled)} из {len(servers)}."]
            lines += enabled
            if skipped:
                lines.append("Не тронуты (нужно решение человека):")
                lines += skipped
            lines.append("Перезапусти opencode, чтобы он подхватил изменения.")
            return lines, errors

        self._start(job, "registry")

    def _reg_check_all(self) -> None:
        """Живая проверка требований. Идёт в фоне: запускает программы."""
        base = self._reg_base()
        dest = self._reg_dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return

        def job(progress):
            servers = mcp_registry.load_servers(base)
            mcp_registry.mark_installed(servers, dest)
            self.reg_servers = servers
            self._reg_paint()
            messages: list[str] = []
            for server in servers:
                state = self._reg_state_text(server)
                messages.append(f"{server.name}: {state}")
            return messages, []

        self._start(job, "registry")

    def _reg_enable(self) -> None:
        dest = self._reg_dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        server = self._reg_current()
        if server is None:
            self._warn("Выберите сервер в списке.")
            return

        # CapCut — удалённый адрес. Общее окно «скопируй из студии» ему
        # врёт: адрес MCP даёт хост, а не редактор.
        if server.id == "capcut":
            self._reg_engine_setup(server, dest)
            return

        # Сервер, который включается внутри другой программы, сначала
        # спрашивает конфигурацию. Без неё запись в настройки была бы
        # враньём: блок без токена заведомо не подключится.
        if server.manual_setup:
            self._reg_ask_config(server, dest)
            return

        # DBHub без подключения к базе — блок, которому нечего отдавать,
        # а с нерабочей базой — блок, который opencode будет ждать 30
        # секунд и покажет «Не удалось». Поэтому у него «Включить» идёт
        # тем же путём, что автонастройка: сначала живая проверка связи,
        # и только потом запись.
        if server.id == "dbhub":
            self._reg_auto()
            return

        # У моста LMArena «Включить» идёт тем же путём, что автонастройка:
        # без токена арены и ответа модели блок в настройках был бы
        # нерабочим, а сам мост включается только после предупреждений.
        if server.id == "lmarena":
            self._reg_auto()
            return

        # Файл моста программа умеет проверить сама. Без него команда
        # впишется, а лаунчер сразу откажется. Спрашиваем, не молчим.
        gap = engine_setup.gap(dest, server.id) if server.id in engine_setup.IDS else ""
        if gap:
            answer = QMessageBox.question(
                self,
                "Лаунчер откажется",
                gap + "\n\nОткрыть настройку вместо простого включения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._reg_engine_setup(server, dest)
                return

        def job(progress):
            return mcp_registry.enable(dest, server, progress=progress)

        self._start(job, "registry")

    def _db_add_source(self) -> None:
        """Вписывает подключение к базе в файл DBHub.

        Подключение — не настройка opencode, а отдельный файл рядом с
        ними. Поэтому он живёт не в кнопке «Включить», а в своей:
        вписать базу можно и до включения сервера, и для второй базы.
        """
        dest = self._reg_dest()
        server = self._reg_current()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        if server is None or server.id != "dbhub":
            self._warn("Подключения к базам есть только у DBHub. "
                       "Выберите его строку в списке.")
            return

        dialog = DbhubConnectionDialog(dest, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for line in dialog.messages:
            self.log.add(line, "ok")
        self.log.add(
            "Дальше — «Проверить соединение»: живая проверка скажет, "
            "отвечает ли база, до записи в настройки opencode.", "ok"
        )
        self._reg_show_detail()

    def _db_check(self) -> None:
        """Живая проверка связи с базами DBHub.

        Настоящий разговор с сервером по протоколу MCP: сервер поднимает
        сама программа, отвечает он или нет — видно по ответу, а не по
        тому, что порт занят. Ничего не записывает.
        """
        dest = self._reg_dest()
        server = self._reg_current()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        if server is None or server.id != "dbhub":
            self._warn("Проверять связь с базой умеет только DBHub. "
                       "Выберите его строку в списке.")
            return
        sources = dbhub.read_sources(dest)
        if not sources:
            self._warn("Подключений нет. Нажми «Добавить подключение» "
                       "и впиши базу.")
            return

        def job(progress):
            return dbhub.check_connection(dest, sources, progress=progress)

        self._start(job, "dbhub")

    def _br_choose(self) -> None:
        """Выбор браузера, профиля и окна для моста Playwright MCP.

        Выбор ложится отдельным файлом рядом с настройками opencode, а не
        в них самих: сменить браузер можно, не трогая настройки opencode.
        """
        dest = self._reg_dest()
        server = self._reg_current()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        if server is None or server.id != "browsers":
            self._warn("Выбирать браузер можно только у строки «Браузеры». "
                       "Выберите её в списке.")
            return

        dialog = BrowserChoiceDialog(dest, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for line in dialog.messages:
            self.log.add(line, "ok")
        self._reg_show_detail()

    def _br_check(self) -> None:
        """Живая проверка браузера.

        Поднимает мост и открывает страницу выбранным браузером: сервер
        отвечает, страница открылась, заголовок прочитан. Ничего не
        записывает — только говорит, работает ли выбранный браузер.
        """
        dest = self._reg_dest()
        server = self._reg_current()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        if server is None or server.id != "browsers":
            self._warn("Проверять браузер можно только у строки «Браузеры». "
                       "Выберите её в списке.")
            return
        if not browsers.config_path(dest).is_file():
            self._warn("Браузер ещё не выбран. Нажми «Выбрать браузер», "
                       "иначе проверять нечего.")
            return
        choice = browsers.read_choice(dest)

        def job(progress):
            return browsers.check_connection(dest, choice, progress=progress)

        self._start(job, "browsers")

    def _or_target(self) -> Path | None:
        """Папка настроек и строка OmniRoute — общая проверка для кнопок.

        Четыре кнопки моста делают разное, но требование у них одно:
        выбрана папка настроек opencode и выделена строка «OmniRoute».
        Иначе нажатие было бы враньём — оно трогало бы чужую строку.
        """
        dest = self._reg_dest()
        server = self._reg_current()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return None
        if server is None or server.id != "omniroute":
            self._warn("Это работа строки «OmniRoute». Выберите её в списке.")
            return None
        return dest

    def _or_deploy(self) -> None:
        """Разворачивает OmniRoute в папку моста. В opencode не пишет."""
        dest = self._or_target()
        if dest is None:
            return

        def job(progress):
            return omniroute.deploy(progress=progress)

        self._start(job, "omniroute")

    def _or_start(self) -> None:
        """Поднимает сервер, ждёт ответа API и подключает бесплатных.

        В opencode не пишет. Провайдеры подключаются здесь же, потому что
        каталог бесплатных у новой версии мог измениться, а человек про
        второй шаг помнить не должен.
        """
        dest = self._or_target()
        if dest is None:
            return

        def job(progress):
            return omniroute.bring_up(dest, progress=progress)

        self._start(job, "omniroute")

    def _or_restart(self) -> None:
        """Перезапускает сервер и заново подключает бесплатных провайдеров.

        Так же лечится зависший или упавший мост. Каталог бесплатных
        провайдеров читается заново, поэтому изменившийся список
        подхватывается сам.
        """
        dest = self._or_target()
        if dest is None:
            return

        def job(progress):
            return omniroute.restart(dest, progress=progress)

        self._start(job, "omniroute")

    def _or_status(self) -> None:
        """Показывает состояние моста словами: ничего не меняет."""
        dest = self._or_target()
        if dest is None:
            return
        text = omniroute.status_text(dest)
        self.log.clear_log()
        self.log.add(text, "ok" if "отвечает" in text else "warn")
        # Подробности под таблицей обновляются тем же текстом: там его
        # видно, не открывая журнал.
        self._reg_show_detail()

    def _or_open_panel(self) -> None:
        """Открывает локальную панель OmniRoute в браузере.

        Сначала живая проверка, и только потом открытие: при выключенном
        сервере человек увидел бы страницу с ошибкой подключения и
        решил, что программа сломалась. Открывает `ui.open_link`, а не
        `webbrowser.open` — тот запускает внешнюю программу, а программа
        работает на pythonw, и на экране появилось бы чёрное окно.
        """
        dest = self._or_target()
        if dest is None:
            return
        ok, note = omniroute.panel_ready(dest)
        if not ok:
            self.log.clear_log()
            self.log.add(note, "warn")
            return
        url = omniroute.panel_url()
        opened = ui.open_link(url)
        self.log.clear_log()
        self.log.add(note, "ok")
        if not opened:
            self.log.add(
                "Браузер не взял адрес — открой его сам: " + url, "warn")
        self._reg_show_detail()

    def _lm_target(self) -> Path | None:
        """Папка настроек и строка LMArena — общая проверка для кнопок.

        Пять кнопок моста делают разное, но требование у них одно:
        выбрана папка настроек opencode и выделена строка «LMArena».
        Иначе нажатие трогало бы чужую строку.
        """
        dest = self._reg_dest()
        server = self._reg_current()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return None
        if server is None or server.id != "lmarena":
            self._warn("Это работа строки «LMArena». Выберите её в списке.")
            return None
        return dest

    def _lm_confirm(self) -> bool:
        """Спрашивает согласие на работу через веб-сервис арены.

        Мост выключен по умолчанию, поэтому согласие спрашивается перед
        каждым включением: один раз прочитанное предупреждение не должно
        превращаться в «я когда-то нажал галочку».
        """
        dialog = LmarenaWarningDialog(self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _lm_deploy(self) -> None:
        """Ставит окружение моста и зависимости. В opencode не пишет."""
        dest = self._lm_target()
        if dest is None:
            return

        def job(progress):
            return lmarena.deploy(progress=progress)

        self._start(job, "lmarena")

    def _lm_start(self) -> None:
        """Поднимает мост и ждёт ответа API. В opencode ничего не пишет."""
        dest = self._lm_target()
        if dest is None or not self._lm_confirm():
            return

        def job(progress):
            return lmarena.bring_up(dest, progress=progress)

        self._start(job, "lmarena")

    def _lm_restart(self) -> None:
        """Перезапускает мост: так лечится зависший и подхватывается токен."""
        dest = self._lm_target()
        if dest is None or not self._lm_confirm():
            return

        def job(progress):
            return lmarena.restart(dest, progress=progress)

        self._start(job, "lmarena")

    def _lm_status(self) -> None:
        """Показывает состояние моста словами: ничего не меняет."""
        dest = self._lm_target()
        if dest is None:
            return
        text = lmarena.status_text(dest)
        self.log.clear_log()
        self.log.add(text, "ok" if "отвечает" in text else "warn")
        self._reg_show_detail()

    def _lm_token(self) -> None:
        """Спрашивает свежий токен арены и кладёт его рядом с настройками.

        Мост читает токен только из своего config.json, поэтому после
        сохранения предлагается перезапуск: список моделей мост тянет с
        арены на старте и раз в полчаса, а не по каждому запросу.
        """
        dest = self._lm_target()
        if dest is None:
            return
        dialog = LmarenaTokenDialog(dest, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for line in dialog.messages:
            self.log.add(line, "ok")
        if lmarena.deployed() and lmarena.health(dest, timeout=3)[0]:
            answer = QMessageBox.question(
                self,
                "Мост уже запущен",
                "Токен сохранён. Мост уже запущен — перезапустить его "
                "сейчас, чтобы он сразу взял новый токен и перечитал "
                "список моделей с арены?\n\nЭто то же, что кнопка "
                "«Перезапустить».",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._lm_restart()
        self._reg_show_detail()

    def _reg_auto(self) -> None:
        """Настраивает сервер целиком, без конфигураций вручную.

        Автонастройка умеет Android Studio, OBS, эмулятор, DBHub, браузеры,
        OmniRoute и LMArena. У DBHub она упирается в подключение: без
        вписанной базы проверять нечего, поэтому сначала предлагается
        «Добавить подключение». У OmniRoute порядок другой: развернуть,
        запустить, получить ответ API — и только потом писать в настройки.
        У LMArena так же, но проверка строже: живой ответ модели через
        арену. Не ответила — в настройки не пишется ничего.
        """
        dest = self._reg_dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        server = self._reg_current()
        possible, why = self._reg_auto_possible(server)
        if not possible or server is None:
            self._warn(why)
            return

        # Мосты движков и агентов настраиваются не здесь: у них нет
        # своего файла конфигурации, их настройка — это окно с одним
        # вопросом. Всё, что можно сделать без чужого окна, делает оно.
        if server.id in engine_setup.IDS:
            self._reg_engine_setup(server, dest)
            return

        # Ключ реестра с путём установки OBS. Без него студия не знает,
        # где установлена, и падает с ошибкой про языковой файл, хотя
        # файл на месте. Запись в реестр — внешнее действие, поэтому
        # спрашиваем отдельно и по умолчанию отвечаем «нет».
        fix_install_path = False
        # У OBS пароль спрашивается отдельно: его негде взять, кроме
        # самого человека или генератора программы.
        password = ""
        if server.id == "obs":
            trouble = bridges.obs_install_problem()
            if trouble:
                answer = QMessageBox.question(
                    self,
                    "OBS не знает, где установлена",
                    trouble
                    + "\n\nСоздать ключ реестра HKCU\\Software\\OBSStudio "
                      "с путём установки? Запись делается только для "
                      "текущего пользователя и ничего не удаляет.",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self._warn(trouble)
                    return
                fix_install_path = True
            password = self._ask_obs_password(dest)
            if password is None:
                return

        # Мост LMArena спрашивает согласие каждый раз: он работает через
        # веб-сервис арены, и «я согласился когда-то раньше» тут не годится.
        if server.id == "lmarena" and not self._lm_confirm():
            return

        def job(progress):
            if server.id == "android-studio":
                return android_studio.auto_setup(dest, server, progress=progress)
            if server.id == "obs":
                return bridges.auto_setup_obs(
                    dest, server, password, progress=progress,
                    allow_install_path_fix=fix_install_path)
            if server.id == "dbhub":
                return dbhub.auto_setup(dest, server, progress=progress)
            if server.id == "browsers":
                return browsers.auto_setup(dest, server, progress=progress)
            if server.id == "omniroute":
                return omniroute.auto_setup(dest, server, progress=progress)
            if server.id == "lmarena":
                return lmarena.auto_setup(dest, server, progress=progress)
            if server.id in editor_plugins.HANDLERS:
                # Мост с плагином (Ghidra и подобные): окно настроек у него
                # своего нет, ставить плагин умеет модуль редакторов.
                return editor_plugins.auto_setup(server.id, progress=progress), []
            return bridges.auto_setup_emulator(dest, server, progress=progress)

        self._start(job, "registry")

    def _ask_obs_password(self, dest: Path) -> str | None:
        """Спрашивает пароль OBS: показать, сгенерировать, вписать свой.

        None означает «человек закрыл окно» — тогда ничего не делаем.
        """
        current = bridges.read_password(dest)
        dialog = ObsPasswordDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        password = dialog.password()
        if not password:
            self._warn("Пароль пустой. Мост без него не подключится.")
            return None
        if dialog.save_path():
            ok, note = bridges.copy_password_to(dest, dialog.save_path())
            if ok:
                self.log.add(note, "ok")
            else:
                self._warn(note)
                return None
        return password

    def _reg_ask_config(self, server: mcp_registry.Server, dest: Path) -> None:
        """Спрашивает конфигурацию и, если её дали, включает сервер."""
        import json

        saved = mcp_registry.load_manual_config(dest, server.id)
        dialog = ManualConfigDialog(server, self)
        if saved:
            # Показать прошлую, чтобы человек мог её поправить, а не
            # искать заново. Токен в поле виден целиком, и это правильно:
            # человек должен видеть, что именно попадёт в настройки.
            # Спрятать его было бы удобнее программе и хуже человеку.
            text = json.dumps(
                {"mcpServers": {server.id: saved}}, ensure_ascii=False, indent=2
            )
            dialog.text.setPlainText(text)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ok, note = mcp_registry.save_manual_config(
            dest, server.id, dialog.config_text()
        )
        if not ok:
            self._warn(note)
            return

        def job(progress):
            return mcp_registry.enable(dest, server, progress=progress)

        self._start(job, "registry")

    def _reg_disable(self) -> None:
        dest = self._reg_dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
            return
        server = self._reg_current()
        if server is None:
            self._warn("Выберите сервер в списке.")
            return

        def job(progress):
            return mcp_registry.disable(dest, server)

        self._start(job, "registry")

    def _reg_open_source(self) -> None:
        server = self._reg_current()
        if server is None or not server.source:
            self._warn("У этого сервера нет источника в реестре.")
            return
        # Ссылка из реестра, а не пользовательский ввод: всё равно
        # показываем, что открываем, и ждём подтверждения.
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Открыть источник?")
        box.setText(f"Открыть в браузере?\n\n{server.source}")
        box.setStandardButtons(
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel
        )
        if box.exec() != QMessageBox.StandardButton.Open:
            return
        import webbrowser  # локальный импорт: нужен только здесь

        try:
            webbrowser.open(server.source)
        except Exception as exc:  # noqa: BLE001
            self._warn(f"Не открылось: {exc}")

    # ---- состояние

    def _selection(self) -> set[str]:
        # Мосты ПК и NCP — часть базы, а не расширение: у них нет галочки
        # и они подставляются всегда. Иначе можно было бы снять память,
        # не понимая, что происходит.
        picked = {name for name, box in self.checks.items() if box.isChecked()}
        picked |= set(self._chosen_caps_agents())
        return picked | set(opencode_caps.CAPS_ALWAYS)

    def _pselection(self) -> set[str]:
        return {name for name, box in self.pchecks.items() if box.isChecked()}

    def _antiblock_opts(self) -> dict[str, bool]:
        """Галочки шага 4 — состав набора обхода блокировок."""
        return {key: box.isChecked() for key, box in self.achecks.items()}

    def _refresh_ab_state(self) -> None:
        """Строка состояния обхода: свой канал, запасной пул или тишина.

        Обновляется при открытии секции и после кнопок проверки. Две
        проверки локальных портов стоят почти ноль: закрытый порт падает
        с отказом сразу, а не по таймауту, поэтому ждать не приходится и
        поток не нужен — так же сделано и для кнопки DNS.
        """
        item = getattr(self, "lbl_ab_state", None)
        if item is None:
            return
        try:
            import antiblock  # noqa: PLC0415 — рядом лежит

            state, text = antiblock.channel_state()
            color = {
                antiblock.CHANNEL_OWN: ui.OK,
                antiblock.CHANNEL_FALLBACK: ui.WARN,
            }.get(state, ui.ERROR)
        except Exception as exc:  # noqa: BLE001 — строка не должна ронять окно
            text, color = f"проверка не запустилась: {exc}", ui.ERROR
        item.setText(f"Обход: {text}")
        item.setStyleSheet(f"color: {color};")

    def _save_ab_port(self) -> None:
        """Кнопка «Сохранить»: записать порт фасада.

        Занятый порт не сохраняем. Иначе настройка останется в файле и
        обнаружится только при следующем запуске обхода — когда фасад не
        поднимется. Здесь человек ещё может выбрать другой.
        """
        import antiblock as _ab  # noqa: PLC0415 — рядом лежит

        value = self.spin_ab_port.value()
        why = _ab.port_error(value)
        if why:
            self.log.add(f"Порт не сохранён: {why}.", "warn")
            return
        if _ab._port_listening(_ab.FACADE_HOST, value):
            owner = _ab.who_listens(value) or "неизвестным процессом"
            free = _ab.suggest_free_port(value)
            tip = (f"Свободный рядом: {free}. Впишите его и сохраните ещё раз."
                   if free else "Свободного порта рядом не нашлось.")
            self.log.add(
                f"Порт {value} занят ({owner}). Не сохранён. {tip}", "warn")
            return
        previous = _ab.facade_port()
        ok, msg = _ab.set_facade_port(value)
        self.log.add(msg, "ok" if ok else "warn")
        if ok and previous != value and _ab._port_listening(
                _ab.FACADE_HOST, previous):
            self.log.add(
                f"Фасад сейчас работает на {previous}. Новый порт вступит в "
                "силу после перезапуска обхода.", "warn")
        self.spin_ab_port.setValue(_ab.facade_port())
        self._refresh_ab_state()

    def _check_antiblock(self) -> None:
        """Кнопка «Проверить подключение»: слушает ли фасад свой порт."""
        try:
            import antiblock  # noqa: PLC0415 — рядом лежит

            ok, text = antiblock.check_connection()
        except Exception as exc:
            ok, text = False, f"Проверка не запустилась: {exc}"
        self.log.add(text, "ok" if ok else "warn")
        self._refresh_ab_state()

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
        self._refresh_ab_state()

    # ---- навыки поштучно

    def _fill_caps_skills(self) -> None:
        """Список навыков базы: все отмечены, как при подключении."""
        self.caps_skills_list.blockSignals(True)
        self.caps_skills_list.clear()
        for skill in core.list_skills(self._base()):
            desc = skill["description"]
            text = core.skill_item_text(skill)
            row = QListWidgetItem(text)
            row.setData(1000, skill["name"])
            row.setToolTip(desc or skill["title"])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)
            self.caps_skills_list.addItem(row)
        self.caps_skills_list.blockSignals(False)
        self._caps_skills_changed()
        fit_skills_height(self.caps_skills_list)

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

    def _check_skill_updates(self) -> None:
        """Проверить, не появилось ли нового у авторов наших скилов.

        Идёт в сеть и в рабочий поток: двадцать скилов — это двадцать
        запросов, по 0,3 секунды пауза между ними, и на это нужны
        секунды. Главный поток при этом свободен, окно не «отвечает».
        """
        import skill_sources

        base = self._base()

        def job(progress):
            rows, errors = skill_sources.check_updates(base, progress)
            # Результат кладём на вкладку: диалог покажет именно его, а
            # не результат повторного запроса из обработчика.
            self._skill_check_rows = rows
            lines = [f"{r['skill']}: {r['state']}" + (
                f" ({r['date']})" if r["date"] else "") for r in rows]
            return lines, errors

        self._start(job, "skills-check")

    def _skill_update_report(self, rows: list) -> None:
        """Диалог по итогам проверки: у кого появилось и как это смотреть."""
        import skill_sources

        if not rows:
            self._warn("Проверять нечего: список источников пуст.")
            return
        behind = [r for r in rows if r["state"] == skill_sources.ST_BEHIND]
        fresh = [r for r in rows if r["state"] == skill_sources.ST_FRESH]
        unknown = [r for r in rows if r["state"] == skill_sources.ST_UNKNOWN]
        offline = [r for r in rows if r["state"] == skill_sources.ST_NO_NET]

        parts = []
        if behind:
            parts.append("У авторов появилось: " + ", ".join(
                r["skill"] for r in behind))
        if fresh:
            parts.append(f"Совпадает с авторским: {len(fresh)}.")
        if unknown:
            parts.append("Источник неизвестен, проверка в следующий раз: "
                         + ", ".join(r["skill"] for r in unknown))
        if offline:
            parts.append("Не проверилось (нет сети или адрес отвергнут): "
                         + ", ".join(r["skill"] for r in offline))
        parts.append("")
        parts.append("Ничего не обновлено: наши скилы — переводы, и "
                     "оригинал автора затёр бы перевод. Открой разницу "
                     "и переводи сам.")

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Обновления скилов")
        dialog.setText("\n".join(parts))
        if behind:
            names = "\n".join(r["skill"] for r in behind)
            box = QVBoxLayout()
            chooser = QComboBox()
            chooser.addItems(names.split("\n"))
            show = QPushButton("Посмотреть разницу")
            take = QPushButton("Взять оригинал автора")

            def _show():
                src = next((r for r in behind if r["skill"] == chooser.currentText()),
                           None)
                if src is None:
                    return
                theirs = skill_sources.fetch_original(src)
                if not theirs:
                    self._warn("Оригинал не скачался: нет сети или папка "
                               "называется иначе.")
                    return
                ours = skill_sources.local_skill_text(self._base(), src["skill"])
                lines = skill_sources.diff_lines(ours, theirs)
                dlg = QMessageBox(self)
                dlg.setWindowTitle(f"Разница: {src['skill']}")
                dlg.setText("Слева наш перевод, справа оригинал автора.\n"
                            "Перевод не тронут.")
                dlg.setDetailedText("\n".join(lines[:400]))
                dlg.exec()

            def _take():
                src = next((r for r in behind if r["skill"] == chooser.currentText()),
                           None)
                if src is None:
                    return
                theirs = skill_sources.fetch_original(src)
                if not theirs:
                    self._warn("Оригинал не скачался.")
                    return
                folder = core.current_base("opencode") / "skills" / src["skill"]
                path = skill_sources.save_original(folder, theirs)
                if path is None:
                    self._warn("Не удалось записать оригинал.")
                    return
                self.log.add(f"Оригинал {src['skill']} сохранён: {path}", "ok")
                dialog.close()

            show.clicked.connect(_show)
            take.clicked.connect(_take)
            box.addWidget(chooser)
            row = QHBoxLayout()
            row.addWidget(show)
            row.addWidget(take)
            box.addLayout(row)
            holder = QWidget()
            holder.setLayout(box)
            dialog.setInformativeText("Выбери скил:")
            holder.setParent(dialog)
            holder.setVisible(True)
            holder.move(dialog.width() - 220, dialog.height() - 80)
            holder.raise_()
        dialog.exec()

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
        """Показать, что уже стоит, — не замораживая окно.

        Здесь всё живое: caps_status и providers_status читают настройки,
        rtk/caveman/pxpipe/auto-improve/greenlight/qwen_review зовут
        внешние программы, а pxpipe ещё и стучится в сеть. На этой
        машине такая проверка занимает 3.4 секунды, и раньше она шла
        прямо в потоке окна сразу после показа — интерфейс замирал
        ровно в тот момент, когда человек начинал им пользоваться
        (замерено 22.10.2026: сборка 8.6 с, потом ещё 3.4 с ступора).

        Теперь сбор состояния идёт в Worker, а окно тем временем живёт.
        Подпись честно говорит, что идёт проверка, и меняется, когда
        ответ готов.
        """
        dest = self._dest()
        if dest is None or not dest.is_dir():
            self.state_hint.setStyleSheet(f"color: {ui.WARN};")
            self.state_hint.setText("Папки пока нет — при установке будет создана.")
            return
        self.state_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
        self.state_hint.setText("Смотрим, что уже стоит…")
        worker = Worker(lambda _progress: self._status_work(dest))
        self._status_worker = worker
        worker.finished.connect(lambda: self._status_finished(worker))
        worker.start()

    def _status_work(self, dest: Path) -> tuple[list[str], list[str], str]:
        """Собрать состояние возможностей — без виджетов, для Worker.

        Возвращает (что уже стоит, строки-пояснения, текст ошибки).
        Ни одного обращения к окну: только файлы, внешние программы и
        сеть, поэтому звать это можно из другого потока.
        """
        try:
            status = opencode_caps.caps_status(dest)
            pstatus = opencode_caps.providers_status(dest)
        except Exception as exc:  # noqa: BLE001 — причину покажем в окне
            return [], [], str(exc)
        # Подпись берём по цепочке: TITLES → список возможностей → само имя.
        # Раньше здесь стояло TITLES[n] прямой подстановкой, и новая
        # возможность, которой в TITLES нет, роняла окно: исключение из слота
        # PyQt проглатывает и закрывает программу. Найдено 15.10.2026.
        inside = [self._cap_title(n) for n in status if status[n]]
        inside += [title for name, (title, _k, _b) in opencode_caps.PROVIDER_PRESETS.items()
                   if pstatus.get(name)]
        # Строка про rtk и caveman — отдельно от «уже стоит». Без неё
        # галочка «rtk» выглядела бы рабочей, хотя без бинарника в PATH она
        # ничего не впишет: программа обязана сказать это до нажатия.
        try:
            data = rtk.status(dest)
        except Exception:
            data = {}
        try:
            cword = str(caveman.status(dest).get("word") or "")
        except Exception:
            cword = ""
        notes: list[str] = []
        if data:
            if data.get("binary"):
                notes.append(
                    "rtk: программа найдена"
                    + (f" ({data['version']})" if data.get("version") else "")
                    + "."
                )
            else:
                notes.append(
                    "rtk: программа не найдена в PATH — включение ничего не "
                    "впишет, пока она не поставлена по README автора."
                )
        notes.append(
            "caveman: сейчас уровень «" + (cword or "лёгкий")
            + "», галочка выберет тот, что стоит в списке."
        )
        # Строка про pxpipe: без запущенного прокси галочка ничего не
        # впишет, и сказать об этом надо до нажатия, а не после.
        try:
            px = pxpipe.status(dest)
        except Exception:
            px = {}
        if px:
            where = str(px.get("upstream") or "")
            if px.get("running"):
                notes.append(
                    "pxpipe: прокси отвечает"
                    + (f" и пересылает запросы к {where}" if where else "")
                    + ("." if px.get("ours") else " (запущен не программой).")
                )
            else:
                notes.append(
                    "pxpipe: прокси не отвечает — пока он не запущен, "
                    "включение ничего не впишет в настройки."
                )
        # Строка про auto-improve: цикл не пойдёт без ключа, git и requests,
        # и сказать об этом надо до нажатия, а не после.
        try:
            ai = auto_improve.check(dest)
        except Exception:
            ai = {}
        try:
            ai_tags = auto_improve.seen_tags(dest)
        except Exception:
            ai_tags = []
        if ai:
            if ai.get("ready"):
                notes.append(
                    "auto-improve: готов к запуску, "
                    + auto_improve.key_status(dest)
                    + (f"; ход: {len(ai_tags)}" if ai_tags else "")
                    + "."
                )
            else:
                notes.append(
                    "auto-improve: не готов — "
                    + "; ".join(ai.get("missing") or []) + "."
                )
        # Строка про greenlight: не собран, нет Go или копия разошлась — об
        # этом надо сказать до нажатия, а не после.
        try:
            gl = greenlight.check(dest)
        except Exception:
            gl = {}
        if gl:
            if gl.get("ready"):
                notes.append(f"greenlight: готов, {gl.get('version')}.")
            else:
                reason = "не собран" if not gl.get("binary") else "не отвечает"
                where = ("Go не найден — собрать нечем." if not gl.get("go")
                         else "Go найден: собери командой greenlight.py build.")
                notes.append(f"greenlight: {reason}. {where}")
        # Строка про второго ревьюера: без развёрнутого qwen и выбранной
        # модели проверка не пойдёт — сказать об этом до нажатия.
        try:
            qw = qwen_review.check(dest)
        except Exception:
            qw = {}
        if qw:
            if qw.get("ready"):
                notes.append(f"Qwen Code: ревьюер готов, {qw.get('version')}.")
            else:
                selection = qw.get("selection") or {}
                if not qw.get("binary"):
                    notes.append("Qwen Code: не развёрнут — настрой работает скиллом qwen-review-setup.")
                elif not selection.get("model"):
                    notes.append("Qwen Code: модель ревьюера не выбрана — настрой через скилл.")
                else:
                    notes.append("Qwen Code: ревьюер не готов — " + "; ".join(
                        (qw.get("missing") or ["смотри строку ниже"])[:1]) + ".")
        return inside, notes, ""

    def _status_finished(self, worker: Worker) -> None:
        """Показать собранное состояние. Старое выполнение — мимо.

        За время проверки мог прийти новый вызов (после установки, из
        «Обновить»), и его слово главнее: результат устаревшего потока
        человеку уже не нужен.
        """
        if getattr(self, "_status_worker", None) is not worker:
            return
        self._status_worker = None
        if isinstance(worker.result, Exception):
            self.state_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.state_hint.setText(f"Не прочиталось: {worker.result}")
            return
        inside, notes, error = worker.result
        if error:
            self.state_hint.setStyleSheet(f"color: {ui.ERROR};")
            self.state_hint.setText(f"Не прочиталось: {error}")
            return
        if inside:
            self.state_hint.setStyleSheet(f"color: {ui.OK};")
            text = "Уже стоит:\n- " + "\n- ".join(inside)
        else:
            self.state_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            text = "Наших возможностей здесь пока нет."
        self.state_hint.setText(text + "\n" + "\n".join(notes))
        # Кнопка запуска ревьюера живёт по галочке, а не по результату
        # проверки: включать её здесь — значит гасить кнопку каждый раз,
        # когда qwen не развёрнут, хотя человек её только что отметил.
        self.btn_qw_run.setEnabled(bool(self.checks["qwen-review"].isChecked()))

    # ---- выбор папки

    def _cap_title(self, name: str) -> str:
        """Подпись возможности: TITLES, иначе список, иначе само имя.

        Агенты приходят с именами вида `agent:имя`, их в TITLES нет — значит,
        подпись берётся из списка возможностей, где она уже собрана из
        реестра агентов.
        """
        title = self.TITLES.get(name)
        if title:
            return title
        for cap_name, cap_title in opencode_caps.CAPS_CHOICES:
            if cap_name == name:
                return cap_title
        return name

    def _chosen_caps_agents(self) -> list[str]:
        """Отмеченные агенты в виде возможностей `agent:имя`."""
        names: list[str] = []
        for index in range(self.caps_agents_list.count()):
            row = self.caps_agents_list.item(index)
            if row.checkState() == Qt.CheckState.Checked:
                names.append(str(row.data(1000)))
        return names

    def _set_all_caps_agents(self, on: bool) -> None:
        """Отметить всех или снять всех — как у списка навыков."""
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.caps_agents_list.blockSignals(True)
        for index in range(self.caps_agents_list.count()):
            self.caps_agents_list.item(index).setCheckState(state)
        self.caps_agents_list.blockSignals(False)
        self._caps_agents_changed()

    def _caps_agents_changed(self) -> None:
        """Подпись под списком: сколько отмечено и что будет поставлено."""
        total = self.caps_agents_list.count()
        chosen = len(self._chosen_caps_agents())
        if total == 0:
            self.caps_agents_hint.setStyleSheet(f"color: {ui.TEXT_DIM};")
            self.caps_agents_hint.setText("Агентов нет — нечего ставить.")
            return
        self.caps_agents_hint.setStyleSheet("")
        self.caps_agents_hint.setText(
            f"Отмечено {chosen} из {total}. Файлы кладутся в папку agents "
            "рядом с настройками opencode.")

    def _pick_dest(self) -> None:
        start = self.dest_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Папка настроек opencode", start
        )
        if chosen:
            self.dest_edit.setText(chosen)

    # ---- уведомления Windows о завершении фоновой работы

    #: Что показывать в уведомлении при успехе. Короткое: во всплывающем
    #: сообщении Windows длинный текст всё равно обрезается.
    JOBS = {
        "registry": ("Проверка мостов закончена",
                     "Проверили серверы MCP — подробности в журнале"),
        "auto": ("Автоматическая настройка закончена",
                 "Мосты настроены — подробности в журнале"),
    }

    def _notify(self, title: str, text: str) -> None:
        """Отправить уведомление окну программы — оно разошлёт его в трей."""
        window = self.window()
        notify = getattr(window, "notify", None)
        if callable(notify):
            notify(title, text)

    def _notify_done(self, messages: list[str], errors: list[str]) -> None:
        """Сообщить, что фоновая работа закончилась.

        Пока идёт проверка или развёртывание, окно обычно свёрнуто. Если
        сообщения не будет, человек не узнает, что всё готово, и будет
        ждать впустую.
        """
        title, text = self.JOBS.get(self._what, ("Готово", "Работа завершена"))
        if errors:
            self._notify(f"{title}: есть замечания",
                         f"Замечаний: {len(errors)}. Подробности в журнале")
        elif messages:
            self._notify(title, str(messages[-1]).strip()[:90] or text)

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
            self._notify(f"{self._what}: прервано", str(result)[:90])
            return
        messages, errors = result
        # Строки, которые работа уже выдала в журнал через `progress`,
        # повторно не добавляем. Иначе всё, что печаталось по ходу
        # дела, дублируется в конце: кнопка «Развернуть» у OmniRoute
        # показывала «Ставлю OmniRoute…» и «развёрнут» по два раза
        # (измерено 19.10.2026). Работа при этом выполнялась один раз —
        # дублировался только текст, и человек решал, что программа
        # ставит пакет дважды.
        shown = self.log.toPlainText() if hasattr(self.log, "toPlainText") else ""
        for line in messages:
            if not line or line in shown:
                continue
            self.log.add(line, "ok")
            shown += line + "\n"
        if errors:
            self.log.add("Готово, но с замечаниями:", "warn")
            for line in errors:
                self.log.add(f"  {line}", "error")
        else:
            self.log.add("Готово.", "ok")
        self._notify_done(messages, errors)
        self._refresh()
        # Включение и выключение сервера меняют его состояние в таблице.
        # Перечитываем здесь, в главном потоке: из рабочего потока трогать
        # виджеты нельзя, а признак «включён» надо ставить по факту
        # записанного блока, а не по факту нажатия кнопки.
        if self._what == "registry":
            reg_dest = self._reg_dest()
            if reg_dest is not None:
                mcp_registry.mark_installed(self.reg_servers, reg_dest)
                self._reg_paint()
        elif self._what == "skills-check":
            # Отчёт по скилам показываем диалогом: в журнале строки
            # «у автора появилось» легко пролистать, а человек пришёл
            # сюда за ответом. Результат берём из работы, а не проверяем
            # заново: повторный запрос — это двадцать обращений в сеть
            # впустую и, что хуже, возможно другой ответ.
            rows = getattr(self, "_skill_check_rows", None)
            if rows:
                self._skill_update_report(rows)

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
        # Уровень caveman и провайдера pxpipe выбирать больше негде: выбор
        # уехал в скиллы вместе с карточками. Поэтому уровень берётся из
        # модуля (по умолчанию лёгкий), а провайдер не задаётся — pxpipe
        # возьмёт его из данных запущенного прокси, и это правильнее списка
        # в окне: так источник совпадает с тем, куда реально уходят запросы.
        level = caveman.DEFAULT_LEVEL
        px_source = ""

        def job(progress):
            m1, e1 = ([], [])
            m2, e2 = ([], [])
            if selection:
                m1, e1 = opencode_caps.install_caps(
                    base, dest, selection, progress=progress,
                    antiblock_opts=self._antiblock_opts(),
                    caveman_level=level,
                    pxpipe_provider=px_source,
                )
            if pselection:
                # У LMArena блок провайдера собирается из живого моста:
                # имена моделей называет арена, и выдумать их нельзя. Мост
                # молчит — пропускаем его и говорим словами, а не пишем
                # провайдера без моделей.
                chosen = set(pselection)
                blocks: dict[str, str] = {}
                lm_names: list[str] = []
                if "lmarena" in chosen:
                    names, note = lmarena.chat_models(dest)
                    if names:
                        lm_names = names
                        blocks["lmarena"] = lmarena.provider_block(names)
                    else:
                        chosen.discard("lmarena")
                        e2.append(
                            "LMArena пропущен: модели моста не прочитались ("
                            + (note or "список пуст")
                            + "). Запусти мост и обнови токен — тогда "
                            "список моделей подставится сам."
                        )
                if chosen:
                    m2, e2 = opencode_caps.install_providers(
                        dest, chosen, progress=progress, blocks=blocks)
                    m2 = list(m2)
                    if "lmarena" in chosen:
                        m2.append(
                            f"Провайдер LMArena вписан с моделями арены: "
                            f"{len(lm_names)}."
                        )
                else:
                    m2 = []
            return (m1 + m2, e1 + e2)

        self._start(job, "install")


    def _ai_toggled(self, on: bool) -> None:
        """Галочка auto-improve ставит и снимает плагин.

        Сам цикл улучшения уехал в скилл auto-improve: кнопок в этом окне
        больше нет. Галочка ничего не блокирует и ничего не запускает.
        """
        if on:
            self.log.add(
                "auto-improve отмечен. Цикл тратит токены и коммитит в ветку "
                "improve/<тег> — запускай на копии проекта или в отдельной ветке.",
                "warn",
            )

    def _gl_toggled(self, on: bool) -> None:
        """Галочка greenlight ставит и снимает плагин.

        Сам сканер уехал в скилл greenlight: кнопок в этом окне больше нет.
        Облачная проверка вдобавок требует отдельного подтверждения — про
        это сказано и в журнале, и в скилле.
        """
        if on:
            self.log.add(
                "greenlight отмечен. Проверка «preflight» и «список проверок» "
                "идут офлайн; «Проверка в облаке Revyl» отправит сценарии в "
                "сторонний сервис — для неё спрашивается отдельное "
                "подтверждение.",
                "warn",
            )

    def _qw_toggled(self, on: bool) -> None:
        """Галочка qwen-review разрешает проверку изменений и спор.

        Сама галочка ничего не запускает: она лишь открывает кнопки. Режим
        «спор» — отдельный переключатель, и он тоже выключен по умолчанию.
        """
        for name in ("btn_qw_run", "qw_debate", "qw_rounds", "btn_qw_forget"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(bool(on))
        if not on:
            box = getattr(self, "qw_debate", None)
            if box is not None and box.isChecked():
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)
            self._qw_debate_toggled(False)
        else:
            self.log.add(
                "Qwen Code — второй ревьюер отмечен. Ревьюер файлы не правит, "
                "но код изменений уходит выбранному провайдеру. "
                + qwen_review.COST_WARNING,
                "warn",
            )
            self._qw_debate_toggled(self.qw_debate.isChecked())

    def _qw_debate_toggled(self, on: bool) -> None:
        """«Спор» — отдельный выключатель: без него раундов не будет.

        Состояние галочки переводится в режим из общего списка
        qwen_review.MODES по полю flag и запоминается в _qw_mode_id:
        не хардкодом, а из данных.
        """
        self._qw_mode_id = qwen_review.mode_from_flag(bool(on))
        button = getattr(self, "btn_qw_reply", None)
        if button is not None:
            enabled = bool(on) and bool(self.checks.get("qwen-review") is not None
                                        and self.checks["qwen-review"].isChecked())
            button.setEnabled(enabled)
        if on:
            self.log.add(qwen_review.DEBATE_WARNING, "warn")

    def _qw_dest(self) -> Path | None:
        """Папка настроек для кнопок ревьюера. None — не выбрана."""
        dest = self._dest()
        if dest is None:
            self._warn("Не выбрана папка настроек opencode.")
        return dest

    def _qw_mask_reason(self, text: str, provider_id: str = "") -> str:
        """Вычищает ключ из чужого текста перед показом в окне.

        Причины ошибок приходят от провайдеров, и те любят цитировать
        присланный ключ целиком. check_provider_models чистит причины
        уже в рабочем потоке, но здесь последний рубеж: маскируется
        всё, что попало в окно, — и причины, и заметки. Маскируется
        ключом ИМЕННО того провайдера, чей результат рисуем: если
        передан provider_id (проверявшийся), берём его, а не «выбранный
        в окне» — с выбором в окне теперь работает не оно, а скилл.
        """
        text = str(text or "")
        dest = self._dest()
        provider = str(provider_id or "")
        if not dest or not provider:
            return text
        try:
            key, _source = qwen_review.provider_key_info(dest, provider)
        except Exception:  # noqa: BLE001 — чужие настройки не должны ронять окно
            return text
        if not key:
            return text
        return qwen_review.mask_text(text, key)

    # ---- проверка доступности моделей провайдера

    def _qw_render_check(self, results, notes=(), from_cache: bool = False,
                         provider_id: str = "") -> None:
        """Рисует состояния моделей. Сети здесь нет: что передано — то и показ.

        Результаты — {модель: (состояние, причина)}: ✔ отвечает, ✘ точно
        нет, ? не знаю. Каждая причина перед показом проходит через
        маску ключа — того провайдера, чей это результат, а не того,
        кто сейчас выбран. Список виден, только когда есть что показывать.
        """
        self.qw_check_list.clear()
        shown = 0
        for model in sorted(results):
            state, reason = results[model]
            symbol = qwen_review.CHECK_SYMBOL.get(str(state), "?")
            reason = self._qw_mask_reason(reason, provider_id)
            line = f"{symbol} {model}" + (f" — {reason}" if reason else "")
            item = QListWidgetItem(line)
            # Полная строка — в подсказке: список узкий, и по ширине
            # длинную причину он переносит, но подпись в строке может
            # всё равно не влезть — тогда она хотя бы в подсказке.
            item.setToolTip(line)
            self.qw_check_list.addItem(item)
            shown += 1
        self.qw_check_list.setVisible(shown > 0)
        parts = [str(note) for note in notes]
        if from_cache:
            parts.insert(0, f"Показан кэш проверки "
                            f"({qwen_review.CHECK_CACHE_HOURS} ч): живая "
                            f"проверка — по кнопке, сейчас по API не били.")
        self.qw_check_progress.setText(" ".join(parts))

    def _qw_show_cached(self) -> None:
        """Кэш проверки (24 ч) — без сети, с пометкой «из кэша».

        Читается в GUI-потоке: это чтение своего файла, не запрос к
        провайдеру. Пока идёт живая проверка, кэш не перерисовывается,
        чтобы не затирать живой прогресс.
        """
        if getattr(self, "_qw_check_worker", None) is not None:
            return
        dest = self._dest()
        provider = str((qwen_review.chosen(dest) or {}).get("provider") or "")
        results = {}
        if dest and provider:
            try:
                results = qwen_review.cached_states(dest, provider)
            except Exception:  # noqa: BLE001
                results = {}
        self._qw_render_check(results, from_cache=bool(results))

    def _qw_check_models(self) -> None:
        """Запускает проверку моделей в отдельном потоке.

        Сам обработчик сети не касается: он только собирает выбор
        провайдера и стартует QwenCheckModels. Кнопка гаснет до конца
        проверки — второе нажатие не может удвоить расход токенов.
        """
        dest = self._qw_dest()
        if dest is None:
            return
        provider = str((qwen_review.chosen(dest) or {}).get("provider") or "")
        if not provider:
            self._warn(
                "Не выбран провайдер: проверять доступность нечего. "
                "Провайдеры берутся из настроек opencode — настрой выбор "
                "через скилл: «настрой ревьюера»."
            )
            return
        self.btn_qw_check_models.setEnabled(False)
        self.qw_check_progress.setText("Проверяю доступность моделей…")
        self._qw_check_worker = QwenCheckModels(dest, provider, self)
        self._qw_check_worker.progress.connect(self._qw_check_models_progress)
        self._qw_check_worker.finished.connect(self._qw_check_models_done)
        self._qw_check_worker.start()

    def _qw_check_models_progress(self, text: str) -> None:
        """Прогресс из рабочего потока: «Проверено X из Y»."""
        self.qw_check_progress.setText(text)

    def _qw_check_models_done(self) -> None:
        """Проверка кончилась: включаем кнопку и рисуем результат."""
        self.btn_qw_check_models.setEnabled(True)
        worker = self._qw_check_worker
        self._qw_check_worker = None
        provider_id = str(getattr(worker, "_provider", "") if worker else "")
        result = worker.result if worker is not None else None
        if isinstance(result, Exception):
            self.qw_check_progress.setText(
                "Проверка прервалась: "
                + self._qw_mask_reason(str(result), provider_id))
            return
        results, notes = result
        notes = [self._qw_mask_reason(note, provider_id) for note in notes]
        # Рисуем маской того провайдера, которого проверял воркер: у него
        # берём и provider_id, чтобы маска была чужого не касалась.
        self._qw_render_check(
            results, notes, provider_id=provider_id)

    def _qw_run(self) -> None:
        """Проверяет изменения вторым ревьюером. Только чтение."""
        dest = self._qw_dest()
        if dest is None:
            return
        if not self.checks["qwen-review"].isChecked():
            self._warn(
                "Сначала отметь галочку «Qwen Code — второй ревьюер»: "
                "по умолчанию ревьюер выключен."
            )
            return
        dialog = QwenReviewDialog(self)
        # Начальное значение комбо режима — режим вкладки: галочка «спор»
        # включена → спор, снята → одна проверка. Человек поправит сам,
        # если ему нужно тройное ревью.
        _default_mode = qwen_review.mode_from_flag(self.qw_debate.isChecked())
        _i = dialog.mode.findData(_default_mode)
        if _i >= 0:
            dialog.mode.setCurrentIndex(_i)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        rounds = int(self.qw_rounds.value())
        mode = str(values.get("mode") or qwen_review.MODE_ONCE)
        if mode == qwen_review.MODE_DEBATE:
            answer = QMessageBox.question(
                self, "Ревьюер и спор",
                qwen_review.COST_WARNING + "\n\n" + qwen_review.DEBATE_WARNING
                + f"\n\nРаундов разрешено: {rounds}. Продолжить?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        if mode == qwen_review.MODE_VOTE:
            # Тройное ревью: три модели из панели, один diff, свод с
            # метками «кого заметили двое/трое». Пустая панель — отказ
            # словами, а не пустой запуск: ревью не тратится ни секунды.
            def job(progress):
                return qwen_review.review_vote(
                    dest, Path(values["project"]), values["base"],
                    progress=progress,
                )
        else:
            def job(progress):
                return qwen_review.review(
                    dest, Path(values["project"]), values["base"],
                    rounds=rounds, progress=progress,
                )

        self._start(job, "Qwen Code")

    def _qw_reply(self) -> None:
        """Следующий раунд спора: возражение уходит ревьюеру."""
        dest = self._qw_dest()
        if dest is None:
            return
        if not (self.checks["qwen-review"].isChecked()
                and qwen_review.mode_from_flag(self.qw_debate.isChecked())
                == qwen_review.MODE_DEBATE):
            self._warn(
                "Спор выключен: отметь галочку qwen-review и переключатель "
                "«спор», иначе раундов не будет."
            )
            return
        state = qwen_review.debate_state(dest)
        if not state.get("transcript"):
            self._warn(
                "Спора пока не было: сначала нажми «Проверить изменения…» — "
                "первое ревью и есть первый раунд."
            )
            return
        limit = int(self.qw_rounds.value())
        dialog = QwenReplyDialog(
            int(state.get("round") or 0) + 1, limit, str(state.get("project") or ""), self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reply = dialog.values()
        project = str(state.get("project") or "")
        base = str(state.get("base") or "")

        def job(progress):
            return qwen_review.review(
                dest, Path(project), base, reply=reply, rounds=limit,
                progress=progress,
            )

        self._start(job, "Qwen Code")

    def _qw_forget(self) -> None:
        """Забывает ход спора: счёт раундов начнётся заново."""
        dest = self._qw_dest()
        if dest is None:
            return
        if not self.checks["qwen-review"].isChecked():
            self._warn("Сначала отметь галочку «Qwen Code — второй ревьюер».")
            return

        def job(progress):
            return qwen_review.clear_debate(dest)

        self._start(job, "Qwen Code")

    def _qw_setup(self) -> None:
        """Окно фраз-триггеров: что сказать агенту для настройки ревьюера.

        Сама настройка — скилл qwen-review-setup за пределами окна. Здесь
        только подсказка: фразы, которые человек вставляет агенту.
        """
        dialog = QwenSetupDialog(self)
        dialog.exec()

    def _px_confirm(self) -> bool:
        """Спрашивает согласие на сжатие запросов картинками.

        Галочка снята по умолчанию, поэтому согласие спрашивается и при
        её включении, и перед каждым запуском прокси: один раз прочитанное
        предупреждение не должно превращаться в «я когда-то согласился».
        """
        dialog = PxpipeWarningDialog(self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _px_toggled(self, on: bool) -> None:
        """Галочка pxpipe включается только после согласия.

        Выключению согласие не нужно: отказаться должно быть всегда можно.
        """
        if not on:
            return
        if self._px_confirm():
            return
        box = self.checks.get("pxpipe")
        if box is not None:
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self.log.add("pxpipe остался выключен: согласие не дано.", "warn")

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


# ------------------------------------------------------------- вкладка «Программы»


#: Цвет заголовка состояния по самому состоянию. Три состояния — три цвета,
#: и четвёртого не бывает: программа либо стоит, либо нет, либо «нечем
#: проверять». Придумывать оттенок для четвёртого состояния нельзя, его
#: просто не существует.
_STATE_COLOR = {
    program_cards.STATE_OK: ui.OK,
    program_cards.STATE_MISSING: ui.WARN,
    program_cards.STATE_UNKNOWN: ui.TEXT_DIM,
}


class ProgramsTab(ScrollPage):
    """Программы, без которых мосты не работают: карточки, кнопки, состояние.

    Этап 5 раздела 7 плана. Вкладка **ничего не знает сама**: карточки
    приходят из `program_cards`, который читает реестр, а установку
    запускает `winget_install`. Здесь только вид и реакция на кнопки.

    У кнопки установки три честных ограничения, все три видны человеку:

    * **прав администратора вкладка не берёт сама.** Реестр помечает
      Blender и Adobe как `needs_admin`, но окно UAC не должно всплывать
      неожиданно (раздел 14.5 плана). Если winget упрётся в права, кнопка
      скажет об этом и даст готовую команду с `--scope machine`;
    * **сверка подписи не блокирует установку.** Файла установщика у нас
      нет, сверять нечего. Пакет ставит winget: он сверяет **хеш**
      установщика с манифестом своего источника, но подписанта
      (`expected_signer`) не сверяет — такого механизма у него нет. Наша
      сверка нужна, когда файл попадает к нам, то есть позже. Требовать
      её сейчас значило бы заблокировать кнопку навсегда;
    * **после установки состояние перечитывается по-настоящему**, а не
      считается успехом по коду возврата. winget местами возвращает 0,
      не сделав ничего.
    """

    def __init__(self, parent=None) -> None:
        self._worker: Worker | None = None
        self._cards: dict[str, program_cards.Card] = {}
        self._rows: dict[str, dict] = {}
        # Что сказать в строке результата после перерисовки. Без этого
        # итог установки пропал бы: перерисовка идёт сразу после неё и
        # стирает всё написанное, а человек увидел бы пустую строку
        # там, где должен узнать, что произошло.
        self._messages: dict[str, str] = {}
        # Категория из подменю и строка поиска. Пустые — показать всё.
        self._prog_group = ""
        self._prog_query = ""
        self._prog_all: list = []
        self._prog_placed: dict = {}
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)
        self.reload()

    # ---- сборка окна

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        outer.addWidget(ui.label("Программы", kind="title"))
        # Короткая строка вместо абзаца: длинный серый текст сверху
        # никто не читает. Полное объяснение — в подсказке у значка.
        intro = QHBoxLayout()
        intro.setSpacing(6)
        intro.addWidget(
            ui.label("Карточки из реестра: что стоит и чего не хватает.",
                     kind="dim", wrap=True),
            1,
        )
        info = QLabel("ⓘ")
        info.setObjectName("infoDot")
        info.setToolTip(
            "Здесь то, без чего мосты работать не будут. Карточки строятся "
            "из реестра: отдельного списка программ нет, иначе он сразу "
            "разошёлся бы с тем, что на самом деле стоит."
        )
        intro.addWidget(info)
        outer.addLayout(intro)

        # Полоса общих замечаний. Сюда попадает и «данные поехали», и
        # «winget на машине нет» — обе вещи человек обязан увидеть до
        # того, как начнёт нажимать кнопки.
        self.notice = ui.label("", kind="dim", wrap=True)
        outer.addWidget(self.notice)

        # Поиск и перепроверка — в одной строке над карточками.
        search_row = QHBoxLayout()
        self.prog_search = QLineEdit()
        self.prog_search.setPlaceholderText("Поиск программ: имя или категория…")
        self.prog_search.setClearButtonEnabled(True)
        self.prog_search.textChanged.connect(self._prog_apply_filter)
        search_row.addWidget(self.prog_search, 1)
        self.btn_reload = QPushButton("Перепроверить всё")
        self.btn_reload.clicked.connect(self.reload)
        search_row.addWidget(self.btn_reload)
        outer.addLayout(search_row)
        self.prog_counter = ui.label("", kind="dim")
        outer.addWidget(self.prog_counter)

        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(10)
        outer.addLayout(self.cards_box)
        outer.addStretch(1)

    def _base(self) -> Path:
        """Папка программы, а не папка базы.

        Реестр `mcp-registry.json` лежит в папке `данные/` программы.
        `app_root()` возвращает базу пользователя
        (`DataBases/OpenCode_Base`), и вкладка читала бы несуществующий
        файл: карточки выходили бы именами серверов, без раздела
        «нужно мостам» и без единой кнопки установки. Отличие молчаливое —
        вкладка выглядела бы рабочей, показывая пустоту, — поэтому здесь
        написано прямо.
        """
        return core.program_root()

    # ---- наполнение

    def reload(self, wait: bool = False) -> None:
        """Перечитать реестр и перерисовать карточки.

        Живые проверки уходят в сторону от окна: поиск Unity, Godot,
        Roblox и Ghidra обходит папки программ и запускает найденные
        файлы, сверка с реестром зовёт node и npx. На этой машине это
        6 секунд, и раньше они шли прямо при сборке окна — человек
        смотрел на окно загрузки и считал, что программа зависла
        (замерено 22.10.2026: 8.6 с сборки, из них 6.1 с — этот поиск).

        Старые карточки при этом остаются на месте до прихода новых:
        стирать их сразу — значит на шесть секунд оставить человека
        перед пустым экраном. Перерисовка чистит список сама, поэтому
        двойных карточек не будет.

        `wait=True` считает всё на месте. Так зовёт самотест: ему нужен
        готовый список сразу после вызова, а не через событие.
        """
        base = self._base()
        self.notice.setText("Проверяем, что установлено…")
        self.notice.setStyleSheet(f"color: {ui.TEXT_DIM};")
        if wait:
            self._apply_load(self._load_work(base))
            return
        worker = Worker(lambda _progress: self._load_work(base))
        self._load_worker = worker
        worker.finished.connect(lambda: self._load_finished(worker))
        worker.start()

    # ---- живая проверка в стороне от окна

    def _load_work(self, base: Path):
        """Всё, что требует живых проверок, — одной пачкой и без виджетов.

        Карточки, разложение мостов по группам и строка замечаний
        считаются вместе: каждый из этих шагов читает реестр, и делать
        их по отдельности значило бы трижды ждать одни и те же проверки.
        """
        cards = program_cards.cards(base)
        placements = self._placements(base)
        notes, kinds = self._notice_work(base)
        return cards, placements, notes, kinds

    def _load_finished(self, worker: Worker) -> None:
        """Применить готовое. Устаревшее выполнение — мимо: за время
        работы мог прийти новый reload, и его слово главнее.
        """
        if getattr(self, "_load_worker", None) is not worker:
            return
        self._load_worker = None
        if isinstance(worker.result, Exception):
            self.notice.setText(f"Не удалось проверить данные: {worker.result}")
            self.notice.setStyleSheet(f"color: {ui.ERROR};")
            return
        self._apply_load(worker.result)

    def wait_loaded(self, timeout_ms: int = 120000) -> None:
        """Дождаться конца фоновой проверки. Нужно самотесту и выходу."""
        worker = getattr(self, "_load_worker", None)
        if worker is not None:
            worker.wait(timeout_ms)

    def _apply_load(self, result) -> None:
        """Нарисовать карточки по готовым данным (уже в потоке окна)."""
        cards, placements, notes, kinds = result
        # Прежние карточки убираем только сейчас, когда новые уже есть:
        # иначе на время проверки экран оставался пустым.
        self._clear_cards()
        self._cards = {card.key: card for card in cards}
        # Текст исчезнувших предметов не должен копиться: ключ мог
        # остаться от прежней версии реестра.
        alive = set(self._cards)
        for gone in [k for k in self._messages if k not in alive]:
            del self._messages[gone]
        self.notice.setText("   ".join(notes))
        self.notice.setStyleSheet(
            f"color: {ui.ERROR if 'error' in kinds else ui.WARN}" if kinds else ""
        )
        if not cards:
            self.cards_box.addWidget(
                ui.label("Ни одной карточки. Реестр прочитан, но предметов "
                         "в нём нет — скажи об этом разработчику, "
                         "программа тут ни при чём.",
                         kind="warn", wrap=True)
            )
            return
        # Что пришло из реестра, запоминаем: поиск и категория из
        # сайдбара только фильтруют этот список, реестр не перечитывают.
        self._prog_all = cards
        self._prog_placed = placements
        self._paint_cards()

    # ---- фоновая сверка данных (не вешает запуск)

    def _notice_work(self, base: Path) -> tuple[list[str], list[str]]:
        """Что не так с данными о программах: (тексты, виды). Чистая работа,
        без виджетов — выполняется в Worker за пределами потока окна.
        """
        problems = program_cards.section_problem(base)
        notes: list[str] = []
        kinds: list[str] = []
        if problems:
            notes.append("Данные о программах поехали: " + problems)
            kinds.append("error")
        if not winget_install.available():
            notes.append(
                "winget на этой машине нет, поэтому кнопки установки ничего "
                "не сделают. Он входит в Windows 10 версии 1809 и новее."
            )
            kinds.append("warn")
        return notes, kinds

    def _clear_cards(self) -> None:
        """Убрать нарисованные карточки вместе с их строками."""
        while self.cards_box.count():
            item = self.cards_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

    def _paint_cards(self) -> None:
        """Рисует карточки по категориям с учётом поиска и фильтра."""
        while self.cards_box.count():
            item = self.cards_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

        cards = getattr(self, "_prog_all", []) or []
        if not cards:
            return
        names = program_cards.servers_by_name(self._base())
        placed = getattr(self, "_prog_placed", {})
        query = self._prog_query.strip().lower()
        group = self._prog_group

        buckets: dict[str, list] = {}
        for card in cards:
            placement = program_groups.place_card(card, placed)
            if group and placement.group != group:
                continue
            if query:
                haystack = " ".join((
                    card.name, card.state_text, placement.title,
                    card.status,
                )).lower()
                if query not in haystack:
                    continue
            buckets.setdefault(placement.group, []).append((card, placement))

        order = {key: index for index, (key, _t) in enumerate(program_groups.GROUPS)}
        titles = program_groups.GROUP_TITLES
        shown = sum(len(rows) for rows in buckets.values())
        self.prog_counter.setText(
            f"Показано {shown} из {len(cards)}"
            + (f" · категория: {titles.get(group, group)}" if group else "")
            + (f" · поиск: «{self._prog_query.strip()}»" if query else "")
        )
        if not shown:
            self.cards_box.addWidget(
                ui.label("Ничего не найдено. Сбросьте поиск или выберите "
                         "«Все программы» в меню слева.", kind="dim", wrap=True)
            )
            return

        for key, _title in sorted(program_groups.GROUPS, key=lambda p: order[p[0]]):
            rows = buckets.get(key)
            if not rows:
                continue
            self.cards_box.addWidget(
                ui.label(f"{titles[key]} — {len(rows)}", kind="title")
            )
            for card, item in rows:
                self.cards_box.addWidget(self._build_card(card, names, item))
        # Мост, которого нет ни в одной группе, не должен исчезнуть молча.
        for key, rows in buckets.items():
            if key in titles:
                continue
            for card, _item in rows:
                self.cards_box.addWidget(self._build_card(card, names, None))

    def _prog_apply_filter(self, text: str) -> None:
        """Поиск по мере набора."""
        self._prog_query = str(text or "")
        self._paint_cards()

    def set_program_group(self, group_id: str) -> None:
        """Категория из подменю сайдбара. Пустая строка — все программы."""
        self._prog_group = str(group_id or "")
        self._paint_cards()

    def program_group(self) -> str:
        return self._prog_group

    def group_counts(self) -> dict[str, tuple[int, int]]:
        """Сколько карточек в группе и сколько из них с проблемой.

        Нужно подменю: «Движки и игры — 4», и красная отметка у группы,
        где что-то не установлено.
        """
        out: dict[str, list[int]] = {}
        placed = getattr(self, "_prog_placed", {})
        for card in getattr(self, "_prog_all", []) or []:
            placement = program_groups.place_card(card, placed)
            bucket = out.setdefault(placement.group, [0, 0])
            bucket[0] += 1
            if card.state != program_cards.STATE_OK:
                bucket[1] += 1
        return {key: (total, broken) for key, (total, broken) in out.items()}

    def _placements(self, base: Path) -> dict:
        """Разложение мостов по группам. Пусто — виноват реестр, а не окно."""
        try:
            servers = mcp_registry.load_servers(base)
        except Exception:  # noqa: BLE001 — вкладка не должна падать из-за групп
            return {}
        if not servers:
            return {}
        return program_groups.by_bridge(servers)

    def _build_card(self, card: program_cards.Card, names: dict[str, str],
                    item: program_groups.Placement | None = None) -> QWidget:
        """Одна карточка. Виджеты запоминаются: их надо гасить на время
        установки и заполнять заново по ходу дела."""
        # Имя карточки пишется внутри, крупной строкой. Заголовок самой
        # рамки не нужен: он дублировал имя и наезжал на верхнюю границу.
        box = QGroupBox()
        box.setObjectName("programCard")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        head = ui.row()
        name_label = ui.label(card.name, kind="title")
        name_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        head.layout().addWidget(name_label)
        self.status = ui.label(card.status)
        self.status.setStyleSheet(f"color: {_STATE_COLOR.get(card.state, ui.TEXT_DIM)}")
        head.layout().addWidget(self.status)
        head.layout().addStretch(1)
        layout.addWidget(head)

        # Почему карточка в этой группе. Правило видно словами: раскладку,
        # выбранную молча, нельзя ни проверить, ни оспорить.
        if item is not None and item.rule:
            layout.addWidget(ui.label(f"Группа: {item.title} · {item.rule}",
                                      kind="dim", wrap=True))

        needed = program_cards.needed_by_text(card, names)
        if needed:
            layout.addWidget(ui.label(needed, kind="dim", wrap=True))

        layout.addWidget(ui.label(card.state_text, wrap=True))

        pending = card.pending_text()
        if pending:
            layout.addWidget(ui.label(pending, kind="dim", wrap=True))

        # Совместимость версии — только строка. Ни state, ни can_install,
        # ни ready от неё не зависят: номер версии это сообщение человеку,
        # а не основание объявить программу неустановленной. Проверка на
        # это стоит в селфтесте отдельным пунктом.
        if card.compat.declared and card.compat.text:
            layout.addWidget(ui.label(card.compat.text,
                                      kind="warn" if card.compat.warning
                                      else "dim", wrap=True))

        if card.bridge.bundled:
            layout.addWidget(ui.label("Мост лежит внутри программы — отдельно "
                                      "ставить не нужно.", kind="dim", wrap=True))

        if card.alternatives:
            alternatives = self._build_alternatives(card)
            if alternatives is not None:
                layout.addWidget(alternatives)

        layout.addWidget(ui.label(self._verify_text(card), kind="dim", wrap=True))

        if card.install.instructions:
            # Инструкция установки — под спойлером: в открытом виде она
            # растягивала карточку на весь экран.
            toggle = QToolButton()
            toggle.setText("Как это ставится")
            toggle.setCheckable(True)
            toggle.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toggle.setArrowType(Qt.ArrowType.RightArrow)
            toggle.setObjectName("cardSpoiler")
            details = ui.label(card.install.instructions, kind="dim", wrap=True)
            details.setVisible(False)
            details.setContentsMargins(18, 0, 0, 0)

            def toggle_details(checked: bool, _d=details, _b=toggle) -> None:
                _d.setVisible(checked)
                _b.setArrowType(
                    Qt.ArrowType.DownArrow if checked
                    else Qt.ArrowType.RightArrow)

            toggle.toggled.connect(toggle_details)
            layout.addWidget(toggle)
            layout.addWidget(details)

        buttons = ui.flow_row()
        row: dict[str, QPushButton] = {}
        for code, label, hint in card.buttons():
            btn = QPushButton(label)
            btn.setToolTip(hint)
            if code == program_cards.BTN_CHECK:
                btn.clicked.connect(lambda _=False, k=card.key: self._check_one(k))
            elif code == program_cards.BTN_INSTALL:
                btn.clicked.connect(lambda _=False, c=card: self._install_card(c))
                if not card.can_install:
                    btn.setEnabled(False)
            elif code == program_cards.BTN_FETCH:
                btn.clicked.connect(lambda _=False, c=card: self._fetch_card(c))
                if not card.can_fetch:
                    btn.setEnabled(False)
            elif code == program_cards.BTN_UPDATE:
                btn.clicked.connect(
                    lambda _=False, c=card: self._update_card(c))
                if not card.can_update:
                    btn.setEnabled(False)
            elif code == program_cards.BTN_ROLLBACK:
                btn.clicked.connect(
                    lambda _=False, c=card: self._rollback_card(c))
                if not card.can_rollback:
                    btn.setEnabled(False)
            elif code == program_cards.BTN_FOLDER:
                btn.clicked.connect(lambda _=False, p=card.exe_path: self._open_folder(p))
            elif code == program_cards.BTN_PAGE:
                btn.clicked.connect(
                    lambda _=False, u=card.install.official_url: self._open_page(u))
            row[code] = btn
            buttons.add(btn)
        layout.addWidget(buttons)

        # Строка результата: сюда пишется ход установки и итог. Пустая
        # строка — не «ошибок нет», а «здесь ещё ничего не делали».
        result = ui.label("")
        result.setWordWrap(True)
        result.setStyleSheet(f"color: {ui.TEXT_DIM}")
        layout.addWidget(result)

        self._rows[card.key] = {
            "box": box, "status": self.status, "result": result, "buttons": row,
        }
        remembered = self._messages.get(card.key)
        if remembered:
            result.setText(remembered)
        return box

    def _build_alternatives(self, card: program_cards.Card) -> QWidget | None:
        """Варианты программы — как их записал реестр.

        Своя кнопка установки есть только у варианта с методом winget, и
        кнопка честно пишет, что поставит, — потому что у BlueStacks и
        MEmu разный путь, и молчаливый общий список их смешал бы.
        """
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        # Строки без содержимого не показываем: «? — в реестре написано:
        # ничего» пять раз подряд выглядело как поломка, хотя это просто
        # пустые поля реестра.
        lines: list[str] = []
        for alt in card.alternatives:
            name = str(alt.get("program") or "").strip()
            method = str(alt.get("method") or "").strip()
            winget_id = str(alt.get("winget_id") or "").strip()
            note = str(alt.get("note") or "").strip().rstrip(", ")
            if not name:
                continue
            if method == program_cards.METHOD_WINGET:
                lines.append(f"{name} — ставится через winget: {winget_id}")
            elif method == "manual":
                lines.append(f"{name} — кнопки нет, {note}".rstrip(", "))
            elif note:
                lines.append(f"{name} — {note}")
            elif method:
                lines.append(f"{name} — в реестре написано: {method}")
        if not lines:
            return None
        layout.addWidget(ui.label("Варианты:", kind="dim"))
        for text in lines:
            layout.addWidget(ui.label(text, kind="dim", wrap=True))
        return wrap

    @staticmethod
    def _verify_text(card: program_cards.Card) -> str:
        """Строка про подпись. Правду говорит только она.

        Подписант есть у одной программы — у Node.js. У остальных молчать
        нельзя: «проверено» без проверки хуже, чем «проверять не с чем».
        """
        verify = card.verify
        if not verify.can_check:
            if verify.expected_publisher:
                return (f"Подпись: сверять не с чем — файл установщика ещё не "
                        f"скачан. Издатель по каталогу winget: "
                        f"{verify.expected_publisher} — это другое поле, "
                        f"не подписант.")
            return ("Подпись: сверять не с чем — файл установщика ещё не "
                    "скачан, имя подписанта появится вместе с ним.")
        if verify.checked and verify.verified:
            return f"Подпись сходится: подписал {verify.expected_signer}."
        if verify.checked:
            return f"Подпись: {verify.detail}"
        return (f"Подпись: ждём подписанта {verify.expected_signer}, но файл "
                f"ещё не скачан — сверка не запускалась.")

    # ---- действия

    def _open_folder(self, exe_path: str) -> None:
        path = Path(exe_path)
        folder = path if path.is_dir() else path.parent
        if not folder.exists():
            QMessageBox.warning(self, "Папки нет",
                                f"Папки {folder} на машине нет.")
            return
        core.open_in_explorer(folder)

    def _open_page(self, url: str) -> None:
        core.open_url(url)

    def _check_one(self, key: str) -> None:
        """Перепроверить одну карточку.

        Карточки перерисовываются целиком: собирать разницу по одному
        полю — значит держать в виджетах состояние, которое тут же
        устареет. Одна карточка стоит дешевле, чем рассинхрон.
        """
        card = self._cards.get(key)
        if card is None:
            return
        self._set_result(key, "Перепроверяю…")
        self.reload()
        self._set_result(key, "Перепроверено")

    def _install_card(self, card: program_cards.Card) -> None:
        if not card.install.has_button:
            self._set_result(card.key, "В реестре нет описания установки — "
                                       "ставить нечем.")
            return
        if self._worker is not None and self._worker.isRunning():
            self._set_result(card.key, "Уже идёт установка — дождись её.")
            return
        if not self._ask_install(card):
            self._set_result(card.key, "Отказался — ничего не ставлю.")
            return

        self._set_busy(card.key, True)
        if card.install.action == programs.ACTION_VENV_PIP:
            # pip-пакет в своё окружение моста: у него свой ход, не winget.
            self._set_result(card.key, "Ставлю pip-пакет в окружение моста…")
            worker = Worker(
                lambda progress: kinocut_install.install(progress),
                self,
            )
        else:
            if not card.install.winget_id:
                self._set_result(card.key, "В реестре нет идентификатора "
                                           "winget — ставить нечем.")
                return
            self._set_result(card.key, "Запускаю winget…")
            worker = Worker(
                lambda progress: winget_install.install(
                    card.install.winget_id, progress),
                self,
            )
        worker.line.connect(
            lambda text, _kind, k=card.key: self._set_result(k, text))
        worker.finished.connect(
            lambda k=card.key, w=worker: self._install_done(k, w))
        self._worker = worker
        worker.start()

    def _fetch_card(self, card: program_cards.Card) -> None:
        """Докачать плагин моста. Молчание тут недопустимо.

        Качается файл из сети и раскладывается в папку чужой программы,
        поэтому человек должен знать до нажатия три вещи: что именно
        скачается, сколько это весит и куда попадёт. Все три — в вопросе.
        """
        fetcher = getattr(card, "plugin_fetch", None)
        if fetcher is None:
            self._set_result(card.key,
                             "программа не умеет ставить этот плагин — "
                             "спроси разработчика или поставь руками по подсказке.")
            return
        if self._worker is not None and self._worker.isRunning():
            self._set_result(card.key, "Уже идёт работа — дождись её.")
            return
        if not self._ask_fetch(card):
            self._set_result(card.key, "Отказался — ничего не качаю.")
            return
        self._set_busy(card.key, True)
        self._set_result(card.key, "Запускаю…")
        worker = Worker(
            lambda progress: fetcher(progress=progress),
            self,
        )
        worker.line.connect(
            lambda text, _kind, k=card.key: self._set_result(k, text))
        worker.finished.connect(lambda k=card.key, w=worker: self._fetch_done(k, w))
        self._worker = worker
        worker.start()

    def _ask_fetch(self, card: program_cards.Card) -> bool:
        """Спросить перед докачкой. Всегда, даже если кнопка активна."""
        lines = [f"Докачать плагин «{card.plugin.name}»?",
                 f"Как это будет: {card.plugin.hint}",
                 "Плагин кладётся в папку плагинов самой программы. "
                 "Ничего извне не ставится и ничего не удаляется."]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Докачать плагин")
        box.setText("\n\n".join(lines))
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _fetch_done(self, key: str, worker: Worker) -> None:
        result = worker.result
        if isinstance(result, tuple) and len(result) == 2:
            text = str(result[1])
        else:
            text = f"Докачка не закончилась: {result if result else 'неизвестно'}"
        self.reload()
        self._set_result(key, text)

    def _ask_install(self, card: program_cards.Card) -> bool:
        """Спросить перед установкой. Всегда, а не только при правах.

        Права администратора — не единственное, о чём человек должен
        знать заранее: после установки Adobe нужен вход в учётную
        запись, и об этом тоже лучше сказать до, чем после.
        """
        lines = [f"Поставить {card.install.program or card.name}?",
                 f"Идентификатор: {card.install.winget_id}"]
        if card.needs_admin:
            lines.append(
                "Установщик может запросить права администратора — появится "
                "окно Windows с вопросом. Программа сама эти права не берёт.")
        if card.hand_over:
            lines.append("После установки нужно будет войти в учётную запись "
                         "своими руками.")
        lines.append(
            "Подпись установщика я не сверял: файла у меня нет, пакет качает "
            "winget. Он сверяет хеш с манифестом источника, но подписанта "
            "по реестру не сверяет — этого он не умеет.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Установить программу")
        box.setText("\n\n".join(lines))
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _install_done(self, key: str, worker: Worker) -> None:
        result = worker.result
        if not isinstance(result, winget_install.InstallResult):
            self._set_busy(key, False)
            self._set_result(key, "Установка не закончилась: "
                                  f"{result if result else 'неизвестно'}")
            self.reload()
            return
        text = result.describe()
        card = self._cards.get(key)
        if result.needs_rights and card is not None and card.install.winget_id:
            text += ("\n winget упёрся в права. Запусти сам, от администратора:"
                     "\n " + winget_install.command_text(
                         card.install.winget_id, machine=True))
        self._set_busy(key, False)
        self._set_result(key, text)
        # Состояние перечитывается по-настоящему: успех кода возврата не
        # доказывает, что программа появилась.
        self.reload()

    # ------------------------------------------------- обновление и откат

    def _record_before_update(self, card: program_cards.Card) -> str:
        """Запомнить текущую версию ДО обновления.

        Вынесено отдельно, чтобы порядок был виден: вызов обязан стоять
        выше `worker.start()`, и это проверяется сравнением номеров строк в
        селфтесте. Возвращает пустую строку, если записать нечего.
        """
        base = self._base()
        current = card.update.installed
        if not base or not current or not card.servers:
            return ""
        said: list[str] = []
        for server_id in card.servers:
            ok, note = mcp_registry.remember_version(base, server_id, current)
            if not ok:
                said.append(note)
        return " ".join(said)

    def _update_card(self, card: program_cards.Card) -> None:
        """Кнопка «Обновить». Сначала живой вопрос источнику."""
        if not card.install.winget_id:
            self._set_result(card.key, "В реестре нет идентификатора winget — "
                                       "обновлять нечем.")
            return
        if self._worker is not None and self._worker.isRunning():
            self._set_result(card.key, "Уже идёт работа — дождись её.")
            return

        self._set_busy(card.key, True)
        self._set_result(card.key, "Спрашиваю источник…")
        state = winget_install.remote_state(card.install.winget_id)
        self._set_busy(card.key, False)
        if not state.seen:
            self._set_result(card.key, "Обновить не вышло: "
                                       + (state.note or "источник не ответил"))
            return
        if not state.update_available:
            if state.installed and not state.available:
                self._set_result(card.key, f"Обновлений нет: стоит "
                                           f"{state.installed}")
            elif state.installed and state.available:
                self._set_result(card.key,
                                 f"Обновлений нет: стоит {state.installed}, "
                                 f"в источнике {state.available}")
            else:
                self._set_result(card.key, "Обновлений нет, но версия "
                                           "источником не названа")
            return
        if not self._ask_update(card, state):
            self._set_result(card.key, "Отказался — ничего не обновляю.")
            return

        self._set_busy(card.key, True)
        # ПОРЯДОК ВАЖЕН: запись прежней версии идёт ДО запуска обновления.
        warning = self._record_before_update(card)
        if warning:
            self._set_result(card.key, "Прежнюю версию записать не удалось: "
                                       + warning + ". Обновляю, но возврат "
                                       "может не получиться.")
        else:
            self._set_result(card.key, f"Запомнил версию {state.installed}. "
                                       "Обновляю…")
        worker = Worker(
            lambda progress, pkg=card.install.winget_id:
                winget_install.upgrade(pkg, progress),
            self,
        )
        worker.line.connect(
            lambda text, _kind, k=card.key: self._set_result(k, text))
        worker.finished.connect(
            lambda k=card.key, w=worker, s=state: self._update_done(k, w, s))
        self._worker = worker
        worker.start()

    def _ask_update(self, card: program_cards.Card,
                    state: winget_install.RemoteState) -> bool:
        """Спросить перед обновлением. Всегда, даже если кнопка активна."""
        lines = [f"Обновить {card.install.program or card.name}?",
                 f"Идентификатор: {card.install.winget_id}",
                 f"Сейчас стоит: {state.installed}",
                 f"Источник предлагает: {state.available}"]
        if card.needs_admin:
            lines.append("Установщик может запросить права администратора — "
                         "появится окно Windows с вопросом.")
        lines.append("Прежняя версия будет записана ДО обновления, чтобы "
                     "возврат к ней был возможен.")
        lines.append("Если после обновления мост перестанет отвечать, верни "
                     "прежнюю версию кнопкой «Вернуть» в этой же карточке.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Обновить программу")
        box.setText("\n\n".join(lines))
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _update_done(self, key: str, worker: Worker,
                     state: winget_install.RemoteState) -> None:
        """Итог обновления. Версия записывается ПОСЕ — отдельной функцией."""
        result = worker.result
        self._set_busy(key, False)
        if not isinstance(result, winget_install.InstallResult):
            self._set_result(key, "Обновление не закончилось: "
                                  f"{result if result else 'неизвестно'}")
            self.reload()
            return
        text = result.describe()
        if result.needs_rights:
            text += ("\n winget упёрся в права. Запусти сам, от "
                     "администратора.")
        if result.ok and not result.already and state.available:
            # Что стоит ПОСЛЕ — проверяется живым запросом, а не берётся из
            # того, что обещал источник до обновления.
            after = winget_install.remote_state(self._winget_id_of(key))
            base = self._base()
            if base and after.seen and after.installed:
                ok, note = mcp_registry.set_installed_version(
                    base, self._server_id_of(key), after.installed,
                    note="снято живым `winget list` после обновления")
                text += f"\n {note}" if ok else f"\n версию записать не вышло: {note}"
            else:
                text += "\n новую версию снять не удалось — нажми «Проверить»"
        self._set_result(key, text)
        self.reload()

    def _rollback_card(self, card: program_cards.Card) -> None:
        """Кнопка «Вернуть прежнюю версию»."""
        target = card.rollback_target
        if not target:
            self._set_result(card.key, "Откатываться нечем: прежняя версия "
                                       "не записана.")
            return
        if not card.install.winget_id:
            self._set_result(card.key, "В реестре нет идентификатора winget — "
                                       "возвращаться некуда.")
            return
        if self._worker is not None and self._worker.isRunning():
            self._set_result(card.key, "Уже идёт работа — дождись её.")
            return
        self._set_busy(card.key, True)
        self._set_result(card.key, "Спрашиваю источник, есть ли эта версия…")
        offered = winget_install.version_offered(card.install.winget_id, target)
        self._set_busy(card.key, False)
        if not offered:
            self._set_result(card.key, f"Версии {target} больше нет в "
                                       "источнике: вернуться к ней не "
                                       "получится. Нажми «Проверить», чтобы "
                                       "увидеть, что доступно.")
            return
        if not self._ask_rollback(card, target):
            self._set_result(card.key, "Отказался — ничего не меняю.")
            return
        self._set_busy(card.key, True)
        self._set_result(card.key, f"Возвращаю {target}…")
        worker = Worker(
            lambda progress, pkg=card.install.winget_id, want=target:
                winget_install.install_version(pkg, want, progress),
            self,
        )
        worker.line.connect(
            lambda text, _kind, k=card.key: self._set_result(k, text))
        worker.finished.connect(
            lambda k=card.key, w=worker, want=target: self._rollback_done(k, w,
                                                                           want))
        self._worker = worker
        worker.start()

    def _ask_rollback(self, card: program_cards.Card, target: str) -> bool:
        """Спросить перед возвратом к прежней версии."""
        lines = [f"Вернуть {card.install.program or card.name} "
                 f"к версии {target}?",
                 f"Идентификатор: {card.install.winget_id}",
                 f"Сейчас стоит: {card.update.installed or 'не записана'}",
                 f"Источник эту версию предлагает — проверено только что.",
                 "Установщик может запросить права администратора."]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Вернуть прежнюю версию")
        box.setText("\n\n".join(lines))
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _rollback_done(self, key: str, worker: Worker, target: str) -> None:
        """Итог возврата. Версия записывается ПОСЕ."""
        result = worker.result
        self._set_busy(key, False)
        if not isinstance(result, winget_install.InstallResult):
            self._set_result(key, "Возврат не закончился: "
                                  f"{result if result else 'неизвестно'}")
            self.reload()
            return
        text = result.describe()
        if result.ok and not result.already:
            base = self._base()
            ok, note = mcp_registry.set_installed_version(
                base, self._server_id_of(key), target,
                note=f"записано после возврата к версии {target}")
            text += f"\n {note}" if ok else f"\n версию записать не вышл: {note}"
        self._set_result(key, text)
        self.reload()

    def _server_id_of(self, key: str) -> str:
        """Первый сервер карточки. Версии пишутся ему — по одному."""
        card = self._cards.get(key)
        return card.servers[0] if card and card.servers else ""

    def _winget_id_of(self, key: str) -> str:
        card = self._cards.get(key)
        return card.install.winget_id if card else ""

    def _set_busy(self, key: str, busy: bool) -> None:
        """Гасить кнопки на время работы.

        Пока идёт установка, карточка не должна принимать вторую команду:
        две установки одного пакета winget запускать нельзя, и человек
        получит ошибку вместо результата. По той же причине гаснут все
        кнопки карточки, а не только «Установить» — иначе человек успеет
        нажать «Проверить» посреди установки и увидит «не установлена».
        """
        row = self._rows.get(key)
        if row is None:
            return
        card = self._cards.get(key)
        for code, btn in row["buttons"].items():
            if busy:
                btn.setEnabled(False)
            elif code == program_cards.BTN_INSTALL:
                btn.setEnabled(bool(card and card.can_install))
            elif code == program_cards.BTN_FETCH:
                # Возврат после работы — по решению карточки, а не всегда
                # «включено»: кнопка докачки выключена там, где папка
                # закрыта, и после работы её включить нельзя.
                btn.setEnabled(bool(card and card.can_fetch))
            else:
                btn.setEnabled(True)

    def _set_result(self, key: str, text: str) -> None:
        """Написать в строку результата и запомнить на будущее.

        Запоминание обязательно: карточки перерисовываются целиком, и
        написанное здесь иначе пропадало бы при первой же перерисовке —
        то есть сразу после установки.
        """
        self._messages[key] = text
        row = self._rows.get(key)
        if row is None:
            return
        row["result"].setText(text)
        self.refresh_height()

    # ---- показ своего состояния

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        self.refresh_height()


# ---------------------------------------------------------------- вкладка «Инструкция»


class HelpTab(ScrollPage):
    """Детальная инструкция: как пользоваться программой."""

    def __init__(self, parent=None) -> None:
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._build(inner)

    @staticmethod
    def _section(text: str) -> QToolButton:
        """Заголовок раздела — кнопка, которая раскрывает и сворачивает."""
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setChecked(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setArrowType(Qt.ArrowType.DownArrow)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        return button

    @staticmethod
    def _step(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {ui.TEXT}; padding: 2px 4px 2px 18px;"
        )
        return label

    def _collapsible(self, title: str, widgets: list,
                     expanded: bool = False) -> QWidget:
        """Раскрывающийся раздел: заголовок-кнопка и текст под ним.

        По умолчанию свёрнут: длинная инструкция одной стеной текста
        выглядит как аварийный документ. Раскрыт только первый раздел —
        он отвечает на вопрос «что это» и показывает, что остальные
        открываются так же.
        """
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        button = self._section(title)
        button.setChecked(expanded)
        body = ui.column(*widgets, spacing=6)
        body.setVisible(expanded)
        col.addWidget(button)
        col.addWidget(body)

        def toggle(checked: bool) -> None:
            body.setVisible(checked)
            button.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
            )

        button.toggled.connect(toggle)
        button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        return holder

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(8)

        outer.addWidget(ui.label("Как пользоваться программой", kind="title"))

        outer.addWidget(self._collapsible("1. Что это", [
            self._step(
                "Это окно для базы OpenCode. База — папка с текстовыми файлами: "
                "память, библиотека, скиллы, инструкции. Сами базы лежат отдельно, "
                "обычно в DataBases на рабочем столе. Окно их создаёт, подключает "
                "к OpenCode, ставит возможности и показывает, какие сторонние "
                "серверы можно включить."
            ),
            self._step(
                "Запуск: двойной щелчок по «Управление-базой.cmd» в корне базы. "
                "Нужен Python с PyQt6. Системный Python без этого пакета окно не "
                "откроет. Вкладок восемь, ниже — что делает каждая и чего она не "
                "делает. Зелёной галочки «чужой сервер уже ответил» здесь нет: "
                "программа так не пишет, пока ответа не было."
            ),
        ], expanded=True))

        outer.addWidget(self._collapsible("2. Первый запуск", [
            self._step(
                "Программа создаёт папку DataBases на рабочем столе и показывает "
                "приветствие. Новые базы лучше класть туда же: кнопка «Сканировать» "
                "на второй вкладке ищет их на рабочем столе и в DataBases по файлу "
                ".opencode-base.json."
            ),
        ]))

        outer.addWidget(self._collapsible("3. Создать новую базу", [
            self._step(
                "Вкладка «Новая база».\n"
                "1. Папка-родитель. По умолчанию DataBases.\n"
                "2. Имя папки. Пробелы и русские буквы можно. Нельзя знаки "
                "< > : \" / \\ | ? * и служебные имена Windows вроде CON.\n"
                "3. Галочка «Разрешить пароли и ключи» по умолчанию снята. "
                "Без неё нейросеть откажется записывать секреты.\n"
                "4. Откуда взять содержимое: пустой шаблон или копия образца, "
                "со скиллами или без.\n"
                "5. «Подключить базу к программе сразу» — копия уходит в настройки "
                "OpenCode. Папки ваших проектов не трогаются. Прежние файлы памяти "
                "уходят в _previous-version.\n"
                "6. Ярлык. Он должен вести на файл «Открыть-базу.cmd», не на папку.\n"
                "Сначала «Проверить» — это только план, ничего не пишется. "
                "Потом «Создать базу».\n"
                "Перед кнопками есть «Интеграция с Obsidian». Два переключателя "
                "независимы. Оба выключены — ничего нового. «Поддержка Obsidian» "
                "добавляет Главная.md, если её нет, и кнопку «Открыть в Obsidian». "
                "Чужие заметки не затираются. «Obsidian Agent» кладёт файл @obsidian "
                "в базу. Это не живой запуск модели. Если Obsidian не установлен, "
                "база всё равно создаётся."
            ),
            self._step(
                "База — это папка с текстовыми файлами: память, библиотека знаний, "
                "скиллы, инструкции. Скиллы при создании берутся из встроенного "
                "шаблона, вместе с индексом сценариев (skills-index.json) — "
                "нейросеть читает его и сама выбирает нужный скилл по задаче."
            ),
        ]))

        outer.addWidget(self._collapsible("4. Подключить существующую базу", [
            self._step(
                "Вторая вкладка «Подключить»:\n"
                "1) нажмите «Сканировать» — программа найдёт все базы с файлом-"
                "идентификатором .opencode-base.json на рабочем столе и в DataBases;\n"
                "2) выберите базу из списка или укажите папку вручную через «Обзор…»;\n"
                "3) нажмите «Подключить» — файлы базы скопируются в настройки "
                "OpenCode, прежние файлы уйдут в _previous-version."
            ),
        ]))

        outer.addWidget(self._collapsible("5. Мост NCP", [
            self._step(
                "Третья вкладка «Мост NCP — создать»: создаёт переводчик между "
                "OpenCode и библиотекой знаний NCP. Мост умеет 7 операций: "
                "ncp_status (состояние), ncp_search (поиск), ncp_save (сохранить "
                "запись), ncp_read (прочитать), ncp_update (изменить), "
                "ncp_checkpoint (контрольная точка), ncp_reindex (пересобрать "
                "индекс). Путь к библиотеке подставляется автоматически."
            ),
        ]))

        outer.addWidget(self._collapsible(
            "6. Возможности для OpenCode (вкладка «opencode»)", [
            self._step(
                "Здесь ставятся в настройки OpenCode только отмеченные возможности:\n"
                "— команда /голос (голосовой ввод);\n"
                "— агенты и скиллы (поиск, план, код, проверка и другие);\n"
                "— обход блокировок (запуск OpenCode через прокси).\n"
                "Мосты ПК и памяти сюда галочками не входят: они едут с базой и "
                "включаются кнопкой «Подключить»."
            ),
        ]))

        outer.addWidget(self._collapsible(
            "7. Серверы MCP — блок на вкладке «opencode»", [
            self._step(
                "Это не мосты базы. Это сторонние программы из реестра. Таблица: "
                "сервер, состояние, лицензия, число инструментов. Подробности — "
                "в тексте под таблицей.\n"
                "До «Проверить всё» состояние честно «не проверено». Проверка "
                "запускает чужие команды и ничего не устанавливает.\n"
                "«Включить» вписывает команду в opencode.jsonc. «Выключить» убирает "
                "только этот блок. «Открыть источник» открывает страницу проекта.\n"
                "«Настроить автоматически» делает разное:\n"
                "— Android Studio, OBS, эмулятор, DBHub, Браузеры, OmniRoute и "
                "LMArena: настраивает целиком, насколько это можно без чужого окна;\n"
                "— Unity, Unreal, Roblox Studio, Godot, TikTok, CapCut, Spotify, "
                "ChatGPT API, Codex и Cursor: только свою часть. Файл или проверка. "
                "Редактор, сайт и браузер кнопка не открывает и готовым мост не "
                "считает.\n"
                "У LDPlayer этой кнопки нет: ему хватает «Включить».\n"
                "Что именно сделает кнопка у выбранной строки — написано в "
                "подсказке на самой кнопке.\n"
                "После включения перезапустите OpenCode. Пока чужой сервер сам не "
                "ответил, говорить «подключено» нельзя."
            ),
            self._step(
                "Что можно попросить в терминале OpenCode после настройки и перезапуска:\n"
                "— Spotify: «включи трек». Нужны Premium, открытое приложение и "
                "один раз вход пакета. Это Web API, не скачивание файла.\n"
                "— ChatGPT API: «создай новый ответ и продолжи его». Это не сайт "
                "chatgpt.com. Нужны свой ключ и имя модели из кабинета.\n"
                "— Codex: «создай новый чат и выполни команду». По умолчанию только "
                "чтение. Полный доступ к диску не даётся.\n"
                "— Cursor: «создай новый чат и отправь команду». Файлы без явной "
                "просьбы не правятся.\n"
                "VK Музыка и Яндекс.Музыка в списке нет: открытого API на включение "
                "трека нет, скачивать файл программа не будет."
            ),
        ]))

        outer.addWidget(self._collapsible("8. Обход блокировок", [
            self._step(
                "Обход работает только для запущенного через ярлык OpenCode.\n"
                "Каналы по приоритету:\n"
                "1) V2Ray — свой Xray (узлы из встроенных VLESS-подписок, выбирается "
                "быстрейший);\n"
                "2) публичные прокси (список обновляется автоматически, источников 6);\n"
                "3) защищённый DNS (DoH: Google, Cloudflare, Quad9, AdGuard, Yandex, "
                "NextDNS, CleanBrowsing, Mullvad).\n"
                "Фасад сам выбирает канал по скорости и пишет подробный лог в окно "
                "запуска: видно, через что идёт трафик и что отвалилось."
            ),
        ]))

        outer.addWidget(self._collapsible("9. Темы (вкладка «Темы»)", [
            self._step(
                "Папка themes/ в конструкторе и в базе. Заготовка темы OpenCode — "
                "Markdown-файл с полями: цвета, шрифт, размер. Скопируйте заготовку, "
                "заполните своими значениями и попросите ассистента применить тему."
            ),
        ]))

        outer.addWidget(self._collapsible("10. Обновление самой программы", [
            self._step(
                "Программа обновляется файлом из репозитория, не через git pull.\n"
                "«Проверить обновление» смотрит, есть ли новое. Пока не нажали, "
                "«Скачать и применить» выключена: неизвестно, что качать.\n"
                "Перед применением делается бэкап. «Вернуть из бэкапа» откатывает "
                "последнее обновление.\n"
                "Отдельным блоком ниже — мост OmniRoute. Версию программа "
                "спрашивает у официального GitHub проекта "
                "(https://github.com/diegosouzapw/OmniRoute), а сам пакет ставит "
                "из npm ровно той версией, которую назвал GitHub. Пока не нажали "
                "«Проверить», «Обновить мост» выключена: неизвестно, есть ли "
                "что ставить."
            ),
        ]))

        outer.addWidget(self._collapsible("11. Перенос на другой компьютер", [
            self._step(
                "Скопируйте папку базы целиком, установите Python с PyQt6, запустите "
                "«Управление-базу.cmd». Программа сама найдёт базу, подключит мосты "
                "и настроит OpenCode. Ничего вручную прописывать не нужно.\n"
                "Секреты мостов (mcp-tiktok.txt, mcp-spotify.txt, mcp-chatgpt.txt "
                "и другие) в репозиторий не входят: их надо создать заново кнопкой "
                "настройки. Живое подключение само на новом компьютере не появится."
            ),
        ]))

        outer.addWidget(self._collapsible("12. Если что-то не работает", [
            self._step(
                "— OpenCode не видит базу → проверьте memory-base-path.txt и "
                "перезапустите OpenCode;\n"
                "— обход не подключается → запустите ярлык «OpenCode (обход)», "
                "посмотрите лог в окне;\n"
                "— мост NCP не отвечает → проверьте library_path в "
                "tools/ncp-bridge/config.json;\n"
                "— программа не открывается → нужен Python 3 с пакетом PyQt6;\n"
                "— сервер в таблице «не проверено» → это нормально, пока не нажали "
                "«Проверить всё»;\n"
                "— «Включить» вписало команду, а в терминале тишина → перезапустите "
                "OpenCode. Если лаунчер пишет, что нет файла или команды, откройте "
                "«Настроить автоматически»;\n"
                "— Spotify не включает трек → нет Premium, приложение не открыто "
                "или не сделан вход пакета. Программа трек не подделывает;\n"
                "— ChatGPT открывает сайт → не должен. Мост ходит только на "
                "api.openai.com по вашему ключу."
            ),
        ]))


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
        outer.setContentsMargins(18, 16, 18, 16)
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
    def __init__(self, splash=None) -> None:
        super().__init__()
        # Окно загрузки живёт до конца сборки окна, поэтому передаём его
        # сюда: иначе надпись в нём замирает на весь долгий ход работы.
        # Шаг — это ровно то, что происходит сейчас, а не общее «загружаем».
        self._splash_step = (lambda text, percent=0: splash.say(text, percent)) \
            if splash is not None else (lambda text, percent=0: None)
        self.setWindowTitle("Управление базой")
        # Значок рисуется сам (ui.app_icon): файлов с картинками в
        # программе нет, а значок нужен сразу трём местам — заголовку
        # окна, трею и уведомлениям Windows.
        self.tray_quitting = False
        self.setWindowIcon(ui.app_icon())
        self.setMinimumSize(720, 560)
        # Окно — по экрану, а не по заветной цифре. Раньше стояло
        # resize(880, 900), и на экране 1280x720 окно выходило 737 px:
        # Windows срезала низ, и нижние кнопки вкладки уезжали за
        # край экрана — вместе с ними и жалоба «интерфейс не
        # помещается». Теперь размер берётся от доступной области
        # экрана (без панели задач), а лишнее содержимое вкладок
        # уезжает в прокрутку — её даёт ScrollPage.
        _screen = QApplication.primaryScreen()
        _avail = _screen.availableGeometry() if _screen is not None else None
        if _avail is not None:
            # Минимум тоже от экрана: на узком экране заявленные
            # 720 px сами оказались бы больше экрана, и окно снова
            # вылезло бы за край — ровно то, от чего чиним.
            self.setMinimumSize(
                min(720, max(360, _avail.width() - 20)),
                min(560, max(320, _avail.height() - 20)),
            )
            self.resize(
                min(880, max(self.minimumWidth(), _avail.width() - 60)),
                min(900, max(self.minimumHeight(), _avail.height() - 60)),
            )
        else:
            self.resize(880, 900)
        # Значок в трее и сворачивание вместо закрытия. Если система не
        # даёт трей (бывает в самопроверке и на некоторых сборках
        # Windows), программа работает как раньше: крестик закрывает.
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = ui.TrayIcon(self, self)
            self.tray.show()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        # Шапка: название слева, кнопка трея справа. Кнопка нужна
        # потому, что крестик закрывает программу как обычно, а трей
        # стал отдельным действием — раньше он был спрятан вместо
        # закрытия, и выключить программу было нечем.
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(ui.label("Управление базой", kind="title"))
        head.addStretch(1)
        self.tray_button = QPushButton("Свернуть в трей")
        self.tray_button.setObjectName("ghost")
        self.tray_button.clicked.connect(self._on_tray_clicked)
        self.tray_button.setToolTip(
            "Скрыть окно в трей. Программа продолжит работать и придёт "
            "уведомлением, когда проверка закончится. Закрыть программу "
            "можно крестиком или через значок в трее."
        )
        if self.tray is None:
            self.tray_button.setEnabled(False)
            self.tray_button.setToolTip(
                "Система не даёт трей — окно можно только закрыть."
            )
        head.addWidget(self.tray_button)
        layout.addLayout(head)
        layout.addWidget(
            ui.label(
                "База — это папка с текстовыми файлами памяти, правил и скиллов.",
                kind="dim",
            )
        )

        tabs = QTabWidget()
        self.tabs = tabs
        # Шаги загрузки идут прямо здесь, между сборкой вкладок.
        # Раньше окно загрузки писало «Читаем настройки и список
        # мостов…» и молчало все десять секунд, пока собиралось
        # главное окно: на записи экрана это было видно прямо.
        # Шаг не перескакивает через работу — он и есть описание того,
        # что происходит сейчас.
        step = getattr(self, "_splash_step", None)
        step("Собираем вкладки программы…", 50)
        self.create_tab = CreateTab()
        step("Вкладка «Новая база»…", 54)
        self.import_tab = ImportTab()
        step("Вкладка «Подключить»…", 60)
        self.bridge_tab = BridgeTab()
        step("Вкладка «Мост NCP»…", 66)
        self.caps_tab = CapsTab()
        step("Вкладка «opencode»: список мостов…", 74)
        self.programs_tab = ProgramsTab()
        step("Вкладка «Программы»: карточки установленного…", 82)
        self.themes_tab = ThemesTab()

        # Импорт вкладки «Обновление» — здесь, а не вверху файла. Вкладка
        # берёт `ScrollPage` и `Worker` из этого модуля, и импорт наверху
        # дал бы круг: main не успел бы дойти до определения класса,
        # а update_tab уже просил бы его. Измеренная ошибка была ровно
        # такой: «cannot import name 'ScrollPage' from partially
        # initialized module 'main'». Внутри метода main уже загружен
        # целиком, и круг разрывается.
        from update_tab import UpdateTab  # noqa: PLC0415

        step("Вкладка «Обновление»…", 88)
        self.update_tab = UpdateTab()

        step("Вкладка «Инструкция»…", 92)
        self.help_tab = HelpTab()
        step("Расставляем вкладки…", 96)
        # Подписи вкладок короткие не для красоты: восемь
        # длинных русских подписей занимали 861 пиксель, а полоса
        # вкладок при окне 880 показывает около 830 — последние
        # вкладки уезжали за правый край, и до них можно было дойти
        # только стрелками у края полосы.
        tabs.addTab(self.create_tab, "Новая база")
        tabs.addTab(self.import_tab, "Подключить")
        tabs.addTab(self.bridge_tab, "Мост NCP")
        tabs.addTab(self.caps_tab, "opencode")
        tabs.addTab(self.programs_tab, "Программы")
        tabs.addTab(self.themes_tab, "Темы")
        tabs.addTab(self.update_tab, "Обновление")
        tabs.addTab(self.help_tab, "Инструкция")
        self.tabs = tabs

        # ---- боковое меню разделов
        #
        # Полоса вкладок сверху кончится: восемь подписей занимают
        # 861 пиксель, а полоса при окне 880 показывает около 830, и
        # последние вкладки уезжают за край. Меню растёт вниз и не
        # кончается.
        #
        # Пока полоса вкладок остаётся на месте, меню работает как
        # указатель на неё и переключает те же страницы. Так старый
        # код вкладок остаётся рабочим целиком, а меню можно снять
        # одной строкой, если не пригодится.
        self.nav_buttons: list = []
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 8)
        side.setSpacing(3)
        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        badge = QLabel()
        badge.setPixmap(ui.app_icon().pixmap(30, 30))
        badge.setStyleSheet("border: none; background: transparent;")
        logo_row.addWidget(badge)
        logo_text = ui.label("Управление\nбазой", kind="title")
        logo_text.setStyleSheet("font-size: 15px; font-weight: 700;")
        logo_row.addWidget(logo_text)
        logo_row.addStretch(1)
        side.addLayout(logo_row)
        side.addSpacing(6)
        for index in range(tabs.count()):
            button = QPushButton(tabs.tabText(index))
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(24)
            button.clicked.connect(
                lambda _checked=False, i=index: self._open_section(tabs, i))
            side.addWidget(button)
            self.nav_buttons.append(button)
            if tabs.tabText(index) == "opencode":
                side.addWidget(self._build_subnav())
            if tabs.tabText(index) == "Программы":
                side.addWidget(self._build_prog_subnav())

        side.addStretch(1)
        self.nav_status = ui.label("", kind="dim", wrap=True)
        side.addWidget(self.nav_status)
        # Сайдбар и полоса вкладок стоят рядом, поэтому оба едут в
        # общий горизонтальный ряд. Если их положить прямо в верхний
        # вертикальный макет, меню встаёт НАД вкладками, а не сбоку —
        # так и вышло с первой попытки, увидел на снимке.
        #
        # В ряд кладём сразу, без промежуточного добавления в layout:
        # removeWidget отвязывает виджет, и до следующего addLayout он
        # остаётся без родителя, а на сборке мусора удаляется. Кнопки
        # меню после этого оказывались удалёнными объектами.
        _row = QHBoxLayout()
        _row.setContentsMargins(0, 0, 0, 0)
        _row.setSpacing(0)
        _row.addWidget(sidebar)
        _row.addWidget(tabs, 1)
        layout.addLayout(_row, 1)
        # Нижние панели действий: «Создать базу» и «Создать мост» всегда
        # на виду, страница под ними прокручивается.
        self.create_footer = self.create_tab.footer
        self.bridge_footer = self.bridge_tab.footer
        for _footer in (self.create_footer, self.bridge_footer):
            _footer.setVisible(False)
            layout.addWidget(_footer)
        # Полосу вкладок убираем, сам QTabWidget оставляем. Он теперь
        # просто хранилище страниц: всё в программе ходит к разделам
        # через window.tabs, и замена на QStackedWidget сломала бы
        # сорок с лишним проверок, которые смотрят в список вкладок
        # напрямую. Видимую часть навигации делает меню сбоку.
        tabs.tabBar().setVisible(False)
        tabs.setUsesScrollButtons(False)
        # Подсветка едет за текущим разделом: кто бы ни переключил
        # раздел — из меню или программно.
        tabs.currentChanged.connect(self._sync_nav)
        self._sync_nav(tabs.currentIndex())

        self.create_tab.base_ready.connect(self._suggest_import)
        self.create_tab.base_ready.connect(self._suggest_bridge)

    def _open_section(self, tabs, index: int) -> None:
        """Открыть раздел из меню.

        Подсветку ставим сами, а не ждём currentChanged. Клик по
        уже открытому разделу индекс не меняет, сигнал не приходит, а
        кнопка с checkable при этом снимает с себя отметку — раздел
        оставался открытым и без подсветки, и меню выглядело сломанным.
        """
        tabs.setCurrentIndex(index)
        self._sync_nav(index)
        # Раздел открыт целиком: человек ещё не выбирал категорию, и
        # подсвеченный «Все мосты» над экраном агентов сбивал с толку.
        if index == self._opencode_index():
            self._bridge_picked = False
            self.caps_tab.set_bridge_category("")
        if index == self._programs_index():
            self._programs_picked = False
            self.programs_tab.set_program_group("")

    def _build_subnav(self) -> QWidget:
        """Подменю категорий мостов под пунктом «opencode».

        Категорий девять, и в высоту окна они влезают только компактными
        строками. Подменю видно лишь когда открыт opencode: в остальных
        разделах оно занимало бы место без пользы.
        """
        self.nav_sub = QWidget()
        self.nav_sub.setObjectName("navSub")
        sub = QVBoxLayout(self.nav_sub)
        sub.setContentsMargins(20, 4, 2, 6)
        sub.setSpacing(1)
        self.nav_sub_buttons: list = []
        # Выбрана ли категория руками. Пока нет — подменю ничего не
        # подсвечивает: раздел открыт целиком, а не отфильтрован.
        self._bridge_picked = False

        all_button = QPushButton("Все мосты")
        all_button.setObjectName("subnav")
        all_button.setCheckable(True)
        all_button.setChecked(True)
        all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        all_button.setMinimumHeight(19)
        all_button.clicked.connect(lambda: self._open_bridge_group(""))
        sub.addWidget(all_button)
        self.nav_sub_buttons.append(all_button)

        for key, title in mcp_categories.GROUPS:
            if key == "other":
                continue
            button = QPushButton(title)
            button.setObjectName("subnav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(19)
            button.clicked.connect(
                lambda _checked=False, k=key: self._open_bridge_group(k))
            sub.addWidget(button)
            self.nav_sub_buttons.append(button)
        # Высота считается по строкам, а не берётся из sizeHint:/n        # до показа окна sizeHint ещё не знает стиля, выходит меньше
        # фактической — и последние строки наезжали на «Программы».
        rows = 1 + len([k for k, _t in mcp_categories.GROUPS
                        if k != "other"])
        self.nav_sub.setFixedHeight(rows * 19 + (rows - 1) + 10)
        self.nav_sub.setVisible(False)
        return self.nav_sub

    def _build_prog_subnav(self) -> QWidget:
        """Подменю категорий программ под пунктом «Программы».

        Категории те же, что раскладывает program_groups, с числом
        карточек: «Движки и игры — 4». У группы, где что-то не стоит,
        число красное — проблемные места видно до клика.
        """
        self.nav_prog_sub = QWidget()
        self.nav_prog_sub.setObjectName("navSub")
        sub = QVBoxLayout(self.nav_prog_sub)
        sub.setContentsMargins(20, 4, 2, 6)
        sub.setSpacing(1)
        self.nav_prog_buttons: list = []
        self._programs_picked = False

        all_button = QPushButton("Все программы")
        all_button.setObjectName("subnav")
        all_button.setCheckable(True)
        all_button.setChecked(True)
        all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        all_button.setMinimumHeight(19)
        all_button.clicked.connect(lambda: self._open_program_group(""))
        sub.addWidget(all_button)
        self.nav_prog_buttons.append(all_button)

        # В сайдбаре подписи короче: полные названия не влезают в 190
        # пикселей и упираются в край.
        short_titles = {
            "engines": "Движки и игры",
            "editors": "Редакторы",
            "office": "Офис",
            "media": "Медиа",
            "record": "Запись",
            "devices": "Эмуляторы",
            "shared": "Общие",
            "bridges": "Служебные",
            "other": "Прочее",
        }
        for key, title in program_groups.GROUPS:
            button = QPushButton(short_titles.get(key, title))
            button.setProperty("group", key)
            button.setObjectName("subnav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(19)
            button.clicked.connect(
                lambda _checked=False, k=key: self._open_program_group(k))
            sub.addWidget(button)
            self.nav_prog_buttons.append(button)
        rows = 1 + len(program_groups.GROUPS)
        self.nav_prog_sub.setFixedHeight(rows * 19 + (rows - 1) + 10)
        self.nav_prog_sub.setVisible(False)
        return self.nav_prog_sub

    def _programs_index(self) -> int:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == "Программы":
                return index
        return -1

    def _open_program_group(self, group_id: str) -> None:
        """Открыть «Программы» и показать только эту категорию."""
        index = self._programs_index()
        if index < 0:
            return
        self._programs_picked = True
        self.tabs.setCurrentIndex(index)
        self.programs_tab.set_program_group(group_id)
        self._sync_nav(index)
        self._sync_prog_subnav(group_id)

    def _sync_prog_subnav(self, group_id: str) -> None:
        for button in getattr(self, "nav_prog_buttons", []) or []:
            key = button.property("group")
            if key is None:
                checked = not group_id
            else:
                checked = key == group_id
            button.setChecked(bool(checked))

    def _refresh_prog_subnav(self) -> None:
        """Счётчики и цвет проблемных групп в подменю программ."""
        counts = self.programs_tab.group_counts()
        for button in getattr(self, "nav_prog_buttons", []) or []:
            key = button.property("group")
            if key is None:
                continue
            base = button.text().split(" — ")[0]
            total, broken = counts.get(key, (0, 0))
            # Группа без карточек не нужна в меню: пустой пункт только
            # занимает высоту, которой и так впритык.
            button.setVisible(bool(total))
            button.setText(f"{base} — {total}" if total else base)
            # Жёлтый, а не красный: «не установлено» — обычное дело,
            # красный оставляем для настоящих сбоев.
            if broken:
                button.setStyleSheet(f"color: {ui.WARN};")
            else:
                button.setStyleSheet("")
        # Высота — по числу видимых строк: скрытое «Прочее» не должно
        # оставлять пустую полосу.
        shown = sum(1 for b in self.nav_prog_buttons if not b.isHidden())
        self.nav_prog_sub.setFixedHeight(
            max(1, shown) * 19 + max(0, shown - 1) + 10)
        self._sync_prog_subnav(self.programs_tab.program_group())

    def _opencode_index(self) -> int:
        """Номер вкладки opencode. Ищем по подписи, а не по числу."""
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == "opencode":
                return index
        return -1

    def _open_bridge_group(self, group_id: str) -> None:
        """Открыть opencode и показать в таблице только эту категорию."""
        index = self._opencode_index()
        if index < 0:
            return
        self._bridge_picked = True
        self.tabs.setCurrentIndex(index)
        self.caps_tab.set_bridge_category(group_id)
        self._sync_nav(index)
        self._sync_subnav(group_id)
        # Подменю называется «Все мосты», а вкладка открывается на
        # агентах — без прокрутки человек не видел, что фильтр сработал.
        QTimer.singleShot(0, lambda: self.caps_tab.ensureWidgetVisible(
            self.caps_tab.reg_table, 0, 30))

    def _sync_subnav(self, group_id: str) -> None:
        """Отметить в подменю выбранную категорию."""
        for button in getattr(self, "nav_sub_buttons", []) or []:
            text = button.text()
            checked = (text == "Все мосты" and not group_id) or (
                group_id and text == mcp_categories.title(group_id))
            button.setChecked(bool(checked))

    def _sync_nav(self, index: int) -> None:
        """Отметить в меню тот раздел, что открыт в полосе вкладок.

        Подпись снизу показывает, какая вкладка открыта. Это не
        украшение: меню и полоса — два указателя на одно, и без
        отметки нельзя было понять, где вы находитесь, если раздел
        переключили стрелками у края полосы.
        """
        for i, button in enumerate(getattr(self, "nav_buttons", []) or []):
            button.setChecked(i == index)
        buttons = getattr(self, "nav_buttons", []) or []
        if 0 <= index < len(buttons):
            status = getattr(self, "nav_status", None)
            if status is not None:
                status.setText(buttons[index].text())
        create_footer = getattr(self, "create_footer", None)
        if create_footer is not None:
            create_footer.setVisible(index == 0)
        bridge_footer = getattr(self, "bridge_footer", None)
        if bridge_footer is not None:
            bridge_footer.setVisible(
                index == next((i for i in range(self.tabs.count())
                               if self.tabs.tabText(i) == "Мост NCP"), -1))
        sub = getattr(self, "nav_sub", None)
        prog_sub = getattr(self, "nav_prog_sub", None)
        if sub is not None:
            sub_visible = index == self._opencode_index()
            sub.setVisible(sub_visible)
            if sub_visible and not getattr(self, "_bridge_picked", False):
                # Раздел открыт целиком: подсвеченный «Все мосты» над
                # экраном агентов сбивал с толку.
                for button in getattr(self, "nav_sub_buttons", []) or []:
                    button.setChecked(False)
        if prog_sub is not None:
            prog_visible = index == self._programs_index()
            prog_sub.setVisible(prog_visible)
            if prog_visible:
                # В «Программах» подменю и есть сам экран: «Все программы»
                # — честное текущее состояние, и оно подсвечено. Снимать
                # подсветку здесь значило бы показать неактивный пункт.
                self._refresh_prog_subnav()
        # Подпись раздела внизу дублирует открытый раздел и отнимает
        # высоту у подменю — на время подменю её прячем.
        status = getattr(self, "nav_status", None)
        if status is not None:
            any_sub = bool((sub is not None and sub.isVisible())
                           or (prog_sub is not None and prog_sub.isVisible()))
            status.setVisible(not any_sub)

    def closeEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        """Крестик закрывает программу, как закрывал раньше.

        Сначала было сделано наоборот — крестик сворачивал в трей. Не
        вышло: закрыть программу было нечем, человек жал крестик раз
        за разом и не мог её выключить. Трей остался, но теперь это
        отдельное действие — кнопка «Свернуть в трей», а не замена
        закрытию.

        Здесь же выставляется флаг отмены фоновой загрузки, а поток сам
        доходит до безопасной точки и убирает недокачанный файл.
        Принудительная остановка потока здесь не годилась бы: она
        прервала бы запись посреди файла, и следующий запуск принял бы
        его за годный архив — он лежит во временной папке под тем же
        именем.
        """
        tab = getattr(self, "update_tab", None)
        if tab is not None and hasattr(tab, "stop"):
            tab.stop()
        # Проверка моделей живёт в отдельном потоке: убивать её на
        # середине нельзя — внутри платные запросы, а QThread, убитый
        # вместе с окном, роняет процесс («Destroyed while thread is
        # still running»). Отвязываем её сигналы от умирающего окна и
        # откладываем выход: воркер доначистит кэш и сам завершит
        # программу своим finished. Значок трея (ниже) остаётся
        # запасным выходом, если проверка затянется.
        worker = getattr(self, "_qw_check_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.progress.disconnect(self._qw_check_models_progress)
                worker.finished.disconnect(self._qw_check_models_done)
            except TypeError:
                pass
            worker.setParent(None)
            # Держим ссылку сами: без неё Python соберёт объект прямо
            # под работающим потоком.
            _QW_DETACHED_WORKERS.append(worker)
            worker.finished.connect(_qw_detached_worker_finished)
            self._qw_check_worker = None
            self._qw_quit_pending = True
        super().closeEvent(event)
        # Значок трея намеренно НЕ прячем: он и есть запасной выход.
        # Прятали — и получалось ровно то, на что жаловались: закрыли
        # окно, значок исчез, а программа из-за занятого потока не
        # завершилась. На экране не осталось ничего, и закрыть её было
        # уже нечем. Оставляем значок на месте всегда, кроме настоящего
        # выхода через «Закрыть программу» в его меню.
        if self.tray is not None and not self.tray_quitting:
            self.tray.show()
        # Закрытие последнего окна намеренно не завершает программу
        # (так мосты переживают закрытие вкладки), поэтому выход
        # вызываем сами. Иначе крестик закрывал бы окно, а процесс
        # оставался бы жить в фоне без единого окна.
        app = QApplication.instance()
        if app is not None and not getattr(self, "_qw_quit_pending", False):
            app.quit()

    def minimize_to_tray(self) -> None:
        """Свернуть окно в трей — по кнопке, а не вместо закрытия."""
        if self.tray is None:
            self.showMinimized()
            return
        self.tray.hide_to_tray()

    def _on_tray_clicked(self) -> None:
        """Кнопка «Свернуть в трей» в шапке окна."""
        self.minimize_to_tray()

    def notify(self, title: str, text: str = "") -> None:
        """Уведомление Windows через значок в трее.

        Фоновая работа идёт минуту-другую, а окно человек в это время
        может свернуть — сообщение о том, что всё готово, должно прийти
        само. Если трея нет (например, в самопроверке), уведомление
        просто ничего не делает.
        """
        tray = getattr(self, "tray", None)
        if tray is None:
            return
        from PyQt6.QtWidgets import QSystemTrayIcon

        tray.showMessage(
            title, text or title,
            QSystemTrayIcon.MessageIcon.Information, 6000,
        )

    def refresh_now(self) -> None:
        """Обновить состояние из меню трея."""
        for tab in (getattr(self, "caps_tab", None),
                    getattr(self, "programs_tab", None)):
            refresh = getattr(tab, "refresh", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:  # noqa: BLE001 — обновление не должно ронять программу
                    pass

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


# ------------------------------------------------- единственный экземпляр

#: Имя локального сокета, которым программа занимает место единственного
#: экземпляра.
APP_SOCKET_NAME = "opencode-base-dbapp"

#: Сервер держим в переменной модуля: если он попадёт в сборщик мусора,
#: сокет закроется и защита перестанет работать.
_SINGLE_SERVER = None
_SINGLE_WINDOW = None


def _socket_name() -> str:
    """Имя сокета с учётом пользователя.

    На одном компьютере могут работать два разных человека, и общее
    имя заставило бы их мешать друг другу.
    """
    try:
        user = os.environ.get("USERNAME") or getpass.getuser()
    except Exception:  # noqa: BLE001 - имя пользователя не повод не открыться
        user = "user"
    return f"{APP_SOCKET_NAME}-{user or 'user'}"


def _lock_path() -> Path:
    """Путь файла-метки «занято»."""
    import tempfile

    name = _socket_name()
    return Path(tempfile.gettempdir()) / f"{name}.lock"


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс с таким номером.

    os.kill(pid, 0) на Windows вызывает TerminateProcess, а это
    убийство, поэтому здесь спрашиваем у системы через OpenProcess.
    """
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes

    query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(query, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == still_active
        return True
    except Exception:  # noqa: BLE001
        return True
    finally:
        kernel32.CloseHandle(handle)


def _acquire_instance_lock() -> bool:
    """Занять метку экземпляра. True — место свободно, оно наше.

    Метка создаётся одной операцией O_EXCL: выиграть может ровно один,
    даже если десять процессов стартуют в одну миллисекунду. Один
    локальный сокет такой гарантии не даёт — три копии успевали
    создать слушатель по очереди и все три считали себя первыми.
    """
    path = _lock_path()
    for _ in range(3):
        try:
            handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = int(path.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                holder = 0
            if holder and holder != os.getpid() and _pid_alive(holder):
                return False
            # метка осталась от аварийно убитого запуска — забираем
            try:
                path.unlink()
            except OSError:
                return False
            continue
        except OSError:
            return True  # метку создать нельзя — не блокируем запуск
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
        return True
    return False


def _raise_window() -> None:
    """Показать уже открытое окно."""
    window = _SINGLE_WINDOW
    if window is None:
        return
    try:
        window.showNormal()
        window.raise_()
        window.activateWindow()
    except RuntimeError:
        # окно уже закрыто, а сокет ещё жив — просто молча выходим
        pass


def claim_single_instance() -> bool:
    """Занять место единственного экземпляра.

    True — мы первые и должны открыть окно. False — программа уже
    запущена: её окно показано, а этот процесс тихо завершается.

    Зачем. Окружение на этой машине удваивает запуск любого Python:
    один и тот же процесс появляется дважды, и повторяется это даже
    для пустого скрипта, который только спит. Программа с этим ничего
    не может поделать — зато может не показывать лишние окна. Без
    защиты один щелчок по ярлыку открывал три-четыре окна.
    """
    global _SINGLE_SERVER, _SINGLE_WINDOW
    # Метка проверяется первой и решает всё: если место занято, второй
    # экземпляр должен показать чужое окно и выйти.
    if not _acquire_instance_lock():
        return False
    try:
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    except ImportError:
        # Qt без сети: метку уже взяли, окно всё равно откроется
        return True

    name = _socket_name()
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(400):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(400)
        probe.disconnectFromServer()
        return False

    # Сокета нет: значит мы первые. Остатки от аварийно убитого
    # прежнего запуска убираем, иначе сервер не поднимется.
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.setSocketOptions(
        QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        # Занять не вышло: лучше открыться, чем молча не показаться
        return True

    def _on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(_raise_window)
        conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(_on_connection)
    _SINGLE_SERVER = server
    return True


def _set_taskbar_name(name: str) -> None:
    """Назовить программу в панели задач и в списке Alt+Tab.

    Зачем. По умолчанию Windows показывает там имя запущенного
    интерпретатора, и в списке окон висело `Python` — выглядело так,
    будто открыт чужой скрипт. Имя программы задаётся один раз на
    процесс, до появления любых окон.

    На Windows это идентификатор приложения (AppUserModelID); без него
    панель задач группирует окно по имени файла, то есть по pythonw.
    На других системах функция не нужна и не вызывается.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(name)
    except Exception:
        # Не fatally: без этого программа работает, просто в панели
        # задач остаётся имя интерпретатора.
        pass


def run() -> int:
    app = QApplication(sys.argv)
    # Имя в панели задач — как просил человек: OpenCodeBase, а не
    # Python. Заголовок окна при этом остаётся человеческим.
    _set_taskbar_name("OpenCodeBase")
    app.setApplicationName("OpenCodeBase")
    app.setApplicationDisplayName("OpenCodeBase")
    app.setOrganizationName("OpenCodeBase")
    ui.apply_dark_theme(app)
    # Крестик закрывает программу, поэтому идти по умолчанию нельзя:
    # закрыли окно с мостами — мосты должны остаться работать.
    app.setQuitOnLastWindowClosed(False)

    if not claim_single_instance():
        return 0

    # Окно загрузки показываем сразу, до тяжёлой сборки главного окна:
    # она занимает секунды, и без этого человек видит только молчание.
    splash = ui.SplashWindow()
    splash.show()
    splash.say("Запуск программы…", 5)
    app.processEvents()

    # Импорты здесь, а не в самом блоке ниже. Стоило поставить их там —
    # и `core` становился локальной переменной на всю функцию: обращение
    # к core.first_run_done() выше падало с UnboundLocalError, программа
    # умирала за 0.3 секунды, а лаунчер показывал эту ошибку в консоли.
    # Выглядело при этом как «программа зависла».
    import core
    import mcp_registry
    import opencode_caps

    if not core.first_run_done():
        splash.say("Первый запуск: готовим папку с базами…", 20)
        app.processEvents()
        folder = core.ensure_data_bases_folder()
        splash.hide()
        from ui_first_run import FirstRunDialog

        dlg = FirstRunDialog(folder)
        dlg.exec()
        core.mark_first_run_done()
        splash.show()

    splash.say("Читаем настройки и список мостов…", 45)
    app.processEvents()

    # Старые блоки мостов запускают консоль и открывают окна cmd.
    # Переписываем их на запуск без окна, пока окно загрузки видно.
    quiet_notes: list[str] = []
    try:
        _base = core.current_base("opencode")
        if _base is not None:
            quiet_notes, _ = mcp_registry.quiet_migrate(
                opencode_caps.opencode_dir(),
                mcp_registry.load_servers(_base, check=False),
            )
    except Exception:
        # Перепись настроек не обязана быть частью запуска: если она
        # не вышла, программа всё равно должна открыться.
        quiet_notes = []

    global _SINGLE_WINDOW
    window = MainWindow(splash=splash)
    _SINGLE_WINDOW = window
    # Показ окна идёт ДО прокрутки очереди событий, и это не порядок
    # ради порядка. Проверки вкладки opencode отложены на таймер, а
    # таймер срабатывает на первом же processEvents. Если крутить очередь
    # раньше, отложенные проверки успевают отработать до показа окна, и
    # весь выигрыш пропадает: измерено 9.4 с против 2.9 с.
    window.show()
    splash.say("Готово", 100)
    app.processEvents()
    splash.hide()
    if quiet_notes:
        # Говорим сразу и один раз: окно уже на экране, а отсчёт
        # уходит в трей, и человек узнает об изменениях поздно.
        window.notify("Мосты переписаны", "\n".join(quiet_notes))
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
