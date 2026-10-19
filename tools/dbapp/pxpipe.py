"""pxpipe — локальный прокси, который сжимает запрос картинками.

Что это. Маленькая программа-посредник на этой же машине: между opencode и
нейросетью она переписывает громоздкие куски запроса (описание инструментов,
старую историю, большие результаты команд) в плотные картинки PNG. Картинка
стоит примерно одинаково независимо от того, сколько в ней текста, поэтому в
окно контекста помещается больше. Ответ нейросети прокси не трогает вовсе.

Куда он смотрит. Прокси принимает запросы на `127.0.0.1:47821` (адрес из
README автора) и пересылает их дальше — туда, куда указано переменной
`PXPIPE_UPSTREAM`. Программа подставляет туда адрес выбранного провайдера
opencode, поэтому запросы продолжают идти к тому же месту, только теперь
через прокси.

Что программа делает и чего не делает:

  * запускает прокси командой автора `npx pxpipe-proxy` (версия закреплена,
    см. PACKAGE_VERSION) и останавливает только свой процесс;
  * добавляет в настройки opencode свою запись провайдера `pxpipe` между
    своими метками — копию моделей выбранного провайдера. Чужих записей не
    переписывает;
  * проверяет живость прокси до записи в настройки: не отвечает — в настройки
    не пишется ничего;
  * не копирует код pxpipe в репозиторий (пакет берётся из npm, файлы автора
    к нам не едут) и не добавляет его в реестр MCP: это не сервер, а прокси;
  * не включает себя молча: галочка «pxpipe» на вкладке opencode по умолчанию
    снята, а перед запуском показывается предупреждение автора про модели,
    которые плохо различают символы.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
import sys

def _hidden_startupinfo():
    """Окно консоли не показывать. Подробности — в core.hidden_startupinfo.

    Отдельная функция с ленивым импортом, а не `import core` наверху:
    модуль читают и лаунчеры, и проверки, и лишняя связь между ними
    лишний раз ломается.

    Зачем это. 19.10.2026 человек нажал кнопку у моста OBS, и у него
    открылось чёрное окно консоли. Программа работает на pythonw — у
    неё самой консоли нет, и Windows на каждый запуск внешней
    программы без этой просьбы создаёт новое окно.
    """
    try:
        from core import hidden_startupinfo

        return hidden_startupinfo()
    except Exception:  # noqa: BLE001 — без этого просто откроется окно
        return None

# Под pythonw (оконный Python, без консоли) sys.stdout равен None:
# .reconfigure() на нём роняет импорт модуля, а модуль импортирует
# main.py при старте — программа не открывалась совсем. Найдено живьём.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass

# ------------------------------------------------------------------ источник

#: Откуда берётся прокси: README автора, команда запуска и адрес — оттуда.
SOURCE = "https://github.com/teamchong/pxpipe"
PACKAGE = "pxpipe-proxy"
#: Версия закреплена не случайно: на 0.14.0 проверены и запуск, и пересылка
#: запросов, и запись в настройки. Обновление — правкой этой строки.
PACKAGE_VERSION = "0.14.0"
PACKAGE_NOTE = "выпуск 28.09.2026"
LICENSE = "MIT"
#: Слепок текста лицензии из npm-пакета: им самопроверка сверяет копию
#: tools/thirdparty/pxpipe/LICENSE с тем, что раздаёт автор.
LICENSE_BLOB = "6b5f347bc4c1531a3d3878fa08053df097c0c845"

#: Адрес прокси. Из README автора: «proxy on 127.0.0.1:47821».
HOST = "127.0.0.1"
PORT = 47821

#: Имя нашей записи провайдера в настройках opencode, папка данных рядом с
#: ними и ключ в общем манифесте программы.
PROVIDER = "pxpipe"
DATA_NAME = "pxpipe-data"
MANIFEST_KEY = "pxpipe"

#: Сколько ждать ответа прокси и сколько — остановки.
START_TIMEOUT = 120
CHECK_TIMEOUT = 20
STATS_TIMEOUT = 120
STOP_TIMEOUT = 30

#: Предупреждение автора, дословно по смыслу его README: сжатие теряет
#: точность на символах. Показывается перед запуском, пишется в README и в
#: уведомления о чужих лицензиях.
WARNING = (
    "pxpipe переписывает часть запроса картинками, и это сжатие с потерями.\n"
    "По собственным тестам автора часть моделей плохо различает символы при\n"
    "дословной расшифровке плотного текста: точные строки, идентификаторы,\n"
    "хеши и ключи могут быть прочитаны неверно — и молча, без ошибки.\n"
    "Поэтому включай осознанно и сначала проверь на несложной задаче.\n"
    "\n"
    "Ещё три его же оговорки: описание инструментов и старую историю он\n"
    "превращает в картинки только для моделей из своего списка (по умолчанию\n"
    "claude-fable-5 и все Gemini), остальные запросы идут как есть; экономия\n"
    "зависит от задач — на редком тексте сжатие может не окупиться; числа\n"
    "59–70% из его README — это заявление автора, независимо не проверенное."
)


# ------------------------------------------------------------------ адреса


def host() -> str:
    """Адрес, на котором слушает прокси."""
    return HOST


def port() -> int:
    """Порт прокси. Переменные PORT/HOST уважаются: иначе проверки писали бы
    в занятый порт человека."""
    raw = os.environ.get("PXPIPE_PORT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return PORT


def base_url() -> str:
    """Адрес прокси без /v1: его видят opencode и панель."""
    return f"http://{host()}:{port()}"


def dashboard_url() -> str:
    """Панель прокси — по README она живёт в корне."""
    return base_url() + "/"


def data_dir(dest: Path) -> Path:
    """Папка данных программы — рядом с настройками opencode."""
    return Path(dest) / DATA_NAME


def pid_file(dest: Path) -> Path:
    return data_dir(dest) / "pxpipe.pid"


def log_file(dest: Path) -> Path:
    return data_dir(dest) / "pxpipe.log"


def events_file(dest: Path) -> Path:
    """Журнал событий прокси. Автор пишет его в домашнюю папку; программа
    держит свой рядом с настройками, чтобы статистика была под рукой."""
    return data_dir(dest) / "events.jsonl"


def session_state_file(dest: Path) -> Path:
    return data_dir(dest) / "session-state.json"


# ------------------------------------------------------------------ запуск


def find_npx() -> str | None:
    """Где лежит npx. На Windows это npx.cmd."""
    return (shutil.which("npx") or shutil.which("npx.cmd")
            or shutil.which("npx.ps1"))


def _wrap_cmd(argv: list[str]) -> list[str]:
    """Обёртка для .cmd/.bat на Windows: CreateProcess их не запускает."""
    if argv and str(argv[0]).lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC") or "cmd.exe", "/c", *argv]
    return argv


def launch_command() -> list[str]:
    """Команда запуска прокси — как в README автора: `npx pxpipe-proxy`.

    Версия закреплена: `npx pxpipe-proxy` взял бы что угодно свежее и мог бы
    сменить поведение молча.
    """
    npx = find_npx() or "npx"
    return _wrap_cmd([npx, "--yes", f"{PACKAGE}@{PACKAGE_VERSION}"])


def _run(args: list[str], timeout: int, env: dict | None = None,
         cwd: Path | None = None) -> tuple[int, str, str]:
    """Запускает программу и возвращает код, вывод и ошибки (текстом)."""
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, env=env,
            cwd=str(cwd) if cwd else None, startupinfo=_hidden_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return done.returncode, done.stdout or "", done.stderr or ""


def package_version() -> str:
    """Спрашивает версию пакета у npx. Пусто — пакет недоступен."""
    if not find_npx():
        return ""
    code, out, err = _run(launch_command() + ["--version"], STATS_TIMEOUT)
    text = (out or err).strip().splitlines()
    if code != 0 or not text:
        return ""
    return text[-1].strip()


# ------------------------------------------------------------------ живость


def dashboard_ok(timeout: float = CHECK_TIMEOUT) -> tuple[bool, str]:
    """Живая проверка: отвечает ли панель прокси на своём адресе.

    Это и есть «прокси работает»: панель отдаёт сам прокси, и по её ответу
    видно, что порт занят им, а не чем-то посторонним.
    """
    url = dashboard_url()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer:
            code = int(getattr(answer, "status", 0) or 0)
            head = answer.read(600).decode("utf-8", "replace").lower()
    except (OSError, urllib.error.URLError) as exc:
        return False, f"прокси не отвечает на {url} ({exc})"
    if code != 200:
        return False, f"на {url} отвечает код {code} — это не панель pxpipe"
    if "pxpipe" not in head or "<html" not in head:
        return False, (
            f"на {url} отвечает не панель pxpipe — порт занят другой программой"
        )
    return True, f"панель pxpipe отвечает на {url}"


def _pid(dest: Path) -> int | None:
    """Номер нашего процесса из файла. None — файла нет или он битый."""
    try:
        data = json.loads(pid_file(dest).read_text(encoding="utf-8"))
        pid = int(data.get("pid") or 0)
    except (OSError, ValueError, TypeError):
        return None
    return pid or None


def _launch_info(dest: Path) -> dict:
    """Что записано о запуске: номер процесса, порт и куда пересылает."""
    try:
        data = json.loads(pid_file(dest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _port_busy() -> bool:
    """Занят ли порт прокси хоть кем-нибудь. Нужен для честных отказов."""
    import socket

    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host(), port())) == 0


def _upstream_root(url: str) -> str:
    """Корень адреса провайдера для PXPIPE_UPSTREAM.

    Прокси приписывает к этому корню путь запроса как есть (`/v1/chat/
    completions`), поэтому `/v1` из адреса провайдера надо убрать: иначе
    получится `/v1/v1/chat/completions`.
    """
    root = (url or "").strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/")


def _spawn(dest: Path, provider: str = "", upstream: str = "") -> tuple[bool, str]:
    """Поднимает прокси отдельным процессом и пишет его журнал в файл."""
    folder = data_dir(dest)
    folder.mkdir(parents=True, exist_ok=True)
    log_path = log_file(dest)
    env = dict(os.environ)
    env["PORT"] = str(port())
    env["HOST"] = host()
    env["PXPIPE_LOG"] = str(events_file(dest))
    env["PXPIPE_SESSION_STATE"] = str(session_state_file(dest))
    if upstream:
        env["PXPIPE_UPSTREAM"] = upstream
    try:
        log = open(log_path, "a", encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"Журнал прокси не открылся ({log_path}): {exc}"
    kwargs: dict = {"cwd": str(Path.home()), "env": env,
                    "stdout": log, "stderr": log}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(launch_command(), **kwargs)
    except OSError as exc:
        log.close()
        return False, f"Прокси не запустился: {exc}"
    pgid = 0
    if os.name != "nt":
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = 0
    try:
        pid_file(dest).write_text(
            json.dumps({"pid": proc.pid, "pgid": pgid, "port": port(),
                        "host": host(), "provider": provider,
                        "upstream": upstream},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    return True, f"Прокси запущен отдельным процессом, журнал: {log_path}."


def wait_dashboard(timeout: int = START_TIMEOUT, progress=None) -> tuple[bool, str]:
    """Ждёт, пока панель прокси ответит. Возвращает (получилось, объяснение)."""
    deadline = time.monotonic() + timeout
    note = ""
    while time.monotonic() < deadline:
        ok, note = dashboard_ok(timeout=5)
        if ok:
            return True, note
        time.sleep(1)
    return False, note


def provider_base_url(dest: Path, name: str) -> str:
    """Адрес (baseURL) записи провайдера в настройках. Пусто — не нашлось."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    try:
        text = _config(dest).read_text(encoding="utf-8")
    except OSError:
        return ""
    bounds = opencode_caps.find_key_object(text, name)
    if bounds is None:
        return ""
    match = re.search(r'"baseURL"\s*:\s*"((?:[^"\\]|\\.)*)"',
                      text[bounds[0] : bounds[1]])
    return match.group(1) if match else ""


