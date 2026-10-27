"""Hindsight — банк памяти. Установка, запуск, остановка и проверка сервера.

Роль в программе. При создании базы выбирается тип памяти, и Hindsight —
один из трёх вариантов. Требование человека 25.10.2026: программа САМА
ставит и поднимает сервер, а не только пишет конфиг. Конфиг (выбор uv или
Docker, цена — диск и ОЗУ) показывается в шаге 2 ПРЯМО при создании,
чтобы человек узнал о цене до, а не после.

Факты из официальной документации vectorize-io (проверены 25.10.2026,
страницы installation / mcp-server / monitoring):

- MCP-сервер включён по умолчанию и висит на http://127.0.0.1:8888.
  У каждой базы свой банк: http://127.0.0.1:8888/mcp/<bank>/
  (single-bank режим, 27 инструментов, без авторизации).
- База данных по умолчанию — встроенная PostgreSQL (pg0), данные кладутся
  в ~/.hindsight/data/. Отдельно ставить PostgreSQL не нужно.
- Health: /health/live — процесс жив (БД не трогает), /health/ready —
  то же + можно выполнить SELECT 1 (200 = готов). Берём /health/ready.
- LLM настраивается переменными HINDSIGHT_API_LLM_*: подходящий домашний
  провайдер (OpenAI-совместимый) программа находит в opencode.jsonc и
  передаёт на лету. Ключ в базу не пишется.

Правило «сначала проверка, потом утверждение»: кнопка не говорит
«работает», пока /health/ready не ответил 200.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAM = HERE.parent.parent

#: Окружение Hindsight живёт в папке программы: она сама его ставит,
#: сама обновляет, и оно всегда той версии, что у программы.
VENV_DIR = PROGRAM / "tools" / "thirdparty" / "hindsight-venv"

#: Пакет и версия. Версия закреплена намеренно: `@latest` между проверкой
#: и установкой вправе отдать другой пакет, и человек получит не тот,
#: который видел в подписи.
PACKAGE = "hindsight-api"
VERSION = "1.1.0"
PYTHON = "3.12"

#: Порт и адрес — из документации. Воркеры слушают 8889, но одиночный
#: сервер с встроенной БД обходится одним портом.
PORT = 8888
BASE_URL = "http://127.0.0.1:8888"

#: Docker-образ (full). Размер ~9 ГБ — об этом человеку говорят заранее.
DOCKER_IMAGE = "ghcr.io/vectorize-io/hindsight:latest"
DOCKER_CONTAINER = "hindsight-opencode"

#: Сколько ждать готовности (установку делает кнопка, это запуск).
START_TIMEOUT = 240

#: Запрет установки — та же переменная, что у движков (engine_setup).
NO_INSTALL_ENV = "OPENCODE_NO_AUTO_INSTALL"

#: winget-идентификаторы. Проверены по каталогу winget:
#: astral-sh.uv — сам uv, Docker.DockerDesktop — Docker Desktop.
WINGET_UV = "astral-sh.uv"
WINGET_DOCKER = "Docker.DockerDesktop"

#: Файл с PID запущенного сервера — чтобы кнопка «Остановить» не угадывала
#: процесс по порту (порт может быть занят чужой программой).
PID_FILE = "hindsight.pid"


def _hidden_startupinfo():
    """Окно консоли не показывать. Подробности — в core.hidden_startupinfo."""
    try:
        from core import hidden_startupinfo

        return hidden_startupinfo()
    except Exception:  # noqa: BLE001 — без этого просто откроется окно
        return None


def _auto_install_allowed() -> bool:
    return os.environ.get(NO_INSTALL_ENV, "") == ""


def find_uv() -> Path | None:
    """Ищет uv тем же способом, что остальная программа."""
    try:
        import python_envs  # noqa: PLC0415 — рядом лежит

        return python_envs.find_uv()
    except Exception:  # noqa: BLE001 — поиск не должен ронять
        return None


def find_docker() -> Path | None:
    """Ищет Docker CLI. Файл может быть, а демон — не запущен."""
    found = shutil.which("docker") or shutil.which("docker.exe")
    return Path(found) if found else None


def _run(argv: list[str], timeout: int = 120, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
        startupinfo=_hidden_startupinfo(), env=env,
    )


def venv_python() -> Path:
    return VENV_DIR / "Scripts" / "python.exe"


def _venv_has_package() -> bool:
    """Готово ли окружение: питон есть и пакет в нём есть."""
    python = venv_python()
    if not python.is_file():
        return False
    code = (
        "import importlib.util,sys;"
        "sys.exit(0 if importlib.util.find_spec('hindsight') else 1)"
    )
    try:
        proc = subprocess.run(
            [str(python), "-c", code], capture_output=True, timeout=120,
            startupinfo=_hidden_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def server_script() -> Path:
    """Консольная команда hindsight-api в окружении программы."""
    return VENV_DIR / "Scripts" / "hindsight-api.exe"


def installed() -> bool:
    return _venv_has_package() or server_script().is_file()


# ------------------------------------------------------------- установка

def install_uv(progress=None) -> tuple[bool, list[str]]:
    """Ставит uv через winget, если его нет. Возвращает (получилось, журнал)."""
    log: list[str] = []

    def say(text: str) -> None:
        log.append(text)
        if progress:
            progress(text)

    if find_uv() is not None:
        say("uv уже есть — ставить нечего.")
        return True, log
    if not _auto_install_allowed():
        say(f"Установка запрещена переменной {NO_INSTALL_ENV} — её выставили проверки.")
        return False, log
    if shutil.which("winget") is None:
        say("winget не найден — установить uv не получится.")
        say("Поставьте uv вручную: https://docs.astral.sh/uv/getting-started/installation/")
        return False, log
    say(f"Ставлю uv через winget: {WINGET_UV}…")
    try:
        done = _run(
            ["winget", "install", "-e", "--id", WINGET_UV,
             "--accept-source-agreements", "--accept-package-agreements"],
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"winget не отработал: {exc}")
        return False, log
    if find_uv() is None:
        tail = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-3:]
        say("uv не появился после установки: " + " / ".join(tail)[:300])
        return False, log
    say("uv установлен.")
    return True, log


def install_docker(progress=None) -> tuple[bool, list[str]]:
    """Ставит Docker Desktop через winget (запасной путь Hindsight).

    Docker Desktop сам по себе не «запускается» из-под скрипта сразу:
    после установки нужны WSL2 и первый запуск демона. Честно говорим,
    что дальше делает человек, — не изображаем готовность.
    """
    log: list[str] = []

    def say(text: str) -> None:
        log.append(text)
        if progress:
            progress(text)

    if docker_running():
        say("Docker уже работает — ставить нечего.")
        return True, log
    if not _auto_install_allowed():
        say(f"Установка запрещена переменной {NO_INSTALL_ENV} — её выставили проверки.")
        return False, log
    if shutil.which("winget") is None:
        say("winget не найден — установить Docker Desktop не получится.")
        return False, log
    say(f"Ставлю Docker Desktop через winget: {WINGET_DOCKER}…")
    try:
        done = _run(
            ["winget", "install", "-e", "--id", WINGET_DOCKER,
             "--accept-source-agreements", "--accept-package-agreements"],
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"winget не отработал: {exc}")
        return False, log
    if not find_docker():
        tail = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-3:]
        say("docker после установки не найден: " + " / ".join(tail)[:300])
        return False, log
    say("Docker Desktop установлен. Запустите его один раз (иконка в трее):")
    say("демон поднимается минуту-две, после этого кнопка «Запустить» справится сама.")
    return False, log


def install(progress=None, method: str = "uv") -> tuple[bool, list[str]]:
    """Доводит Hindsight до готового выбранным способом. Честные отказы словами.

    method: "uv" (по умолчанию) — отдельный виртуальный модуль, ~2–3 ГБ
    диска и 1,5–2 ГБ ОЗУ при работе, Docker не нужен. method="docker" —
    официальный образ, ~9 ГБ диска и нужен работающий Docker Desktop.
    Способ выбирает человек заранее, в окне создания базы, где цена
    каждого варианта показана до записи. Без ключа LLM сервер поднимется,
    но память без модели не работает — об этом говорится в отчёте честно.
    """
    log: list[str] = []

    def say(text: str) -> None:
        log.append(text)
        if progress:
            progress(text)

    method = (method or "uv").strip().lower()
    if method not in ("uv", "docker"):
        say(f"Способ установки должен быть «uv» или «docker». Получено: {method!r}.")
        return False, log

    if method == "docker":
        if docker_running():
            say("Docker уже работает — окружение Hindsight поднимет кнопка «Запустить».")
            return True, log
        if not _auto_install_allowed():
            say(f"Установка запрещена переменной {NO_INSTALL_ENV} — её выставили проверки.")
            return False, log
        ok, log2 = install_docker(progress)
        log += log2
        return ok, log

    if installed():
        say("Окружение Hindsight уже стоит.")
        return True, log

    uv = find_uv()
    if uv is None:
        ok, log2 = install_uv(progress)
        log += log2
        if not ok:
            return False, log
        uv = find_uv()
    if uv is None:
        say("uv не найден — ставить окружение нечем.")
        return False, log

    say("Создаю окружение Python 3.12 (пару минут, ставит пакеты и модели).")
    try:
        done = _run(
            [str(uv), "venv", "--python", PYTHON, str(VENV_DIR)],
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"uv venv не отработал: {exc}")
        return False, log
    if not venv_python().is_file():
        tail = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-3:]
        say("Окружение не создалось: " + " / ".join(tail)[:300])
        return False, log

    say(f"Ставлю {PACKAGE}=={VERSION} в окружение…")
    try:
        done = _run(
            [str(uv), "pip", "install", "--python", str(venv_python()),
             f"{PACKAGE}=={VERSION}"],
            timeout=1200,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"Установка не закончилась: {exc}")
        return False, log
    if not installed():
        tail = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-5:]
        say("Пакет не встал: " + " / ".join(tail)[:300])
        return False, log
    say(f"Окружение Hindsight готово ({PACKAGE}=={VERSION}).")
    return True, log


def docker_running() -> bool:
    """Работает ли демон Docker: `docker info` отвечает кодом 0."""
    docker = find_docker()
    if docker is None:
        return False
    try:
        proc = _run([str(docker), "info"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def docker_installed() -> bool:
    return find_docker() is not None


# ----------------------------------------------------------- конфиг LLM

def _strip_jsonc(text: str) -> str:
    """Убирает // и /* */ комментарии, не трогая строки и URL.

    Простой re.sub по ``//`` режет ``https://`` внутри JSON-строк —
    baseURL провайдера выглядит как комментарий. Поэтому идём посимвольно
    и помним, внутри ли мы строки.
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_str:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def llm_from_config(config_dir: Path) -> dict:
    """Находит домашний OpenAI-совместимый провайдер для Hindsight.

    Читает opencode.jsonc (папку настроек) и ищет блок провайдера с
    baseURL и apiKey. Ничего не пишет: ключ в базу не кладём. Если в
    окружении уже стоит HINDSIGHT_API_LLM_API_KEY — считаем, что человек
    настроил сам, и возвращаем пустой словарь.

    Возвращает {provider, base_url, api_key, model} или {} с причиной в
    `note`. Версия для OpenAI-совместимых шлюзов: provider=openai.
    """
    if os.environ.get("HINDSIGHT_API_LLM_API_KEY"):
        return {}

    cfg = config_dir / "opencode.jsonc"
    if not cfg.is_file():
        return {"note": "opencode.jsonc не найден — ключ не откуда взять"}
    try:
        text = _strip_jsonc(cfg.read_text(encoding="utf-8"))
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"note": f"opencode.jsonc не разобрался: {exc}"}
    if not isinstance(data, dict):
        return {"note": "opencode.jsonc неожиданного вида"}

    # Провайдеры: в обеих версиях конфига это словарь «имя провайдера →
    # настройки»; в V1 (opencode 1.x) он лежит в единственном объекте
    # `provider`, в V2 — в `providers`. Обрабатываем оба одинаково.
    blocks = []
    for key in ("provider", "providers"):
        obj = data.get(key)
        if isinstance(obj, dict):
            for name, blk in obj.items():
                blocks.append((str(name), blk))

    preferred = ("dahl", "genapi", "chad", "qwencloud", "mistral")

    def _rank(kv):
        name = kv[0]
        if name in preferred:
            return (0, list(preferred).index(name))
        return (1, 0)

    ordered = sorted(blocks, key=_rank)
    for name, blk in ordered:
        if not isinstance(blk, dict):
            continue
        opts = blk.get("options")
        if not isinstance(opts, dict):
            continue
        base_url = str(opts.get("baseURL") or "").strip()
        api_key = str(opts.get("apiKey") or "").strip()
        if not base_url or not api_key:
            continue
        models = blk.get("models")
        model = ""
        if isinstance(models, dict) and models:
            keys = list(models)
            for want in ("deepseek", "glm", "mini", "flash", "qwen", "mistral"):
                for key in keys:
                    if want in str(key).lower():
                        model = key
                        break
                if model:
                    break
            if not model:
                model = keys[0]
        if not model:
            continue
        return {
            "provider": "openai",
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "provider_name": name,
        }
    return {"note": "в opencode.jsonc нет провайдера с baseURL и ключом"}


