"""Настройка мостов Unity, Unreal, Roblox Studio, Godot, TikTok и CapCut.

Программа умеет только то, что не требует чужого окна: записать файл
рядом с настройками opencode и сказать, чего не хватает. Плагин в
редактор она не ставит и живой ответ редактора не подделывает.

Секреты в возвращаемый текст не попадают.
"""

from __future__ import annotations

import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "launchers"))

import bridge_common as common  # noqa: E402

IDS = (
    "unity", "unreal", "roblox-studio", "godot", "tiktok", "capcut",
    "spotify", "chatgpt", "codex", "cursor",
)

UNITY_GIT = (
    "https://github.com/CoplayDev/unity-mcp.git?path=/MCPForUnity#main"
)

UNREAL_NAME = "mcp-unreal.txt"
GODOT_NAME = "mcp-godot-attach.json"
TIKTOK_NAME = "mcp-tiktok.txt"
CAPCUT_NAME = "mcp-capcut.json"
SPOTIFY_NAME = "mcp-spotify.txt"
CHATGPT_NAME = "mcp-chatgpt.txt"
CURSOR_NAME = "mcp-cursor.txt"

# Сайты CapCut и ByteDance. Это не опубликованный MCP, туда не ходим.
_CAPCUT_HOSTS = (
    "capcut.com",
    "capcut.cn",
    "capcutapi.com",
    "jianying.com",
    "bytedance.com",
    "byteoversea.com",
    "capcutcdn.com",
    "capcutcdn-us.com",
)
_SECRET_QUERY = {
    "token", "access_token", "api_key", "apikey", "key", "secret", "password",
}


def settings_file(dest: Path, name: str) -> Path:
    return Path(dest) / name


def _write(path: Path, text: str) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        return f"Не удалось записать {path}: {exc}"
    return None


def save_unreal(dest: Path, project: str, plugin: str = "") -> tuple[bool, str]:
    """Пишет путь проекта. Плагин 0.6 обязателен, иначе лаунчер откажет."""
    folder = common.project_dir(project.strip())
    if folder is None:
        return False, "Укажи существующую папку проекта или файл .uproject."
    if not common.enginewire_present(folder, plugin.strip()):
        return False, (
            f"В {folder} нет Plugins/EngineWire. Сервер закреплён на "
            "0.6.0-beta-e, старый плагин McpAutomationBridge не подходит. "
            "Путь не записан: лаунчер всё равно отказал бы."
        )
    lines = [f"project={folder}"]
    if plugin.strip():
        lines.append(f"plugin={plugin.strip()}")
    lines.append("")
    path = settings_file(dest, UNREAL_NAME)
    error = _write(path, "\n".join(lines))
    if error:
        return False, error
    return True, (
        f"Путь проекта записан: {path}. Токен capability в файл не входит, "
        "его читает сам сервер. Редактор ещё не отвечал — готовым мост не считается."
    )


def save_godot(dest: Path, text: str) -> tuple[bool, str]:
    """Принимает JSON с полем command или сам список argv."""
    raw = (text or "").strip()
    if not raw:
        return False, "Команда пустая. Скопируй её из дока Godot AI."
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, "Это не JSON. Нужен объект с полем command или список argv."
    if isinstance(data, list):
        data = {"command": data}
    command = common.godot_command(data)
    if not command:
        return False, (
            "В команде нет слова attach, либо это петля на свой лаунчер. "
            "Голый адрес http://127.0.0.1:8000/mcp не подходит."
        )
    path = settings_file(dest, GODOT_NAME)
    body = json.dumps({"command": command}, ensure_ascii=False, indent=2) + "\n"
    error = _write(path, body)
    if error:
        return False, error
    return True, (
        f"Команда attach записана: {path}. Аргументы в это сообщение не "
        "входят: в них может быть capability. Редактор ещё не отвечал."
    )