def start(dest: Path, provider: str = "", progress=None) -> tuple[list[str], list[str]]:
    """Поднимает прокси и ждёт ответа панели. В opencode ничего не пишет."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    if provider:
        # Номер разбираем по списку: это единственное место, где список
        # нужен. Имя наоборот — НЕ проверяем здесь: раньше неизвестное имя
        # доходило дальше и отказывалось позже, с настоящей причиной
        # (нет baseURL, нет прокси). Проверка по списку заменяла ту причину
        # своей и ломала прежнее поведение.
        if provider.strip().isdigit():
            name, why = resolve_provider(dest, provider)
            if not name:
                say(choices_text(dest))
                return [], [
                    "запускать нечем: " + why + ".",
                    "В настройки opencode ничего не вписано.",
                ]
            provider, why = name, why
            say(f"Провайдер: «{provider}» ({why}).")
        else:
            say(f"Провайдер назван: «{provider.strip()}».")
    else:
        # Провайдера не назвали. Если в настройках есть кого взять — берём
        # оттуда: так добавленный человеком провайдер подхватывается сам.
        # Если взять некого, идём дальше как шли: прокси умеет работать на
        # адресах по умолчанию. Ошибкой «нет ни одного провайдера» это
        # заканчиваться не должно.
        pick, why = suggest_provider(dest)
        if pick:
            provider = pick
            say(f"Провайдер не назван — беру из настроек: «{provider}» "
                f"({why}). Свой выбор: pxpipe.py choose.")

    if not find_npx():
        return [], [
            "npx не найден: он ставится вместе с Node.js, а pxpipe берётся "
            "командой `npx pxpipe-proxy` из README автора.",
            "В настройки opencode ничего не вписано.",
        ]

    ok, note = dashboard_ok(timeout=3)
    if ok:
        info = _launch_info(dest)
        if info.get("pid"):
            where = info.get("upstream") or "адреса по умолчанию"
            say(f"Прокси уже отвечает — второй экземпляр не поднимаю (пересылает к {where}).")
            return messages, errors
        return [], [
            f"На {base_url()} уже работает pxpipe, но запущен не программой: "
            "неизвестно, куда он пересылает запросы. Останови его сам и "
            "запусти командой pxpipe.py start — тогда программа будет знать, "
            "к какому провайдеру идут запросы.",
            "В настройки opencode ничего не вписано.",
        ]

    upstream = provider_base_url(dest, provider) if provider else ""
    if provider and not upstream:
        # Сообщения накопленные выше возвращаем: иначе строка «Провайдер
        # назван» исчезала бы, и человек не видел бы, к кому он обращался.
        messages.append(
            f"Провайдер: «{provider}» — в настройках у него нет baseURL, "
            f"пересылать некуда."
        )
        return messages, [
            f"У провайдера «{provider}» в настройках нет baseURL — непонятно, "
            "куда пересылать запросы.",
            "В настройки opencode ничего не вписано.",
        ]
    root = _upstream_root(upstream)
    if root:
        say(f"Прокси будет пересылать запросы к {upstream}.")
    else:
        say(
            "Провайдер не выбран: прокси пойдёт на адреса по умолчанию — "
            "api.anthropic.com и api.openai.com, со своим ключом."
        )
    say("Запускаю прокси: " + " ".join(launch_command()) + "…")
    started, note = _spawn(dest, provider=provider, upstream=root)
    if not started:
        return messages, [note, "В настройки opencode ничего не вписано."]

    ok, note = wait_dashboard(progress=progress)
    if not ok:
        tail = _tail(log_file(dest))
        errors.append(
            f"Прокси не ответил за {START_TIMEOUT} с: {note}. "
            "Первый запуск скачивает пакет из npm — если это он, повтори "
            "команду." + (f" Журнал: {tail}" if tail else "")
        )
        return messages, errors
    say(note)
    return messages, errors


def _tail(path: Path, limit: int = 400) -> str:
    """Последние строки журнала — для объяснения отказа."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return " | ".join(lines[-3:])[:limit]


