# -*- coding: utf-8 -*-
"""Обход блокировок для opencode — установка по выбору.

Простыми словами: кладёт в папку настроек opencode переводчика
(фасад на своём порту, по умолчанию 17890 — порт задаётся
в настройках), бесплатные списки SOCKS5 и VLESS-подписки,
команду /обход и, по желанию, ярлык «OpenCode (обход)» с иконкой
программы на рабочий стол. Пул узлов фасад обновляет сам раз в сутки
с тех же источников. Глобальные переменные Windows не меняются:
прокси отдаётся только запущенному через ярлык OpenCode.

Правила (как везде в окне):
  * чужое не затираем: файл, который не наш, пропускаем с сообщением;
  * убираем не в корзину, а в _previous-version/antiblock — вернуть можно;
  * что поставили — записываем в общий манифест, по нему же убираем;
  * настоящий ~/.config/opencode трогаем только из окна, проверки —
    всегда во временной папке.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path

#: Движок: переводчик и запускалки. Без них обход не работает.
ENGINE_FILES = (
    "http_facade.py",
    "pool_refresh.py",
    "xray_runner.py",
    "start_opencode_proxy.cmd",
    "start_opencode_proxy.ps1",
)

#: Защищённый DNS (запасной способ обхода) — отдельная опция, чтобы
#: человек мог включить/выключить этот канал при установке.
DNS_FILES = (
    "dns_resolver.py",
)

#: Запускалки других программ через тот же обход. Движка они не
#: добавляют и сами по себе ничего не делают: без фасада и Xray файл
#: бесполезен, поэтому ставятся вместе с `facade`.
#:
#: Раньше эти два файла лежали в папке набора, но в список не попадали, и
#: проверка «повтор не двоит и не мусорит в наборе» честно ругалась: набор
#: должен совпадать с папкой, а он не совпадал. Файлы рабочие, выбрасывать
#: их было незачем — их надо было в списке.
EXTRA_LAUNCHERS = (
    "start_gemini_proxy.cmd",
    "start_gemini_proxy.ps1",
)

#: Списки и обновлялка: стартовый пул, подписки, скрипт обновления
#: с его помощником, инструкция.
LISTS_FILES = (
    "public_socks5.txt",
    "subscriptions.txt",
    "refresh_public_nodes.py",
    "check_nodes.py",
    "ЧИТАТЬ-МЕНЯ.txt",
)

#: Команда /обход внутри набора.
COMMAND_SRC = ("command", "antiblock.md")

#: Куда кладётся набор внутри папки настроек opencode.
ANTIBLOCK_DIR = "antiblock"

#: Имя ярлыка на рабочем столе.
SHORTCUT_NAME = "OpenCode (обход).lnk"

#: Старое имя ярлыка (из прежних версий) — тоже убираем при снятии.
LEGACY_SHORTCUT_NAME = "OpenCode через обход.lnk"

#: Путь к исполняемому файлу OpenCode — для иконки ярлыка.
OPENCODE_EXE_HINTS = (
    r"$LOCALAPPDATA\Programs\@opencode-aidesktop\OpenCode.exe",
    r"$LOCALAPPDATA\Programs\@opencode\opencode.exe",
)

#: Адрес фасада по умолчанию.
FACADE_HOST = "127.0.0.1"
FACADE_PORT = 17890

#: Куда кладутся машинные настройки. Путь взят из .gitignore (строка 37):
#: он был зарезервирован под настройки задолго до этой задачи.
PREFS_REL = ("config", "preferences.json")
FACADE_PORT_KEY = "facade_port"

#: Границы порта. Нижняя — 1024, выше системных служб; верхняя — 65535.
PORT_MIN = 1024
PORT_MAX = 65535

#: Порт своего канала: SOCKS5 от xray. Тот же порт и в стартерах
#: (`$XrayPort = 10900`), и в самом раннере (`XRAY_DEFAULT_PORT`), и
#: начало жизни обходчика: «свой Xray слушает 10900 — не трогаю».
#: Различать каналы можно только по нему — фасад поднимается в обоих
#: случаях, а вот SOCKS5 от xray существует ровно тогда, когда канал свой.
XRAY_PORT = 10900

#: Три состояния обхода. Слова — те же, что в плане (20.6): «свой»,
#: «запасной», «не работает».
CHANNEL_OWN = "свой"
CHANNEL_FALLBACK = "запасной"
CHANNEL_DOWN = "не работает"

MANIFEST = ".opencode-base-caps.json"

#: Ключ манифеста с путём к папке программы. Из него стартер берёт, где
#: лежит config/preferences.json — без этого пути рабочая копия стартера
#: читала бы несуществующий файл и молча брала порт по умолчанию.
BASE_KEY = "antiblock_base"


def _read_manifest(dest: Path) -> dict:
    try:
        data = json.loads((dest / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_manifest(dest: Path, data: dict) -> None:
    (dest / MANIFEST).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _src_dir(base: Path) -> Path:
    return Path(base) / "tools" / "antiblock"


def _find_opencode_exe() -> Path | None:
    """Путь к OpenCode.exe — для иконки ярлыка (или None, если не найден)."""
    import os
    import shutil

    for hint in OPENCODE_EXE_HINTS:
        expanded = os.path.expandvars(hint)
        if expanded and Path(expanded).is_file():
            return Path(expanded)
    found = shutil.which("opencode")
    if found:
        return Path(found)
    return None


def default_opts() -> dict[str, bool]:
    """Все галочки включены — обычный случай."""
    return {"facade": True, "lists": True, "command": True, "shortcut": True,
            "dns": True}


def install_antiblock(
    base: Path,
    dest: Path,
    opts: dict[str, bool] | None = None,
    progress=None,
) -> tuple[list[str], list[str]]:
    """Ставит обход в папку настроек opencode. Возвращает (сообщения, ошибки)."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    opts = {**default_opts(), **(opts or {})}
    src = _src_dir(base)
    if not src.is_dir():
        errors.append("В базе нет папки tools/antiblock — ставить нечего.")
        return messages, errors
    if not (src / "http_facade.py").is_file():
        errors.append("В tools/antiblock нет http_facade.py — набор неполный.")
        return messages, errors

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    target_dir = dest / ANTIBLOCK_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest = _read_manifest(dest)
    ours = set(manifest.get("antiblock_files", []))

    def place(name: str) -> bool:
        """Кладёт один файл набора. Чужой (не наш) — не трогает."""
        from_src = src / name
        if not from_src.is_file():
            return False
        to = target_dir / name
        if to.is_file():
            try:
                same = to.read_text(encoding="utf-8") == from_src.read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError):
                same = False
            if same:
                ours.add(name)
                return True
            if name not in ours:
                errors.append(
                    f"Файл {name} уже есть и не наш — пропустил. "
                    "Переименуй его или убери вручную."
                )
                return False
        try:
            shutil.copy2(from_src, to)
            ours.add(name)
            return True
        except OSError as exc:
            errors.append(f"Файл {name} не записался: {exc}.")
            return False

    put_engine, put_lists, put_dns, put_extra = 0, 0, 0, 0
    if opts.get("facade"):
        for name in ENGINE_FILES:
            if place(name):
                put_engine += 1
        # Запускалки ставятся вместе с фасадом: он им нужен, без него
        # файл только занимает место.
        for name in EXTRA_LAUNCHERS:
            if place(name):
                put_extra += 1
    if opts.get("lists"):
        for name in LISTS_FILES:
            if place(name):
                put_lists += 1
    if opts.get("dns"):
        for name in DNS_FILES:
            if place(name):
                put_dns += 1
    if put_engine or put_lists or put_dns or put_extra:
        say(
            f"Файлов обхода поставлено: движок {put_engine}, "
            f"списки {put_lists}, защищённый DNS {put_dns}"
            + (f", запускалки {put_extra}" if put_extra else "")
            + "."
        )

    # Файлы в папке набора, которых нет ни в одном списке, не ставятся.
    # Это не ошибка, поэтому в `errors` они не идут, но сказать о них
    # надо: человек написал файл, а набор его не берёт. Так выяснилось
    # с запускалкой Gemini — она лежала в папке молча, пока проверка
    # селфтеста не сказала, что набор и папка не совпадают.
    if src.is_dir():
        listed = (set(ENGINE_FILES) | set(LISTS_FILES) | set(DNS_FILES)
                  | set(EXTRA_LAUNCHERS))
        unregistered = sorted(
            item.name for item in src.iterdir()
            if item.is_file()
            and not item.name.startswith("public_socks5.local")
            and item.name not in listed
        )
        if unregistered:
            say(
                "Не входят в набор и не ставятся (список набора в "
                "antiblock.py): " + ", ".join(unregistered)
            )

    # --- команда /обход: видна в OpenCode в списке команд
    if opts.get("command"):
        cmd_src = src.joinpath(*COMMAND_SRC)
        cmd_dst = dest / "command" / "antiblock.md"
        if cmd_src.is_file():
            if cmd_dst.is_file():
                try:
                    same = cmd_dst.read_text(
                        encoding="utf-8"
                    ) == cmd_src.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    same = False
                if same or str(cmd_dst) in ours:
                    try:
                        cmd_dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(cmd_src, cmd_dst)
                        ours.add(str(cmd_dst))
                        say("Команда /обход поставлена (папка command).")
                    except OSError as exc:
                        errors.append(f"Команда /обход не записалась: {exc}.")
                else:
                    errors.append(
                        "Файл command/antiblock.md уже есть и не наш — пропустил."
                    )
            else:
                try:
                    cmd_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cmd_src, cmd_dst)
                    ours.add(str(cmd_dst))
                    say("Команда /обход поставлена (папка command).")
                except OSError as exc:
                    errors.append(f"Команда /обход не записалась: {exc}.")
        else:
            errors.append("В наборе нет command/antiblock.md — команду ставить не из чего.")

    # --- ярлык на рабочий стол: запуск OpenCode уже через фасад.
    # Отдельный ярлык, но с той же иконкой, что у самой программы.
    if opts.get("shortcut"):
        try:
            import core  # noqa: PLC0415 — рядом лежит, круга нет

            launcher = target_dir / "start_opencode_proxy.cmd"
            link = core.desktop_dir() / SHORTCUT_NAME
            if link.exists():
                say("Ярлык уже есть — не тронут.")
                manifest["antiblock_shortcut"] = str(link)
            elif launcher.is_file():
                icon_path = _find_opencode_exe()
                icon = (
                    f"{icon_path},0"
                    if icon_path
                    else "%SystemRoot%\\System32\\shell32.dll,3"
                )
                if core.make_program_shortcut(
                    link,
                    launcher,
                    description="OpenCode через обход блокировок",
                    icon=icon,
                    workdir=target_dir,
                ):
                    manifest["antiblock_shortcut"] = str(link)
                    say(f"Ярлык создан: {link} (иконка OpenCode)")
                else:
                    errors.append("Ярлык не создался — запусти start_opencode_proxy.cmd вручную.")
            else:
                errors.append("Запускалка .cmd не поставилась — ярлык делать не из чего.")
        except Exception as exc:
            errors.append(f"Ярлык не создался: {exc}.")

    manifest["antiblock_files"] = sorted(ours)
    # Путь к папке программы кладём рядом со списком файлов: стартеры
    # лежат в папке настроек opencode, а настройку читают из папки
    # программы. Связь между этими двумя папками иначе неоткуда взять —
    # подъёмом вверх от $PSScriptRoot до папки программы не дойти, они
    # в разных деревьях.
    manifest[BASE_KEY] = str(Path(base).resolve())
    try:
        _write_manifest(dest, manifest)
    except OSError as exc:
        errors.append(f"Манифест не записался: {exc}.")
    if not errors:
        say("Перезапусти OpenCode через новый ярлык: настройки читаются при старте.")
    return messages, errors