def save_tiktok(dest: Path, token: str, app_id: str) -> tuple[bool, str]:
    """Пишет токен рядом с настройками. Значение в ответ не возвращает."""
    token = (token or "").strip()
    app_id = (app_id or "").strip()
    if not token or not app_id:
        return False, "Нужны и access token, и App ID. Пустое не записываю."
    if "\n" in token or "\n" in app_id or "=" in token:
        return False, "Токен и App ID — одна строка каждый, без знака равенства в токене."
    path = settings_file(dest, TIKTOK_NAME)
    body = (
        "# Токен кабинета TikTok Business. Не копировать в репозиторий.\n"
        f"TIKTOK_ACCESS_TOKEN={token}\n"
        f"TIKTOK_APP_ID={app_id}\n"
    )
    error = _write(path, body)
    if error:
        return False, error
    return True, (
        f"Токен записан в {path}. Само значение сюда не входит. "
        "Запросы пойдут в API TikTok. Живой ответ кабинета не проверялся."
    )


def unity_ready() -> tuple[bool, str]:
    """uvx есть или нет. Пакет в редакторе отсюда не виден."""
    if not common.resolve_exe("uvx"):
        return False, (
            "uvx не найден. Его ставит пакет uv. Без него команду Unity "
            "вписывать незачем: лаунчер сразу откажется."
        )
    return True, (
        "uvx найден. Пакет в редактор программа не ставит. В Unity: "
        "Window → Package Manager → Add package from git URL, адрес "
        f"{UNITY_GIT}. Пока проект с пакетом не открыт, мост не над чем работать."
    )


def gap(dest: Path, server_id: str) -> str:
    """Чего не хватает, чтобы лаунчер вообще стартовал. Секретов в тексте нет."""
    dest = Path(dest)
    if server_id == "unity":
        ok, note = unity_ready()
        return "" if ok else note
    if server_id == "roblox-studio":
        ok, note = roblox_ready()
        return "" if ok else note
    if server_id == "capcut":
        return capcut_gap(dest)
    if server_id == "codex":
        ok, note = codex_ready()
        return "" if ok else note
    if server_id == "cursor":
        ok, note = cursor_ready()
        return "" if ok else note
    names = {
        "unreal": UNREAL_NAME,
        "godot": GODOT_NAME,
        "tiktok": TIKTOK_NAME,
        "spotify": SPOTIFY_NAME,
        "chatgpt": CHATGPT_NAME,
    }
    name = names.get(server_id)
    if name and not (dest / name).is_file():
        if server_id in ("spotify", "chatgpt"):
            return (
                f"Нет файла {name} рядом с настройками. «Включить» впишет команду, "
                "но лаунчер откажется. «Настроить автоматически» запишет файл "
                "и не скажет, что сервис уже ответил."
            )
        return (
            f"Нет файла {name} рядом с настройками. «Включить» впишет команду, "
            "но лаунчер откажется. «Настроить автоматически» запишет файл и "
            "не скажет, что редактор уже ответил."
        )
    return ""


def mirror_for_launcher(dest: Path, name: str) -> str:
    """Копирует файл туда, откуда его читает лаунчер, если папки разные.

    В текст ответа содержимое не входит.
    """
    src = Path(dest) / name
    other = common.settings_dir()
    try:
        same = src.parent.resolve() == other.resolve()
    except OSError:
        same = str(src.parent) == str(other)
    if same or not src.is_file():
        return ""
    target = other / name
    try:
        other.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
        target.chmod(0o600)
    except OSError as exc:
        return f"Лаунчер ищет файл в {other}, скопировать не удалось: {exc}"
    return f"Лаунчер читает {target}, туда тоже скопировано."