def _pid_record(dest: Path) -> dict:
    """Наш файл с номером процесса целиком. Пусто — файла нет или он битый."""
    try:
        text = pid_file(dest).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _listener_pid() -> int | None:
    """Номер процесса, который держит наш порт. None — выяснить не вышло."""
    if os.name == "nt":
        code, out, _err = _run(["netstat", "-ano", "-p", "TCP"], timeout=30)
        for line in out.splitlines():
            if f":{port()} " in line and "LISTEN" in line.upper():
                tail = line.split()
                if tail and tail[-1].isdigit():
                    return int(tail[-1])
        return None
    code, out, _err = _run(["ss", "-ltnpH", f"sport = :{port()}"], timeout=20)
    if code == 0:
        found = re.search(r"pid=(\d+)", out)
        if found:
            return int(found.group(1))
    code, out, _err = _run(
        ["lsof", "-nP", f"-iTCP:{port()}", "-sTCP:LISTEN", "-t"], timeout=20
    )
    if code == 0 and out.strip().split():
        first = out.strip().split()[0]
        if first.isdigit():
            return int(first)
    return None


def _kill_listener(dest: Path, pid: int) -> bool:
    """Добивает процесс, который остался на нашем порту. Да — порт освободился."""
    ok, _note = dashboard_ok(timeout=5)
    if not ok:
        return False
    _run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=60) if os.name == "nt" \
        else None
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not _port_busy():
            return True
        time.sleep(1)
    return False