def remove_antiblock(
    dest: Path, progress=None
) -> tuple[list[str], list[str]]:
    """Убирает обход. Файлы уезжают в _previous-version/antiblock, не в корзину."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    dest = Path(dest)
    manifest = _read_manifest(dest)
    ours = set(manifest.get("antiblock_files", []))
    target_dir = dest / ANTIBLOCK_DIR

    import core  # noqa: PLC0415 — рядом лежит, круга нет

    # собираем всё наше: и по манифесту, и то, что лежит в папке набора
    victims: list[Path] = []
    cmd_dst = dest / "command" / "antiblock.md"
    if str(cmd_dst) in ours and cmd_dst.is_file():
        victims.append(cmd_dst)
    if target_dir.is_dir():
        for item in sorted(target_dir.iterdir()):
            if item.is_file() and (
                item.name in ours
                or item.name in ENGINE_FILES
                or item.name in LISTS_FILES
                or item.name in EXTRA_LAUNCHERS
            ):
                victims.append(item)

    if victims:
        backup = dest / "_previous-version" / "antiblock"
        try:
            backup.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            errors.append(f"Запасная папка не создалась: {exc}.")
            return messages, errors
        moved = 0
        for item in victims:
            try:
                spot = backup / item.name
                if spot.exists():
                    if spot.is_dir():
                        shutil.rmtree(spot)
                    else:
                        spot.unlink()
                shutil.move(str(item), str(spot))
                moved += 1
            except OSError as exc:
                errors.append(f"Файл {item.name} не убрался: {exc}.")
        say(f"Убрано в _previous-version/antiblock: {moved}.")
    else:
        say("Файлов обхода нет — убирать нечего.")

    link_raw = manifest.get("antiblock_shortcut", "")
    shortcut_targets = []
    if link_raw:
        shortcut_targets.append(Path(str(link_raw)))
    shortcut_targets.append(core.desktop_dir() / SHORTCUT_NAME)
    shortcut_targets.append(core.desktop_dir() / LEGACY_SHORTCUT_NAME)
    backup_dir = dest / "_previous-version" / "antiblock"
    removed_links = 0
    for link in shortcut_targets:
        if link.is_file() and link.name in {SHORTCUT_NAME, LEGACY_SHORTCUT_NAME}:
            try:
                backup_dir.mkdir(parents=True, exist_ok=True)
                spot = backup_dir / link.name
                if spot.exists():
                    spot.unlink()
                shutil.move(str(link), str(spot))
                removed_links += 1
            except OSError as exc:
                errors.append(f"Ярлык {link.name} не убрался: {exc}.")
    if removed_links:
        say(f"Ярлыки с рабочего стола убраны в _previous-version/antiblock: {removed_links}.")
    manifest.pop("antiblock_files", None)
    manifest.pop(BASE_KEY, None)
    manifest.pop("antiblock_shortcut", None)
    try:
        _write_manifest(dest, manifest)
    except OSError as exc:
        errors.append(f"Манифест не записался: {exc}.")
    return messages, errors


def antiblock_status(dest: Path) -> bool:
    """Стоит ли обход: движок и команда на месте."""
    dest = Path(dest)
    return bool(
        (dest / ANTIBLOCK_DIR / "http_facade.py").is_file()
        and (dest / "command" / "antiblock.md").is_file()
    )


def _port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    """Слушает ли локальный порт. Без интернета, только свой компьютер.

    Отдельная функция потому, что портов теперь два — фасад и свой
    канал, — а проверка одна и та же. Закрытый локальный порт падает
    мгновенно с отказом, а не по таймауту, поэтому вызов дешёвый и
    годится для строки состояния при открытии вкладки.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def facade_running(
    host: str = FACADE_HOST, port: int = FACADE_PORT, timeout: float = 1.0
) -> bool:
    """Слушает ли фасад свой порт."""
    return _port_listening(host, port, timeout)


