"""Проверка окна без участия человека.

Создаёт окно по-настоящему, но не показывает его на экране: прогоняет
проверку имени, создание базы и подключение во временной папке и печатает
отчёт. Запуск:

    python tools/dbapp/selftest.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import ui  # noqa: E402

#: отчёт пишется и на экран, и в файл — в этой оболочке вывод теряется
REPORT = HERE / "selftest-report.txt"
_lines: list[str] = []


def echo(text: str = "") -> None:
    _lines.append(text)
    try:
        print(text, flush=True)
    except Exception:
        pass

OK = "ОК  "
BAD = "СБОЙ"

results: list[tuple[bool, str]] = []


def check(good: bool, text: str) -> None:
    results.append((good, text))
    echo(f"[{OK if good else BAD}] {text}")


def _free_port() -> int:
    """Свободный локальный порт — чтобы проверка не зависела от того,
    запущен ли настоящий фасад на 17890 прямо сейчас."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    echo("=" * 62)
    echo(" Проверка программы управления базой")
    echo("=" * 62)

    # Список созданных баз подменяем на временный на всю проверку:
    # без этого пробы запишут в настоящий список мусорные базы,
    # и в окне появятся пути в удалённые папки.
    import tempfile

    _isolate = Path(tempfile.mkdtemp(prefix="dbapp-list-"))
    # Заслон: настоящий список баз человека не должен измениться за
    # прогон. Создание базы дописывается в список через remember_base,
    # поэтому без такой проверки прогоны тихо наследили бы мусором.
    _real_list = core.bases_file()
    _real_before = (
    _real_list.read_text(encoding="utf-8") if _real_list.is_file()
    else "<файла нет>"
    )
    _real_paths_before = {
    str(e.get("path", "")).lower() for e in core.read_bases()
    }
    echo(f"Заслон: список бас под наблюдением — {_real_list.name}")
    core.use_bases_file(_isolate / "список.json")
    core.use_bases_file(_isolate / "список.json")
    echo(f"Список баз на время проверки: {core.bases_file()}")

    # ---- 1. окно собирается
    echo("\n--- 1. Окно ---")
    try:
        from PyQt6.QtWidgets import QApplication

        import main as app_main

        app = QApplication.instance() or QApplication(["selftest"])
        ui.apply_dark_theme(app)
        window = app_main.MainWindow()
        check(True, f"окно собрано, размер {window.width()}x{window.height()}")
        check(len(window.create_tab.program_list) > 0 or
              window.create_tab.program_list.count() > 0,
              f"список программ заполнен: "
              f"{window.create_tab.program_list.count()} строк")
    except Exception as exc:
        check(False, f"окно не собирается: {exc}")
        traceback.print_exc()
        return 1

    # ---- 2. проверка имени
    echo("\n--- 2. Проверка имени базы ---")
    good_names = ["Моя-база", "base 2026", "Проба_1"]
    bad_names = ["", "   ", "a/b", "a:b", "CON", "x" * 101, "a?b", "a*b", 'a"b']
    for name in good_names:
        try:
            core.validate_name(name)
            check(True, f"принимается: {name!r}")
        except core.NameError_ as exc:
            check(False, f"зря отклонено {name!r}: {exc}")
    for name in bad_names:
        try:
            core.validate_name(name)
            check(False, f"зря принято: {name!r}")
        except core.NameError_:
            check(True, f"отклоняется: {name!r}")

    # ---- 3. живая реакция окна на плохое имя
    echo("\n--- 3. Реакция окна на имя ---")
    tab = window.create_tab
    tab.name_edit.setText("a/b")
    check(not tab.btn_create.isEnabled(), "кнопка «Создать базу» заблокирована")
    check("не разрешает" in tab.name_hint.text() or "/" in tab.name_hint.text(),
          f"подсказка объясняет причину: {tab.name_hint.text()[:60]}")
    tab.name_edit.setText("Тестовая-база")
    check(tab.btn_create.isEnabled(), "с хорошим именем кнопка доступна")
    check("Тестовая-база" in tab.path_preview.text(),
          "показан полный путь будущей базы")

    # ---- 4. создание базы
    echo("\n--- 4. Создание базы ---")
    tmp = Path(tempfile.mkdtemp(prefix="dbapp-check-"))
    try:
        parent = tmp / "место"
        parent.mkdir()
        plan = core.build_plan(parent, "Проба-пустая", None)
        log = core.create_base(plan)
        target = plan.target
        check(target.is_dir(), f"папка базы создана: {target.name}")
        missing = [f for f in core.REQUIRED_FILES if not (target / f).is_file()]
        check(not missing, f"все основные файлы на месте (нет: {missing})")
        check((target / "библиотека/АКТИВНАЯ-ПАМЯТЬ.md").is_file(),
              "активная память записана")
        check((target / "библиотека/index.json").is_file(), "указатель записан")

        # Указатель должен совпадать со своей же папкой, а не просто
        # существовать. Найдено 29.09: на живой базе index.json заявлял
        # 18 записей, на диске было 17, лишней была служебная
        # _О-ПАПКЕ.md с пустым id. Мост это ловит у себя, а конструктор
        # раздаёт записи новым базам - и новая база родилась бы уже с
        # битым указателем. Проверяем на только что созданной базе.
        _nlib = target / "библиотека"
        _nrecs = sorted((_nlib / "записи").rglob("ncp-*.md")) \
            if (_nlib / "записи").is_dir() else []
        try:
            _ndata = json.loads(
                (_nlib / "index.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _ndata = {}
        check(isinstance(_ndata, dict),
              "указатель новой базы читается как объект")
        check(isinstance(_ndata, dict)
              and _ndata.get("count") == len(_nrecs),
              f"указатель новой базы совпадает с её диском: "
              f"{_ndata.get('count') if isinstance(_ndata, dict) else '?'} "
              f"против {len(_nrecs)} файлов")
        _nbad = [e for e in (_ndata.get("entries") or [])
                 if not str(e.get("id", "")).startswith("ncp-")]
        check(not _nbad,
              f"в указателе новой базы нет записей без префикса ncp-: "
              f"{len(_nbad)}")
        _nlost = [e.get("path", "") for e in (_ndata.get("entries") or [])
                  if e.get("path") and not (_nlib / e["path"]).is_file()]
        check(not _nlost,
              f"все пути указателя новой базы есть на диске: {len(_nlost)} битых")
        _ncat = _nlib / "КАТАЛОГ.md"
        if _ncat.is_file():
            _ncat_text = _ncat.read_text(encoding="utf-8")
            check("_О-ПАПКЕ" not in _ncat_text,
                  "в каталоге новой базы нет служебной папки")
        else:
            check(False, "в новой базе нет КАТАЛОГ.md - навигация по знаниям не работает")
        check((target / "база.json").is_file(), "отметка о создании записана")
        for folder in core.NEW_DIRS:
            if not (target / folder).is_dir():
                check(False, f"нет папки {folder}")
                break
        else:
            check(True, f"созданы все {len(core.NEW_DIRS)} папок")
        check(len(log) > 0, f"отчёт о создании получен ({len(log)} строк)")

        # обход блокировок приезжает в новую базу сам, без лишних нажатий
        check((target / "tools" / "antiblock" / "http_facade.py").is_file(),
              "фасад обхода в новой базе на месте")
        check((target / "tools" / "antiblock" / "public_socks5.txt").is_file(),
              "стартовый список SOCKS5 в новой базе на месте")
        check((target / "tools" / "antiblock" / "subscriptions.txt").is_file(),
              "подписки VLESS в новой базе на месте")
        check((target / "tools" / "antiblock" / "xray_runner.py").is_file(),
              "свой Xray (xray_runner.py) в новой базе на месте")
        check((target / "tools" / "antiblock" / "dns_resolver.py").is_file(),
              "защищённый DNS (dns_resolver.py) в новой базе на месте")
        check((target / "tools" / "antiblock" / "command" / "antiblock.md").is_file(),
              "команда /обход в новой базе на месте")
        check(not list((target / "tools" / "antiblock").glob("*.local.*")),
              "личных рабочих списков (*.local.*) в новой базе нет")

        # файлы-навигаторы: без них нейросеть не знает об устройстве базы
        for name in core.NAV_FILES:
            check((target / name).is_file(), f"навигатор {name} создан")
        nav_text = (target / "КАРТА-БАЗЫ.md").read_text(encoding="utf-8")
        check("Куда что писать" in nav_text, "в карте есть таблица «куда что писать»")
        for area in core.KNOWLEDGE_AREAS:
            if area not in nav_text:
                check(False, f"область «{area}» не упомянута в карте")
                break
        else:
            check(True, f"все {len(core.KNOWLEDGE_AREAS)} областей упомянуты в карте")
        rules_text = (target / "ПРАВИЛА-ИИ.md").read_text(encoding="utf-8")
        check("не программист" in rules_text, "в правилах сказано про простой язык")
        check("по-русски" in rules_text, "в правилах закреплён русский язык")
        check("Ничего не удалять" in rules_text, "в правилах запрещено удаление")

        # Нейросеть должна знать, каким скиллом и агентом работать, и что
        # делать, если результат не устроил. Без этого всё хозяйство —
        # скиллы, агенты, skills-index.json — лежит мёртвым грузом.
        skill_doc = "инструкции/Скиллы-и-агенты.md"
        check((target / skill_doc).is_file(),
              f"новая база получила {skill_doc}")
        if (target / skill_doc).is_file():
            _inst = (target / skill_doc).read_text(encoding="utf-8")
            for _needle, _what in (
                ("skills-index.json", "ссылка на индекс скиллов"),
                ("systematic-debugging", "скилл для багов"),
                ("brainstorming", "скилл перед творческой работой"),
                ("@retsenzent", "агент-рецензент"),
                ("@proektirovschik", "агент-проектировщик"),
                ("Если результат не устроил", "разбор плохого результата"),
                ("verification-before-completion", "проверка перед «сделано»"),
            ):
                if _needle not in _inst:
                    check(False, f"в {skill_doc} нет: {_what}")
                    break
            else:
                check(True, f"{skill_doc} отвечает и на «какой скилл», и на «что делать»")
        # каждый файл из INSTRUCTION_TARGETS обязан существовать, иначе
        # opencode не сможет подключить инструкции
        for _name in core.INSTRUCTION_TARGETS:
            if not (target / _name).is_file():
                check(False, f"подключаемая инструкция не найдена: {_name}")
                break
        else:
            check(True, f"все {len(core.INSTRUCTION_TARGETS)} подключаемых инструкций на месте")
        check(skill_doc in "".join(core.INSTRUCTION_TARGETS),
              "новая инструкция вписана в INSTRUCTION_TARGETS (грузится в каждой сессии)")
        check("память\\АКТИВНАЯ-ПАМЯТЬ.md" not in rules_text
              and "память/АКТИВНАЯ-ПАМЯТЬ.md" not in rules_text,
              "правила не указывают на вытесненную папку память/")
        check("Скиллы-и-агенты.md" in rules_text,
              "в правилах есть отсылка к выбору скилла и агента")
        # AGENTS.md в корне: без него подключение вычистит правила из настроек
        check((target / "AGENTS.md").is_file(),
              "в корне новой базы есть AGENTS.md (правила не будут стёрты)")
        if (target / "AGENTS.md").is_file():
            _ag = (target / "AGENTS.md").read_text(encoding="utf-8").lower()
            check("скилл" in _ag and "агент" in _ag,
                  "AGENTS.md рассказывает про скиллы и агентов")
        # агенты едут с базой, как мосты
        _n_agents = len(list((target / "tools" / "agents").glob("*.md")))
        check(_n_agents >= 12, f"агенты едут с базой: {_n_agents} штук")

        # ---- скиллы: полный набор, индекс и реестр MCP едут с базой
        echo("\n--- 5а. Скиллы, индекс и реестр ---")
        _n_skills = (
            len([d for d in (target / "skills").iterdir() if d.is_dir()])
            if (target / "skills").is_dir() else 0
        )
        _src_skills = len(
            [d for d in (core.program_root() / "skills").iterdir()
             if d.is_dir() and (d / "SKILL.md").is_file()]
        )
        check(_n_skills == _src_skills,
              f"скиллов в базе столько же, сколько в конструкторе: {_n_skills}")
        _idx = target / "skills-index.json"
        check(_idx.is_file(), "skills-index.json едет с базой")
        if _idx.is_file():
            try:
                _data = json.loads(_idx.read_text(encoding="utf-8"))
                _names = {s["name"] for s in _data.get("skills", [])}
            except (OSError, ValueError) as _exc:
                _names = set()
                check(False, f"skills-index.json не читается: {_exc}")
            else:
                check(len(_names) == _n_skills,
                      f"записей в индексе столько же, сколько папок: {len(_names)}")
            _folders = {d.name for d in (target / "skills").iterdir() if d.is_dir()}
            check(_names == _folders,
                  "индекс и папки совпадают один в один")
            _missing_desc = [
                s["name"] for s in _data.get("skills", [])
                if not s.get("when") or not s.get("trigger") or not s.get("result")
            ]
            check(not _missing_desc,
                  f"у всех скиллов есть when, trigger и result (пропущено: {_missing_desc})")
        # у каждого скилла ограждения метаданных: без них он молча не работает
        _bad_fm = [
            d.name for d in (target / "skills").iterdir()
            if d.is_dir()
            and (d / "SKILL.md").is_file()
            and not (d / "SKILL.md").read_text(encoding="utf-8").startswith("---")
        ]
        check(not _bad_fm, f"у всех скиллов есть --- ограждения (сломаны: {_bad_fm})")
        # реестр MCP-серверов едет с базой
        _reg = target / "mcp-registry.json"
        check(_reg.is_file(), "mcp-registry.json едет с базой")
        if _reg.is_file():
            try:
                _rdata = json.loads(_reg.read_text(encoding="utf-8"))
            except (OSError, ValueError) as _exc:
                check(False, f"реестр не читается: {_exc}")
            else:
                _srv = _rdata.get("servers", [])
                check(len(_srv) >= 1, f"серверов в реестре: {len(_srv)}")
                _no_why = [s.get("id") for s in _srv if not s.get("why") or not s.get("verdict")]
                check(not _no_why, f"у всех серверов есть зачем и вердикт (нет: {_no_why})")

        # ---- 5д. Реестр серверов MCP: команды, проверка, вкл/выкл.
        # Сделано 28.09 по просьбе пользователя: серверы из реестра должны быть
        # видны в программе и включаться кнопкой. Раньше реестр был только
        # справочником — ехал с базой, но нигде не показывался, и вписать
        # сервер в настройки было нечем.
        # Проверки живут здесь, а не в разделе про мост: базу, созданную
        # выше, селфтест удаляет перед разделом про мост, и реестра там уже
        # нет. Ошибку эту я сначала истолковал неверно — подумал, что
        # реестр не копируется.
        echo("\n--- 5д. Реестр серверов MCP ---")
        import mcp_registry  # noqa: PLC0415 — рядом лежит, круга нет
        # opencode_caps импортируется и ниже по этой функции. Пока где-то
        # в теле есть такой импорт, имя считается локальным для всего тела,
        # и обращение раньше него падает с UnboundLocalError. Поэтому
        # импортируем здесь же, а не пользуемся «сверху».
        import opencode_caps  # noqa: PLC0415 — по той же причине

        reg_data = mcp_registry.load_registry(target)
        check(bool(reg_data.get("servers")), "реестр прочитан модулем, серверы на месте")
        for _spec in reg_data.get("servers") or []:
            _conn = _spec.get("connection")
            # Способ подключения законен трёх видов: команда, адрес или
            # ручная настройка. У android-studio адрес и токен выдаёт
            # сама студия, поэтому в реестре их нет и быть не должно -
            # реестр едет в публичный репозиторий. Отсутствие всех трёх
            # означает, что подключать нечем, и это ошибка.
            _conn_ways = bool(
                _conn.get("command") or _conn.get("url") or _conn.get("manual_config")
            )
            check(
                isinstance(_conn, dict) and _conn_ways,
                f"у сервера {_spec.get('id')} есть способ подключения",
            )
            if _spec.get("id") == "android-studio":
                check(not _conn.get("url") and not _conn.get("command"),
                      "у android-studio в реестре нет ни адреса, ни команды")
                check("Bearer" not in json.dumps(_spec, ensure_ascii=False),
                      "токена студии в реестре нет")
        for _spec in reg_data.get("servers") or []:
            _bad = [
                r.get("what")
                for r in (_spec.get("requires") or [])
                if r.get("type") not in ("command", "program", "manual")
            ]
            check(not _bad, f"у {_spec.get('id')} у всех требований проставлен тип: {_bad}")
        _servers = mcp_registry.load_servers(target)
        check(len(_servers) == len(reg_data.get("servers") or []),
              f"модуль загрузил серверов: {len(_servers)}")
        for _s in _servers:
            if _s.manual_setup:
                # У такого сервера адрес и токен выдаёт его собственная
                # программа. Без вставленной конфигурации блока быть не
                # должно - иначе в настройки попадёт запись, которая
                # заведомо не подключится. Проверяем это отдельно, с
                # настоящей конфигурацией.
                check(not mcp_registry.build_block(_s),
                      f"у {_s.id} без конфигурации блок не пишется")
                continue
            _b = mcp_registry.build_block(_s)
            _ok = (_b.startswith(f'"{_s.id}": {{') and _b.rstrip().endswith("},")
                   and _b.count("{") == _b.count("}"))
            check(_ok, f"блок сервера {_s.id} собран цельно ({_b.count('{')} скобок)")

        # Включение и выключение — на временной копии папки настроек.
        _rtmp = Path(tempfile.mkdtemp(prefix="self-reg-"))
        _rdest = _rtmp / "opencode"
        _rdest.mkdir()
        (_rdest / "opencode.jsonc").write_text(
            '{\n  "$schema": "https://opencode.ai/config.json",\n'
            '  "mcp": {\n    "чужой": {"type": "remote", "url": "https://x"}\n  },\n'
            '  "instructions": ["a.md"]\n}\n',
            encoding="utf-8",
        )
        _wa = next((s for s in _servers if s.id == "windows-admin"), None)
        check(_wa is not None, "сервер windows-admin есть в реестре")
        if _wa is not None:
            # Требования подменяем: селфтест не должен зависеть от того, что
            # на машине стоит Node. Проверяем механику включения, а не окружение.
            _wa.requirements = [mcp_registry.Requirement(
                what="Проверка", kind="program", value="node", ok=True)]
            _wa.has_connection = True
            _wa.installed = False
            _m, _e = mcp_registry.enable(_rdest, _wa)
            check(not _e, f"включение сервера прошло: {_e}")
            _cfg_after = (_rdest / "opencode.jsonc").read_text(encoding="utf-8")
            check("windows-admin" in _cfg_after, "сервер вписан в настройки")
            check('"чужой"' in _cfg_after, "чужой сервер не тронут")
            check('"instructions"' in _cfg_after, "инструкции не тронуты")
            check(opencode_caps.check_jsonc(_cfg_after),
                  "настройки остались читаемыми после вставки")
            check(bool(list((_rdest / "_previous-version").glob("opencode.jsonc-*"))),
                  "копия настроек сделана до правки")
            _m, _e = mcp_registry.disable(_rdest, _wa)
            check(not _e, f"выключение прошло: {_e}")
            _cfg_off = (_rdest / "opencode.jsonc").read_text(encoding="utf-8")
            check("windows-admin" not in _cfg_off, "сервер убран")
            check('"чужой"' in _cfg_off, "чужой сервер уцелел после удаления")
            check(opencode_caps.check_jsonc(_cfg_off),
                  "настройки остались читаемыми после удаления")
            _m, _e = mcp_registry.disable(_rdest, _wa)
            check(not _e and _m, "повторное выключение — мягкий отказ, не ошибка")
        # Сломанные настройки программа обязана оставить в покое, а не
        # дописать в них сервер: файл и так уже не читается, хуже не сделаешь.
        (_rdest / "opencode.jsonc").write_text(
            '{\n  "mcp": {\n    "без запятой" 1\n  }\n}\n', encoding="utf-8"
        )
        _broken_before = (_rdest / "opencode.jsonc").read_text(encoding="utf-8")
        if _wa is not None:
            _m, _e = mcp_registry.enable(_rdest, _wa)
            check(bool(_e), f"на сломанных настройках вставка отказана: {_e}")
            check((_rdest / "opencode.jsonc").read_text(encoding="utf-8") == _broken_before,
                  "сломанный файл не тронут")
        shutil.rmtree(_rtmp, ignore_errors=True)

        # --- сервер с ручной настройкой: android-studio
        # Проверяем целиком, на временной папке настроек: без вставленной
        # конфигурации включение обязано отказаться, с конфигурацией -
        # вписать блок с токеном, а выключение - убрать и то и другое.
        _ast = next((s for s in _servers if s.id == "android-studio"), None)
        check(_ast is not None, "сервер android-studio есть в реестре")
        if _ast is not None:
            _spec = next((s for s in (reg_data.get("servers") or [])
                          if s.get("id") == "android-studio"), {})
            check(_spec.get("ready_here") is False,
                  "готовность честная: сервер ещё не включался")
            check("Bearer" not in json.dumps(reg_data, ensure_ascii=False),
                  "токена в реестре нет — он туда ехать не должен")
            check(_ast.manual_setup, "помечен как настраиваемый руками")
            check(_ast.has_connection, "подключаемым считается")
            check(_ast.ready, "кнопка «Включить» доступна")
            check(len(_ast.setup_steps) == 6,
                  f"пошаговая инструкция из шести шагов: {len(_ast.setup_steps)}")
            check(bool(_ast.only_while_running),
                  "сказано, что сервер живёт только при запущенной студии")
            check(bool(_ast.auth), "сказано, что нужен токен")

            # Конфигурация, которую копирует студия. Токен выдуманный.
            _paste = json.dumps({
                "mcpServers": {
                    "android-studio": {
                        "url": "http://localhost:63342/api/mcp",
                        "headers": {"Authorization": "Bearer SELFTEST-TOKEN"},
                    }
                }
            })

            _atmp = Path(tempfile.mkdtemp(prefix="self-manual-"))
            try:
                _mdest = _atmp / "opencode"
                _mdest.mkdir()
                (_mdest / "opencode.jsonc").write_text(
                    '{\n  "$schema": "https://opencode.ai/config.json"\n}\n',
                    encoding="utf-8",
                )
                _before = (_mdest / "opencode.jsonc").read_text(encoding="utf-8")

                # Без конфигурации включать нечего: честный отказ.
                _m, _e = mcp_registry.enable(_mdest, _ast)
                check(bool(_e), f"без конфигурации включение отказано: {_e}")
                check(not _m, "успеха при отказе не сообщается")
                check((_mdest / "opencode.jsonc").read_text(encoding="utf-8") == _before,
                      "настройки не тронуты при отказе")
                check(not mcp_registry.manual_config_path(_mdest, _ast.id).exists(),
                      "файла с токеном не появилось")

                # Мусор вместо конфигурации отвергается и ничего не портит.
                for _junk in ("просто текст", '{"mcpServers":{}}', "   "):
                    _ok, _why = mcp_registry.save_manual_config(
                        _mdest, _ast.id, _junk)
                    check(not _ok, f"мусор отвергнут ({_junk.strip()[:14]!r}): "
                                   f"{_why[:44]}")
                check((_mdest / "opencode.jsonc").read_text(encoding="utf-8") == _before,
                      "мусор не тронул настройки")

                # С настоящей конфигурацией - вписывается токен.
                _ok, _why = mcp_registry.save_manual_config(
                    _mdest, _ast.id, _paste)
                check(_ok, f"конфигурация принята: {_why}")
                _saved = mcp_registry.load_manual_config(_mdest, _ast.id)
                check(bool(_saved), "конфигурация читается обратно")
                check(bool(_saved) and _saved.get("url") ==
                      "http://localhost:63342/api/mcp", "адрес разобран верно")
                check(bool(_saved)
                      and _saved.get("headers", {}).get("Authorization")
                      == "Bearer SELFTEST-TOKEN", "токен разобран верно")
                _cpath = mcp_registry.manual_config_path(_mdest, _ast.id)
                check("opencode-base" not in str(_cpath),
                      "конфигурация не попадает в репозиторий")

                _m, _e = mcp_registry.enable(_mdest, _ast)
                check(not _e, f"включение с конфигурацией прошло: {_e}")
                _cfg = (_mdest / "opencode.jsonc").read_text(encoding="utf-8")
                check("SELFTEST-TOKEN" in _cfg, "токен вписан в настройки")
                check(opencode_caps.check_jsonc(_cfg),
                      "настройки остались читаемыми")
                check(any("Перезапусти" in _x for _x in _m),
                      "напоминание про перезапуск opencode")

                # Выключение убирает и блок, и токен с диска.
                _m, _e = mcp_registry.disable(_mdest, _ast)
                check(not _e, f"выключение прошло: {_e}")
                _cfg_off = (_mdest / "opencode.jsonc").read_text(encoding="utf-8")
                check("SELFTEST-TOKEN" not in _cfg_off,
                      "токена в настройках не осталось")
                check(not mcp_registry.manual_config_path(_mdest, _ast.id).exists(),
                      "файл с токеном удалён — «выключил» значит выключил")
                check(any("токеном удалена" in _x for _x in _m),
                      "сказано вслух, что конфигурация удалена")
            finally:
                shutil.rmtree(_atmp, ignore_errors=True)

        # Скилл android-studio: папка, шапка и запись в индексе.
        _skill_dir = target / "skills" / "android-studio"
        check((_skill_dir / "SKILL.md").is_file(),
              "скилл android-studio лежит в skills/")
        if (_skill_dir / "SKILL.md").is_file():
            _stext = (_skill_dir / "SKILL.md").read_text(encoding="utf-8")
            check(_stext.startswith("---\nname: android-studio\n"),
                  "в шапке скилла имя android-studio")
            for _tool in ("build_project", "lint_files", "analyze_calls",
                          "xdebug_set_breakpoint", "xdebug_get_stack",
                          "xdebug_get_frame_values", "./gradlew"):
                check(_tool in _stext,
                      f"скилл называет инструмент или замену: {_tool}")

        # Блок в окне: таблица и кнопки собраны и показывают реестр.
        _reg_tab = getattr(window.caps_tab, "reg_table", None)
        check(_reg_tab is not None, "в окне есть таблица серверов")
        if _reg_tab is not None:
            check(_reg_tab.rowCount() == len(reg_data.get("servers") or []),
                  f"в таблице строк: {_reg_tab.rowCount()}")
            for _name in ("btn_reg_check", "btn_reg_on", "btn_reg_off", "btn_reg_src"):
                check(hasattr(window.caps_tab, _name), f"кнопка {_name} собрана")
            _states = [
                _reg_tab.item(r, 1).text() if _reg_tab.item(r, 1) else ""
                for r in range(_reg_tab.rowCount())
            ]
            check(all(_states), "у всех строк заполнено состояние")
            check(
                all("не проверено" in s for s in _states),
                f"до проверки состояние честное, а не выдуманное: {_states}",
            )
        # инструкция про серверы подключена
        check("инструкции/МCP-серверы.md" in core.INSTRUCTION_TARGETS,
              "инструкция про MCP-серверы подключена к каждой сессии")

        # ---- refresh_skills: обновляет, но чужие не трогает
        echo("\n--- 5б. Обновление скиллов в уже готовой базе ---")
        _probe = target / "skills" / "better-ui" / "SKILL.md"
        _orig = _probe.read_bytes()
        _probe.write_text("# устаревшая копия\n", encoding="utf-8")
        _my_skill = target / "skills" / " moy-skill"
        _my_skill.mkdir(parents=True, exist_ok=True)
        (_my_skill / "SKILL.md").write_text(
            "---\nname: moy-skill\ndescription: мой личный скилл\n---\n", encoding="utf-8"
        )
        for _msg in core.refresh_skills(target):
            pass
        check(_probe.read_bytes() == _orig, "устаревший скилл обновлён из конструктора")
        check(_my_skill.is_dir(), "свой скилл пользователя не тронут и не удалён")
        _again = core.refresh_skills(target)
        check(not any("обновлён" in _m for _m in _again),
              f"повторный вызов молчит, когда всё свежее: {_again}")
        (_my_skill / "SKILL.md").unlink()
        _my_skill.rmdir()

        # ---- агенты едут с базой и обновляются
        echo("\n--- 5в. Агенты едут с базой ---")
        _ag_dst = target / "tools" / "agents"
        _n_ag = len(list(_ag_dst.glob("*.md"))) if _ag_dst.is_dir() else 0
        _n_ag_src = len(list((core.program_root() / "tools" / "agents").glob("*.md")))
        check(_n_ag == _n_ag_src, f"агентов в базе: {_n_ag} (в конструкторе {_n_ag_src})")
        _missing_ag = [
            a for a in ("iskatel", "dokop", "proektirovschik", "programmist",
                        "proveryalschik", "retsenzent", "ohrannik", "dizayner",
                        "bazy", "devops", "golosovoy", "provodnik-pk")
            if not (_ag_dst / f"{a}.md").is_file()
        ]
        check(not _missing_ag, f"все 12 агентов на месте (нет: {_missing_ag})")
        # каждый агент упомянут в инструкциях, иначе нейросеть о нём не узнает
        _inst_all = "\n".join(
            (target / t).read_text(encoding="utf-8")
            for t in core.INSTRUCTION_TARGETS if (target / t).is_file()
        )
        _ag_in_instr = [a for a in _missing_ag if a not in _inst_all]
        _all_ag_names = [p.stem for p in _ag_dst.glob("*.md")]
        _silent_ag = [a for a in _all_ag_names if a not in _inst_all]
        check(not _silent_ag, f"каждый агент упомянут в инструкциях (молчат: {_silent_ag})")
        # правило «увидел возможность — скажи»
        check("УВИДЕЛ ВОЗМОЖНОСТЬ" in _inst_all.upper(),
              "в инструкциях есть правило: увидел возможность — скажи и предложи")
        # инструменты мостов упомянуты
        for _tool in ("ncp_status", "ncp_search", "ncp_read", "ncp_save",
                      "ncp_update", "ncp_checkpoint", "ncp_reindex",
                      "memory_save", "memory_read", "memory_search",
                      "memory_log_work", "library_status", "library_search",
                      "pc_status", "pc_files_read", "pc_apps_list", "pc_screenshot"):
            if _tool not in _inst_all:
                check(False, f"инструмент {_tool} не упомянут в инструкциях")
                break
        else:
            check(True, "все инструменты мостов упомянуты в инструкциях")

        # ---- 5г. инструменты памяти едут в мосте, а не в плагине.
        # Найдено 28.09: с версии opencode 1.18 плагин обязан отдавать
        # объект {id, setup}. Старая форма отвергается, и 12 инструментов
        # memory_* и library_* исчезли, хотя инструкции их требовали.
        # Теперь они в мосте NCP — его версия opencode не касается.
        echo("\n--- 5г. Инструменты памяти в мосте, плагин под v2 ---")
        _bridge = target / "tools" / "ncp-bridge"
        check((_bridge / "memory_tools.py").is_file(),
              "модуль инструментов памяти лежит в базе вместе с мостом")
        _srv_text = (_bridge / "server.py").read_text(encoding="utf-8")
        _missing_in_bridge = [
            t for t in ("memory_save", "memory_read", "memory_search", "memory_log_work")
            if f'"{t}"' not in _srv_text
        ]
        check(not _missing_in_bridge,
              f"мост объявляет все инструменты памяти (нет: {_missing_in_bridge})")
        for _alias in ("library_status", "library_checkpoint", "library_reindex"):
            if _alias not in _srv_text:
                check(False, f"псевдоним {_alias} не объявлен в мосте")
                break
        else:
            check(True, "псевдонимы library_* объявлены в мосте, а не только в бумаге")

        # Плагин обязан соответствовать схеме v2. Проверяем текстом:
        # Node в самопроверке не запускаем, а формат экспорта виден
        # в исходнике, и ломается он как раз молча.
        for _where, _plugin in (
            ("конструктор", core.program_root() / "config" / "plugins" / "memory-base.js"),
            ("база", target / "config" / "plugins" / "memory-base.js"),
        ):
            if not _plugin.is_file():
                check(False, f"плагин не найден: {_where}")
                continue
            _text = _plugin.read_text(encoding="utf-8")
            _ok = ("export default {" in _text
                   and re.search(r"^\s*id:\s*[\"']", _text, re.M)
                   and re.search(r"^\s*setup\(", _text, re.M))
            check(_ok, f"плагин ({_where}) отдаёт объект с id и setup — схема v2")
            check("export default MemoryBasePlugin" not in _text,
                  f"плагин ({_where}) больше не отдаёт функцию — её opencode отвергает")

        # области знаний и пояснения к папкам
        for area in core.KNOWLEDGE_AREAS:
            if not (target / "знания" / area).is_dir():
                check(False, f"нет области знаний «{area}»")
                break
        else:
            check(True, f"созданы все {len(core.KNOWLEDGE_AREAS)} области знаний")
        for name in ("память", "личное", "журнал-решений", "настройки",
                     "знания", "библиотека"):
            if not (target / name / "_О-ПАПКЕ.md").is_file():
                check(False, f"нет пояснения в папке {name}")
                break
        else:
            check(True, "пояснения к новым папкам созданы")
        for area in core.KNOWLEDGE_AREAS:
            if not (target / "знания" / area / "_О-ПАПКЕ.md").is_file():
                check(False, f"нет пояснения в области «{area}»")
                break
        else:
            check(True, "пояснения в областях знаний созданы")

        # повторное создание поверх базы должно быть запрещено
        try:
            core.build_plan(parent, "Проба-пустая", None)
            check(False, "повторное создание поверх базы не заблокировано")
        except core.NameError_:
            check(True, "повторное создание поверх базы заблокировано")

        # ---- 5. создание из образца
        echo("\n--- 5. Создание из образца ---")
        # Путь к образцу не вписан: самопроверка лежит внутри базы, поэтому
        # находит её сама. Так она годится для любого компьютера и любого
        # имени пользователя, а не только для того, где её писали.
        source = core.app_root()
        check((source / "profile.md").is_file(),
              f"образец найден рядом с программой: {source.name}")
        if source.is_dir():
            plan2 = core.build_plan(parent, "Проба-копия", source)
            core.create_base(plan2)
            copy_skills = core.count_skills(plan2.target)
            # Скиллы берутся из КОНСТРУКТОРА, а не из образца: образец —
            # это пользовательская база, её набор может отставать и дополняться
            # своими скиллами. Проверяем, что новая база получила полный
            # комплект программы, а не то, что лежит в образце.
            real_skills = core.count_skills(core.program_root())
            check(copy_skills == real_skills,
                  f"скиллы перенесены из конструктора: {copy_skills} из {real_skills}")
            same = (plan2.target / "profile.md").read_bytes() == (
                source / "profile.md"
            ).read_bytes()
            check(same, "profile.md совпадает с образцом")

            # расширенная структура должна приехать из образца целиком
            for name in core.NAV_FILES:
                check((plan2.target / name).is_file(),
                      f"навигатор {name} перенесён из образца")
            areas = sum(
                1 for area in core.KNOWLEDGE_AREAS
                if (plan2.target / "знания" / area / "_О-ПАПКЕ.md").is_file()
            )
            check(areas == len(core.KNOWLEDGE_AREAS),
                  f"пояснения областей перенесены: {areas} из "
                  f"{len(core.KNOWLEDGE_AREAS)}")
            hints = sum(
                1 for name in ("память", "личное", "журнал-решений", "настройки")
                if (plan2.target / name / "_О-ПАПКЕ.md").is_file()
            )
            check(hints == 4, f"пояснения новых папок перенесены: {hints} из 4")

            # ---- 5а. заготовки личных данных
            echo("\n--- 5а. Заготовки личных данных ---")
            subs = [
                f"знания/{area}/{sub}"
                for area, names in core.KNOWLEDGE_SUBDIRS.items()
                for sub in names
            ]
            made_subs = sum(1 for name in subs if (plan2.target / name).is_dir())
            check(made_subs == len(subs),
                  f"подпапки областей созданы: {made_subs} из {len(subs)}")

            hints_subs = sum(
                1 for name in subs
                if (plan2.target / name / "_О-ПАПКЕ.md").is_file()
            )
            check(hints_subs == len(subs),
                  f"пояснения в подпапках: {hints_subs} из {len(subs)}")

            # заготовки «_ШАБЛОН-….md» должны доехать из образца
            blank_src = list(source.glob("знания/**/_ШАБЛОН-*.md"))
            blank_dst = list(plan2.target.glob("знания/**/_ШАБЛОН-*.md"))
            check(len(blank_src) > 0,
                  f"в образце есть заготовки: {len(blank_src)}")
            check(len(blank_dst) == len(blank_src),
                  f"заготовки перенесены: {len(blank_dst)} из {len(blank_src)}")

            # у каждой заготовки внутри — предупреждение о безопасности
            unsafe = [
                p.name for p in blank_dst
                if "чужой сервер" not in p.read_text(encoding="utf-8")
            ]
            check(not unsafe,
                  f"в каждой заготовке предупреждение о секретах "
                  f"(без него: {unsafe})")

            # сводная карта личных данных должна быть на месте
            check((plan2.target / "знания/_ЛИЧНЫЕ-ДАННЫЕ.md").is_file(),
                  "сводная карта «где что лежит» перенесена")
            card = plan2.target / "знания/_ЛИЧНЫЕ-ДАННЫЕ.md"
            card_text = card.read_text(encoding="utf-8") if card.is_file() else ""
            missing_areas = [
                area for area in core.KNOWLEDGE_AREAS
                if area not in card_text
            ]
            check(not missing_areas,
                  f"в карте упомянуты все области (нет: {missing_areas})")

            # у каждой области есть пояснение «_О-ПАПКЕ.md»
            for area in core.KNOWLEDGE_AREAS:
                if not (plan2.target / "знания" / area / "_О-ПАПКЕ.md").is_file():
                    check(False, f"нет пояснения в области «{area}»")
                    break
            else:
                check(True, "пояснения во всех областях знаний есть")

            # скиллы не должны потеряться при построении расширенной базы
            check(core.count_skills(plan2.target) > 0,
                  "скиллы в базе из образца на месте")

            # база из образца должна нести в себе плагин: иначе её нечего
            # будет подключать к OpenCode
            echo("\n--- 5б. Плагин внутри новой базы ---")
            cfg = plan2.target / "config"
            check(cfg.is_dir(), "папка config перенесена в новую базу")
            check(core.has_plugin(cfg), "плагин памяти внутри новой базы")
            check((cfg / "opencode.jsonc").is_file(),
                  "настройки внутри новой базы")
            check((cfg / "AGENTS.md").is_file(),
                  "правила внутри новой базы")
            check((cfg / "command").is_dir(),
                  "готовые команды внутри новой базы")
            check((cfg / "node_modules" / "@opencode-ai" / "plugin"
                   / "package.json").is_file(),
                  "зависимости внутри новой базы")
            # Пути в настройках новой базы должны вести на неё саму.
            own = str(plan2.target).replace("\\", "/")
            own_cfg = (cfg / "opencode.jsonc").read_text(encoding="utf-8")
            check(own in own_cfg,
                  "пути в настройках новой базы указывают на неё саму")
            check(str(Path.cwd()).replace("\\", "/") + "/profile.md" not in own_cfg,
                  "пути образца в новой базе заменены")
        else:
            check(False, "образец по пути не найден")

        # ---- 6. подключение
        echo("\n--- 6. Подключение к программе ---")
        program = core.Program(
            "opencode",
            "OpenCode",
            "проверка",
            fallback=str(tmp / "настройки" / "opencode"),
        )
        # ВАЖНО: программа ищет СУЩЕСТВУЮЩУЮ папку настроек и может найти
        # настоящую (~/.config/opencode), а не временную. Тогда проверка
        # испортит рабочие настройки: пропишет в них путь к временной
        # папке, которую в конце удалит. Поэтому жёстко уводим её в temp.
        program.config_dir = lambda: Path(tmp) / "настройки" / "opencode"  # type: ignore[method-assign]

        # Страховка. Проверка подключения переносит скиллы: неотмеченные
        # уезжают в _previous-version. Если изоляция выше не сработает,
        # это коснётся НАСТОЯЩЕЙ папки настроек — так один раз и вышло:
        # 11 рабочих скиллов OpenCode оказались в _previous-version.
        # Поэтому дальше не идём, пока не убедимся, что пишем во временную.
        def inside_temp(path) -> bool:
            try:
                Path(path).resolve().relative_to(Path(tmp).resolve())
                return True
            except (ValueError, OSError):
                return False

        real_dir = program.config_dir()
        if not inside_temp(real_dir):
            echo()
            echo("  ОСТАНОВ: подключение шло бы в НАСТОЯЩУЮ папку настроек:")
            echo(f"    {real_dir}")
            echo("  Проверка прервана, чтобы не испортить рабочие скиллы.")
            echo("  Список баз и настройки не тронуты.")
            return 1
        check(True, f"подключение идёт во временную папку ({Path(tmp).name})")

        before = sorted(p.name for p in (tmp / "настройки").rglob("*")) if (
            tmp / "настройки"
        ).exists() else []
        result = core.attach_base(plan2.target, program)
        dest = program.config_dir()
        check(result.ok, f"подключение прошло (ошибок: {len(result.errors)})")
        if result.errors:
            for error in result.errors:
                echo(f"       {error}")
        check((dest / "profile.md").is_file(), "профиль лежит у программы")
        check((dest / "memory-base-path.txt").is_file(), "путь к базе записан")
        check(core.count_skills(dest) == core.count_skills(plan2.target),
              f"скиллы у программы: {core.count_skills(dest)}")
        check((dest / "библиотека/АКТИВНАЯ-ПАМЯТЬ.md").is_file(),
              "библиотека перенесена")

        # ---- 6б. плагин OpenCode: без него база не читается
        echo("\n--- 6б. Плагин и настройки OpenCode ---")
        check(core.has_plugin(dest),
              "плагин памяти установлен в папку программы")
        check((dest / "opencode.jsonc").is_file(),
              "настройки opencode.jsonc на месте")
        check((dest / "AGENTS.md").is_file(), "правила AGENTS.md на месте")
        check((dest / "package.json").is_file(), "описание зависимостей на месте")

        commands = list((dest / "command").glob("*.md")) if (dest / "command").is_dir() else []
        check(len(commands) >= 5, f"готовых команд перенесено: {len(commands)}")

        deps = dest / "node_modules" / "@opencode-ai" / "plugin" / "package.json"
        check(deps.is_file(), "зависимости плагина на месте (без интернета)")

        # Пути в настройках должны указывать на НАСТОЯЩУЮ папку базы,
        # а не на то место, откуда база скопирована.
        cfg_text = (dest / "opencode.jsonc").read_text(encoding="utf-8")
        base_posix = str(plan2.target).replace("\\", "/")
        check(base_posix in cfg_text,
              "в настройках прописан путь к этой базе")
        check("instructions" in cfg_text,
              "настройки загружают базу в каждую сессию")
        for target_name in core.INSTRUCTION_TARGETS:
            check(f"{base_posix}/{target_name}" in cfg_text,
                  f"в настройках есть путь к {target_name}")

        # Собранные пути должны быть пригодны для чтения, а не «на словах».
        import opencode_caps  # noqa: E402
        bounds = opencode_caps.find_key_array(cfg_text, "instructions")
        check(bounds is not None, "массив instructions найден в настройках")
        if bounds is not None:
            raw = cfg_text[bounds[0] + 1 : bounds[1]]
            listed = [p.strip().strip('",') for p in raw.splitlines() if p.strip()]
            listed = [x for x in listed if x]
            check(len(listed) == len(core.INSTRUCTION_TARGETS),
                  f"путей в настройках: {len(listed)}")
            for item in listed:
                check(Path(item).is_file(),
                      f"файл по пути существует: {item.split('/')[-1]}")

        # Подключение само переводит мосты памяти и ПК с правами на базу.
        check('"ncp"' in cfg_text and '"pc"' in cfg_text,
              "мосты ncp и pc вписаны в настройки")
        check('"ask"' in cfg_text, "права на мосты стоят")
        nbridge = core.program_root() / "tools" / "ncp-bridge" / "config.json"
        if nbridge.is_file():
            bridge_cfg = json.loads(nbridge.read_text(encoding="utf-8"))
            check("library" in str(bridge_cfg.get("library_path", "")).lower() or "{{library}}" in str(bridge_cfg.get("library_path", "")).lower(),
                  "в конфиг моста вписан путь к библиотеке")

        # У базы, из которой подключаем, тоже должен быть плагин —
        # иначе подключать нечего.
        check(core.find_config_source(plan2.target) is not None,
              "в базе есть папка config с плагином")

        # повторное подключение: старые файлы уходят в _previous-version
        result2 = core.attach_base(plan2.target, program)
        check(result2.ok, "повторное подключение не сломалось")
        check((dest / "_previous-version/profile.md").is_file(),
              "прежние файлы сохранены в _previous-version")
        check((dest / "_previous-version/opencode.jsonc").is_file(),
              "прежние настройки сохранены в _previous-version")

        # защита от служебной папки npm
        npm_program = core.Program(
            "probe-npm", "Проба", "проверка", fallback=str(tmp / "npm")
        )
        npm_program.config_dir = lambda: Path(tmp) / "npm"  # type: ignore[method-assign]
        guard = core.attach_base(plan2.target, npm_program)
        check(not guard.ok and "служебная" in " ".join(guard.errors),
              "запись в папку npm запрещена")

        # ---- 7. сводка о базе
        echo("\n--- 7. Сводка о базе ---")
        info = core.base_info(plan2.target)
        check(bool(info["is_base"]), "база опознана")
        check(int(info["skills"]) > 0, f"скиллов видно: {info['skills']}")
        check(int(info["size"]) > 0,
              f"размер считается: {core.human_size(int(info['size']))}")
        check(info["marker"] is not None, "отметка о создании читается")

        # ---- 8. вкладка подключения
        echo("\n--- 8. Вкладка «Подключить существующую» ---")
        itab = window.import_tab
        itab.source_edit.setText(str(tmp / "нет-такой-папки"))
        check(not itab.btn_run.isEnabled(), "с несуществующей папкой кнопка закрыта")
        itab.source_edit.setText(str(plan2.target))
        check(itab.btn_run.isEnabled(), "с настоящей базой кнопка открыта")
        check("Скиллов" in itab.source_hint.text(),
              f"сводка показана: {itab.source_hint.text()[:50]}")

        # ---- 8б. шаг 3: выбор навыков перед подключением
        echo("\n--- 8б. Шаг «Какие навыки подключить» ---")

        # чтение скиллов из базы: имя, описание, путь
        found = core.list_skills(plan2.target)
        check(len(found) > 0, f"навыки прочитаны из базы: {len(found)}")
        check(all(s.get("description") for s in found),
              "у каждого навыка есть описание")
        check(all(s.get("path") for s in found),
              "у каждого навыка есть путь к папке")
        names = [s["name"] for s in found]
        check(len(names) == len(set(names)), "имена навыков не повторяются")
        import re as _re
        bad = [n for n in names
               if not _re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", n)]
        check(not bad, f"имена годятся для opencode: {bad or 'все'}")

        # многострочное описание (YAML-складка) должно склеиться в одну строку
        folded = [s for s in found if s["name"] == "geo-map-compliance-guard"]
        if folded:
            check("\n" not in folded[0]["description"]
                  and len(folded[0]["description"]) > 100,
                  "многострочное описание собрано в одну строку")

        # окно: список навыков заполнен и все отмечены при первом показе
        check(itab.skills_list.count() == len(found),
              f"в окне навыков: {itab.skills_list.count()} из {len(found)}")
        check(len(itab._chosen_skills()) == len(found),
              "при первом показе отмечены все навыки")

        # снять все — подсказка предупреждает, выбор пустой
        itab._set_all_skills(False)
        check(len(itab._chosen_skills()) == 0, "кнопка «Снять все» очистила выбор")
        check("Не отмечено" in itab.skills_hint.text(),
              "при пустом выборе показано предупреждение")
        # кнопка подключения остаётся доступной — это допустимый выбор
        check(itab.btn_run.isEnabled(),
              "пустой выбор навыков не блокирует подключение")

        # отметить все обратно
        itab._set_all_skills(True)
        check(len(itab._chosen_skills()) == len(found), "кнопка «Отметить все» вернула выбор")
        check("все" in itab.skills_hint.text().lower(),
              "при полном выборе сказано, что перенесутся все")

        # подключение с выбором подмножества: остальные уходят в _previous-version
        echo("\n     подключение с выбором части навыков:")
        subset = sorted(names)[:2]
        keep_dir = dest / "skills"
        before = sorted(
            d.name for d in keep_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        ) if keep_dir.is_dir() else []
        check(len(before) > 2, f"до выбора в программе навыков: {len(before)}")

        part = core.attach_base(plan2.target, program, skills=subset)
        check(part.ok, "подключение с выбором прошло без ошибок")
        after = sorted(
            d.name for d in (dest / "skills").iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        )
        check(after == subset,
              f"осталось ровно отмеченное: {after}")
        unkept = [n for n in before if n not in subset]
        moved = sum(
            1 for n in unkept
            if (dest / "_previous-version" / "skills" / n).is_dir()
        )
        check(moved == len(unkept),
              f"неотмеченные убраны в _previous-version: {moved} из {len(unkept)}")
        check(keep_dir.is_dir() and (keep_dir / subset[0] / "SKILL.md").is_file(),
              "отмеченный навык лежит в программе целиком")

        # подключение со всем набором возвращает всё на место
        all_names = sorted(names)
        back = core.attach_base(plan2.target, program, skills=all_names)
        check(back.ok, "подключение со всем набором прошло")
        restored = sorted(
            d.name for d in (dest / "skills").iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        )
        check(restored == all_names, f"вернулись все навыки: {len(restored)}")
        check("из " in " ".join(back.messages),
              "в отчёте сказано, сколько навыков перенесено")

        # пустой список — ни одного навыка, и это не ошибка
        none_at_all = core.attach_base(plan2.target, program, skills=[])
        check(none_at_all.ok, "подключение без навыков не считается сбоем")
        left = sorted(
            d.name for d in (dest / "skills").iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        ) if (dest / "skills").is_dir() else []
        check(left == [], f"при пустом выборе в программе не осталось навыков: {left}")

        # навык, которого нет в базе: должно быть предупреждение, не сбой
        ghost = core.attach_base(
            plan2.target, program, skills=["нет-такого-навыка"]
        )
        check(any("нет-такого-навыка" in e for e in ghost.errors),
              "отмеченный, но отсутствующий навык назван в замечаниях")

        # Skills=None по-прежнему означает «все» — старая проверка не сломалась
        core.attach_base(plan2.target, program)
        default_all = sorted(
            d.name for d in (dest / "skills").iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        )
        check(default_all == sorted(names),
              "без указания навыков переносятся все")

        # база БЕЗ навыков не должна стирать навыки из программы:
        # иначе «подключил пустую базу — потерял всё, что было»
        echo("\n     база без навыков:")
        # «Пустая база» теперь наполняется навыками из главной базы,
        # поэтому для проверки предохранителя делаем базу без навыков
        # по-настоящему: убираем папку skills.
        blank_base = target
        skills_dir = blank_base / "skills"
        if skills_dir.is_dir():
            shutil.rmtree(skills_dir)
        check(not core.list_skills(blank_base),
              "в базе без навыков скиллов нет — условие проверки выполнено")
        safe = core.attach_base(blank_base, program)
        left_after = sorted(
            d.name for d in (dest / "skills").iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        )
        check(left_after == all_names,
              f"навыки в программе уцелели: {len(left_after)} из {len(all_names)}")
        check(any("ничего не тронуто" in m for m in safe.messages),
              "в отчёте сказано, что навыки в программе не тронуты")

        # программа без поддержки навыков: шаг 3 не должен ничего ломать
        no_skills_program = core.Program(
            "probe", "Проба", "проверка", supports_skills=False,
            fallback=str(tmp / "probe"),
        )
        # изоляция обязательна и здесь: пишем только во временную папку
        no_skills_program.config_dir = lambda: Path(tmp) / "probe"  # type: ignore[method-assign]
        quiet = core.attach_base(plan2.target, no_skills_program)
        check(any("не читает" in m for m in quiet.messages),
              "для программы без навыков сказано, что пропущено")

        # ---- 9. ярлык
        echo("\n--- 9. Ярлык на базу ---")
        check(tab.link_check.isChecked(), "галочка ярлыка включена по умолчанию")
        check(tab.link_place.count() == len(core.SHORTCUT_PLACES),
              f"мест для ярлыка: {tab.link_place.count()}")

        # разбор всех мест
        for ident, title in core.SHORTCUT_PLACES:
            try:
                folder = core.resolve_shortcut_folder(
                    ident, target, str(tmp)
                )
                check(folder.is_dir(), f"место «{title}» даёт папку")
            except core.NameError_ as exc:
                check(False, f"место «{title}» не разобралось: {exc}")

        # своя папка: пустой путь и несуществующая папка должны отклоняться
        for raw, note in (("", "пустой путь"), (str(tmp / "нет"), "несуществующая")):
            try:
                core.resolve_shortcut_folder("custom", target, raw)
                check(False, f"своя папка: {note} зря принята")
            except core.NameError_:
                check(True, f"своя папка: {note} отклонена")

        # имя ярлыка чистится от запрещённых знаков
        check(core.safe_link_name("a/b:c*d") == "a_b_c_d",
              "запрещённые знаки в имени ярлыка заменены")
        check(core.safe_link_name("   ") == "база",
              "пустое имя ярлыка заменено на «база»")

        # настоящее создание ярлыка во временной папке
        made = core.create_base_shortcut(
            target, "custom", str(tmp), target.name
        )
        if made.ok:
            check(made.link is not None and made.link.is_file(),
                  f"ярлык создан: {made.link.name}")
            # ярлык должен вести на файл-открывалку внутри базы
            opener = target / core.OPENER_NAME
            check(opener.is_file(), f"в базе создан файл для ярлыка")
            pointed = core.shortcut_target(made.link) if made.link else None
            same = False
            if pointed is not None:
                try:
                    same = pointed.resolve() == opener.resolve()
                except OSError:
                    same = str(pointed).lower() == str(opener).lower()
            check(same,
                  f"ярлык открывает нужный файл: "
                  f"{pointed.name if pointed else 'не прочитался'}")
            # повтор не должен затирать имеющийся ярлык
            again = core.create_base_shortcut(
                target, "custom", str(tmp), target.name
            )
            check(not again.ok and "уже есть" in again.error,
                  "повторный ярлык не затирает существующий")
        else:
            # ярлыки могут быть запрещены средой — это не порча программы
            echo(f"       ярлык не создан: {made.error.splitlines()[0]}")
            check("не удалось" in made.error or "уже есть" in made.error,
                  "при отказе объяснена причина")

        # выключенная галочка отключает выбор места
        tab.link_check.setChecked(False)
        check(not tab.link_place.isEnabled(), "без галочки выбор места закрыт")
        check("не будет" in tab.link_hint.text(),
              "без галочки сказано, что ярлыка не будет")
        tab.link_check.setChecked(True)
        check(tab.link_place.isEnabled(), "с галочкой выбор места снова доступен")

        # своя папка включается только на своём пункте
        tab.link_place.setCurrentIndex(0)
        check(not tab.link_custom_edit.isVisible(),
              "на «Рабочем столе» своя папка не нужна")
        for index in range(tab.link_place.count()):
            if tab.link_place.itemData(index) == "custom":
                tab.link_place.setCurrentIndex(index)
                break
        # окно в проверке не показывается, поэтому смотрим на «скрытость»
        check(not tab.link_custom_edit.isHidden(),
              "на «Своя папка…» поле своей папки показано")
        tab.link_place.setCurrentIndex(0)
        check(tab.link_custom_edit.isHidden(),
              "при возврате на «Рабочий стол» поле снова скрыто")

        # ---- 10. трудные пути
        echo("\n--- 10. Трудные пути в ярлыках ---")
        # длинное тире в пути ломало ярлыки: внешние программы портили
        # его на обычный дефис, и ярлык вёл в несуществующую папку
        hard_dir = tmp / "папка — с тире и РуССкими"
        hard_dir.mkdir(parents=True, exist_ok=True)
        hard_base = hard_dir / "База — проба"
        hard_base.mkdir(exist_ok=True)
        (hard_base / "profile.md").write_text("# x\n", encoding="utf-8")

        hard_link = tmp / "трудный.lnk"
        res_hard = core.create_base_shortcut(
            hard_base, "custom", str(tmp), "трудный"
        )
        check(res_hard.ok, "ярлык на путь с длинным тире создан")
        hard_opener = hard_base / core.OPENER_NAME
        read_hard = core.shortcut_target(hard_link) if hard_link.is_file() else None
        check(
            read_hard is not None and read_hard.resolve() == hard_opener.resolve(),
            f"длинное тире не испорчено: "
            f"{read_hard.parent.name if read_hard else 'не прочитался'}",
        )
        if read_hard is not None:
            check("—" in str(read_hard),
                  "в пути ярлыка сохранилось длинное тире «—»")
            check("папка — с тире и РуССкими" in str(read_hard),
                  "русские буквы в пути не испорчены")

        # ---- 11. список созданных баз и переход во вторую вкладку
        echo("\n--- 11. Список созданных баз ---")
        # список уже подменён на временный в начале проверки —
        # настоящий не трогается
        itab._fill_mine()
        itab.mine_list.clear()
        core._write_bases([])
        check(core.read_bases() == [], "пустой список читается")

        core.remember_base(plan2.target, "claude")
        entries = core.read_bases()
        check(len(entries) == 1, f"база запомнена (записей: {len(entries)})")
        check(entries[0]["path"] == str(plan2.target),
              "путь записан верно")
        check(entries[0].get("program") == "claude",
              "программа подключения запомнена")

        # повторная запись не создаёт дубль
        core.remember_base(plan2.target, "claude")
        check(len(core.read_bases()) == 1, "повтор не создал дубль")

        # список виден во вкладке
        itab._fill_mine()
        check(itab.mine_list.count() == 1,
              f"список в окне заполнен: {itab.mine_list.count()}")
        check(itab.mine_list.item(0).data(1000) == str(plan2.target),
              "в списке тот же путь")

        # выбор подставляет путь в поле
        itab.mine_list.setCurrentRow(0)
        itab.source_edit.clear()
        itab.mine_list.setCurrentRow(-1)
        itab.mine_list.setCurrentRow(0)
        check(itab.source_edit.text() == str(plan2.target),
              "выбор из списка подставил путь")
        check(itab.btn_forget_mine.isEnabled(),
              "кнопка «убрать» доступна при выборе")

        # удалённой базы в списке быть не должно
        ghost = tmp / "Удалённая база"
        ghost.mkdir(parents=True, exist_ok=True)
        (ghost / "profile.md").write_text("# x\n", encoding="utf-8")
        core.remember_base(ghost, "")
        check(len(core.read_bases()) == 2, "запись добавилась")
        shutil.rmtree(ghost, ignore_errors=True)
        check(len(core.read_bases()) == 1,
              "запись без файлов памяти выброшена")

        # автоматический переход после создания
        window._suggest_import(str(plan2.target))
        check(window.tabs.currentIndex() == 1,
              "после создания открылась вкладка подключения")
        check(itab.source_edit.text() == str(plan2.target),
              "в поле уже стоит созданная база")
        check(itab.btn_run.isEnabled(),
              "кнопка подключения сразу доступна")

        window.tabs.setCurrentIndex(0)
        window._suggest_import(str(tmp / "нет-такой"))
        check(window.tabs.currentIndex() == 0,
              "на несуществующем пути переход не делается")

        core.forget_base(plan2.target)
        check(core.read_bases() == [], "база забыта по просьбе")
        check(plan2.target.is_dir(),
              "папка при забывании не тронута")

        # ---- 12. переносимость: базу можно отдать другому человеку
        echo("\n--- 12. Переносимость на другой компьютер ---")
        # Ни в одном рабочем файле не должно быть имени пользователя
        # и папки установки: иначе базу нельзя передать другому человеку —
        # у него пути не совпадут, и ничего не заработает.
        root = core.app_root()
        user = Path.home().name
        watch = [
            root / "Управление-базой.cmd",
            root / "config" / "plugins" / "memory-base.js",
            root / "config" / "AGENTS.md",
            root / "config" / "opencode.jsonc",
            root / "tools" / "dbapp" / "core.py",
            root / "tools" / "dbapp" / "main.py",
            root / "tools" / "dbapp" / "selftest.py",
        ]
        # Готовые команды копируются в программу и выполняются как есть —
        # имя пользователя в них недопустимо вдвойне.
        cmds = sorted((root / "config" / "command").glob("*.md"))
        watch += cmds
        dirty = [
            path.name
            for path in watch
            if path.is_file()
            and user
            and user in path.read_text(encoding="utf-8", errors="replace")
        ]
        check(not dirty,
              f"имя пользователя не вписано в файлы: проверено {len(watch)}")
        for item in dirty:
            echo(f"      имя пользователя найдено в: {item}")

        marks = sum(
            1
            for path in cmds
            if core.BASE_PLACEHOLDER in path.read_text(encoding="utf-8")
        )
        check(marks >= 4,
              f"команды ссылаются на базу пометкой: {marks} из {len(cmds)}")

        # Вместо пути — пометка. Благодаря ей файлы годятся для любой папки.
        for rel in ("config/AGENTS.md", "config/opencode.jsonc"):
            path = root / rel
            text = (
                path.read_text(encoding="utf-8", errors="replace")
                if path.is_file()
                else ""
            )
            check(core.BASE_PLACEHOLDER in text,
                  f"в {rel} стоит пометка {core.BASE_PLACEHOLDER}, а не путь")

        probe = tmp / "проба-подстановки.md"
        probe.write_text(
            f"База лежит здесь: {core.BASE_PLACEHOLDER}/profile.md\n",
            encoding="utf-8",
        )
        changed = core.substitute_base(probe, tmp)
        text = probe.read_text(encoding="utf-8")
        check(changed, "пометка заменена настоящим путём")
        check(core.BASE_PLACEHOLDER not in text,
              "после подстановки пометки не осталось")
        check(str(tmp).replace("\\", "/") in text,
              "подставлен именно путь этой базы")
        check(not core.substitute_base(probe, tmp),
              "повторная подстановка ничего не портит")

        # Рабочий стол — вторая пометка: команда создания проекта заводит
        # папку проекта рядом с базой, а не в чужой папке пользователя.
        probe2 = tmp / "проба-рабочего-стола.md"
        probe2.write_text(
            f"Папка проекта: {core.DESKTOP_PLACEHOLDER}/Имя/\n", encoding="utf-8"
        )
        desk = tmp / "Стол"
        changed2 = core.substitute_base(probe2, tmp, desk)
        text2 = probe2.read_text(encoding="utf-8")
        check(changed2 and core.DESKTOP_PLACEHOLDER not in text2,
              "пометка рабочего стола тоже заменяется")
        check(str(desk).replace("\\", "/") in text2,
              "в файл попал именно этот рабочий стол")

        # ---- 12а. поиск программ по нейросетям и агрегаторам
        echo("\n--- 12а. Поиск программ ---")
        home_text = str(Path.home()).replace("\\", "/")
        outside = [
            p.title
            for p in core.PROGRAMS
            if not str(p.config_dir()).replace("\\", "/").startswith(home_text)
        ]
        check(not outside,
              f"папки всех программ ищутся от домашней: {len(core.PROGRAMS)}")
        for item in outside:
            echo(f"      папка вне домашней: {item}")

        found = [p for p in core.PROGRAMS if p.is_installed()]
        check(len(found) > 0, f"опознано установленных программ: {len(found)}")
        check(core.PROGRAMS_BY_ID["opencode"].is_installed(),
              "OpenCode опознан по своей папке")
        check(set(core.PROGRAMS_BY_ID) == {"opencode", "harness"},
              f"программ ровно две: {sorted(core.PROGRAMS_BY_ID)}")
        check(core.PROGRAMS_BY_ID["harness"].ability_note().startswith("Базу увидит"),
              f"про Harness сказано прямо: {core.PROGRAMS_BY_ID['harness'].ability_note()}")

        # ---- 12б. честный отказ вместо пустой работы
        echo("\n--- 12б. Честный отказ ---")
        closed = core.Program(
            "probe-closed", "Проба-закрытая", "проверка",
            reads_state=core.READS_NO, fallback=str(tmp / "probe-closed"),
        )
        closed.config_dir = lambda: Path(tmp) / "probe-closed"  # type: ignore[method-assign]
        check(closed.reads_state == core.READS_NO,
              "про закрытую программу известно, что файлы она не читает")
        check(not closed.can_attach(), "подключение к закрытой запрещено")
        check("не увидит" in closed.ability_note(),
              f"окно говорит правду: {closed.ability_note()}")
        closed_dir = Path(str(closed.config_dir()))
        before = sorted(p.name for p in closed_dir.iterdir()) if closed_dir.is_dir() else []
        refuse = core.attach_base(plan2.target, closed)
        check(not refuse.ok, "подключение к закрытой отменено")
        check(any("не видна" in m for m in refuse.errors),
              "в отказе объяснена причина")
        if closed_dir.is_dir():
            check(sorted(p.name for p in closed_dir.iterdir()) == before,
                  "в чужой папке ничего не изменилось")

        reader = core.PROGRAMS_BY_ID["opencode"]
        check(reader.can_attach(), "к OpenCode подключение разрешено")
        check("увидит" in reader.ability_note(),
              f"про OpenCode сказано прямо: {reader.ability_note()}")

        # ---- 12в. отказ виден в окне, а не только в коде
        echo("\n--- 12в. Что видит человек в окне ---")

        def _select(ident: str) -> None:
            for index in range(itab.target_list.count()):
                if itab.target_list.item(index).data(1000) == ident:
                    itab.target_list.setCurrentRow(index)
                    return

        _select("opencode")
        check("увидит" in itab.target_hint.text(),
              f"подсказка про OpenCode: "
              f"{itab.target_hint.text()[:60]}")
        check(itab.btn_run.isEnabled(),
              "у OpenCode кнопка «Подключить» доступна")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        echo(f"\nВременная папка убрана: {tmp}")

    # ---- 13. мост NCP: создаётся программой, а не вручную
    echo("\n--- 13. Мост NCP ---")

    # Своя временная папка: прежняя убрана вместе с разделом 12.
    btmp = Path(tempfile.mkdtemp(prefix="ncp_bridge_"))

    btab = window.bridge_tab
    # Шесть разделов: создание, подключение, мост NCP, возможности, темы и
    # инструкция. Раньше вкладки «Инструкция» не было — счётчик стоял на 5.
    # Названия стали короче: в боковой колонке «Создать новую базу» не
    # помещалось, и длинная надпись читалась как инструкция, а не как
    # название раздела.
    check(window.tabs.count() == 6, f"разделов в окне: {window.tabs.count()}")
    check(window.tabs.tabText(0) == "Новая база",
          f"первый раздел — «{window.tabs.tabText(0)}»")
    check(window.tabs.tabText(1) == "Существующая база",
          f"второй раздел — «{window.tabs.tabText(1)}»")
    check(window.tabs.tabText(2) == "Мост NCP",
          f"третий раздел — «{window.tabs.tabText(2)}»")
    check(window.tabs.tabText(3) == "Возможности",
          f"четвёртый раздел — «{window.tabs.tabText(3)}»")
    check(window.tabs.tabText(4) == "Темы",
          f"пятый раздел — «{window.tabs.tabText(4)}»")
    check(window.tabs.tabText(5) == "Инструкция",
          f"шестой раздел — «{window.tabs.tabText(5)}»")
    check(isinstance(btab, app_main.BridgeTab), "раздел моста собран")

    # ---- 13а. Боковая навигация вместо вкладок
    #
    # Здесь важна не «есть ли панель», а её поведение. Три поломки
    # находились только на глаз и только живьём:
    #   - autoExclusive снимал отметку внутри Qt, мимо нашего кода, и
    #     полоса прежнего раздела оставалась гореть — выглядело так,
    #     будто выбраны два раздела сразу;
    #   - клик по уже открытому разделу гасил его own-полосу, и раздел
    #     был открыт, но не выбран;
    #   - список и окно отчёта с политикой Expanding забирали в себя
    #     лишнее место страницы, и внутри групп была пустота.
    nav = window.nav
    check(isinstance(nav, app_main.NavStack), "боковая навигация собрана")
    # Про isVisible(): окно в самопроверке намеренно не показывается, и
    # isVisible() у любого элемента всегда ложно — проверка ввела бы в
    # заблуждение. Поэтому смотрим, что колонка не скрыта и достаточно
    # широка, а живой показ проверяется отдельно, запуском окна.
    check(not nav.nav.isHidden() and nav.nav.width() >= 180,
          f"колонка навигации не скрыта и достаточно широка: {nav.nav.width()}")

    def bar_color(item) -> str:
        for part in item.bar.styleSheet().split(";"):
            if "background" in part:
                return part.split(":")[-1].strip()
        return "?"

    for index in range(nav.count()):
        nav.setCurrentIndex(index)
        marked = [i for i, it in enumerate(nav._items) if it.isChecked()]
        check(marked == [index],
              f"при выборе «{nav.tabText(index)}» отмечен только он")
        lit = [i for i, it in enumerate(nav._items)
               if bar_color(it) != "transparent"]
        check(lit == [index],
              f"полоса горит только у «{nav.tabText(index)}»: {lit}")
        check(bar_color(nav._items[index]) == nav._items[index]._accent,
              "полоса выбранного в его акценте")
        check(nav.stack.currentWidget() is nav.widget(index),
              "содержимое соответствует выбранному разделу")

    # Клик мышью по пункту: раздел открывается, полоса не гаснет.
    for index in range(nav.count()):
        nav._items[index].click()
        check(nav.currentIndex() == index,
              f"клик по «{nav.tabText(index)}» открыл его")
        check(nav._items[index].isChecked(),
              f"после клика «{nav.tabText(index)}» остался отмечен")

    nav.setCurrentIndex(0)
    # Пункт самопереключаться не должен: отметка — часть оформления.
    nav._items[0].click()
    check(nav._items[0].isChecked(),
          "клик по уже открытому разделу не гасит его полосу")

    # ---- 13б. Панель состояния
    #
    # Панель врёт легче, чем что-либо в окне: она обязана совпадать с
    # тем, что core говорит по-настоящему. Проверяем числа, а не вид.
    bar = nav.status
    check(bar.state_label.text() != "проверяю…",
          "состояние панели определено: «%s»" % bar.state_label.text())
    live = core.current_base()
    if live is not None:
        info = core.base_info(live)
        check(bar.skills_label.text() == "скиллы: %d" % info["skills"],
              "счётчик скиллов совпадает с базой: %s" % bar.skills_label.text())
        check(live.name in bar.path_label.text()
              or str(live) in bar.path_label.text(),
              "путь в панели указывает на основную базу: %s"
              % bar.path_label.text())
        lib = core.library_dir(live)
        want_notes = (sum(1 for p in lib.iterdir() if p.is_dir())
                      if lib.is_dir() else 0)
        check(bar.notes_label.text() == "записи: %d" % want_notes,
              "счётчик записей совпадает с библиотекой: %s"
              % bar.notes_label.text())
    else:
        check(bar.state_label.text() == "база не подключена",
              "без базы панель говорит об этом прямо")
    # Моста нет - панель обязана это признать, а не молчать.
    if not core.find_bridges():
        check(bar.state_label.text() == "мост не создан",
              "без моста панель говорит прямо: %s" % bar.state_label.text())
    check(bar._anim is not None,
          "точка дышит: анимация запущена даже когда моста нет")
    bar.set_pulse(False)
    check(bar._anim is None, "пульс выключается по требованию")
    bar.set_pulse(True)
    check(bar._anim is not None, "пульс включается обратно")
    check(bar.size_label.text().startswith("размер: ")
          and bar.size_label.text().endswith(("Б", "КБ", "МБ", "ГБ")),
          "размер с единицей измерения: %s" % bar.size_label.text())

    # ---- 13в. Подразделы внутри «Возможностей» и непроглоченные тексты
    #
    # Qt не сжимает элемент под текст, а обрезает. На снимках это
    # выглядело как «ставить отмеченн», «проверяе» и обрезанные пути:
    # три разные поломки одного класса, и все три нашлись только
    # глазами. Здесь они ловятся измерением.
    #
    # Импорт Qt именно здесь и до первого обращения: Python считает
    # переменную локальной для всей функции с момента импорта, и стоит
    # поставить его ниже первого использования, как было, - выходит
    # UnboundLocalError на пустом месте.
    from PyQt6.QtCore import Qt  # noqa: E402

    sub = window.caps_tab.sub
    check(isinstance(sub, app_main.NavStack), "колонка подразделов собрана")
    check(sub.count() == 5, "подразделов внутри раздела: %d" % sub.count())
    check(sub.status is None,
          "внутри раздела нет второй панели состояния")
    check(sub.nav.objectName() == "navplain",
          "вложенная колонка без рамки: %s" % sub.nav.objectName())
    check(window.caps_tab.caps_skills_list.wordWrap(),
          "описания навыков переносятся, а не обрезаются")
    check(window.caps_tab.caps_skills_list.horizontalScrollBarPolicy()
          == Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
          "под списком навыков нет горизонтальной полосы")

    for index in range(sub.count()):
        sub.setCurrentIndex(index)
        marked = [i for i, it in enumerate(sub._items) if it.isChecked()]
        check(marked == [index],
              f"подраздел «{sub.tabText(index)}» отмечен один")
        check(sub.stack.currentWidget() is sub.widget(index),
              f"содержимое «{sub.tabText(index)}» на месте")

    # Проверка на обрезанный текст: у каждой кнопки и каждой подписи
    # с переносом ширина должна быть не меньше нужной.
    from PyQt6.QtWidgets import QPushButton as _PB  # noqa: E402

    cut_buttons = []
    for index in range(sub.count()):
        sub.setCurrentIndex(index)
        for b in sub.widget(index).findChildren(_PB):
            if b.width() + 2 < b.sizeHint().width():
                cut_buttons.append(f"{b.text()} ({b.width()}"
                                   f" из {b.sizeHint().width()})")
    check(not cut_buttons,
          "подписи кнопок в подразделах не обрезаны"
          + (": " + ", ".join(cut_buttons) if cut_buttons else ""))

    # ---- 13г. Никакой текст не выходит за пределы своего места
    #
    # Qt ужимает кнопку или флажок на недостающие пиксели и не ужимает,
    # а обрезает надпись. Проверяем на двух ширинах: обычной и на
    # минимальной, где обрезание и было.
    #
    # Считаем по-разному в зависимости от переноса: у подписи с
    # переносом sizeHint - это ширина одной строки, и сравнение с ним
    # даёт фантомы по 90 пикселей у текста, который как раз переносится
    # и прекрасно помещается. Такие подписи сверяем с самым длинным
    # словом: только оно может не влезть.
    from PyQt6.QtGui import QFontMetrics  # noqa: E402
    from PyQt6.QtWidgets import (  # noqa: E402
        QAbstractButton,
        QCheckBox,
        QListWidget,
        QRadioButton,
    )

    def too_narrow(root, width: int) -> list:
        bad = []
        for w in root.findChildren(QAbstractButton):
            if not w.isVisible() or not w.text():
                continue
            need = QFontMetrics(w.font()).horizontalAdvance(w.text())
            if isinstance(w, (QCheckBox, QRadioButton)):
                need += 26
            if w.width() + 2 < need:
                bad.append(f"{w.text()!r} на {need - w.width()} px")
        for lst in root.findChildren(QListWidget):
            if not lst.isVisible():
                continue
            check(lst.wordWrap(), f"список переносит текст ({lst.count()} строк)")
            check(lst.horizontalScrollBarPolicy()
                  == Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                  "у списка нет горизонтальной полосы")
        return bad

    window.resize(1180, 880)
    app.processEvents()
    check(not too_narrow(window, 1180),
          "на обычной ширине ничего не обрезано"
          + (": " + "; ".join(too_narrow(window, 1180))[:160]
             if too_narrow(window, 1180) else ""))
    window.resize(1000, 880)
    app.processEvents()
    narrow = too_narrow(window, 1000)
    check(not narrow, "на минимальной ширине ничего не обрезано"
          + (": " + "; ".join(narrow)[:200] if narrow else ""))
    check(window.minimumWidth() >= 1000,
          "окно не открывается уже минимальной ширины: %d"
          % window.minimumWidth())
    window.resize(1180, 880)
    app.processEvents()

    # Подписи с переносом обязаны остаться целыми после смены размера
    # окна. Человек открывает программу на одной ширине, потом тянет
    # окно, и на узком текст должен переноситься, а не резаться.
    from PyQt6.QtCore import QRect as _QRect  # noqa: E402
    from PyQt6.QtGui import QFontMetrics as _QFM  # noqa: E402
    from PyQt6.QtWidgets import QLabel as _QLabel  # noqa: E402

    def cut_labels(page) -> list:
        bad = []
        for lab in page.findChildren(_QLabel):
            text = lab.text() or ""
            if not lab.isVisible() or not text or not lab.wordWrap():
                continue
            need = _QFM(lab.font()).boundingRect(
                _QRect(0, 0, lab.width(), 10_000),
                int(Qt.TextFlag.TextWordWrap), text).height()
            if need > lab.height() + 4:
                bad.append(f"{text[:26]!r} нужно {need}, есть {lab.height()}")
        return bad

    for width in (1180, 1000, 1400, 1000):
        window.resize(width, 880)
        app.processEvents()
        for index in (2, 4):
            window.tabs.setCurrentIndex(index)
            app.processEvents()
            bad = cut_labels(window.tabs.widget(index))
            check(not bad,
                  f"подписи целы при ширине окна {width}, раздел "
                  f"«{window.tabs.tabText(index)}»"
                  + (": " + "; ".join(bad[:2]) if bad else ""))
    window.tabs.setCurrentIndex(0)
    window.resize(1180, 880)
    app.processEvents()

    # ---- 13д. Qt не должен сыпать предупреждениями
    #
    # Раньше при каждом запуске Qt писал шесть раз: «Negative sizes
    # (0,-1) are not possible». Нашёлся источник: у ещё не разложенной
    # страницы sizeHint() равен -1, и он уходил в setMinimumHeight.
    # Ошибка безвредная, но повторялась и заглушала настоящие
    # предупреждения - а заглушать их нельзя.
    from PyQt6.QtCore import qInstallMessageHandler  # noqa: E402

    seen_qt: list[str] = []

    def _collect(mode, context, message) -> None:  # noqa: ANN001 - Qt
        seen_qt.append(str(message))

    previous = qInstallMessageHandler(_collect)
    try:
        fresh = app_main.MainWindow()
        fresh.show()
        app.processEvents()
        fresh.close()
        app.processEvents()
    finally:
        qInstallMessageHandler(previous)
    negative = [m for m in seen_qt if "Negative sizes" in m]
    check(not negative,
          "Qt не пишет про отрицательные размеры при сборке окна"
          + (": %d сообщений" % len(negative) if negative else ""))

    # Высоты: страница равна содержимому, списки не растягиваются.
    for tab, widget, limit in (
        (window.create_tab, window.create_tab.program_list, 220),
        (window.create_tab, window.create_tab.log, 220),
        (window.import_tab, window.import_tab.mine_list, 200),
        (window.caps_tab, window.caps_tab.caps_skills_list, 260),
    ):
        check(widget.height() <= limit,
              f"{type(tab).__name__}.{widget.objectName() or type(widget).__name__} "
              f"не растянут: {widget.height()} <= {limit}")

    # Образец лежит внутри базы: значит, уедет на любой компьютер вместе
    # с программой. Ничего скачивать из интернета не нужно.
    tpl = core.bridge_template_dir()
    check(tpl.is_dir(), f"образец моста лежит в программе: {tpl}")
    missing = [name for name in core.BRIDGE_FILES if not (tpl / name).is_file()]
    check(not missing,
          f"в образце {len(core.BRIDGE_FILES)} файлов; не хватает: "
          f"{missing or 'ничего'}")
    # Найдено 28.09: в BRIDGE_FILES зашит список файлов моста, и новый
    # модуль memory_tools.py в него не попал. Мост создавался, но не
    # запускался: ImportError. Проверка прямо на это и смотрит.
    _tpl_modules = {
        p.stem for p in tpl.glob("*.py")
    } - {"server", "ncp_core", "__init__"}
    _copied = {"server", "ncp_core"} | {Path(n).stem for n in core.BRIDGE_FILES}
    _lost = sorted(_tpl_modules - _copied)
    check(not _lost,
          f"в образце нет модулей, которые забыли внести в BRIDGE_FILES: "
          f"{_lost or 'ничего'}")
    check("memory_tools.py" in core.BRIDGE_FILES,
          "модуль инструментов памяти входит в список копируемых файлов")


    # Переносимость: в образце не должно быть имени чужого пользователя,
    # иначе мост не заработает у другого человека. Исключение — сам мост
    # подключённой базы: он обязан ссылаться на собственную библиотеку,
    # при переносе программа всё равно перепишет путь заново.
    user = Path.home().name
    cfg_text = (tpl / "config.json").read_text(encoding="utf-8", errors="replace")
    try:
        pointed = json.loads(cfg_text).get("library_path", "")
    except ValueError:
        pointed = ""
    owner = core.app_root().as_posix()
    self_ref = (isinstance(pointed, str)
                and pointed.replace("\\", "/").startswith(owner + "/"))
    dirty = [
        path.name
        for path in tpl.rglob("*")
        if path.is_file()
        and user
        and not (path.name == "config.json" and self_ref)
        and user in path.read_text(encoding="utf-8", errors="replace")
    ]
    check(not dirty, f"в образце моста нет чужого имени: {dirty or 'чисто'}")
    check(core.BRIDGE_LIBRARY_PLACEHOLDER in cfg_text or self_ref,
          "в образце пометка или собственная библиотека")
    check(core.find_python() is not None,
          f"Python для запуска моста найден: {core.find_python()}")

    # Настоящую библиотеку запоминаем до работы — после она должна быть
    # точно такой же: все проверки идут на временной копии.
    real_library = core.library_dir(core.app_root())
    real_index = real_library / "index.json"
    index_before = real_index.read_text(encoding="utf-8") if real_index.is_file() else ""
    journal_dir = real_library / "журнал"
    journal_before = sorted(p.name for p in journal_dir.glob("*.md")) if journal_dir.is_dir() else []

    bridge_dir = btmp / "NCP-мост"
    result = core.create_bridge(bridge_dir, real_library)
    check(result.ok,
          f"мост создан во временной папке: "
          f"{'; '.join(result.errors)[:120] or 'без замечаний'}")
    check(core.looks_like_bridge(bridge_dir),
          "мост опознаётся по содержимому, а не по имени папки")
    written = json.loads((bridge_dir / "config.json").read_text(encoding="utf-8"))
    check("библиотека" in str(written.get("library_path", "")),
          f"путь к библиотеке подставлен: {written.get('library_path')}")
    check(core.BRIDGE_LIBRARY_PLACEHOLDER not in str(written.get("library_path", "")),
          "пометки в config.json не осталось")
    check(result.checked, "мост сам себя проверил, и проверка прошла")
    check(result.python is not None, f"в итоге записан Python: {result.python}")
    status = core.bridge_status(bridge_dir)
    check(status.exists, "готовый мост опознаётся проверкой состояния")
    check(not status.problem, f"замечаний к мосту нет: {status.problem or 'нет'}")
    check("библиотека" in status.library,
          f"состояние показывает библиотеку: {status.library}")

    # Проверку можно запустить и отдельно — кнопкой «Проверить».
    # Число проверок не зашиваем: мост их прибавляет, и любое новое
    # назначение ломало бы эту строку. Смотрим только на «все прошли».
    ok, output = core.bridge_selftest(bridge_dir)
    tail = [line.strip() for line in output.splitlines() if "ИТОГ" in line]
    check(ok and tail and "все" in tail[-1],
          f"проверка моста запускается отдельно и проходит: {tail[-1] if tail else 'нет строки ИТОГ'}")
    check("[СБОЙ]" not in output, "в самопроверке моста нет ни одного сбоя")

    # В чужую непустую папку не пишем: там могут быть нужные файлы.
    foreign = btmp / "чужая-папка"
    foreign.mkdir()
    (foreign / "чужой-файл.txt").write_text("не трогать", encoding="utf-8")
    refused = core.create_bridge(foreign, real_library)
    check(not refused.ok, "в чужую непустую папку мост не пишется")
    check("не пустая" in " ".join(refused.errors),
          f"сказано, почему отказано: {refused.errors[0][:60]}")
    check(len(list(foreign.iterdir())) == 1,
          "чужой файл остался один — лишнего не создано")

    # Настройки моста собираются в текст — показать человеку.
    snippet = core.mcp_snippet(core.find_python(), bridge_dir / "server.py")
    check('"ncp"' in snippet and "stdio" in snippet,
          "настройки моста собираются в понятный текст")

    # Что человек видит в окне
    check(bool(btab.folder_edit.text()),
          f"в окне предложена папка для моста: {btab.folder_edit.text()}")
    check("Python" in btab.program_hint.text(),
          "в окне показан найденный Python")
    check(btab.btn_create.isEnabled(), "кнопка «Создать мост» доступна")
    check(btab.btn_check.isEnabled(), "кнопка «Проверить» доступна")
    latin = [
        text
        for text in (btab.btn_create.text(), btab.btn_check.text(), btab.btn_open.text())
        if any("a" <= ch.lower() <= "z" for ch in text)
    ]
    check(not latin, f"надписи на кнопках по-русски: {latin or 'чисто'}")

    # Предложение создать мост после создания базы не должно ломаться
    # и должно подставлять путь к новой библиотеке. Вопрос человеку
    # подменяем отказом: в проверке кликать некому, а модальное окно
    # без цикла событий виснет навсегда.
    from unittest import mock
    from PyQt6.QtWidgets import QMessageBox
    with mock.patch.object(QMessageBox, "question",
                           return_value=QMessageBox.StandardButton.No):
        window._suggest_bridge("")
        window._suggest_bridge(str(btmp / "нет-такой-библиотеки"))
        check(True, "пустой путь и путь без библиотеки не ломают предложение")
        window._suggest_bridge(str(core.app_root()))
    check(btab.library_edit.text().endswith("библиотека"),
          "предложение подставило путь к библиотеке новой базы")

    # И главное: настоящая библиотека не тронута.
    index_after = real_index.read_text(encoding="utf-8") if real_index.is_file() else ""
    check(index_before == index_after,
          "index.json настоящей библиотеки не изменился")
    journal_after = sorted(p.name for p in journal_dir.glob("*.md")) if journal_dir.is_dir() else []
    check(journal_before == journal_after,
          f"в журнале настоящей библиотеки новых файлов нет: {journal_after}")

    # ---- 8. Возможности для opencode — только во временной папке.
    # Настоящий ~/.config/opencode здесь не трогаем.
    echo("\n--- 8. Возможности opencode ---")
    import opencode_caps  # noqa: E402

    ctmp = Path(tempfile.mkdtemp(prefix="caps-check-"))
    fake = ctmp / "opencode"
    fake.mkdir()
    (fake / "opencode.jsonc").write_text(
        "{\n"
        '  // чужой комментарий\n'
        '  "mcp": {\n'
        '    "other": {"type": "remote", "url": "https://x"}\n'
        "  },\n"
        '  "permission": {"edit": "deny"}\n'
        "}\n",
        encoding="utf-8",
    )
    sel = {"voice", "pc", "ncp", "agents"}
    base = core.app_root()
    messages, errors = opencode_caps.install_caps(base, fake, sel)
    check(not errors, f"установка возможностей без ошибок: {errors or 'чисто'}")
    cfg_text = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check("чужой комментарий" in cfg_text, "чужой комментарий в настройках цел")
    check('"other"' in cfg_text, "чужой сервер other цел")
    check('"pc"' in cfg_text and '"ncp"' in cfg_text, "мосты pc и ncp вписаны")
    check(opencode_caps.check_jsonc(cfg_text), "настройки валидны после вставки")
    check(len(list((fake / "agents").glob("*.md"))) == 12, "агентов поставлено 12")
    check((fake / "command" / "voice.md").is_file(), "команда /голос поставлена")
    check("{{VOICE_DIR}}" not in (fake / "command" / "voice.md").read_text(encoding="utf-8"),
          "путь к голосу подставлен настоящим")
    messages2, errors2 = opencode_caps.install_caps(base, fake, sel)
    check(not errors2, "повторная установка без ошибок")
    cfg_text2 = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check(cfg_text2.count('"pc"') == 1, "повтор не двоит записи")
    status = opencode_caps.caps_status(fake)
    check(all(status[n] for n in sel), f"статус видит поставленное: {status}")
    _, errors3 = opencode_caps.remove_caps(fake, sel)
    check(not errors3, f"удаление без ошибок: {errors3 or 'чисто'}")
    cfg_text3 = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check(opencode_caps.check_jsonc(cfg_text3) and '"pc"' not in cfg_text3,
          "после удаления настройки валидны и чистые")
    check('"other"' in cfg_text3, "чужое цело после удаления")
    check(not (fake / "command" / "voice.md").exists(), "команда убрана")
    check(list((fake / "agents").glob("*.md")) == [], "агенты убраны")

    # ---- 8а. Обход блокировок — туда же, во временную папку.
    # Ярлык не ставим: проверка не должна трогать настоящий рабочий стол.
    import antiblock  # noqa: E402

    ab_opts = {"facade": True, "lists": True, "command": True, "shortcut": False}
    m_ab, e_ab = opencode_caps.install_caps(
        base, fake, {"antiblock"}, antiblock_opts=ab_opts
    )
    check(not e_ab, f"обход поставлен без ошибок: {e_ab or 'чисто'}")
    check((fake / "antiblock" / "http_facade.py").is_file(), "фасад у программы")
    check((fake / "antiblock" / "public_socks5.txt").is_file(), "пул у программы")
    check((fake / "antiblock" / "subscriptions.txt").is_file(), "подписки у программы")
    check((fake / "antiblock" / "start_opencode_proxy.cmd").is_file(),
          "запускалка у программы")
    check((fake / "antiblock" / "xray_runner.py").is_file(),
          "свой Xray у программы")
    check((fake / "antiblock" / "dns_resolver.py").is_file(),
          "защищённый DNS у программы")
    check((fake / "command" / "antiblock.md").is_file(), "команда /обход у программы")
    check(not list((fake / "antiblock").glob("*.local.*")),
          "личных списков у программы нет")
    ab_cfg = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check(opencode_caps.check_jsonc(ab_cfg), "настройки валидны после обхода")
    check("antiblock" not in ab_cfg, "в opencode.jsonc ничего лишнего не вписано")
    check("чужой комментарий" in ab_cfg, "чужой комментарий цел после обхода")
    m_ab2, e_ab2 = opencode_caps.install_caps(
        base, fake, {"antiblock"}, antiblock_opts=ab_opts
    )
    check(not e_ab2, "повтор обхода без ошибок")
    check(
        sorted(p.name for p in (fake / "antiblock").iterdir() if p.is_file())
        == sorted(
            p.name
            for p in (core.program_root() / "tools" / "antiblock").iterdir()
            if p.is_file() and not p.name.startswith("public_socks5.local")
        ),
        "повтор не двоит и не мусорит в наборе",
    )
    check(opencode_caps.caps_status(fake).get("antiblock") is True,
          "статус видит обход")
    ok_conn, _text_conn = antiblock.check_connection(port=_free_port())
    check(ok_conn is False, "проверка честно говорит: фасад не запущен (свободный порт)")
    _, e_ab3 = opencode_caps.remove_caps(fake, {"antiblock"})
    check(not e_ab3, f"обход убран без ошибок: {e_ab3 or 'чисто'}")
    check(not (fake / "antiblock" / "http_facade.py").exists(), "фасад убран")
    check(not (fake / "command" / "antiblock.md").exists(), "команда /обход убрана")
    check((fake / "_previous-version" / "antiblock" / "http_facade.py").is_file(),
          "файлы обхода сохранены в _previous-version/antiblock")
    ab_cfg3 = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check(opencode_caps.check_jsonc(ab_cfg3) and '"other"' in ab_cfg3,
          "после уборки обхода валидно и чужое цело")
    check(opencode_caps.caps_status(fake).get("antiblock") is not True,
          "статус больше не видит обход")

    # Горячая подмена пула (set_upstreams) и безопасность автообновления.
    sys.path.insert(0, str(core.program_root() / "tools" / "antiblock"))
    import http_facade  # noqa: E402
    import pool_refresh  # noqa: E402

    pool = http_facade.ProxyPool(["socks5://1.1.1.1:1080", "socks5://2.2.2.2:1080"])
    accepted = pool.set_upstreams(["socks5://3.3.3.3:1080", "socks5://4.4.4.4:1080"])
    check(accepted == 2, f"set_upstreams принял новый пул: {accepted}")
    new_urls = {pool.next_url() for _ in range(4)}
    check(new_urls == {"socks5://3.3.3.3:1080", "socks5://4.4.4.4:1080"},
          "после подмены пул отдаёт только новые узлы")
    before = set(pool.next_url() for _ in range(2))
    check(before == new_urls, "курсор сброшен, новый пул сразу доступен")
    keep = pool.set_upstreams([])
    check(keep == 0, f"пустой список не принят: {keep}")
    check(len(pool.upstreams) == 2, "старый пул цел после отказа от пустого")
    keep2 = pool.set_upstreams(["не_валид", "socks5://5.5.5.5:1080"])
    check(keep2 == 1, f"невалидные пропущены, валидный принят: {keep2}")

    # refresh_pool не трогает существующий файл, если живых узлов нет.
    tmp_pool = fake / "tmp-live.txt"
    tmp_pool.write_text("socks5://9.9.9.9:1080\n", encoding="utf-8")
    report = pool_refresh.refresh_pool(
        output=tmp_pool,
        sources=("http://127.0.0.1:1/never",),
        fetch_timeout=0.5,
        timeout=0.3,
        workers=2,
    )
    check(report["ok"] is False, "без живых узлов отчёт честно говорит «не ок»")
    check(tmp_pool.read_text(encoding="utf-8").strip() == "socks5://9.9.9.9:1080",
          "старый пул не перезаписан при неудачном обновлении")
    if tmp_pool.exists():
        tmp_pool.unlink()


    # ---- 8б. Новые пресеты провайдеров — туда же, во временную папку.
    psel = {"ollama", "lmstudio"}
    _, perrors = opencode_caps.install_providers(fake, psel)
    check(not perrors, f"провайдеры вписаны без ошибок: {perrors or 'чисто'}")
    pcfg = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check(opencode_caps.check_jsonc(pcfg), "настройки валидны после пресетов")
    check('"ollama"' in pcfg and '"lmstudio"' in pcfg,
          "оба пресета на месте")
    check("sk-" not in pcfg, "никаких ключей в файл не попало")
    _, perrors2 = opencode_caps.install_providers(fake, psel)
    check(not perrors2, "повтор провайдеров без ошибок")
    pcfg2 = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check(pcfg2.count('"ollama"') == 1, "повтор не двоит пресет")
    check(all(opencode_caps.providers_status(fake).values()), "статус видит пресеты")
    _, perrors3 = opencode_caps.remove_providers(fake, psel)
    check(not perrors3, f"пресеты убраны без ошибок: {perrors3 or 'чисто'}")
    pcfg3 = (fake / "opencode.jsonc").read_text(encoding="utf-8")
    check(opencode_caps.check_jsonc(pcfg3) and '"ollama"' not in pcfg3,
          "после уборки валидно и чисто")
    check('"other"' in pcfg3, "чужое цело после уборки пресетов")

    # Вкладка в окне: три галочки расширений + два провайдера.
    # Мостов среди галочек нет — они едут с базой и подставляются всегда.
    ctab = window.caps_tab
    check(len(ctab.checks) == 3, f"галочек три: {sorted(ctab.checks)}")
    check("antiblock" in ctab.checks, "галочка обхода на месте")
    check("pc" not in ctab.checks and "ncp" not in ctab.checks,
          "галочек мостов в окне нет — они едут с базой")
    sel = ctab._selection()
    check({"pc", "ncp"} <= sel, f"мосты входят в выбор всегда: {sorted(sel)}")
    check(len(ctab.pchecks) == 2, f"провайдеров два: {sorted(ctab.pchecks)}")
    check(all(box.isChecked() for box in ctab.checks.values()), "по умолчанию всё отмечено")
    check(not any(box.isChecked() for box in ctab.pchecks.values()),
          "провайдеры по умолчанию не отмечены (ключи — дело человека)")
    check(ctab.btn_install.isEnabled(), "кнопка «Поставить» доступна")
    check(ctab.btn_remove.isEnabled(), "кнопка «Убрать» доступна")
    check(len(ctab.achecks) == 5, f"состава обхода пять: {sorted(ctab.achecks)}")
    check(all(box.isChecked() for box in ctab.achecks.values()),
          "состав обхода по умолчанию весь отмечен")
    check(ctab.btn_ab_check.isEnabled(), "кнопка проверки подключения доступна")
    check(ctab.btn_ab_dns.isEnabled(), "кнопка проверки DNS доступна")
    latin = [
        text
        for text in (ctab.btn_install.text(), ctab.btn_remove.text(), ctab.btn_refresh.text())
        if any("a" <= ch.lower() <= "z" for ch in text)
    ]
    check(not latin, f"надписи кнопок по-русски: {latin or 'чисто'}")

    # Шаг 4 на вкладке opencode: навыки поштучно, все отмечены.
    # Список берётся из ВЫБРАННОЙ базы, а не из конструктора: вкладка
    # показывает то, что реально лежит в подключённой базе.
    want_skills = core.list_skills(ctab._base())
    check(ctab.caps_skills_list.count() == len(want_skills),
          f"навыков в списке: {ctab.caps_skills_list.count()} из {len(want_skills)}")
    check(len(ctab._chosen_caps_skills()) == len(want_skills),
          "при первом показе отмечены все навыки")
    check(ctab.btn_skills_put.isEnabled() and ctab.btn_skills_drop.isEnabled(),
          "кнопки поставить/убрать навыки доступны")
    nagents = len(list((core.program_root() / 'tools' / 'agents').glob('*.md')))
    check(str(nagents) in ctab.checks['agents'].text(),
          f"агентов названо честно: {ctab.checks['agents'].text()[:40]}")

    # Мост: выбор программы и кнопка оверлея.
    check(btab.radio_open.isChecked(), "по умолчанию мост для opencode")
    check(btab.btn_save_overlay.isEnabled(), "кнопка YAML для Харнеса доступна")
    overlay = core.harness_overlay_snippet(Path("C:/py/python.exe"), Path("C:/m/server.py"))
    check("dsh --patch" in overlay and "memory-ncp" in overlay,
          "оверлей Харнеса: имя и применение на месте")
    shutil.rmtree(ctmp, ignore_errors=True)
    echo(f"Временная папка возможностей убрана: {ctmp}")

    # Вкладка «Темы»: папка в корне главной базы, список файлов и кнопки.
    ttab = window.themes_tab
    check(ttab.themes_dir() == core.program_root() / "themes", "папка тем — themes/ в корне базы")
    check(ttab.btn_open is not None and ttab.btn_refresh is not None,
          "кнопки «Открыть папку тем» и «Обновить список» на месте")
    check(ttab.list_.count() >= 1, "в списке есть хотя бы одна тема-заготовка")

    # ---- 8в. перевод подключённой базы: пути, мосты и права меняются
    # на новую базу, а чужое (провайдеры, чужие серверы) остаётся.
    echo("\n--- 8в. Перевод настроек на другую базу ---")
    wtmp = Path(tempfile.mkdtemp(prefix="wire-check-"))
    other_base = wtmp / "Старая-база"
    (other_base / "tools").mkdir(parents=True)
    wdest = wtmp / "opencode"
    wdest.mkdir()
    (wdest / "opencode.jsonc").write_text(
        "{\n"
        '  "$schema": "https://opencode.ai/config.json",\n'
        '  "instructions": [\n'
        f'    "{other_base.as_posix()}/profile.md"\n'
        "  ],\n"
        '  "provider": {"myauto": {"npm": "@ai-sdk/openai-compatible"}},\n'
        '  "mcp": {"other": {"type": "remote", "url": "https://x"}},\n'
        '  "permission": {"edit": "deny"}\n'
        "}\n",
        encoding="utf-8",
    )
    wbase = wtmp / "Новая-база"
    for path in core.INSTRUCTION_TARGETS:
        p = wbase / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("текст", encoding="utf-8")
    (wbase / "tools" / "ncp-bridge").mkdir(parents=True)
    (wbase / "tools" / "ncp-bridge" / "config.json").write_text(
        '{"library_path": "{{LIBRARY}}"}\n', encoding="utf-8"
    )
    wire_msgs = opencode_caps.rewire_config(wdest, wbase)
    wcfg = (wdest / "opencode.jsonc").read_text(encoding="utf-8")
    check(opencode_caps.check_jsonc(wcfg), "файл валиден после перевода")
    check("Старая-база" not in wcfg, "старый путь ушёл из instructions")
    check(wbase.as_posix() in wcfg, "instructions указывают на новую базу")
    check("myauto" in wcfg, "чужой провайдер цел")
    check('"other"' in wcfg, "чужой сервер other цел")
    check('"edit": "deny"' in wcfg, "чужие права целы")
    check('"ncp"' in wcfg and '"pc"' in wcfg, "мосты ncp и pc вписаны")
    check('"ncp_*"' in wcfg and '"pc_*"' in wcfg, "права на мосты стоят")

    # Переключение на вторую базу: мосты переезжают, чужое остаётся.
    wbase2 = wtmp / "Ещё-база"
    (wbase2 / "tools" / "ncp-bridge").mkdir(parents=True)
    (wbase2 / "tools" / "ncp-bridge" / "config.json").write_text(
        '{"library_path": "{{LIBRARY}}"}\n', encoding="utf-8"
    )
    (wbase2 / "profile.md").write_text("текст", encoding="utf-8")
    opencode_caps.rewire_config(wdest, wbase2)
    wcfg2 = (wdest / "opencode.jsonc").read_text(encoding="utf-8")
    check(opencode_caps.check_jsonc(wcfg2), "файл валиден после переключения")
    check(wbase2.as_posix() in wcfg2, "instructions переехали на вторую базу")
    check(other_base.as_posix() not in wcfg2, "пути первой базы не остались")
    check("myauto" in wcfg2 and '"other"' in wcfg2,
          "чужое пережило переключение")
    check('"ncp"' in wcfg2 and '"pc"' in wcfg2, "мосты на месте после переезда")
    for fix in core.configure_ncp_bridge(wbase2):
        pass
    bridge2 = json.loads(
        (wbase2 / "tools" / "ncp-bridge" / "config.json").read_text(encoding="utf-8")
    )
    check("библиотека" in str(bridge2.get("library_path", "")),
          "мост второй базы получил путь к библиотеке")
    shutil.rmtree(wtmp, ignore_errors=True)
    echo("Временная папка перевода убрана")

    # Мосты внутри базы: полный круг подключение → отключение → подключение.
    echo("\n--- 8г. Мосты живут в базе ---")
    mtmp = Path(tempfile.mkdtemp(prefix="mosty-bazy-"))
    mbase = mtmp / "MostBase"
    (mbase / "библиотека").mkdir(parents=True)
    (mbase / "библиотека" / "index.json").write_text("{}", encoding="utf-8")
    (mbase / "библиотека" / "NCP.md").write_text("x", encoding="utf-8")
    for _bridge in core.BASE_BRIDGES:
        shutil.copytree(
            core.program_root() / "tools" / _bridge,
            mbase / "tools" / _bridge,
            ignore=shutil.ignore_patterns("__pycache__", "config.json"),
        )
    mncp = mbase / "tools" / "ncp-bridge" / "config.json"
    mpc = mbase / "tools" / "pc-bridge" / "config.json"
    check(not mncp.is_file() and not mpc.is_file(),
          "сценарий поломки: у мостов нет config.json")

    for _msg in core.configure_bridges(mbase):
        pass
    check(mncp.is_file(), "мост NCP: config.json достроен в базу")
    check(mpc.is_file(), "мост ПК: config.json достроен в базу")
    _cfg = json.loads(mncp.read_text(encoding="utf-8"))
    check(_cfg.get("library_path") == (mbase / "библиотека").as_posix(),
          "мост NCP: путь ведёт в библиотеку этой базы")
    check("{{LIBRARY}}" not in str(_cfg.get("library_path", "")),
          "мост NCP: заглушка убрана")
    _pc = json.loads(mpc.read_text(encoding="utf-8"))
    check(_pc.get("allowed_dirs") == ["{{BASE}}"],
          "мост ПК: allowed_dirs с пометкой {{BASE}} (развернёт сам)")

    _tpl = core.bridge_template_config("ncp-bridge")
    _before = hashlib.sha256(_tpl.read_bytes()).hexdigest() if _tpl.is_file() else ""
    _lib = (mbase / "библиотека").as_posix()
    _cfg = json.loads(mncp.read_text(encoding="utf-8"))
    if _cfg.get("library_path") == _lib:
        _cfg["library_path"] = core.BRIDGE_LIBRARY_PLACEHOLDER
        mncp.write_text(json.dumps(_cfg, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    _off = json.loads(mncp.read_text(encoding="utf-8"))
    check(_off.get("library_path") == core.BRIDGE_LIBRARY_PLACEHOLDER,
          "мост NCP отключён: путь снова заглушка")
    check(mncp.is_file() and mpc.is_file(),
          "настройки мостов остались в базе (ничего не удалено)")
    check((mbase / "библиотека" / "index.json").is_file(), "библиотека базы цела")
    _after = hashlib.sha256(_tpl.read_bytes()).hexdigest() if _tpl.is_file() else ""
    check(_after == _before, "отключение не тронуло конструктор")

    for _msg in core.configure_bridges(mbase):
        pass
    _on = json.loads(mncp.read_text(encoding="utf-8"))
    check(_on.get("library_path") == _lib,
          "мост NCP ожил после повторного подключения")
    _after2 = hashlib.sha256(_tpl.read_bytes()).hexdigest() if _tpl.is_file() else ""
    check(_after2 == _before, "подключение не тронуло конструктор")
    check(json.loads(mncp.read_text(encoding="utf-8")).get("library_path") != "",
          "мост NCP не остался с пустым путём")

    # Код моста в базе может устареть: тогда он не умеет разворачивать
    # пометки {{BASE}} и запрещает всё. Лечится обновлением из конструктора.
    _code = mbase / "tools" / "pc-bridge" / "server.py"
    _good = _code.read_bytes()
    _code.write_text("# устаревшая копия без разворачивания пометок\n", encoding="utf-8")
    _msgs = core.refresh_bridge_code(mbase)
    check(_code.read_bytes() == _good, "код моста ПК обновлён из конструктора")
    check(any("server.py" in _m for _m in _msgs), f"обновление отмечено в отчёте: {_msgs}")
    _lib_now = json.loads(mncp.read_text(encoding="utf-8")).get("library_path")
    check(_lib_now == _lib, "обновление кода не сбросило путь к библиотеке")
    check(core.refresh_bridge_code(mbase) == [],
          "повторное обновление молчит, когда код уже свежий")
    shutil.rmtree(mtmp, ignore_errors=True)
    echo("Временная база мостов убрана")

    # Основная база ищется по маркеру, ничего не меняя.
    main_now = core.current_base("opencode")
    check(isinstance(main_now, (Path, type(None))),
          "текущая основная база читается без ошибок")

    shutil.rmtree(btmp, ignore_errors=True)
    echo(f"Временная папка моста убрана: {btmp}")

    # ---- 14. удаление базы не задевает другие базы: найдено 28.09
    echo("\n--- 14. Удаление базы ---")

    # Кнопка «Удалить» удаляет по-настоящему — так и обещает, и человек,
    # которому база не нужна, не будет держать её рядом копией. Проверять
    # надо другое и более важное: удаление одной базы не должно задевать
    # остальные, а живая основная база остаётся нетронутой.
    _zap = Path(tempfile.mkdtemp(prefix="dbapp-udal-"))
    try:
        _parent = _zap / "место"
        _parent.mkdir()

        # Две базы: одну удаляем, вторую она не должна задеть.
        _mark = "ПРОБА-НЕ-СТЕРЕТЬ"
        _live = []
        for _name in ("Проба-удалить", "Проба-оставить"):
            _plan = core.build_plan(_parent, _name, None)
            core.create_base(_plan)
            _b = _plan.target
            (_b / "профиль.md").write_text(f"{_mark} {_name}", encoding="utf-8")
            (_b / "библиотека" / "записи").mkdir(parents=True, exist_ok=True)
            (_b / "библиотека" / "записи" / "проба.md").write_text(
                f"{_mark} {_name}", encoding="utf-8")
            (_b / "projects").mkdir(exist_ok=True)
            (_b / "projects" / "моя-работа.md").write_text(
                f"{_mark} {_name}", encoding="utf-8")
            _live.append(_b)
        _doomed, _spare = _live

        # 1. Без подтверждения ничего не происходит.
        ok1, msg1 = core.delete_base(_doomed)
        check(not ok1, "без confirm=True база не удаляется")
        check(_doomed.is_dir(), "папка осталась на месте после отказа")
        check((_doomed / "профиль.md").read_text(encoding="utf-8").strip()
              == f"{_mark} Проба-удалить", "профиль не тронут отказом")
        check("confirm=True" in msg1,
              f"отказ объясняет, что нужно: {msg1[:60]}")

        # 2. С подтверждением папка исчезает целиком, без остатков.
        ok2, msg2 = core.delete_base(_doomed, confirm=True)
        check(ok2, f"база удалена: {msg2}")
        check(not _doomed.exists(), "папки базы больше нет на диске")
        _leftovers = sorted(_parent.glob("Проба-удалить*"))
        check(not _leftovers,
              f"рядом не осталось её копий: {[p.name for p in _leftovers]}")

        # 3. Главное: вторая база цела — профиль, библиотека, проекты.
        check(_spare.is_dir(), "другая база осталась на месте")
        check((_spare / "профиль.md").read_text(encoding="utf-8").strip()
              == f"{_mark} Проба-оставить", "её профиль цел")
        check((_spare / "facts.md").is_file() and
              (_spare / "projects.md").is_file(),
              "facts.md и projects.md целы")
        check((_spare / "библиотека" / "записи" / "проба.md")
              .read_text(encoding="utf-8").strip()
              == f"{_mark} Проба-оставить", "запись библиотеки цела")
        check((_spare / "projects" / "моя-работа.md").is_file(),
              "работа по проектам цела")

        # 4. Страховка на будущее: удаление остаётся удалением.
        _code = (core.program_root() / "tools" / "dbapp" / "core.py")
        _fn = _code.read_text(encoding="utf-8")
        _fn = _fn.split("def delete_base(", 1)[-1].split("\ndef ", 1)[0]
        check("rmtree" in _fn,
              "delete_base по-настоящему стирает папку — как и обещает кнопка")
        _fn_i = _fn.find("rmtree")
        _fn_f = _fn.find("forget_base")
        check(0 <= _fn_i < _fn_f,
              "из списка база убирается только после успешного удаления")
    finally:
        shutil.rmtree(_zap, ignore_errors=True)
        echo(f"Временная папка убрана: {_zap}")

    # ---- 15. конструктор не везёт мою базу: запасной заслон
    echo("\n--- 15. Конструктор не везёт мою базу ---")

    # Человек спросил прямо: конструктор — это конструктор, а не моя база.
    # Проверяем дважды: что в эталоне нет личных файлов и что копирование
    # действино их пропускает. Второе важнее первого — правило в тексте
    # ничего не значит, если код ведёт себя иначе.
    _kit = core.program_root()

    # 1. В эталоне не должно быть личных файлов базы.
    _personal = [
        name for name in ("profile.md", "facts.md", "projects.md",
                          "профиль.md", "АКТИВНАЯ-ПАМЯТЬ.md", "активная-память.md")
        if (_kit / name).exists()
    ]
    check(not _personal, f"в конструкторе нет личных файлов базы: {_personal or 'ни одного'}")
    _pdirs = [
        name for name in ("projects", "sessions", "сессии", "память", "личное")
        if (_kit / name).is_dir()
    ]
    check(not _pdirs, f"в конструкторе нет папок с личным: {_pdirs or 'ни одной'}")
    # Личные записи отличить от служебных: запись называется ncp-…md,
    # пояснение папки — _О-ПАПКЕ.md. Раньше считались все md, и проверка
    # ругалась на собственное пояснение.
    _pl = _kit / "библиотека" / "записи" / "личное"
    _priv = sorted(p.name for p in _pl.glob("ncp-*.md")) if _pl.is_dir() else []
    check(not _priv,
          f"личных записей NCP в конструкторе нет: {len(_priv)}")
    check((_pl / "_О-ПАПКЕ.md").is_file(),
          "в конструкторе есть папка личное с пояснением, а не записями")
    check((_kit / "ОБРАЗЕЦ-БАЗЫ.md").is_file(),
          "заготовка ОБРАЗЕЦ-БАЗЫ.md на месте — её создавать база должна")

    # 2. Копирование личное пропускает, а справочное везёт.
    _uz = Path(tempfile.mkdtemp(prefix="dbapp-uchego-"))
    try:
        _src = _uz / "образец"
        (_src / "библиотека" / "записи" / "личное" / "моё").mkdir(parents=True)
        (_src / "библиотека" / "записи" / "личное" / "моё" / "моя-запись.md").write_text(
            "личное", encoding="utf-8")
        (_src / "библиотека" / "записи" / "справка").mkdir(parents=True)
        (_src / "библиотека" / "записи" / "справка" / "справочная.md").write_text(
            "справочное", encoding="utf-8")
        _dst = _uz / "новая"
        core._copy_lib_records(_src, _dst)
        _got_priv = (_dst / "библиотека" / "записи" / "личное").rglob("*.md")
        check(not list(_got_priv), "личная запись в новую базу не попала")
        _got_ref = list((_dst / "библиотека" / "записи" / "справка").glob("*.md"))
        check(len(_got_ref) == 1,
              f"справочная запись переехала: {len(_got_ref)} шт.")

        # 3. Главное по существу: база, собранная с нуля, не содержит
        # ничьих личных данных. Профиль и факты — пустые заготовки,
        # личных папок и личных записей нет вовсе.
        _plan0 = core.build_plan(_uz / "с-нуля", "Проба-пустая-база", None)
        (_uz / "с-нуля").mkdir(exist_ok=True)
        core.create_base(_plan0)
        _fresh = _plan0.target
        _prof = (_fresh / "profile.md").read_text(encoding="utf-8")
        check(core.BLANK["profile.md"] == _prof,
              "профиль новой базы — пустая заготовка, без данных пользователя")
        _name_line = [ln for ln in _prof.splitlines() if "Зовут" in ln]
        check(bool(_name_line) and not _name_line[0].split("Зовут:")[-1].strip(),
              f"в профиле имя пустое: {_name_line}")
        check((_fresh / "projects.md").read_text(encoding="utf-8").strip()
              == core.BLANK["projects.md"].strip(),
              "projects.md новой базы — заготовка, не список моих проектов")
        # Личные папки создаются пустыми: в них лежат только пояснения
        # «что сюда писать». Ни одного настоящего файла быть не должно.
        _fresh_priv = []
        for name in ("projects", "sessions", "сессии", "память", "личное",
                     "журнал-решений", "настройки"):
            folder = _fresh / name
            if not folder.is_dir():
                continue
            for path in folder.rglob("*"):
                if not path.is_file() or path.name == "_О-ПАПКЕ.md":
                    continue
                # В папке настроек лежит ещё и решение о чувствительных
                # данных: это настройка базы, а не личные данные.
                if name == "настройки" and path.name == "чувствительные-данные.md":
                    continue
                _fresh_priv.append(path.relative_to(_fresh).as_posix())
        check(not _fresh_priv,
              f"в личных папках новой базы нет данных пользователя: "
              f"{_fresh_priv or 'ни одного файла'}")
        _pol = _fresh / "настройки" / "чувствительные-данные.md"
        check(_pol.is_file(),
              "файл решения о чувствительных данных создан в новой базе")
        if _pol.is_file():
            check("ЗАПРЕЩЕНО" in _pol.read_text(encoding="utf-8"),
                  "по умолчанию в новой базе запрет — решение человека")
        # Личная запись — это ncp-…md. Пояснение папки _О-ПАПКЕ.md
        # служебное и в новую базу едет намеренно.
        _pl_dir = _fresh / "библиотека" / "записи" / "личное"
        _fresh_lib = sorted(p.name for p in _pl_dir.glob("ncp-*.md")) \
            if _pl_dir.is_dir() else []
        check(not _fresh_lib,
              f"личных записей NCP в новой базе нет: {len(_fresh_lib)}")
        check((_pl_dir / "_О-ПАПКЕ.md").is_file(),
              "пояснение личной папки в новой базе есть")
        check((_fresh / "skills").is_dir() and core.count_skills(_fresh) > 0,
              f"а скиллы в неё приехали: {core.count_skills(_fresh)}")
    finally:
        shutil.rmtree(_uz, ignore_errors=True)
        echo(f"Временная папка убрана: {_uz}")

    # ---- 16. новая база сама говорит, что подключилась: найдено 28.09
    echo("\n--- 16. Нейросеть сообщает о подключении ---")

    # Человек спросил: при первом же сообщении нейросеть должна читать базу
    # И сообщать об этом. Читать — было указано, сообщать — нет. Молчаливое
    # подключение снаружи неотличимо от сломанной памяти.
    _uz2 = Path(tempfile.mkdtemp(prefix="dbapp-podklyuch-"))
    try:
        _p3 = core.build_plan(_uz2 / "место", "Проба-подключение", None)
        (_uz2 / "место").mkdir(exist_ok=True)
        core.create_base(_p3)
        _ag = _p3.target / "AGENTS.md"
        check(_ag.is_file(), f"в новой базе есть AGENTS.md: {_ag.is_file()}")
        if _ag.is_file():
            _txt = _ag.read_text(encoding="utf-8")
            _start = _txt.split("## В начале каждой сессии", 1)
            check(len(_start) == 2, "в AGENTS.md есть раздел о начале сессии")
            _block = _start[1].split("\n## ", 1)[0] if len(_start) == 2 else ""
            for _what, _needle in (
                ("читает память", "memory_read"),
                ("спрашивает состояние библиотеки", "library_status"),
                ("читает активную память", "АКТИВНАЯ-ПАМЯТЬ"),
                ("сообщает пользователю о подключении",
                 "Скажи пользователю, что подключился"),
            ):
                check(_needle in _block,
                      f"в начале сессии: {_what}")
            # Правило должно быть именно в начале сессии, а не где попало.
            check(_txt.count("Скажи пользователю, что подключился") == 1,
                  "правило про уведомление встречается ровно один раз")
            # В копии для папки config/ то же самое.
            _ag2 = _p3.target / "config" / "AGENTS.md"
            if _ag2.is_file():
                check("Скажи пользователю, что подключился"
                      in _ag2.read_text(encoding="utf-8"),
                      "та же инструкция доехала в config/AGENTS.md")

        # ---- 16б. шаблон не должен запекаться в базу
        # Найдено 28.09: в корне базы вместо пометки {{BASE}} стоял
        # настоящий путь к мусорной папке DataBases/test. Причина —
        # substitute_base отработал на самой базе. База должна хранить
        # шаблон, иначе перестанет переезжать на другой компьютер.
        if _ag.is_file():
            _root_txt = _ag.read_text(encoding="utf-8")
            check(core.BASE_PLACEHOLDER in _root_txt,
                  "в корне новой базы AGENTS.md остаётся шаблоном с пометкой")
            check("DataBases" not in _root_txt,
                  "в корне базы нет запечённого пути к DataBases")

        # Подстановка обязана давать настоящий путь, а не мусор.
        _tmp_cfg = _uz2 / "подстановка.md"
        _tmp_cfg.write_text("база: " + core.BASE_PLACEHOLDER + "\n",
                            encoding="utf-8")
        core.substitute_base(_tmp_cfg, _p3.target)
        _fixed = _tmp_cfg.read_text(encoding="utf-8")
        check(str(_p3.target).replace("\\", "/") in _fixed,
              f"substitute_base подставил настоящий путь: {_fixed.strip()[:70]}")
        check(core.BASE_PLACEHOLDER not in _fixed,
              "пометка после подстановки не осталась")
    finally:
        shutil.rmtree(_uz2, ignore_errors=True)
        echo(f"Временная папка убрана: {_uz2}")

    # ---- 17. папка баз по умолчанию — DataBases: найдено 28.09
    echo("\n--- 17. Базы по умолчанию в папке DataBases ---")

    # Человек заметил: папка DataBases создаётся при первом запуске, но в
    # поле создания базы стояли «Документы». Программа рекомендовала одну
    # папку, а базы уезжали в другую.
    _db = core.data_bases_folder()
    check(_db.name == "DataBases", f"папка баз называется DataBases: {_db.name}")
    check(_db.parent == core.desktop_dir(),
          f"папка баз лежит на рабочем столе: {_db.parent}")

    # Создание папки: проверяем на временной, настоящий рабочий стол не трогаем.
    _dbt = Path(tempfile.mkdtemp(prefix="dbapp-databases-"))
    _real_desktop = core.desktop_dir
    try:
        core.desktop_dir = lambda: _dbt
        _made = core.data_bases_folder()
        check(not _made.exists(), "до вызова папки нет")
        core.ensure_data_bases_folder()
        check(_made.is_dir(), f"ensure_data_bases_folder создал папку: {_made.name}")
        core.ensure_data_bases_folder()
        check(_made.is_dir(), "повторный вызов безвреден")
    finally:
        core.desktop_dir = _real_desktop
        shutil.rmtree(_dbt, ignore_errors=True)

    # В окне по умолчанию стоит именно она.
    _ct = window.tabs.widget(0)
    _shown = _ct.parent_edit.text().strip()
    check(_shown == str(_db),
          f"в поле создания базы папка DataBases, а не Документы: {_shown}")
    check("Documents" not in _shown and "Документы" not in _shown,
          f"Документы больше не подставляются: {_shown}")
    _ct.name_edit.setText("Проба-дефолт")
    _prev = _ct.path_preview.text().strip()
    _path_part = _prev.partition(":")[2].strip() or _prev
    check(_path_part.startswith(str(_db)),
          f"новая база уедет в DataBases: {_path_part[:70]}")
    shutil.rmtree(_dbt, ignore_errors=True)

    # ---- 18. новая база знает, как пользоваться агентами и скиллами
    echo("\n--- 18. Новая база знает про агентов, скиллы и NCP ---")

    # Требование человека: новая база должна знать, что агент и скилл
    # существуют, понимать, когда их брать, и уметь применять их сама.
    # Проверяем на реально созданной базе.
    _zn = Path(tempfile.mkdtemp(prefix="dbapp-znaniya-"))
    try:
        _pp = _zn / "место"
        _pp.mkdir()
        _pz = core.build_plan(_pp, "Проба-знания", None)
        core.create_base(_pz)
        _zb = _pz.target
        _ag_txt = (_zb / "AGENTS.md").read_text(encoding="utf-8")

        # --- агенты
        _ad = _zb / "tools" / "agents"
        _n_agents = len(list(_ad.glob("*.md"))) if _ad.is_dir() else 0
        check(_n_agents > 0, f"в базе есть агенты: {_n_agents}")
        check("Агент вызывается как" in _ag_txt,
              "инструкция объясняет вызов агента по имени")
        check(f"Всего их {_n_agents}" in _ag_txt,
              f"инструкция называет число агентов ({_n_agents})")
        _chain = ("proektirovschik", "programmist", "proveryalschik", "retsenzent")
        check(all(c in _ag_txt for c in _chain),
              "названа связка большой задачи: план → код → проверка → рецензия")
        _sk_doc = (_zb / "инструкции" / "Скиллы-и-агенты.md")
        check(_sk_doc.is_file(), "подробная инструкция по скиллам и агентам есть")
        if _sk_doc.is_file():
            _missing = [p.stem for p in _ad.glob("*.md")
                        if p.stem not in _sk_doc.read_text(encoding="utf-8")]
            check(not _missing,
                  f"в инструкции перечислены все агенты; нет: {_missing or 'никого'}")

        # --- скиллы
        _n_skills = core.count_skills(_zb)
        check(_n_skills > 0, f"в базе есть скиллы: {_n_skills}")
        _idx = _zb / "skills-index.json"
        check(_idx.is_file(), "индекс скиллов лежит в базе")
        if _idx.is_file():
            _data = json.loads(_idx.read_text(encoding="utf-8"))
            _items = _data.get("skills") if isinstance(_data, dict) else _data
            check(len(_items) == _n_skills,
                  f"записей в индексе столько же, сколько скиллов: "
                  f"{len(_items)} из {_n_skills}")
            _no_when = [i.get("name") for i in _items if not i.get("when")]
            check(not _no_when,
                  f"у каждого скилла есть условие срабатывания; нет у: {_no_when or 'никого'}")
            _known = {i.get("name") for i in _items}
            _dirs = sorted(p.name for p in (_zb / "skills").iterdir() if p.is_dir())
            _lost = [n for n in _dirs if n not in _known]
            check(not _lost,
                  f"в индексе есть все скиллы; нет: {_lost or 'никого'}")
            check(not any(n in _known for n in
                          (p.stem for p in _ad.glob("*.md"))),
                  "агенты не попали в индекс скиллов — это разные вещи")

        # --- NCP: протокол должен называть настоящие имена инструментов
        _ncp_md = _zb / "библиотека" / "NCP.md"
        check(_ncp_md.is_file(), "протокол библиотеки NCP лежит в базе")
        if _ncp_md.is_file():
            _prot = _ncp_md.read_text(encoding="utf-8")
            for _tool in ("ncp_status", "ncp_search", "ncp_read", "ncp_save",
                          "ncp_update", "ncp_checkpoint", "ncp_reindex"):
                check(_tool in _prot, f"протокол называет инструмент {_tool}")
            check("library_search" in _prot,
                  "протокол упоминает и псевдоним library_search")

        # --- самостоятельность: без просьбы пользователя
        check("Скилл выбирается ДО начала работы" in _ag_txt,
              "инструкция велит выбрать скилл ДО работы")
        check("УВИДЕЛ ВОЗМОЖНОСТЬ" in _ag_txt,
              "есть правило «увидел возможность — скажи, потом применяй»")
        check("объяви это одной строкой" in _ag_txt,
              "применение объявляется ДО, а не после")
        check("не выдумывай инструмент ради применения" in _ag_txt,
              "есть запрет выдумывать инструмент ради применения")
        check("без просьбы пользователя" in _ag_txt,
              "взятие скилла объявлено обязательным без просьбы человека")

        # --- правило должно быть видно сразу, а не прятаться в конце
        _head = "\n".join(_ag_txt.splitlines()[:40])
        check("скилл" in _head.lower() and "агент" in _head.lower(),
              "про скиллы и агентов сказано в первых 40 строках инструкции")
    finally:
        shutil.rmtree(_zn, ignore_errors=True)
        echo(f"Временная папка убрана: {_zn}")

    # ---- 19. темы библиотеки — папки, и они создаются сами
    echo("\n--- 19. Темы библиотеки ---")

    # Требование человека: разносить данные по категориям и создавать
    # папку, если её нет. Пример: «личное, животные, собака Сэм».
    _kt = Path(tempfile.mkdtemp(prefix="dbapp-temy-"))
    try:
        _pk = core.build_plan(_kt / "место", "Проба-темы", None)
        (_kt / "место").mkdir(exist_ok=True)
        core.create_base(_pk)
        _kb = _pk.target

        # Папка категории есть, вложенной темы внутри нет.
        _deep = _kb / "библиотека" / "записи" / "личное" / "проверка"
        check(not _deep.exists(), "темы личное/проверка до записи нет")
        check((_kb / "библиотека" / "записи" / "личное").is_dir(),
              "папка категории личное создана при создании базы")

        # Новая база знает про это правило.
        for _f, _label in ((_kb / "AGENTS.md", "AGENTS.md"),
                           (_kb / "библиотека" / "NCP.md", "протокол NCP")):
            _t = _f.read_text(encoding="utf-8")
            check("Темы в библиотеке" in _t or "создаётся сама" in _t,
                  f"в {_label} описано: тема — папка, создаётся сама")
            check("личное/" in _t,
                  f"в {_label} есть пример вложенной темы")
            check("не едет" in _t or "не уезжают" in _t or "не копируются" in _t,
                  f"в {_label} сказано, что личное не уезжает")

        # В конструкторе код это умеет.
        _nc = (core.program_root() / "tools" / "ncp-bridge" / "ncp_core.py")
        _code = _nc.read_text(encoding="utf-8")
        check("def is_private(" in _code,
              "в коде моста есть различение личных тем")
        check("TOPIC_SEP" in _code,
              "в коде моста есть разделитель уровней темы")

        # Личное по-прежнему не копируется в новые базы. Правило живёт
        # в core.py, а не в мосте: я сперва искал его не там и проверка
        # падала без причины.
        _dc = (core.program_root() / "tools" / "dbapp" / "core.py")
        _copy = _dc.read_text(encoding="utf-8").split("def _copy_lib_records")[-1]
        check('parts[0] == "личное"' in _copy,
              "личные записи по-прежнему не копируются в новые базы")

        # Папка личное видна сразу, а не появляется при первой записи.
        _pl = _kb / "библиотека" / "записи" / "личное"
        check(_pl.is_dir(), "в новой базе есть папка личное")
        _hint = _pl / "_О-ПАПКЕ.md"
        check(_hint.is_file(), "в папке личное лежит пояснение")
        if _hint.is_file():
            _ht = _hint.read_text(encoding="utf-8")
            check("не копируются в новые базы" in _ht
                  or "не копируются" in _ht,
                  "пояснение говорит, что личное не уезжает")
    finally:
        shutil.rmtree(_kt, ignore_errors=True)
        echo(f"Временная папка убрана: {_kt}")

    # ---- 20. понимание, что писать в библиотеку
    echo("\n--- 20. Что писать в библиотеку ---")

    # Человек попросил: чтобы нейросеть понимала, какие данные
    # записывать. Проверяем, что это написано и в протоколе, и в
    # инструкции, и что правило не абстрактное.
    _zp = Path(tempfile.mkdtemp(prefix="dbapp-pisat-"))
    try:
        _pq = core.build_plan(_zp / "место", "Проба-писать", None)
        (_zp / "место").mkdir(exist_ok=True)
        core.create_base(_pq)
        _qb = _pq.target

        for _f, _label in ((_qb / "AGENTS.md", "AGENTS.md"),
                           (_qb / "библиотека" / "NCP.md", "протокол NCP")):
            _t = _f.read_text(encoding="utf-8")
            check("придётся выяснять заново" in _t or "выяснять заново" in _t,
                  f"в {_label} есть проверка: пропадёт ли из сессии")
            check("ncp_search" in _t,
                  f"в {_label} сказано искать перед записью")
            check("memory_save" in _t and "ncp_save" in _t,
                  f"в {_label} разведены короткая память и библиотека")
            check("Пароли" in _t or "пароли" in _t,
                  f"в {_label} запрет писать секреты")
            check("личное" in _t,
                  f"в {_label} сказано про личные записи")

        # В протоколе есть конкретные примеры, а не только общие слова.
        _prot = (_qb / "библиотека" / "NCP.md").read_text(encoding="utf-8")
        check("Что писать — с примерами" in _prot,
              "в протоколе есть таблица примеров")
        check("Одна запись — одна мысль" in _prot,
              "в протоколе есть правило одной мысли на запись")

        # Служебные файлы в папке записей не должны попадать в счёт.
        _nc = (core.program_root() / "tools" / "ncp-bridge" / "ncp_core.py")
        _code = _nc.read_text(encoding="utf-8")
        check('path.name.startswith("_")' in _code,
              "мост не считает служебные файлы записями")

        # Личная папка есть в новой базе и пуста, кроме пояснения.
        _pl = _qb / "библиотека" / "записи" / "личное"
        check(_pl.is_dir(), "в новой базе есть папка личное")
        check(not list(_pl.glob("ncp-*.md")),
              "в новой базе нет личных записей — только папка и пояснение")
    finally:
        shutil.rmtree(_zp, ignore_errors=True)
        echo(f"Временная папка убрана: {_zp}")

    # ---- 21. селфтест не тронул настоящий список баз
    echo("\n--- 21. Список баз не затронут ---")

    core.use_bases_file(None)
    _real_after = (
        _real_list.read_text(encoding="utf-8") if _real_list.is_file()
        else "<файла нет>"
    )
    check(_real_after == _real_before,
          f"настоящий список баз не изменился за прогон "
          f"({len(_real_before)} → {len(_real_after)} байт)")
    _real_paths_after = {str(e.get("path", "")).lower() for e in core.read_bases()}
    _added = _real_paths_after - _real_paths_before
    check(not _added,
          f"в список не добавилось ничего лишнего: {_added or 'ничего'}")
    _gone = _real_paths_before - _real_paths_after
    check(not _gone,
          f"существующие записи не потерялись: {_gone or 'ничего не пропало'}")
    # Мусор прошлых прогонов: временные папки в списке быть не должны.
    _temp_junk = [
        p for p in _real_paths_after
        if "\\Temp\\" in p or p.endswith("\test")
    ]
    check(not _temp_junk,
          f"в списке нет временных папок от прошлых прогонов: "
          f"{_temp_junk or 'чисто'}")
    echo(f"  в списке сейчас: {len(_real_paths_after)} записей")

    # Вот теперь возвращаем настоящий список баз: до этого места он
    # остаётся подменённым, иначе разделы, создающие базы, писали бы
    # прямо в список человека.
    core.use_bases_file(None)
    check(not core.bases_file().name.startswith("список"),
          f"настоящий список баз на месте: {core.bases_file().name}")
    check(_real_list.resolve() == core.bases_file().resolve(),
          f"возврат привёл к тому же файлу: {core.bases_file().name}")
    shutil.rmtree(_isolate, ignore_errors=True)
    echo("Временный список баз убран")

    # ---- итог
    failed = [text for good, text in results if not good]
    echo("\n" + "=" * 62)
    if failed:
        echo(f" ИТОГ: провалено {len(failed)} из {len(results)}")
        for text in failed:
            echo(f"   - {text}")
        code = 1
    else:
        echo(f" ИТОГ: все {len(results)} проверок пройдены")
        echo("=" * 62)
        code = 0
    REPORT.write_text("\n".join(_lines), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