def stop(dest: Path, progress=None) -> tuple[list[str], list[str]]:
    """Останавливает прокси, который запустила программа.

    Чужой процесс на порту не трогается: без своего файла с номером процесса
    программа только говорит, что прокси не её.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    pid = _pid(dest)
    if pid is None:
        if _port_busy():
            return [], [
                f"На порту {port()} кто-то есть, но это не наш прокси: программа "
                "чужие процессы не останавливает. Закрой его сам или укажи "
                "другой порт переменной PXPIPE_PORT.",
            ]
        say("Прокси и так не запущен.")
        return messages, errors

    record = _pid_record(dest)
    pgid = int(record.get("pgid") or 0) or pid

    def _signal(sig: int) -> None:
        """Гасит весь запущенный нами узел процессов.

        `npx` запускает сам прокси отдельным процессом-ребёнком, поэтому
        одиночный сигнал оставлял бы ребёнка держать порт. Группа процесса
        записана при запуске; если её уже нет, бьём по номеру процесса.
        Свою же группу не трогаем — иначе убьём себя.
        """
        if os.name == "nt":
            _run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=60)
            return
        if pgid and pgid != os.getpgrp():
            try:
                os.killpg(pgid, sig)
                return
            except OSError:
                pass
        try:
            os.kill(pid, sig)
        except OSError:
            pass

    _signal(signal.SIGTERM)
    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        if not _port_busy():
            break
        time.sleep(1)
    else:
        _signal(signal.SIGKILL)
        time.sleep(2)
        if _port_busy():
            # Бывает, что узел процессов отцепился и в файле остался только
            # номер. Тогда добиваем того, кто держит порт, — но лишь если
            # на порту и правда панель pxpipe, чужие процессы не трогаем.
            left = _listener_pid()
            if left is None or not _kill_listener(dest, left):
                return messages, [
                    f"Процесс {pid} не отпустил порт {port()}. Проверь "
                    "диспетчер задач."
                ]
    try:
        pid_file(dest).unlink()
    except OSError:
        pass
    say("Прокси остановлен.")
    return messages, errors


# ------------------------------------------------------------------ настройки


def _config(dest: Path) -> Path:
    return Path(dest) / "opencode.jsonc"


def _provider_names(dest: Path) -> list[str]:
    """Имена провайдеров верхнего уровня из opencode.jsonc, по порядку."""
    try:
        text = _config(dest).read_text(encoding="utf-8")
    except OSError:
        return []
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    bounds = opencode_caps.find_key_object(text, "provider")
    if bounds is None:
        return []
    chunk = text[bounds[0] : bounds[1]]
    names: list[str] = []
    depth = 0
    in_str = False
    escape = False
    i = 0
    while i < len(chunk):
        ch = chunk[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            match = re.match(r'"((?:[^"\\]|\\.)*)"\s*:\s*\{', chunk[i:])
            if match and depth == 1:
                names.append(match.group(1))
            in_str = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return names


def provider_choices(dest: Path) -> list[str]:
    """Какие провайдеры есть в настройках — из них выбирается, к кому
    пересылать запросы. Наши пресеты идут первыми: они чаще всего и нужны."""
    names = _provider_names(dest)
    known: list[str] = []
    try:
        manifest = opencode_caps_manifest(dest)
        known = [str(n) for n in manifest.get("providers", [])]
    except Exception:  # noqa: BLE001 — чужая пачка настроек не должна ронять окно
        known = []
    ordered = [n for n in known if n in names]
    ordered += [n for n in names if n not in ordered and n != PROVIDER]
    return ordered


def opencode_caps_manifest(dest: Path) -> dict:
    """Манифест программы из папки настроек (наш же, но через модуль)."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    return opencode_caps.read_manifest(Path(dest))