def channel_state(
    host: str = FACADE_HOST,
    xray_port: int = XRAY_PORT,
    facade_port: int = FACADE_PORT,
    timeout: float = 1.0,
) -> tuple[str, str]:
    """Чем жив обход прямо сейчас: своим каналом, запасным или ничем.

    Различает по портам, как это уже делают стартеры: свой Xray на
    `xray_port` — значит канал свой; молчит, но фасад на `facade_port`
    жив — значит держимся на бесплатном пуле; молчат оба — обхода нет.

    Требуется §20.6 плана: когда запасной включён, программа обязана
    говорить об этом прямо. Молчание тут врёт: снаружи всё выглядит
    как будто канал один, а на деле трафик идёт через чужие машины.
    """
    if _port_listening(host, xray_port, timeout):
        return CHANNEL_OWN, f"Свой канал: Xray слушает {host}:{xray_port}."
    if _port_listening(host, facade_port, timeout):
        return CHANNEL_FALLBACK, (
            f"Запасной канал: своего Xray на {host}:{xray_port} нет, "
            "фасад держится на бесплатном пуле. Это чужие машины — "
            "через них нельзя передавать пароли и ключи."
        )
    return CHANNEL_DOWN, (
        f"Обход не работает: нет ни своего канала ({host}:{xray_port}), "
        f"ни фасада ({host}:{facade_port}). Запусти OpenCode через "
        "ярлык «OpenCode (обход)»."
    )


