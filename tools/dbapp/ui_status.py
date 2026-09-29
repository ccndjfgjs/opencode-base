"""Панель состояния внизу боковой колонки.

Зачем она нужна. Человек открывает программу и первым делом спрашивает
«а что сейчас подключено и работает ли мост». Раньше ответ на это был
разбросан по шести вкладкам: путь — в первой, состояние моста — в
третьей, счётчики — в четвёртой. Панель собирает ответ в одном месте
и держит его перед глазами всегда, независимо от раздела.

Что в ней три строки:
- точка и название состояния — «мост работает» или «моста нет»;
- путь к основной базе, сокращённый по середине, чтобы длинный путь
  не выталкивал остальное за край;
- три счётчика: скиллы, записи библиотеки, размер.

Пульсирующая точка — единственный запоминающийся элемент окна. Она
говорит «здесь что-то живое» без единого слова. Дыхание намеренно
медленное и негромкое: быстрая пульсация утомляет, и её перестаёшь
замечать уже через минуту.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QSize,
    QTimer,
    QVariantAnimation,
    Qt,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import core
import ui

# Диаметр точки в покое и в наивысшей яркости. Разница небольшая:
# точка должна дышать, а не мигать.
DOT_MIN = 8
DOT_MAX = 11
PULSE_MS = 2200


def short_path(path: Path | str, limit: int = 34) -> str:
    """Сократить путь, оставив самое важное: имя папки и её родителя.

    Обрезать с конца нельзя — там самое интересное («OpenCode_Base»),
    а терять надо середину, состоящую из повторяющихся «Dedy_Sher».
    """
    text = str(path)
    if len(text) <= limit:
        return text
    parts = Path(text).parts
    if len(parts) < 3:
        return "…" + text[-limit + 1:]
    head = parts[1] if parts[0].endswith(":") else parts[0]
    tail = "…\\".join(parts[-2:])
    return f"{head}\\{tail}"


def human_size(size: int) -> str:
    """Размер папки так, как его пишут люди: «205,7 МБ»."""
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.1f}".replace(".", ",") + f" {unit}"
        value /= 1024
    return "0 Б"


class StatusBar(QFrame):
    """Панель состояния: точка, состояние моста, путь и счётчики."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusbar")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.setStyleSheet(f"""
        QFrame#statusbar {{
            border-top: 1px solid {ui.BORDER};
            background: transparent;
        }}
        QFrame#statusbar QLabel {{ background: transparent; }}
        """)

        outer = QVBoxLayout(self)
        # Отступ слева и справа обязателен: без него точка упиралась в
        # край колонки и срезалась наполовину, а строка счётчиков
        # обрывалась на «205,7» без единицы измерения.
        outer.setContentsMargins(ui.S2, ui.S3, ui.S2, ui.S2)
        outer.setSpacing(ui.S1)

        # --- строка 1: точка и состояние
        top = QHBoxLayout()
        top.setSpacing(ui.S2)
        self.dot = QFrame()
        self.dot.setFixedSize(DOT_MIN, DOT_MIN)
        self.dot.setStyleSheet(
            f"background: {ui.TEXT_3}; border-radius: {DOT_MIN // 2}px;"
        )
        top.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self.state_label = QLabel("проверяю…")
        self.state_label.setStyleSheet(f"color: {ui.TEXT_2}; font-size: 13px;")
        top.addWidget(self.state_label, 1)
        outer.addLayout(top)

        # --- строка 2: путь
        self.path_label = QLabel("—")
        self.path_label.setStyleSheet(
            f"color: {ui.TEXT_3}; font-size: 12px;"
        )
        self.path_label.setToolTip("")
        self.path_label.setWordWrap(True)
        outer.addWidget(self.path_label)

        # --- строка 3: счётчики одной строкой
        #
        # Три подписи с двоеточиями в колонке 214 пикселей не помещались:
        # строка обрывалась на «размер: 205,7» без «МБ», и человек
        # гадал, мегабайты там или гигабайты. Поэтому подписи короче,
        # а единицы измерения не отбрасываются.
        self.counts_label = QLabel("—")
        self.counts_label.setStyleSheet(
            f"color: {ui.TEXT_3}; font-size: 11.5px;"
        )
        self.counts_label.setWordWrap(True)
        outer.addWidget(self.counts_label)
        self.skills_label = self._count("скиллы")
        self.notes_label = self._count("записи")
        self.size_label = self._count("размер")

        self._anim: QVariantAnimation | None = None
        self._pulse_enabled = True
        self._dot_color = ui.TEXT_3
        self.refresh()

    def _count(self, name: str) -> QLabel:
        """Счётчик, который не видно, но значение которого проверяется.

        На экране счётчики собраны в одну строку: три подписи в колонке
        214 пикселей обрезались. Сами значения остаются отдельными
        подписями - по ним проверки сверяют, что панель не соврёт.
        """
        widget = QLabel(f"{name}: —")
        widget.setStyleSheet(f"color: {ui.TEXT_3}; font-size: 11.5px;")
        widget.setToolTip(name)
        widget.setVisible(False)
        return widget

    def _update_counts(self) -> None:
        """Собрать счётчики в строку, которая помещается в колонку."""
        skills = self.skills_label.text().split(":")[-1].strip()
        notes = self.notes_label.text().split(":")[-1].strip()
        size = self.size_label.text().split(":")[-1].strip()
        self.counts_label.setText(
            f"{skills} скиллов · {notes} записей · {size}"
        )
        self.counts_label.setToolTip(
            f"скиллов: {skills}\nзаписей в библиотеке: {notes}\nразмер: {size}"
        )

    # ------------------------------------------------------------ пульс

    def set_pulse(self, enabled: bool) -> None:
        """Включить или выключить дыхание точки.

        Нужно для людей, которым движение мешает: точка остаётся на
        месте и показывает состояние цветом, просто перестаёт пульсировать.
        """
        self._pulse_enabled = enabled
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if enabled:
            self._start_pulse()
        else:
            self._paint_dot(1.0)

    def _start_pulse(self) -> None:
        if not self._pulse_enabled:
            return
        # Анимируем не свойство размера, а число от 0 до 1 и сами меняем
        # размер точки. Причина: у точки стоял setFixedSize, а он
        # зажимает и минимум, и максимум - анимация minimumSize
        # молча ничего не делала, и точка не дышала, хотя код был верный.
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(PULSE_MS)
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.0)
        self._anim.setLoopCount(-1)
        # Мягкое ускорение и замедление: ровный линейный пульс выглядит
        # как мигание лампочки, а не как дыхание.
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.start()

    def _on_value(self, value) -> None:  # noqa: ANN001 - Qt-сигнал
        level = float(value)
        size = DOT_MIN + round((DOT_MAX - DOT_MIN) * level)
        self.dot.setFixedSize(size, size)
        self._paint_dot(level)

    def _paint_dot(self, level: float) -> None:
        color = QColor(self._dot_color)
        color.setAlphaF(0.45 + 0.55 * max(0.0, min(1.0, level)))
        # Радиус считаем от текущего размера, а не от DOT_MIN: точка
        # растёт при пульсе, и постоянный радиус превращал её в
        # скруглённый квадрат, когда она раздувалась до 11 пикселей.
        size = max(1, self.dot.width())
        self.dot.setStyleSheet(
            f"background: {color.name(QColor.NameFormat.HexArgb)};"
            f" border-radius: {size // 2}px;"
        )

    # ------------------------------------------------------------ данные

    def refresh(self) -> None:
        """Пересчитать всё, что показывает панель.

        Ошибки проглатываются намеренно: панель состояния не должна
        ронять программу. Если что-то не прочиталось — показываем
        «—» и ждём следующего обновления.
        """
        try:
            self._refresh_inner()
        finally:
            # Пульс запускается здесь, а не внутри подсчёта состояния.
            # Раньше он стартовал в ветке «мост есть», и у человека без
            # моста - то есть почти у каждого, кто только поставил
            # программу, - точка молча стояла. Именно там она нужнее
            # всего: видно, что пора обратить внимание.
            if self._pulse_enabled and self._anim is None:
                self._start_pulse()

    def _refresh_inner(self) -> None:
        base = None
        try:
            base = core.current_base()
        except Exception:  # noqa: BLE001 - панель не должна ронять окно
            base = None

        if base is None:
            self._dot_color = ui.TEXT_3
            self.state_label.setText("база не подключена")
            self.state_label.setStyleSheet(f"color: {ui.TEXT_3}; font-size: 13px;")
            self.path_label.setText("—")
            self.path_label.setToolTip("")
            for widget in (self.skills_label, self.notes_label,
                           self.size_label):
                widget.setText(widget.text().split(":")[0] + ": —")
            self._update_counts()
            self._paint_dot(1.0)
            return

        self.path_label.setText(short_path(base))
        self.path_label.setToolTip(str(base))

        try:
            info = core.base_info(base)
        except Exception:  # noqa: BLE001
            info = {}
        self.skills_label.setText(f"скиллы: {info.get('skills', 0)}")
        self.size_label.setText(
            "размер: " + human_size(int(info.get("size", 0) or 0))
        )
        self._refresh_notes(base)
        self._refresh_bridge()
        self._update_counts()

    def _refresh_notes(self, base: Path) -> None:
        count = 0
        try:
            lib = core.library_dir(base)
            if lib.is_dir():
                count = sum(1 for p in lib.iterdir() if p.is_dir())
        except Exception:  # noqa: BLE001
            count = 0
        self.notes_label.setText(f"записи: {count}")

    def _refresh_bridge(self) -> None:
        """Состояние моста: есть ли он и все ли файлы на месте."""
        try:
            bridges = core.find_bridges()
        except Exception:  # noqa: BLE001
            bridges = []
        if not bridges:
            self._dot_color = ui.WARN
            self.state_label.setText("мост не создан")
            self.state_label.setStyleSheet(f"color: {ui.WARN}; font-size: 13px;")
            self.state_label.setToolTip(
                "Без моста библиотека остаётся просто файлами, "
                "которые никто не читает. Создайте его в разделе «Мост NCP»."
            )
            self._paint_dot(1.0)
            return

        folder = bridges[0]
        try:
            status = core.bridge_status(folder)
        except Exception:  # noqa: BLE001
            status = None

        missing = list(getattr(status, "missing", []) or [])
        problem = str(getattr(status, "problem", "") or "")
        if problem:
            self._dot_color = ui.ERROR
            self.state_label.setText("мост требует внимания")
            self.state_label.setStyleSheet(
                f"color: {ui.ERROR}; font-size: 13px;"
            )
            self.state_label.setToolTip(problem)
        elif missing:
            self._dot_color = ui.WARN
            self.state_label.setText("мост не дописан")
            self.state_label.setStyleSheet(f"color: {ui.WARN}; font-size: 13px;")
            self.state_label.setToolTip(
                "Не хватает файлов: " + ", ".join(missing[:6])
            )
        else:
            self._dot_color = ui.OK
            self.state_label.setText("мост работает")
            self.state_label.setStyleSheet(f"color: {ui.OK}; font-size: 13px;")
            self.state_label.setToolTip(
                f"Мост: {folder}\nВсе {len(core.BRIDGE_FILES)} файлов на месте."
            )
        self._paint_dot(1.0)