def provider_entry(dest: Path, source: str) -> tuple[str, str]:
    """Собирает нашу запись провайдера: копию моделей источника.

    Возвращает (текст записи, ошибка). Модели берутся из записи источника
    как есть: имена моделей называет провайдер, выдумывать их нельзя.
    """
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    try:
        text = _config(dest).read_text(encoding="utf-8")
    except OSError as exc:
        return "", f"opencode.jsonc не читается: {exc}"
    provider = opencode_caps.find_key_object(text, "provider")
    if provider is None:
        return "", "В настройках нет раздела provider — сначала поставь провайдера."
    chunk = text[provider[0] : provider[1]]
    if not opencode_caps.has_entry(chunk, source):
        return "", f"Провайдера «{source}» в настройках нет."
    src = opencode_caps.find_key_object(text, source, provider[0])
    if src is None:
        return "", f"Запись провайдера «{source}» не разобралась."
    src_text = text[src[0] : src[1]]
    models = opencode_caps.find_key_object(text, "models", src[0])
    if models is None or models[0] > src[1]:
        return "", (
            f"У провайдера «{source}» нет списка моделей — копировать нечего. "
            "Поставь его провайдером с моделями и повтори."
        )
    models_text = text[models[0] : models[1] + 1]
    options = ['        "baseURL": "' + base_url() + '/v1"']
    key = re.search(r'"apiKey"\s*:\s*"((?:[^"\\]|\\.)*)"', src_text)
    if key:
        options.append('        "apiKey": "' + key.group(1) + '"')
    entry = (
        '"' + PROVIDER + '": {\n'
        '      "npm": "@ai-sdk/openai-compatible",\n'
        '      "name": "pxpipe — прокси к ' + source + '",\n'
        '      "options": {\n' + ",\n".join(options) + "\n      },\n"
        '      "models": ' + models_text + "\n    },"
    )
    return entry, ""


def _block_text(text: str, obj_key: str = "provider", name: str = PROVIDER) -> str:
    """Текст нашего блока между метками. Пусто — блока нет."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    begin = opencode_caps.BEGIN_TPL.format(name=f"{obj_key}.{name}")
    end = opencode_caps.END_TPL.format(name=f"{obj_key}.{name}")
    start = text.find(begin)
    if start < 0:
        return ""
    stop = text.find(end, start)
    if stop < 0:
        return ""
    return text[start + len(begin) : stop]


#: Проверкам запускать прокси нельзя: проверка не имеет права менять машину,
#: на которой сама работает. Та же переменная, что у rtk и greenlight.
NO_INSTALL_ENV = "OPENCODE_NO_AUTO_INSTALL"


def ensure_proxy(dest: Path, provider: str = "",
                 progress=None) -> tuple[list[str], list[str]]:
    """Поднимает прокси, если он не отвечает: галочка доводит до готового сама.

    Найдено 15.10.2026 живым прогоном: раньше установка просто отказывалась и
    требовала, чтобы человек сам вспомнил про `pxpipe.py start`. Прокси и есть
    та зависимость, которую надо доставить, а не предъявлять человеку.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    ok, _note = dashboard_ok(timeout=5)
    if ok:
        if _launch_info(dest).get("pid"):
            return messages, errors
        return messages, [
            "Прокси отвечает, но запущен не программой — неизвестно, куда он "
            "пересылает запросы. Остановите его и повторите галочку.",
        ]

    if os.environ.get(NO_INSTALL_ENV, ""):
        # Как и остальные отказы: «pxpipe не включён» и про то, что в настройки
        # ничего не попало (эту строку дописывает install). Найдено 16.10.2026
        # полным прогоном самопроверки.
        return messages, [f"pxpipe не включён: запуск прокси запрещён "
                          f"переменной {NO_INSTALL_ENV} — её выставили проверки."]

    name = (provider or "").strip() or suggest_provider(dest)[0]
    if not name:
        return messages, [
            "провайдера выбрать не из чего: в настройках opencode нет ни одного "
            "с адресом. Добавьте провайдера или назовите его прямо: "
            "pxpipe.py start <имя>.",
        ]
    say(f"Прокси не отвечает — поднимаю сам на провайдере «{name}».")
    start_messages, start_errors = start(dest, provider=name, progress=say)
    messages += start_messages
    return messages, start_errors