def roblox_ready() -> tuple[bool, str]:
    """Файл mcp.bat создаёт сама Studio. Нет файла — включать нечего."""
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return False, "LOCALAPPDATA не задан. Это окно рассчитано на Windows."
    path = Path(local) / "Roblox" / "mcp.bat"
    if not path.is_file():
        return False, (
            f"Нет {path}. Его создаёт Roblox Studio, не эта программа. "
            "Assistant → … → Manage MCP Servers → Enable Studio as MCP server, "
            "затем нажми кнопку ещё раз. Готовым мост не считается."
        )
    return True, (
        f"Найден {path}. Это только файл запуска. Студия ещё не отвечала, "
        "и зелёной галочки нет."
    )


def _host_blocked(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == name or host.endswith("." + name) for name in _CAPCUT_HOSTS)


def _private_host(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def internet_mcp_url(text: str) -> tuple[str, str]:
    """Проверяет адрес удалённого MCP. Второй элемент — причина отказа."""
    raw = (text or "").strip()
    if not raw:
        return "", "Адрес пустой. Его должен дать твой хост, программа его не выдумывает."
    if any(ch.isspace() for ch in raw):
        return "", "Адрес — одна строка, без пробелов."
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        return "", (
            "По интернету нужен адрес https. http, localhost и сайт CapCut "
            "не подходят: токен по ним ушёл бы открытым или не туда."
        )
    if parsed.username or parsed.password:
        return "", "Токен в адрес не вписывай. Для него отдельное поле."
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        return "", "Нужен настоящий хост в интернете, не короткое имя компьютера."
    if _host_blocked(host):
        return "", (
            "Это сайт CapCut или ByteDance, не сервер MCP. Опубликованного "
            "адреса у них нет, и программа туда не ходит."
        )
    if _private_host(host):
        return "", "Это не интернет: частный адрес и localhost отвергаются."
    secret = [key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
              if key.lower() in _SECRET_QUERY]
    if secret:
        return "", "Секрет в адресе не пиши. Положи его в поле токена."
    if len(raw) > 2000:
        return "", "Адрес слишком длинный."
    return raw, ""


def _read_capcut(dest: Path) -> dict:
    path = settings_file(dest, CAPCUT_NAME)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def capcut_gap(dest: Path) -> str:
    """Чего не хватает для удалённого CapCut. Секрета в тексте нет."""
    data = _read_capcut(dest)
    url, error = internet_mcp_url(str(data.get("url") or ""))
    if error:
        if not data:
            return (
                "Нет файла mcp-capcut.json с адресом MCP по https. "
                "Сайт CapCut таким адресом не является. "
                "«Настроить автоматически» запишет адрес и не скажет, что сервер ответил."
            )
        return error
    return "" if url else "Адрес MCP не записан."


def save_capcut(dest: Path, url: str, token: str = "") -> tuple[bool, str]:
    """Пишет адрес удалённого MCP. Токен в ответ не возвращает и на сайт не ходит."""
    clean, error = internet_mcp_url(url)
    if error:
        return False, error
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if "\n" in token or "\r" in token:
        return False, "Токен — одна строка. Пустой можно оставить, если хост его не просит."
    headers: dict[str, str] = {}
    kept = False
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        old = _read_capcut(dest).get("headers")
        if isinstance(old, dict) and old.get("Authorization"):
            headers["Authorization"] = str(old["Authorization"])
            kept = True
    path = settings_file(dest, CAPCUT_NAME)
    body = json.dumps({"url": clean, "headers": headers}, ensure_ascii=False, indent=2) + "\n"
    error = _write(path, body)
    if error:
        return False, error
    host = urlparse(clean).hostname or "хост"
    auth = ""
    if token or kept:
        auth = (
            " Заголовок авторизации в файл положен, значение сюда не входит. "
            "При включении opencode положит его в opencode.jsonc на этом "
            "компьютере: иначе удалённый сервер его не увидит. В репозиторий "
            "этот файл не копировать."
        )
    else:
        auth = " Токена нет. Если хост его просит, подключение откажет."
    return True, (
        f"Адрес MCP записан, хост {host}.{auth} "
        "Запрос по адресу не выполнялся. Это не сайт CapCut и не экспорт ролика."
    )


def _one_line(value: str, label: str) -> tuple[str, str]:
    text = (value or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return "", f"{label} — одна строка без пробелов."
    if len(text) > 400:
        return "", f"{label} слишком длинный."
    return text, ""


def save_spotify(dest: Path, client_id: str) -> tuple[bool, str]:
    """Пишет Client ID. В аккаунт Spotify не входит и трек не включает."""
    clean, error = _one_line(client_id, "Client ID")
    if error:
        return False, error
    path = settings_file(dest, SPOTIFY_NAME)
    error = _write(path, f"SPOTIFY_CLIENT_ID={clean}\n")
    if error:
        return False, error
    return True, (
        "Client ID записан в mcp-spotify.txt. Значение сюда не входит. "
        "Пакет @xavifabregat/spotify-mcp@0.1.2 ходит в Spotify Web API. "
        "Это не программа Spotify. Воспроизведение просит Premium и уже "
        "открытое приложение. Вход делает мастер пакета, эта кнопка браузер не открывала."
    )


def save_chatgpt(dest: Path, key: str, model: str) -> tuple[bool, str]:
    """Пишет ключ и имя модели. На сайт chatgpt.com не ходит."""
    clean_key, error = _one_line(key, "Ключ API")
    if error:
        return False, error
    clean_model, error = _one_line(model, "Имя модели")
    if error:
        return False, error
    if clean_key.lower().startswith("bearer"):
        return False, "Ключ без слова Bearer."
    path = settings_file(dest, CHATGPT_NAME)
    error = _write(
        path, f"OPENAI_API_KEY={clean_key}\nOPENAI_MODEL={clean_model}\n",
    )
    if error:
        return False, error
    return True, (
        "Ключ и модель записаны в mcp-chatgpt.txt. Значения сюда не входят. "
        "Мост ходит только на api.openai.com. Сайт chatgpt.com не открывается. "
        "Запрос сейчас не делался."
    )


def save_cursor(dest: Path, key: str = "") -> tuple[bool, str]:
    """Ключ необязателен: Cursor CLI может взять свой уже сделанный вход."""
    key = (key or "").strip()
    if key:
        clean, error = _one_line(key, "Ключ Cursor")
        if error:
            return False, error
        body = f"CURSOR_API_KEY={clean}\n"
        note = "Ключ записан, значение сюда не входит. "
    else:
        body = "# ключа нет, Cursor возьмёт свой вход, если он уже сделан\n"
        note = "Ключ не записан. Если вход в Cursor CLI уже есть, мост его не трогает. "
    path = settings_file(dest, CURSOR_NAME)
    error = _write(path, body)
    if error:
        return False, error
    return True, (
        note + "Команда agent create-chat создаёт чат, agent -p --resume шлёт текст. "
        "Сайт не открывался. --yolo не передаётся. Живой запрос не делался."
    )


def codex_ready() -> tuple[bool, str]:
    exe = common.resolve_exe("codex")
    if not exe:
        return False, (
            "Команда codex не найдена. Её ставит winget OpenAI.Codex. "
            "Потом нужен свой вход: codex login. Пароль эта программа не спрашивает "
            "и сайт не открывает."
        )
    return True, (
        f"Найдена команда {exe}. Это только файл. Вход не проверялся. "
        "По умолчанию песочница только на чтение. danger-full-access не передаётся."
    )


def cursor_ready() -> tuple[bool, str]:
    exe = common.resolve_exe("agent")
    if not exe:
        return False, (
            "Команда agent не найдена. Это Cursor CLI, не любой файл с таким именем. "
            "Установка описана на https://cursor.com/docs/cli/installation. "
            "Сайт отсюда не открывается."
        )
    return True, (
        f"Найдена команда {exe}. Если это не Cursor CLI, мост не заработает. "
        "Ключ можно оставить пустым, если вход уже сделан. "
        "--force не ставится, пока явно не попросят правки."
    )