def env_for_llm(config_dir: Path) -> dict:
    """Переменные окружения Hindsight из конфига. Ключи не пишет и не печатает."""
    env = dict(os.environ)
    llm = llm_from_config(config_dir)
    if not llm or "api_key" not in llm:
        return env
    env["HINDSIGHT_API_LLM_PROVIDER"] = llm["provider"]  # openai — совместимый
    env["HINDSIGHT_API_LLM_API_KEY"] = llm["api_key"]
    env["HINDSIGHT_API_LLM_MODEL"] = llm["model"]
    env["HINDSIGHT_API_LLM_BASE_URL"] = llm["base_url"]
    # Документация: факты на языке пользователя. Пользователь — русский.
    env["HINDSIGHT_API_LLM_OUTPUT_LANGUAGE"] = "Russian"
    env["HINDSIGHT_API_LLM_TEMPERATURE"] = "0.0"
    env["HINDSIGHT_API_WORKER_ID"] = "hindsight-opencode"
    return env


def llm_note(config_dir: Path) -> str:
    """Для отчёта: какой провайдер и модель будут использоваться."""
    if os.environ.get("HINDSIGHT_API_LLM_API_KEY"):
        return "ключ задан в окружении — сервер использует его как есть"
    llm = llm_from_config(config_dir)
    if not llm:
        return llm.get("note", "провайдер не найден")
    return (
        f"провайдер {llm.get('provider_name')}, модель {llm.get('model')}"
        f" ({llm.get('base_url')})"
    )


