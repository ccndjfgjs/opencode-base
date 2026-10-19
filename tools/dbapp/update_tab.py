r"""Вкладка «Обновление»: что стоит, что доступно, что делать.

**Откуда берётся всё, что вкладка показывает.** Только из уже проверенных
слоёв `update_source` и `update_download`. Вкладка не решает ничего
сама: она спрашивает, показывает ответ и запускает действие. Иначе
правило «только HTTPS, только github.com» рано или поздно будет
продублировано здесь и разойдётся с тем, что проверяет скачивание.

**Почему кнопки выключены с причиной, а не спрятаны.** Так уже сделано
для кнопок карточек программ, и §22.2 требует того же: человек должен
получить причину ДО нажатия. Спрятанная кнопка выглядит как «здесь не
работает», выключенная с подсказкой — как «вот почему».

**Почему индикатор показывает то, что происходит, а не «идёт загрузка».**
Скачивание может занять минуты, и молчаливая полоса без числа выглядит
как зависание. Поэтому рядом с полосой — сколько скачано из сколького и
что делается сейчас.

**Отмена при закрытии окна.** Окно закрывает человек, а поток живёт
отдельно. Закрытие выставляет флаг, поток замечает его после очередного
куска, удаляет недокачанный файл и завершается. Недокачанный архив,
оставшийся во временной папке, был бы принят за годный при следующем
запуске — поэтому удаление встроено в скачивание, а не сюда.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import selfupdate as _selfupdate  # noqa: E402
import omniroute as _or  # noqa: E402
import omniroute_update as _orupd  # noqa: E402
import update_download as _dl  # noqa: E402
import update_source as _src  # noqa: E402
from ui import flow_row, label  # noqa: E402

# ScrollPage и Worker живут в main.py, а не в ui.py: `label` — это про вид,
# а полоса прокрутки и поток — про устройство окна.
#
# Импорт отсюда работает только потому, что main.py подключает эту
# вкладку ИЗНУТРИ MainWindow.__init__, когда он уже загружен целиком.
# При импорте наверху файла круг был бы мгновенным: main не дошёл бы до
# определения ScrollPage, а update_tab уже просил бы его.
# Проверено: ошибка «cannot import name 'ScrollPage' from partially
# initialized module 'main'».
from main import ScrollPage, Worker  # noqa: E402


class UpdateTab(ScrollPage):
    """Обновление самой программы: проверка, скачивание, применение, откат.

    Три состояния кнопки «Скачать и применить»:
      * есть новое обновление — включена;
      * обновлений нет — выключена, в подсказке сказано почему;
      * проверка ещё не делалась — выключена, и в подсказке сказано, что
        сначала надо проверить.
    """

    def __init__(self, parent=None) -> None:
        inner = QWidget()
        super().__init__(inner, parent)
        self._page = inner
        self._worker = None
        self._cancel = False
        self._found: tuple[str, str] | None = None
        self._or_remote: str = ""
        self._build(inner)
        self.refresh()

    # -------------------------------------------------------------- сборка

    def _build(self, page: QWidget) -> None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        outer.addWidget(label(
            "Обновление самой программы. Программа — распакованная копия, "
            "а не git-клон, поэтому обновление приходит файлом из "
            "репозитория. Перед применением делается бэкап, откат — "
            "отдельной кнопкой.",
            kind="dim", wrap=True,
        ))

        # --- состояние
        box = QGroupBox("Состояние")
        bl = QVBoxLayout(box)
        self.lbl_local = QLabel("—")
        self.lbl_local.setWordWrap(True)
        self.lbl_remote = QLabel("—")
        self.lbl_remote.setWordWrap(True)
        self.lbl_rate = QLabel("")
        self.lbl_rate.setWordWrap(True)
        bl.addWidget(label("Локальная версия", kind="dim"))
        bl.addWidget(self.lbl_local)
        bl.addWidget(label("В репозитории", kind="dim"))
        bl.addWidget(self.lbl_remote)
        bl.addWidget(self.lbl_rate)
        outer.addWidget(box)

        # --- ход загрузки
        prog = QGroupBox("Ход загрузки")
        pl = QVBoxLayout(prog)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.lbl_step = QLabel("")
        self.lbl_step.setWordWrap(True)
        pl.addWidget(self.progress)
        pl.addWidget(self.lbl_step)
        outer.addWidget(prog)

        # --- кнопки
        # Ряд переносящийся: три кнопки с длинными подписями в обычном
        # QHBoxLayout при узком окне сжимаются, и подписи срезаются.
        row = flow_row()
        self.btn_check = QPushButton("Проверить обновление")
        self.btn_check.clicked.connect(self._check_clicked)
        self.btn_apply = QPushButton("Скачать и применить")
        self.btn_apply.clicked.connect(self._apply_clicked)
        self.btn_apply.setEnabled(False)
        self.btn_rollback = QPushButton("Вернуть из бэкапа")
        self.btn_rollback.clicked.connect(self._rollback_clicked)
        self.btn_rollback.setEnabled(False)
        row.add(self.btn_check)
        row.add(self.btn_apply)
        row.add(self.btn_rollback)
        outer.addWidget(row)

        # --- бэкап
        box2 = QGroupBox("Бэкап перед последним обновлением")
        b2 = QVBoxLayout(box2)
        self.lbl_backup = QLabel("—")
        self.lbl_backup.setWordWrap(True)
        b2.addWidget(self.lbl_backup)
        row2 = flow_row()
        self.btn_open_backup = QPushButton("Открыть папку")
        self.btn_open_backup.clicked.connect(self._open_backup)
        self.btn_drop_backup = QPushButton("Удалить бэкап")
        self.btn_drop_backup.clicked.connect(self._drop_backup_clicked)
        row2.add(self.btn_open_backup)
        row2.add(self.btn_drop_backup)
        b2.addWidget(row2)
        outer.addWidget(box2)

        # --- мост OmniRoute
        #
        # Отдельный блок, а не ещё одна строка в общий список: у моста
        # другой источник версии (официальный GitHub проекта, а не
        # релиз программы) и другое действие (поставить пакет, а не
        # заменить файлы программы). Смешаны они были бы в одну кнопку,
        # и непонятно было бы, что именно обновится.
        box3 = QGroupBox("Мост OmniRoute")
        b3 = QVBoxLayout(box3)
        self.lbl_or = QLabel("—")
        self.lbl_or.setWordWrap(True)
        b3.addWidget(label("Версия моста", kind="dim"))
        b3.addWidget(self.lbl_or)
        row3 = flow_row()
        self.btn_or_check = QPushButton("Проверить")
        self.btn_or_check.setToolTip(
            "Спросить официальный GitHub проекта "
            "(https://github.com/diegosouzapw/OmniRoute), какая там версия, "
            "и сравнить с той, что стоит на диске. Ничего не меняет."
        )
        self.btn_or_check.clicked.connect(self._or_check_clicked)
        self.btn_or_update = QPushButton("Обновить мост")
        self.btn_or_update.setEnabled(False)
        self.btn_or_update.setToolTip(
            "Поставить найденную версию. Пока не нажали «Проверить», "
            "выключено: неизвестно, есть ли что ставить."
        )
        self.btn_or_update.clicked.connect(self._or_update_clicked)
        row3.add(self.btn_or_check)
        row3.add(self.btn_or_update)
        b3.addWidget(row3)
        outer.addWidget(box3)

        outer.addStretch(1)

    # -------------------------------------------------------------- состояние

    @staticmethod
    def program_dir() -> Path:
        from core import program_root

        return program_root()

    def _busy(self) -> bool:
        """Идёт ли сейчас поток. Пока идёт — кнопки не трогаем."""
        return self._worker is not None

    def refresh(self) -> None:
        """Перечитать локальное состояние: версия, бэкап, кнопки."""
        base = self.program_dir()
        here = _selfupdate.local_version(base)
        self.lbl_local.setText(
            f"{here or 'не названа'}  (файл ВЕРСИЯ в корне программы)")

        backup = _selfupdate._backup_path(base)
        if backup.is_dir():
            count = len([p for p in backup.rglob("*") if p.is_file()])
            self.lbl_backup.setText(
                f"{backup}\nобъектов внутри: {count}")
            self.btn_rollback.setEnabled(True)
            self.btn_drop_backup.setEnabled(True)
        else:
            self.lbl_backup.setText(
                "Бэкапа нет: обновление ещё не применялось. Откатить "
                "нечего, и кнопка выключена именно поэтому.")
            self.btn_rollback.setEnabled(False)
            self.btn_drop_backup.setEnabled(False)

        if not self._busy():
            self.btn_apply.setEnabled(False)
            self.btn_apply.setToolTip(
                "Сначала нажмите «Проверить обновление»: без проверки "
                "неизвестно, есть ли что качать.")

        # --- мост OmniRoute: что стоит на диске
        if not _or.deployed():
            self.lbl_or.setText(
                "Мост не развёрнут: пакета нет в папке моста. Обновлять "
                "нечего — нажми «Развернуть» у строки OmniRoute на "
                "вкладке opencode.")
            if not self._busy():
                self.btn_or_update.setEnabled(False)
        else:
            here = _or.installed_version() or "версия не названа"
            self.lbl_or.setText(
                f"Стоит: OmniRoute {here}\n"
                f"Источник версии: {_orupd.SOURCE_LABEL}")
            if not self._busy():
                # Кнопка обновления живёт по тому же правилу, что и у
                # программы: выключена, пока не сказано, что ставить.
                self.btn_or_update.setEnabled(bool(self._or_remote)
                                              and _orupd.is_newer(
                                                  here, self._or_remote))

    # -------------------------------------------------------------- проверка

    def _check_clicked(self) -> None:
        if self._busy():
            return
        base = self.program_dir()
        here = _selfupdate.local_version(base)
        self.btn_check.setEnabled(False)
        self.lbl_step.setText("спрашиваю у репозитория…")

        def work(progress):
            source = _src.load_source(base)
            tag, version, meta = _dl.latest_release(source)
            rate = meta.get("rate_left")
            limit = meta.get("rate_limit")
            tail = (f"Осталось запросов к GitHub: {rate} из {limit}."
                    if rate is not None else "")
            import versions as _vs

            newer = bool(here) and _vs.version_tuple(version) > \
                _vs.version_tuple(here)
            if not here:
                newer = True  # локальная версия не названа — не судим
            if newer:
                note = " (предварительный релиз)" \
                    if meta.get("prerelease") else ""
                progress(
                    f"Есть обновление: {here or 'версия не названа'} → "
                    f"{version}{note}. Метка {tag}.{tail}")
            else:
                progress(
                    f"Обновлений нет: стоит {here}, а в репозитории "
                    f"{version} — не новее. Откат — отдельная кнопка. "
                    f"{tail}")
            return (tag, version, meta, here)

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._check_done)
        self._worker.start()

    def _check_done(self) -> None:
        self.btn_check.setEnabled(True)
        worker, self._worker = self._worker, None
        if worker is None or worker.result is None \
                or isinstance(worker.result, Exception):
            return
        tag, version, meta, here = worker.result
        import versions as _vs

        # Метка и версия запоминаются ЗДЕСЬ, а не в потоке: поток живёт
        # отдельно и кнопку применения не трогает. Забыть это — значит
        # скачать не то, что человек только что увидел в подписи.
        self._found = (tag, version)
        prerelease = bool(meta.get("prerelease"))
        newer = _vs.version_tuple(version) > _vs.version_tuple(here)
        self.btn_apply.setEnabled(newer)
        if newer:
            note = " Это предварительный релиз." if prerelease else ""
            self.btn_apply.setToolTip(
                f"Скачать {version} и применить.{note} Перед применением "
                f"будет сделан бэкап, откат — отдельной кнопкой.")
        else:
            self.btn_apply.setToolTip(
                f"Нечего качать: стоит {here}, а в репозитории {version} — "
                f"не новее. Откат — отдельная кнопка.")

    # -------------------------------------------------------------- применение

    def _apply_clicked(self) -> None:
        if self._busy():
            return
        base = self.program_dir()
        answer = QMessageBox.question(
            self, "Применить обновление",
            "Перед заменой будет сделан бэкап текущей версии.\n"
            "Если что-то пойдёт не так, вернёшься кнопкой "
            "«Вернуть из бэкапа».\n\nПродолжить?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._cancel = False
        self.btn_apply.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # не знаем размера заранее

        tag, version = self._pending()

        def work(progress):
            source = _src.load_source(base)
            into = base / "служебное" / "обновление"
            ok, note = _dl.download(
                source, tag, version, into,
                progress=progress,
                cancel=lambda: self._cancel)
            if not ok:
                progress(f"Не вышло: {note}")
                return (False, note, None)
            archive = into / _src.asset_name(source, version)[0]
            progress("применяю: распаковываю поверх программы…")
            done, text = _selfupdate.apply_update(archive, base,
                                                  progress=progress)
            progress(text)
            return (done, text, archive)

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._apply_done)
        self._worker.start()

    def _pending(self) -> tuple[str, str]:
        """Метка и версия, найденные проверкой.

        Отдельное поле, а не чтение с кнопки: после проверки кнопку могли
        нажать ещё раз, и надпись на ней — это уже другое действие.
        Пустая пара означает «проверка не делалась», и тогда кнопка
        применения остаётся выключенной.
        """
        return self._found or ("", "")

    def _step(self, text: str, kind: str = "info") -> None:
        """Принимает строку потока — вместе с её видом.

        Сигнал `Worker.line` несёт ДВА аргумента: текст и вид («info»
        либо «error»). Я сначала написал здесь «Qt звал бы `setText` с
        двумя, и окно упало бы» — это было неверно, и проверка это
        показала: PyQt6 передаёт приёмнику столько аргументов, сколько
        тот берёт, и лишние отбрасывает МОЛЧА.

        То есть коннект к `setText` работал бы. Просто вид «error»
        потерялся бы, и ошибка читалась бы как обычный ход работы:
        человек увидел бы «Ошибка: …» и не отличил бы её от «скачиваю
        файл 3 из 4». Здесь вид принимается, но намеренно не красит
        текст: панику даёт само сообщение, а не цвет.
        """
        self.lbl_step.setText(text)

    def _apply_done(self) -> None:
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.btn_check.setEnabled(True)
        worker, self._worker = self._worker, None
        if worker is None or worker.result is None:
            return
        ok, note, _archive = worker.result
        if ok:
            QMessageBox.information(
                self, "Обновление применено",
                f"{note}\n\nПрограмму нужно перезапустить, чтобы "
                f"подхватился новый код.")
            self.refresh()

    # -------------------------------------------------------------- откат

    def _rollback_clicked(self) -> None:
        if self._busy():
            return
        base = self.program_dir()
        answer = QMessageBox.question(
            self, "Вернуть из бэкапа",
            "Программа вернётся к состоянию до последнего обновления.\n"
            "Бэкап останется на месте — удалить его можно будет потом.\n\n"
            "Продолжить?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.btn_rollback.setEnabled(False)
        self.lbl_step.setText("возвращаю из бэкапа…")

        def work(progress):
            return _selfupdate.rollback(base)

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._rollback_done)
        self._worker.start()

    def _rollback_done(self) -> None:
        self.btn_check.setEnabled(True)
        worker, self._worker = self._worker, None
        note = ""
        if worker is not None and worker.result is not None:
            result = worker.result
            note = result[1] if isinstance(result, tuple) else str(result)
            if isinstance(result, Exception):
                note = f"не вышло: {result}"
        self.lbl_step.setText(note or "откат завершён")
        self.refresh()

    def _drop_backup_clicked(self) -> None:
        base = self.program_dir()
        answer = QMessageBox.question(
            self, "Удалить бэкап",
            "Бэкап удаляется навсегда: вернуть прошлую версию после этого "
            "не получится.\n\nУдалить?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        ok, note = _selfupdate.drop_backup(base)
        self.lbl_step.setText(note)
        self.refresh()

    def _open_backup(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        backup = _selfupdate._backup_path(self.program_dir())
        if backup.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(backup)))

    # -------------------------------------------------------------- мост

    def _or_dest(self) -> Path:
        """Папка настроек opencode — там лежат данные моста."""
        return _or.find_settings_dir()

    def _or_check_clicked(self) -> None:
        """Живой вопрос официальному GitHub и сравнение с диском."""
        if self._busy():
            return
        dest = self._or_dest()
        self.btn_or_check.setEnabled(False)
        self.lbl_step.setText("спрашиваю официальный GitHub проекта…")

        def work(progress):
            messages: list[str] = []
            errors: list[str] = []
            try:
                _tag, remote = _orupd.latest_version()
            except _orupd.UpdateError as exc:
                return ([], [str(exc)], "")
            if not _orupd.is_newer(_or.installed_version() or "", remote):
                progress(f"В репозитории {remote} — не новее стоящей.")
            found, bad = _orupd.check(dest, remote=remote, progress=progress)
            messages.extend(found)
            errors.extend(bad)
            return (messages, errors, remote)

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._or_check_done)
        self._worker.start()

    def _or_check_done(self) -> None:
        worker, self._worker = self._worker, None
        self.btn_or_check.setEnabled(True)
        if worker is None or not isinstance(worker.result, tuple):
            return
        messages, errors, remote = worker.result
        self._or_remote = remote or ""
        for text in messages:
            self.lbl_step.setText(text)
        for text in errors:
            self.lbl_step.setText(text)
        self.refresh()

    def _or_update_clicked(self) -> None:
        """Поставить найденную версию — после вопроса и живого подтверждения."""
        if self._busy():
            return
        dest = self._or_dest()
        here = _or.installed_version() or "не названа"
        there = self._or_remote
        if not there:
            self.lbl_step.setText(
                "Версия в репозитории не названа: нажми «Проверить».")
            return
        answer = QMessageBox.question(
            self, "Обновить мост OmniRoute",
            f"Сейчас стоит: {here}\n"
            f"Поставлю: {there}\n"
            f"Источник версии: {_orupd.SOURCE_LABEL}\n\n"
            "Установка — это npm install, сотни мегабайт и несколько минут. "
            "Пакет ставится в папку моста, глобальные папки Node.js "
            "не трогаются.\n"
            "Сервер надо будет перезапустить — он работает на старой "
            "версии до перезапуска.\n\nПродолжить?")
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._cancel = False
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.btn_or_update.setEnabled(False)

        def work(progress):
            return _orupd.install(dest, there, progress=progress)

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._or_update_done)
        self._worker.start()

    def _or_update_done(self) -> None:
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.btn_or_check.setEnabled(True)
        worker, self._worker = self._worker, None
        if worker is None or not isinstance(worker.result, tuple):
            return
        messages, errors = worker.result
        for text in messages:
            self.lbl_step.setText(text)
        for text in errors:
            self.lbl_step.setText(text)
        # На диске могла встать новая версия: состояние читается заново,
        # а не по тому, что обещала надпись до установки.
        self.refresh()

    # -------------------------------------------------------------- остановка

    def stop(self) -> None:
        """Вызывается при закрытии окна.

        Флаг, а не `terminate()`: принудительная остановка потока во время
        записи оставила бы недокачанный файл на диске, и следующий запуск
        принял бы его за годный архив. С флагом поток сам доходит до
        безопасной точки и убирает файл.
        """
        self._cancel = True
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(5000)  # дать дойти до точки проверки флага