def _prefs_path(base: Path) -> Path:
    return Path(base).joinpath(*PREFS_REL)


def _program_base() -> Path:
    """Папка программы. Через core, а не вычислением от __file__: путь к
    программе должен знать один модуль, а не четыре."""
    from core import program_root  # noqa: PLC0415 — рядом лежит, круга нет
    return program_root()


def load_prefs(base: Path | None = None) -> tuple[dict, str]:
    """Прочитать настройки. Возвращает (словарь, предупреждение).

    Предупреждение непустое, когда файл есть, но прочитать его нельзя.
    Такой случай обязан быть виден: молчаливый откат на дефолт выглядел
    бы как «настройка не работает» без всякой причины.
    """
    path = _prefs_path(base or _program_base())
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, ""
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"Файл настроек {path.name} не прочитан: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"Файл настроек {path.name} битый: {exc}"
    if not isinstance(data, dict):
        return {}, (f"Файл настроек {path.name} не словарь — "
                    "взят порт по умолчанию.")
    return data, ""


def port_error(value: object) -> str:
    """Почему значение не годится. Пустая строка — годится."""
    if isinstance(value, bool) or not isinstance(value, int):
        return "порт должен быть целым числом"
    if not (PORT_MIN <= value <= PORT_MAX):
        return f"порт должен быть от {PORT_MIN} до {PORT_MAX}, а не {value}"
    if value == XRAY_PORT:
        return f"{value} — это порт канала xray, его менять нельзя"
    return ""


