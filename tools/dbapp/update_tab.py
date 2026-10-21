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
import bridge_updates as _bupd  # noqa: E402
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

        # --- скиллы и агенты во всех базах
        #
        # Отдельный блок по той же причине, что и OmniRoute выше: у него
        # другой источник (папка программы — мастер) и другое действие
        # (доехать до каждой базы, которую программа создала или нашла,
        # а не скачать файл из сети). Смешивать их с обновлением самой
        # программы было бы путаницей: обновление программы меняет папку
        # программы, а это — разносит её содержимое по базам.
        #
        # Кто считается базой: то, что нашёл скан по маркеру, плюс список
        # созданных программой (он переживёт и базу вне рабочего стола).
        box4 = QGroupBox("Скиллы и агенты во всех базах")
        b4 = QVBoxLayout(box4)
        self.lbl_sync_bases = QLabel("—")
        self.lbl_sync_bases.setWordWrap(True)
        self.lbl_sync = QLabel("")
        self.lbl_sync.setWordWrap(True)
        b4.addWidget(label(
            "Источник — папка программы (мастер). Копия приезжает в живую "
            "базу и в каждую созданную базу. Чужие скиллы и папки человека "
            "не трогаются.", kind="dim", wrap=True))
        b4.addWidget(self.lbl_sync_bases)
        row4 = flow_row()
        self.btn_sync_skills = QPushButton("Обновить скиллы")
        self.btn_sync_skills.setToolTip(
            "Скиллы, описание навыков и индекс из папки программы — в живую "
            "базу и во все найденные базы. Реестр серверов и таблица версий "
            "мостов едут с ними же (это одна перевозка).")
        self.btn_sync_skills.clicked.connect(self._sync_skills_clicked)
        self.btn_sync_agents = QPushButton("Обновить агентов")
        self.btn_sync_agents.setToolTip(
            "Папка агентов и реестр агентов (agents-index.json) из папки "
            "программы — в живую базу и во все найденные базы. Скиллы при "
            "этом не трогаются.")
        self.btn_sync_agents.clicked.connect(self._sync_agents_clicked)
        row4.add(self.btn_sync_skills)
        row4.add(self.btn_sync_agents)
        b4.addWidget(row4)
        b4.addWidget(self.lbl_sync)
        outer.addWidget(box4)

        # --- версии мостов у авторов
        #
        # Третий источник, третий блок: у мостов свои издатели (PyPI и
        # npm — те же каналы, с которых мосты и ставятся), и своя таблица
        # (данные/bridge-versions.json). Проверка ничего не меняет; кнопка
        # обновления разблокируется только после проверки и обновляет
        # лишь то, что модуль разрешил: закреплённые мосты она отказывается
        # обновлять словами, потому что их пин живёт в коде программы.
        box5 = QGroupBox("Версии мостов")
        b5 = QVBoxLayout(box5)
        self.lbl_bridge_versions = QLabel("")
        self.lbl_bridge_versions.setWordWrap(True)
        b5.addWidget(label(
            "Что стоит и что вышло у автора — по таблице версий мостов. "
            "Закреплённые мосты (Unity, Godot, TikTok) не обновляются "
            "кнопкой: их пин меняется правкой кода с прогоном тестов, "
            "иначе мост ломается о несовместимую версию.", kind="dim",
            wrap=True))
        row5 = flow_row()
        self.btn_bridge_check = QPushButton("Проверить версии у авторов")
        self.btn_bridge_check.setToolTip(
            "Спрашивает последнюю версию у PyPI и npm для мостов, у которых "
            "пакет назван в таблице версий. Ничего не ставит и не меняет.")
        self.btn_bridge_check.clicked.connect(self._bridge_check_clicked)
        self.btn_bridge_update = QPushButton("Обновить, где можно")
        self.btn_bridge_update.setToolTip(
            "Ставит названную версию автора в окружение того моста, у "
            "которого оно есть (сейчас — kinocut) и нет закрепления. "
            "Закреплённые и npx-мосты честно откажутся. После установки "
            "версия перечитывается из окружения.")
        self.btn_bridge_update.setEnabled(False)
        self.btn_bridge_update.clicked.connect(self._bridge_update_clicked)
        row5.add(self.btn_bridge_check)
        row5.add(self.btn_bridge_update)
        b5.addWidget(row5)
        b5.addWidget(self.lbl_bridge_versions)
        outer.addWidget(box5)

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

        # --- скиллы и агенты: сколько баз затронет кнопка
        # --- скиллы и агенты: сколько баз затронет кнопка
        try:
            bases, skipped = self._bases_for_sync()
        except Exception:  # noqa: BLE001 — скан не должен ронять вкладку
            bases, skipped = [], []
        if bases:
            names = ", ".join(b.name for b in bases)
            shown = names if len(names) <= 120 else names[:117] + "..."
            self.lbl_sync_bases.setText(f"Баз найдено: {len(bases)} — {shown}")
        else:
            self.lbl_sync_bases.setText(
                "Баз не найдено: ни по маркеру, ни в списке созданных. "
                "Кнопке будет нечего обновлять.")
        if skipped:
            self.lbl_sync_bases.setText(
                f"{self.lbl_sync_bases.text()}\n"
                f"Пропущены снимки (бэкапы и копии не обновляются): "
                f"{', '.join(skipped[:4])}"
                + (f" и ещё {len(skipped) - 4}" if len(skipped) > 4 else ""))

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

    # ------------------------------------------------- скиллы и агенты

    def _bases_for_sync(self) -> tuple[list[Path], list[str]]:
        """Куда ехать: живая база, найденные по маркеру и созданные.

        Два источника, потому что каждый чего-то не знает: скан видит
        базы по маркеру на рабочем столе и в DataBases, список созданных
        помнит и те, что лежат в необычном месте. Дубли снимаются — одна
        база из двух источников должна обновиться один раз.

        Бэкапы и копии не едут: у снимка тоже есть маркер базы, но
        обновлять снимок — значит портить его. Пропущенные возвращаются
        вторым списком, чтобы отчёт назвал их словами.
        """
        from core import app_root, read_bases, scan_bases

        found: list[Path] = []
        skipped: list[str] = []
        candidates = list(scan_bases())
        candidates.append(app_root())
        for item in read_bases():
            raw = str(item.get("path", "")).strip()
            if raw:
                candidates.append(Path(raw))
        for path in candidates:
            path = Path(path)
            if path in found:
                continue
            if not (path / "profile.md").is_file():
                continue
            name = path.name.lower()
            if "бэкап" in name or "backup" in name or "копия" in name:
                skipped.append(path.name)
                continue
            found.append(path)
        return found, skipped

    def _sync_clicked(self, kind: str) -> None:
        """Разносит скиллы или агентов из программы по всем найденным базам.

        kind: "skills" — скиллы, описание, индекс и копии файлов программы;
        "agents" — только агенты и их реестр. Ход — в общем Worker вкладки:
        это копирование папок, не минутная установка, но десяток баз на
        медленном диске мог бы заморозить окно.
        """
        if self._busy():
            return
        btn = self.btn_sync_skills if kind == "skills" else self.btn_sync_agents
        other = self.btn_sync_agents if kind == "skills" else self.btn_sync_skills
        btn.setEnabled(False)
        other.setEnabled(False)
        self.lbl_step.setText("обновляю во всех базах…")

        def work(progress):
            from core import refresh_agents, refresh_skills

            bases, skipped = self._bases_for_sync()
            if not bases:
                return (["Баз не найдено: ни по маркеру, ни в списке "
                         "созданных. Обновлять нечего."], [])
            progress(f"баз найдено: {len(bases)}"
                     + (f", снимки пропущены: {len(skipped)}" if skipped
                        else ""))
            messages: list[str] = []
            errors: list[str] = []
            for base in bases:
                progress(base.name)
                try:
                    if kind == "skills":
                        msgs = refresh_skills(base)
                    else:
                        msgs = refresh_agents(base)
                except Exception as exc:  # noqa: BLE001 — база с бедой не
                    # должна обрывать остальные: доедем до каждой.
                    errors.append(f"{base.name}: не удалось ({exc})")
                    continue
                tail = "; ".join(msgs) if msgs else "уже свежее"
                messages.append(f"{base.name}: {tail}")
            return (messages, errors)

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._sync_done)
        self._worker.start()

    def _sync_skills_clicked(self) -> None:
        self._sync_clicked("skills")

    def _sync_agents_clicked(self) -> None:
        self._sync_clicked("agents")

    def _sync_done(self) -> None:
        worker, self._worker = self._worker, None
        self.btn_sync_skills.setEnabled(True)
        self.btn_sync_agents.setEnabled(True)
        if worker is None:
            return
        result = worker.result
        if isinstance(result, Exception):
            self.lbl_sync.setText(f"не вышло: {result}")
        elif isinstance(result, tuple):
            messages, errors = result
            report = list(messages) + list(errors)
            self.lbl_sync.setText("\n".join(report) if report else "готово")
        else:
            self.lbl_sync.setText(str(result))

    # ------------------------------------------------------- версии мостов

    def _bridge_check_clicked(self) -> None:
        """Спрашивает у издателей последнюю версию каждого моста.

        Проверка — только чтение: PyPI и npm отдают номер, программа
        сравнивает с таблицей и пишет словами. Ничего не ставится.
        """
        if self._busy():
            return
        self.btn_bridge_check.setEnabled(False)
        self.btn_bridge_update.setEnabled(False)
        self.lbl_step.setText("спрашиваю у издателей пакетов…")

        def work(progress):
            progress("PyPI и npm…")
            return _bupd.check_all(self._settings_dir())

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._bridge_check_done)
        self._worker.start()

    def _bridge_check_done(self) -> None:
        worker, self._worker = self._worker, None
        self.btn_bridge_check.setEnabled(True)
        if worker is None:
            return
        result = worker.result
        if isinstance(result, Exception):
            self.lbl_bridge_versions.setText(f"не вышло: {result}")
            return
        rows, errors = result if isinstance(result, tuple) else ([], [])
        if errors:
            self.lbl_bridge_versions.setText("\n".join(errors))
            return
        self._bridge_rows = rows
        report = []
        updatable = 0
        for row in rows:
            report.append(
                f"{row['bridge']}: стоит {row['installed'] or '—'} | "
                f"у автора {row['latest'] or 'не ответил'} — {row['verdict']}")
            if row["verdict"] == "можно обновить":
                updatable += 1
        self.btn_bridge_update.setEnabled(updatable > 0 and not self._busy())
        self.lbl_bridge_versions.setText("\n".join(report) or "нет данных")

    def _bridge_update_clicked(self) -> None:
        """Обновляет то, что проверка назвала обновляемым.

        Кнопка живёт по правилу вкладки: выключена, пока проверка не
        назвала, что именно можно ставить. Сама установка ещё раз
        спросит у модуля — закреплённый мост откажется словами, даже
        если вердикт устарел.
        """
        if self._busy():
            return
        rows = list(getattr(self, "_bridge_rows", []))
        updatable = [row for row in rows
                     if row["verdict"] == "можно обновить"]
        if not updatable:
            self.lbl_bridge_versions.setText(
                "Обновлять нечего: ни один мост не назван «можно обновить».")
            return
        names = "\n".join(
            f"{row['bridge']} → {row['latest']}" for row in updatable)
        answer = QMessageBox.question(
            self, "Обновить мосты",
            "Поставить названную версию в окружение этих мостов?\n\n"
            + names + "\n\nЗакреплённые мосты не тронутся — откажутся "
            "сами, словами.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.btn_bridge_check.setEnabled(False)
        self.btn_bridge_update.setEnabled(False)
        self.lbl_step.setText("обновляю окружения мостов…")

        def work(progress):
            settings = self._settings_dir()
            messages: list[str] = []
            errors: list[str] = []
            for row in updatable:
                progress(row["bridge"])
                done, failed = _bupd.install(
                    row["bridge"], str(row["latest"]), settings,
                    progress=progress)
                messages.extend(done)
                errors.extend(failed)
            return (messages, errors)

        self._worker = Worker(work)
        self._worker.line.connect(self._step)
        self._worker.finished.connect(self._bridge_update_done)
        self._worker.start()

    def _bridge_update_done(self) -> None:
        worker, self._worker = self._worker, None
        self.btn_bridge_check.setEnabled(True)
        if worker is None:
            return
        result = worker.result
        lines: list[str] = []
        if isinstance(result, Exception):
            lines.append(f"не вышло: {result}")
        elif isinstance(result, tuple):
            messages, errors = result
            lines = list(messages) + list(errors)
        self.lbl_bridge_versions.setText("\n".join(lines) or "готово")
        # Свежий отчёт вместо вчерашнего: то, что поставилось, должно
        # пройти проверку ещё раз — это и есть пост-проверка.
        self._bridge_check_clicked()

    def _settings_dir(self) -> Path:
        from core import PROGRAMS_BY_ID

        return PROGRAMS_BY_ID["opencode"].config_dir()

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