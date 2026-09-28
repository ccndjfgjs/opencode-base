"""Проверка окна без участия человека.

Создаёт окно по-настоящему, но не показывает его на экране: прогоняет
проверку имени, создание базы и подключение во временной папке и печатает
отчёт. Запуск:

    python tools/dbapp/selftest.py
"""

from __future__ import annotations

import hashlib
import json
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
            real_skills = core.count_skills(source)
            check(copy_skills == real_skills,
                  f"скиллы перенесены: {copy_skills} из {real_skills}")
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
    # Шесть вкладок: создание, подключение, мост NCP, opencode, темы и
    # инструкция. Раньше вкладки «Инструкция» не было — счётчик стоял на 5.
    check(window.tabs.count() == 6, f"вкладок в окне: {window.tabs.count()}")
    check(window.tabs.tabText(0) == "Создать новую базу",
          f"первая вкладка — «{window.tabs.tabText(0)}»")
    check(window.tabs.tabText(1) == "Подключить существующую",
          f"вторая вкладка — «{window.tabs.tabText(1)}»")
    check(window.tabs.tabText(2) == "Мост NCP — создать",
          f"третья вкладка — «{window.tabs.tabText(2)}»")
    check(window.tabs.tabText(3) == "opencode",
          f"четвёртая вкладка — «{window.tabs.tabText(3)}»")
    check(window.tabs.tabText(4) == "Темы",
          f"пятая вкладка — «{window.tabs.tabText(4)}»")
    check(window.tabs.tabText(5) == "Инструкция",
          f"шестая вкладка — «{window.tabs.tabText(5)}»")
    check(isinstance(btab, app_main.BridgeTab), "вкладка моста собрана")

    # Образец лежит внутри базы: значит, уедет на любой компьютер вместе
    # с программой. Ничего скачивать из интернета не нужно.
    tpl = core.bridge_template_dir()
    check(tpl.is_dir(), f"образец моста лежит в программе: {tpl}")
    missing = [name for name in core.BRIDGE_FILES if not (tpl / name).is_file()]
    check(not missing,
          f"в образце {len(core.BRIDGE_FILES)} файлов; не хватает: "
          f"{missing or 'ничего'}")

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
    ok, output = core.bridge_selftest(bridge_dir)
    check(ok and "26 проверок" in output,
          "проверка моста запускается отдельно и проходит")

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
    want_skills = core.list_skills(core.program_root())
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

    # возвращаем настоящий список баз и убираем временный
    core.use_bases_file(None)
    check(not core.bases_file().name.startswith("список"),
          f"настоящий список баз на месте: {core.bases_file().name}")
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