def install(dest: Path, provider: str = "", progress=None) -> tuple[list[str], list[str]]:
    """Включает pxpipe: проверяет прокси и вписывает свой провайдер.

    Живая проверка идёт ДО записи: пока прокси не отвечает (или отвечает,
    но поднят не программой), в настройки не пишется ничего. Повторное
    включение при том же содержимом файл не переписывает.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    dest = Path(dest)
    proxy_messages, proxy_errors = ensure_proxy(dest, provider, progress=say)
    messages += proxy_messages
    if proxy_errors:
        return messages, proxy_errors + [
            "В настройки opencode ничего не вписано.",
        ]
    ok, note = dashboard_ok(timeout=5)
    if not ok:
        return messages, [
            f"pxpipe не включён: {note}. Прокси не отвечает даже после попытки "
            "поднять его — проверьте, не занят ли порт.",
            "В настройки opencode ничего не вписано.",
        ]
    info = _launch_info(dest)
    if not info.get("pid"):
        return [], [
            "pxpipe не включён: прокси отвечает, но запущен не программой — "
            "неизвестно, куда он пересылает запросы. Останови его и запусти "
            "командой pxpipe.py start.",
            "В настройки opencode ничего не вписано.",
        ]
    say("Живая проверка прошла: " + note)

    # Источник — тот, с которым поднят прокси: иначе в настройках была бы
    # неправда («прокси к B»), а запросы уходили бы к A.
    src = str(info.get("provider") or "")
    chosen = provider.strip()
    if not src:
        return [], [
            "pxpipe не включён: неизвестно, к какому провайдеру пересылает "
            "запущенный прокси. Останови его и запусти командой "
            "pxpipe.py start <провайдер>.",
            "В настройки opencode ничего не вписано.",
        ]
    if chosen and chosen != src:
        return [], [
            f"pxpipe не включён: прокси запущен с источником «{src}», а выбран "
            f"«{chosen}». Останови командой pxpipe.py stop, потом "
            "pxpipe.py start <провайдер> с нужным провайдером.",
            "В настройки opencode ничего не вписано.",
        ]
    choices = provider_choices(dest)
    if not choices:
        return [], [
            "В настройках нет ни одного провайдера: pxpipe пересылает запросы "
            "к провайдеру, а пересылать некуда. Поставь провайдера (например "
            "OmniRoute) и повтори.",
            "В настройки opencode ничего не вписано.",
        ]
    if src == PROVIDER:
        return [], [
            f"Провайдер «{src}» — это и есть наша запись pxpipe: выбрать её "
            "источником нельзя.",
            "В настройки opencode ничего не вписано.",
        ]
    if src not in choices:
        return [], [
            f"Провайдера «{src}» в настройках нет. Сначала поставь его.",
            "В настройки opencode ничего не вписано.",
        ]

    entry, bad = provider_entry(dest, src)
    if bad:
        return [], [f"pxpipe не включён: {bad}", "В настройки ничего не вписано."]

    cfg = _config(dest)
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"opencode.jsonc не читается: {exc}"]

    # Сравниваем без крайней запятой: update_block её срезает, и без этой
    # мелочи повторное нажатие переписывало бы файл теми же байтами.
    current = _block_text(text).strip().rstrip(",").strip()
    if current and current == entry.strip().rstrip(",").strip():
        say("Провайдер pxpipe уже стоит — файл не менялся.")
        return messages, errors
    if not current and "pxpipe" in text and "provider.pxpipe" in text:
        say("Наш блок pxpipe пуст — перепишу его.")
    if not current and opencode_caps.has_entry(
        text[opencode_caps.find_key_object(text, "provider")[0]:
             opencode_caps.find_key_object(text, "provider")[1]],
        PROVIDER,
    ):
        return [], [
            f"Запись «{PROVIDER}» в настройках уже есть, но она не наша — "
            "программа её не трогает.",
            "В настройки opencode ничего не вписано.",
        ]

    backup_dir = dest / "_previous-version"
    try:
        backup_dir.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(cfg, backup_dir / f"opencode.jsonc-{stamp}")
    except OSError as exc:
        return [], [f"Не сохранилась копия настроек: {exc}"]

    try:
        new_text, changed = opencode_caps.update_block(text, "provider", PROVIDER, entry)
    except ValueError as exc:
        return [], [f"Настройки не тронуты: {exc}"]
    if not changed:
        return [], [
            f"Запись «{PROVIDER}» в настройках не наша — программа её не трогает.",
            "В настройки opencode ничего не вписано.",
        ]
    try:
        cfg.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        return [], [f"opencode.jsonc не записался: {exc}"]

    manifest = opencode_caps.read_manifest(dest)
    manifest[MANIFEST_KEY] = {"provider": PROVIDER, "source": src,
                              "upstream": str(info.get("upstream") or "")}
    opencode_caps.write_manifest(dest, manifest)
    say(f"Провайдер pxpipe вписан: адрес {base_url()}/v1, модели от «{src}».")
    say("В opencode выбери модель у провайдера pxpipe — запросы пойдут через прокси.")
    return messages, errors


def remove(dest: Path, progress=None) -> tuple[list[str], list[str]]:
    """Убирает нашу запись провайдера. Чужое не трогает."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    dest = Path(dest)
    cfg = _config(dest)
    if not cfg.is_file():
        say("Настроек opencode здесь нет — убирать нечего.")
        return messages, errors
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"opencode.jsonc не читается: {exc}"]
    if not _block_text(text):
        say("Провайдера pxpipe в настройках нет — убирать нечего.")
        return messages, errors
    backup_dir = dest / "_previous-version"
    try:
        backup_dir.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(cfg, backup_dir / f"opencode.jsonc-{stamp}")
    except OSError as exc:
        return [], [f"Не сохранилась копия настроек: {exc}"]
    try:
        new_text = opencode_caps.remove_entry(text, "provider", PROVIDER)
        if not opencode_caps.check_jsonc(new_text):
            raise ValueError("после удаления файл не читается — откат")
        cfg.write_text(new_text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [], [f"Настройки не тронуты: {exc}"]
    manifest = opencode_caps.read_manifest(dest)
    manifest.pop(MANIFEST_KEY, None)
    opencode_caps.write_manifest(dest, manifest)
    say("Провайдер pxpipe убран из настроек. Перезапустите opencode.")
    return messages, errors


def stats(dest: Path, progress=None) -> tuple[list[str], list[str]]:
    """Показывает числа прокси по его журналу — без выдумок.

    Журнала нет — так и говорится: прокси ещё не принимал запросы.
    """
    messages: list[str] = []
    errors: list[str] = []
    if not find_npx():
        return [], ["npx не найден: статистику считает тот же пакет из npm."]
    log = events_file(dest)
    if not log.is_file():
        return [], [
            f"Журнала событий нет ({log}) — прокси ещё не принимал запросы. "
            "Запусти его, поработай немного и повтори.",
        ]
    code, out, err = _run(
        launch_command() + ["stats", "--file", str(log)], STATS_TIMEOUT
    )
    if code != 0:
        return [], [f"Статистика не посчиталась (код {code}): "
                    f"{_tail_text(err or out)}"]
    for line in (out or "").strip().splitlines():
        messages.append(line)
    if not messages:
        errors.append("Статистика пуста: пакет ничего не напечатал.")
    return messages, errors


def _tail_text(text: str, limit: int = 300) -> str:
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return " | ".join(lines[-2:])[:limit]


# ------------------------------------------------------------------ состояние


def status(dest: Path) -> dict[str, object]:
    """Что сейчас: стоит ли запись, отвечает ли прокси, чей он."""
    dest = Path(dest)
    try:
        text = _config(dest).read_text(encoding="utf-8")
    except OSError:
        text = ""
    info = _launch_info(dest)
    # Таймаут здесь намеренно короткий, и это измерено, а не привычка.
    # Когда панель не запущена, Windows отклоняет соединение на локальном
    # порту не мгновенно, а примерно через две секунды: измерено на этой
    # машине — timeout=1.0 даёт 1.01 с, timeout=2.0 даёт 2.01 с, и
    # дальше время уже не растёт. Проверка идёт дважды при сборке вкладки
    # opencode, то есть четыре секунды окно загрузки стояло молча.
    # Ответить панель на локальном адресе может за миллисекунды, поэтому
    # секунды хватает с запасом; проверка вручную по-прежнему идёт с
    # своим, более долгим таймаутом.
    running, note = dashboard_ok(timeout=1)
    manifest = {}
    try:
        manifest = opencode_caps_manifest(dest).get(MANIFEST_KEY) or {}
    except Exception:  # noqa: BLE001 — сломанный манифест не должен ронять окно
        manifest = {}
    return {
        "installed": bool(_block_text(text)),
        "running": running,
        "note": note,
        "ours": bool(info.get("pid")),
        "pid": info.get("pid") or 0,
        "upstream": info.get("upstream") or str(manifest.get("upstream") or ""),
        "source": str(manifest.get("source") or ""),
        "npx": find_npx() or "",
        "port": port(),
    }


def _settings_mtime(dest: Path) -> float:
    """Когда последний раз правили настройки opencode.

    Ключи и адреса провайдеров живут там. Правили файл — мог смениться
    провайдер, ключ или адрес, и прокси, поднятый раньше, работает со
    старыми данными. Время файла — единственное, чем это честно видно.
    """
    newest = 0.0
    for name in ("opencode.jsonc", "opencode.json", "auth.json"):
        try:
            newest = max(newest, (Path(dest) / name).stat().st_mtime)
        except OSError:
            continue
    return newest


def stale_note(dest: Path) -> str:
    """Пусто — прокси свежий. Иначе почему он устарел и что делать."""
    info = _launch_info(dest)
    if not info.get("pid"):
        return ""
    try:
        known = pid_file(dest).stat().st_mtime
    except OSError:
        return ""
    # Отсчёт идёт не от запуска прокси, а от более позднего из двух: запуск
    # или последняя вписка плагина. Иначе прокси объявлял бы себя устаревшим
    # сам у себя: вписка плагина меняет настройки, и через секунду status
    # говорил бы «правили после запуска». Живая проверка это вскрыла.
    try:
        known = max(known, _manifest_mtime(dest))
    except OSError:
        pass
    changed = _settings_mtime(dest)
    if changed and changed > known + 1:
        return ("настройки opencode правили ПОСЛЕ того, как прокси поднят и "
                "плагин вписан — провайдер, ключ или адрес могли смениться. "
                "Сменился провайдер или адрес — перезапусти: pxpipe.py restart. "
                "Сменился только ключ — прокси трогать не надо, ключ читает "
                "сам opencode.")
    return ""


def _manifest_mtime(dest: Path) -> float:
    """Когда вписывали плагин. Файл манифеста трогается вместе с настройками."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    return (Path(dest) / opencode_caps.MANIFEST).stat().st_mtime


def suggest_provider(dest: Path) -> tuple[str, str]:
    """Провайдер из настроек прямо сейчас и почему именно он.

    Порядок тот же, что у списка в окне: наши пресеты первыми, потом
    остальные. Список берётся из настроек при каждом вызове, поэтому
    добавленный человеком провайдер появляется сам.
    """
    names = provider_choices(dest)
    if not names:
        return "", "в настройках opencode нет ни одного провайдера"
    if PROVIDER in names:
        return PROVIDER, "это сам прокси"
    return names[0], ("первый из списка ваших провайдеров; назови другой "
                      "явно: pxpipe.py start <имя>")


def status_text(dest: Path) -> str:
    """Строка состояния словами — для окна и для командной строки."""
    data = status(dest)
    parts: list[str] = []
    if data["running"]:
        whose = "запущен программой" if data["ours"] else "запущен не программой"
        parts.append(f"Прокси отвечает на 127.0.0.1:{data['port']} ({whose})")
        if data["upstream"]:
            parts.append(f"пересылает запросы к {data['upstream']}")
    else:
        parts.append(f"Прокси не отвечает на 127.0.0.1:{data['port']}")
    parts.append(
        "провайдер pxpipe в настройках: "
        + ("стоит" if data["installed"] else "не стоит")
    )
    if data["installed"] and data["source"]:
        parts.append(f"модели взяты у «{data['source']}»")
    want, why = suggest_provider(dest)
    if want:
        parts.append(f"из настроек сейчас подходит провайдер «{want}» ({why})")
    if data["running"]:
        stale = stale_note(dest)
        if stale:
            parts.append(stale)
    return ". ".join(parts) + "."


def choices_text(dest: Path) -> str:
    """Список провайдеров из настроек с номерами — то, что видит человек."""
    names = provider_choices(dest)
    if not names:
        return "В настройках opencode нет ни одного провайдера."
    lines = ["Провайдеры в твоих настройках:"]
    usable = 0
    for i, name in enumerate(names, 1):
        # Помечаем тех, к кому пересылать некуда: адреса в настройках нет.
        # Иначе человек выбирает провайдера и получает отказ вместо работы.
        where = provider_base_url(dest, name)
        if where:
            usable += 1
            lines.append(f"  {i}. {name} — {where}")
        else:
            lines.append(f"  {i}. {name} — нет baseURL, прокси через него "
                         f"не заработает")
    if not usable:
        lines.append("Годится ни один: у всех нет baseURL. Прокси нужен "
                     "провайдер с адресом.")
    lines.append("Назови номер или имя. Список читается из настроек при "
                 "каждом запуске — добавленные тобой провайдеры тоже здесь.")
    return "\n".join(lines)


def resolve_provider(dest: Path, given: str = "") -> tuple[str, str]:
    """Что человек назвал: номер из списка или имя. Пусто — не разобрались.

    Возвращает (провайдер, причина). Причина непуста, когда имя не
    найдено: тогда выдумывать ничего нельзя.
    """
    names = provider_choices(dest)
    if not names:
        return "", "в настройках opencode нет ни одного провайдера"
    given = (given or "").strip()
    if not given:
        return "", "провайдер не назван"
    if given.isdigit():
        index = int(given)
        if 1 <= index <= len(names):
            return names[index - 1], f"выбран номер {index}"
        return "", (f"номера {index} нет: в списке от 1 до {len(names)}")
    if given in names:
        return given, "назван именем"
    return "", f"«{given}» нет в списке: {', '.join(names)}"


def choose(dest: Path, progress=None) -> tuple[str, str]:
    """Показывает список и спрашивает номер. Это то, о просил человек.

    Перенаправленный ввод тоже годится: если строка пришла — берём её.
    Отказываем только когда ввода действительно нет, и говорим чем
    заменить: именем или номером прямо в команде.
    """
    import sys as _sys  # noqa: PLC0415 — нужен только здесь

    _say(choices_text(dest))
    _say("Твой выбор (номер или имя, Enter — отмена):")
    try:
        answer = _sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if not answer.strip():
        # Пустая строка и конец ввода — разные вещи. Человек нажал Enter:
        # это отмена. Ввода не было вовсе (агент, конвейер, перенаправление):
        # сказать «отменено» было бы враньём, надо сказать правду.
        if _sys.stdin.isatty():
            return "", "отменено"
        return "", ("ввода не было — выбирать не из чего. Назови провайдера "
                    "явно: pxpipe.py start <номер или имя>")
    name, why = resolve_provider(dest, answer.strip())
    if not name:
        return "", why
    return name, why


def restart(dest: Path, provider: str = "", progress=None) -> tuple[list[str], list[str]]:
    """Перезапускает прокси, заново выбрав провайдера из настроек.

    Нужно, когда провайдер или адрес сменились после запуска. Ключ
    поменялся — перезапуск не нужен, его читает сам opencode.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    _, stop_errors = stop(dest)
    if stop_errors:
        return [], stop_errors
    say("Прокси остановлен.")
    started, start_errors = start(dest, provider=provider, progress=progress)
    return started, start_errors


def _say(text: str) -> None:
    print(text, flush=True)


def _main(argv: list[str]) -> int:
    """Командная строка pxpipe: то же, что делали галочка и кнопки."""
    action = (argv[0] if argv else "status").lower()
    dest = Path(os.environ.get("OPENCODE_CONFIG_DIR")
                or Path.home() / ".config" / "opencode")
    if action in ("-h", "--help", "help"):
        _say("pxpipe.py choose                    — показать твой список и выбрать")
        _say("pxpipe.py status | check | start [номер|имя] | restart [номер|имя]")
        _say("          | stop | install [номер|имя] | remove | stats")
        _say("Провайдера можно не называть: он берётся из настроек opencode "
             "при каждом запуске, а добавленный тобой провайдер появляется сам.")
        _say("Переключатель — на вкладке opencode; здесь то же самое словами.")
        return 0
    if action == "status":
        _say(status_text(dest))
        return 0
    if action == "check":
        ok, note = dashboard_ok()
        _say(("Живая проверка: " if ok else "Живая проверка не прошла: ") + note)
        return 0 if ok else 1
    if action == "choose":
        name, why = choose(dest)
        if not name:
            _say(why)
            return 2
        messages, errors = start(dest, provider=name)
    elif action == "start":
        provider = argv[1] if len(argv) > 1 else ""
        messages, errors = start(dest, provider=provider)
    elif action == "restart":
        provider = argv[1] if len(argv) > 1 else ""
        messages, errors = restart(dest, provider=provider)
    elif action == "stop":
        messages, errors = stop(dest)
    elif action == "install":
        provider = argv[1] if len(argv) > 1 else ""
        messages, errors = install(dest, provider=provider)
    elif action == "remove":
        messages, errors = remove(dest)
    elif action == "stats":
        messages, errors = stats(dest)
    else:
        _say(f"Не знаю такой команды: {action}")
        _say("pxpipe.py choose                    — показать твой список и выбрать")
        _say("pxpipe.py status | check | start [номер|имя] | restart [номер|имя]")
        _say("          | stop | install [номер|имя] | remove | stats")
        _say("Провайдера можно не называть: он берётся из настроек opencode "
             "при каждом запуске, а добавленный тобой провайдер появляется сам.")
        return 2
    for line in messages:
        _say(line)
    for line in errors:
        _say("Ошибка: " + line)
    return 1 if errors else 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main(_sys.argv[1:]))