def facade_port(base: Path | None = None,
                warning: list[str] | None = None) -> int:
    """Порт фасада из настроек. Нет файла или ключа — дефолт.

    Кэша нет намеренно: правка файла руками должна подхватываться сразу,
    а не после перезапуска окна.
    """
    prefs, warn = load_prefs(base)
    if warn and warning is not None:
        warning.append(warn)
    value = prefs.get(FACADE_PORT_KEY, FACADE_PORT)
    return FACADE_PORT if port_error(value) else value


def set_facade_port(value: int,
                    base: Path | None = None) -> tuple[bool, str]:
    """Записать порт фасада. Возвращает (получилось, текст).

    Пишется только свой ключ: чужие настройки в том же файле не трогаем.
    """
    why = port_error(value)
    if why:
        return False, f"Порт не сохранён: {why}."
    root = base or _program_base()
    path = _prefs_path(root)
    prefs, _warn = load_prefs(root)
    prefs[FACADE_PORT_KEY] = int(value)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, (f"Порт не сохранён: {path} — {exc}. В силе остался "
                       f"{prefs.get(FACADE_PORT_KEY, FACADE_PORT)}.")
    return True, f"Порт фасада сохранён: {value}."


def who_listens(port: int) -> str:
    """Имя процесса, который слушает порт. Пусто — определить не удалось.

    Через PowerShell, а не через netstat: netstat переводит состояния в
    зависимость от языка Windows, и разбор строк ломается на другой
    машине. Параметр -State Listen — имя из перечисления, оно не
    переводится. Определить не удалось — возвращаем пустую строку, и
    вызывающий говорит «занят неизвестным процессом».
    """
    script = (
        "$c = Get-NetTCPConnection -State Listen -LocalPort "
        f"{int(port)} -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($c) { (Get-Process -Id $c.OwningProcess).ProcessName }"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return (done.stdout or "").strip()


def suggest_free_port(port: int, host: str = FACADE_HOST,
                      tries: int = 100) -> int:
    """Ближайший свободный порт вверх от заданного. 0 — не нашлось.

    Порт xray пропускается: занять его фасадом нельзя, канал от этого
    перестанет работать. Подбор ограничен: за 100 попыток не нашлось —
    так и говорим, выдумывать ничего не будем.
    """
    candidate = int(port)
    for _ in range(tries):
        if candidate > PORT_MAX:
            return 0
        if candidate != XRAY_PORT and not _port_listening(host, candidate):
            return candidate
        candidate += 1
    return 0


def check_connection(port: int = FACADE_PORT) -> tuple[bool, str]:
    """Проверка для кнопки в окне: запущен ли фасад прямо сейчас."""
    if facade_running(port=port):
        return True, f"Фасад слушает {FACADE_HOST}:{port} — обход работает."
    return (
        False,
        f"Фасад не слушает {FACADE_HOST}:{port}. "
        "Запусти OpenCode через ярлык «OpenCode (обход)» или "
        "start_opencode_proxy.cmd — и нажми проверку снова.",
    )


def check_dns(proxy_url: str = "", timeout: float = 10.0) -> tuple[bool, str]:
    """Проверка защищённого DNS: резолвит тестовый домен через DoH.

    Возвращает (ok, текст). Пробует серверы из dns_resolver;
    если ни один не сработал — честно сообщает об этом.
    """
    import sys
    from pathlib import Path

    try:
        import dns_resolver  # noqa: PLC0415
    except ImportError:
        # dns_resolver может лежать в tools/antiblock главной базы
        src = Path(__file__).resolve().parent.parent / "antiblock"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        try:
            import dns_resolver  # noqa: PLC0415
        except ImportError:
            return False, "Защищённый DNS (dns_resolver.py) не найден в наборе."
    try:
        ips = dns_resolver.resolve_host(
            "example.com", proxy_url=proxy_url, timeout=timeout
        )
    except dns_resolver.DNSResolutionError as exc:
        return False, f"Защищённый DNS не отвечает: {exc}."
    except Exception as exc:  # noqa: BLE001
        return False, f"Проверка DNS не запустилась: {exc}."
    return True, f"Защищённый DNS работает: example.com → {', '.join(ips)}."