# ---------------------------------------------------------------- health

def _http_get_ready(timeout: float = 2.0) -> tuple[int | None, dict]:
    """GET /health/ready. Возвращает (код статуса, тело JSON) или (None, {})."""
    req = urllib.request.Request(BASE_URL + "/health/ready", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            return resp.status, data
    except Exception:  # noqa: BLE001 — недоступность нормальна для проверки
        return None, {}


def status_text() -> str:
    """Одна строка для карточки: «работает», «стоит, не запущен», …"""
    code, data = _http_get_ready(timeout=2.0)
    if code == 200:
        if data.get("status") == "healthy":
            return "сервер работает (готов)"
        return f"сервер отвечает {code}, но не «healthy» — {data.get('status')}"
    if code is None:
        return "сервер не запущен или порт занят чужим процессом"
    return f"сервер отвечает {code} (не 200)"


# ------------------------------------------------------------- запуск

def _pid_file() -> Path:
    return VENV_DIR / PID_FILE


def _read_pid() -> int | None:
    path = _pid_file()
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _write_pid(proc) -> None:
    try:
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        _pid_file().write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pass


def _alive(pid: int) -> bool:
    """Жив ли процесс. os.kill(pid, 0) на Windows убивает — проверяем иначе."""
    if os.name != "nt":
        return True
    try:
        proc = _run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Process -Id {pid} | Select-Object -ExpandProperty ProcessName"],
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    name = (proc.stdout or "").strip().lower()
    return "hindsight" in name or "python" in name


def start(config_dir: Path, method: str = "uv", progress=None) -> tuple[bool, list[str]]:
    """Поднимает сервер Hindsight. (получилось, журнал).

    `config_dir` — папка настроек программы, оттуда берётся ключ LLM.
    `method` — "uv" (по умолчанию) или "docker". Возвращает False с
    причиной словами, если поднять не вышло (правило «сначала проверка»).
    """
    log: list[str] = []

    def say(text: str) -> None:
        log.append(text)
        if progress:
            progress(text)

    code, _data = _http_get_ready(timeout=1.0)
    if code == 200:
        say("Сервер уже работает — повторно не запускаю.")
        return True, log

    if method == "docker":
        return _start_docker(config_dir, say, log)
    return _start_uv(config_dir, say, log)


def _start_uv(config_dir: Path, say, log: list[str]) -> tuple[bool, list[str]]:
    if not installed():
        say("Окружение Hindsight не стоит — нажмите «Установить».")
        return False, log
    script = server_script()
    if not script.is_file():
        say("Консольной команды hindsight-api в окружении нет. Окружение битое.")
        return False, log
    env = env_for_llm(config_dir)
    pid = _read_pid()
    if pid and _alive(pid):
        say(f"Сервер уже запущен (pid {pid}) — повторно не запускаю.")
        return True, log
    say("Запускаю hindsight-api (первый старт создаёт базу в ~/.hindsight/data).")
    try:
        proc = subprocess.Popen(
            [str(script), "--host", "127.0.0.1", "--port", str(PORT)],
            env=env, cwd=str(VENV_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=_hidden_startupinfo(),
        )
    except OSError as exc:
        say(f"Сервер не запустился: {exc}")
        return False, log
    _write_pid(proc)
    # Ждём готовности: первый старт мигрирует БД, это может быть долго.
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        code, _data = _http_get_ready(timeout=1.0)
        if code == 200:
            say("Сервер Hindsight работает: MCP на "
                f"{BASE_URL}/mcp/<банк>/. {llm_note(config_dir)}")
            return True, log
        time.sleep(1.0)
    say(f"За {START_TIMEOUT} секунд сервер не поднялся. Смотрите журнал:")
    say(str(VENV_DIR / "hindsight.log"))
    return False, log


def _start_docker(config_dir: Path, say, log: list[str]) -> tuple[bool, list[str]]:
    if not docker_installed():
        say("Docker не установлен — нажмите «Установить Docker» или выберите uv.")
        return False, log
    if not docker_running():
        say("Docker установлен, но демон не запущен.")
        say("Запустите Docker Desktop (иконка в трее) и повторите.")
        return False, log
    env = env_for_llm(config_dir)
    say("Создаю и запускаю контейнер (первый раз качает образ ~9 ГБ).")
    cmd = [
        str(find_docker()), "run", "-d", "--name", DOCKER_CONTAINER,
        "--restart", "unless-stopped", "-p", f"{PORT}:{PORT}",
        "-e", "HINDSIGHT_API_LLM_API_KEY=" + (env.get("HINDSIGHT_API_LLM_API_KEY") or ""),
        "-e", "HINDSIGHT_API_LLM_PROVIDER=" + env.get("HINDSIGHT_API_LLM_PROVIDER", "openai"),
        "-e", "HINDSIGHT_API_LLM_MODEL=" + env.get("HINDSIGHT_API_LLM_MODEL", ""),
        "-e", "HINDSIGHT_API_LLM_BASE_URL=" + env.get("HINDSIGHT_API_LLM_BASE_URL", ""),
        "-v", "hindsight-data:/home/hindsight/.pg0",
        DOCKER_IMAGE,
    ]
    try:
        done = _run(cmd, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"docker run не отработал: {exc}")
        return False, log
    if done.returncode != 0:
        say("docker run не прошёл: " + ((done.stderr or done.stdout or "").strip()[-300:]))
        return False, log
    deadline = time.monotonic() + START_TIMEOUT
    say("Контейнер создан, жду готовности (первый старт мигрирует БД)…")
    while time.monotonic() < deadline:
        code, _data = _http_get_ready(timeout=1.0)
        if code == 200:
            say(f"Сервер Hindsight в Docker работает: {BASE_URL}/mcp/<банк>/.")
            return True, log
        time.sleep(1.0)
    say(f"За {START_TIMEOUT} секунд контейнер не поднялся. Смотрите: docker logs {DOCKER_CONTAINER}")
    return False, log


def stop(progress=None) -> tuple[bool, list[str]]:
    """Останавливает сервер. Контейнер Docker — останавливает, но не удаляет."""
    log: list[str] = []

    def say(text: str) -> None:
        log.append(text)
        if progress:
            progress(text)

    pid = _read_pid()
    if pid and _alive(pid):
        try:
            _run(["taskkill", "/PID", str(pid)], timeout=30)
            say(f"Сервер остановлен (pid {pid}).")
            return True, log
        except (OSError, subprocess.SubprocessError) as exc:
            say(f"Остановить не вышло: {exc}")
            return False, log
    if docker_installed():
        stop_cmd = [str(find_docker()), "stop", DOCKER_CONTAINER]
        try:
            proc = _run(stop_cmd, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            say(f"docker stop не отработал: {exc}")
            return False, log
        if proc.returncode == 0:
            say(f"Контейнер {DOCKER_CONTAINER} остановлен.")
            return True, log
    say("Сервер не запущен — останавливать нечего.")
    return True, log


# ------------------------------------------------------------ MCP-блок

def mcp_url(bank: str) -> str:
    return f"{BASE_URL}/mcp/{bank}/"


def mcp_block(bank: str) -> str:
    """Запись для секции mcp в opencode.jsonc. Ключа в ней нет."""
    return (
        '"hindsight": {\n'
        '      "type": "remote",\n'
        f'      "url": "{mcp_url(bank)}",\n'
        '      "enabled": true\n'
        "    },"
    )
