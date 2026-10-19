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
            f"В {folder} нет Plugins/EngineWire. В линии 0.6 сервер живёт внутри "
            "плагина, а старый McpAutomationBridge не подходит. "
            "Путь не записан: подключаться всё равно не к чему."
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
        f"Путь проекта записан: {path}. Мост отвечает, только пока открыт "
        "редактор с плагином: сервер поднимает сам плагин."
    )


#: Порт сервера в плагине. 3000 — значение по документации автора, на живой
#: машине НЕ проверено: Unreal здесь не установлен. Поэтому порт всегда
#: спрашивается, а это число живёт только как подсказка в поле ввода.
UNREAL_PORT_DEFAULT = 3000
UNREAL_PORT_NAME = "mcp-unreal-port.txt"


def unreal_port_path(dest: Path) -> Path:
    return settings_file(dest, UNREAL_PORT_NAME)


def read_unreal_port(dest: Path) -> int:
    """Порт из файла настроек. Битое значение — значение по умолчанию."""
    path = unreal_port_path(dest)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return UNREAL_PORT_DEFAULT
    if not raw.isdigit():
        return UNREAL_PORT_DEFAULT
    value = int(raw)
    return value if 1 <= value <= 65535 else UNREAL_PORT_DEFAULT


def save_unreal_port(dest: Path, port: str) -> tuple[bool, str]:
    """Записать порт, который человек назвал. Пустое — оставить как есть."""
    raw = str(port or "").strip()
    if not raw:
        return True, ""
    if not raw.isdigit():
        return False, (f"Порт «{raw}» — не число. Оставь пустым, чтобы взять "
                       f"{UNREAL_PORT_DEFAULT}.")
    value = int(raw)
    if not 1 <= value <= 65535:
        return False, f"Порт {value} — за пределами 1…65535."
    path = unreal_port_path(dest)
    error = _write(path, f"{value}\n")
    if error:
        return False, error
    return True, f"Порт записан: {value}. Адрес: http://127.0.0.1:{value}/mcp"


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


UNITY_NAME = "mcp-unity-project.txt"
GODOT_PROJECT_NAME = "mcp-godot-project.txt"


def save_project(dest: Path, name: str, project: str) -> tuple[bool, str]:
    """Записать папку проекта в свой файл рядом с настройками.

    Общий шаг для трёх мостов: Unity, Unreal и Godot. Плагин у всех трёх
    лежит внутри проекта, а не в программе, поэтому без папки проекта
    ставить нечего — и файл этот пишет сама программа, а не человек в
    блокноте. Путь проверяется по маркеру проекта: если это не папка
    проекта, файл не пишется, иначе плагин осел бы не туда.
    """
    marker = {"mcp-unity-project.txt": "Assets",
              "mcp-godot-project.txt": "project.godot",
              }.get(name)
    text = str(project or "").strip().strip('"')
    if not text:
        return False, "Папка проекта не указана."
    path = Path(text)
    if path.suffix.lower() in (".uproject", ".unity", ".godot"):
        path = path.parent
    if not path.is_dir():
        return False, f"Папки нет: {path}"
    if marker and not (path / marker).exists():
        return False, (f"{path} не похожа на проект: нет файла или папки {marker}. "
                       f"Укажи папку проекта, а не его родителя.")
    target = Path(dest) / name
    written = _write(target, text + "\n")
    if written:
        return False, written
    return True, (f"Проект записан в {target.name}: {path}. По нему программа "
                  f"потом найдёт плагин и поставит его сама.")


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
        if not ok:
            return note
        exe = common.resolve_exe("codex")
        return codex_gap(exe) if exe else ""
    if server_id == "cursor":
        ok, note = cursor_ready()
        if not ok:
            return note
        exe = common.resolve_exe("agent")
        return cursor_gap(exe) if exe else ""
    if server_id == "claude":
        ok, note = claude_ready()
        if not ok:
            return note
        exe = claude_find()
        return claude_gap(exe) if exe else ""
    if server_id == "spotify":
        return spotify_gap(dest)
    names = {
        "unreal": UNREAL_NAME,
        "godot": GODOT_NAME,
        "tiktok": TIKTOK_NAME,
        "chatgpt": CHATGPT_NAME,
    }
    name = names.get(server_id)
    if name and not (dest / name).is_file():
        if server_id == "chatgpt":
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
    tail = (
        "Пакет @xavifabregat/spotify-mcp@0.1.2 ходит в Spotify Web API. "
        "Это не программа Spotify. Вход делает мастер пакета (npx … init), "
        "он открывает браузер — эта кнопка браузер не открывала."
    )
    if not spotify_login_saved():
        tail += (
            " Входа пока нет: папки ~/.spotify-mcp не найдено, значит пакет "
            "ни разу не входил. Поиск и плейлист без входа не ответят."
        )
    if not spotify_app_installed():
        tail += (
            " Приложения Spotify на этом компьютере не найдено: по README пакета "
            "управлять воспроизведением можно только запущенным приложением."
        )
    tail += (
        " Premium нужен и для воспроизведения, и (с февраля 2026) для создания "
        "своего приложения в кабинете Spotify — это тоже из README пакета. "
        "Наличие подписки мост не проверяет."
    )
    return True, (
        "Client ID записан в mcp-spotify.txt. Значение сюда не входит. " + tail
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


def spotify_login_saved() -> bool:
    """Пакет сохраняет свой вход в ~/.spotify-mcp. Нет папки — входа не было."""
    return (Path.home() / ".spotify-mcp").exists()


def spotify_app_installed() -> bool:
    """Установлено ли приложение Spotify. Мосту оно не нужно, playback — да."""
    return bool(common.spotify_app_path())


def spotify_gap(dest: Path) -> str:
    """Чего не хватает Spotify. Файл — половина, вход — вторая половина.

    Отсутствие приложения дыркой не считаем: пакет ходит в Web API и поиск с
    плейлистом работают без него. Предупреждение о приложении даёт save_spotify.
    """
    path = settings_file(Path(dest), SPOTIFY_NAME)
    values = common.parse_kv(common.read_text(path))
    if not values.get("SPOTIFY_CLIENT_ID", "").strip():
        return (
            f"Нет файла {SPOTIFY_NAME} с непустым SPOTIFY_CLIENT_ID. «Включить» "
            "впишет команду, но лаунчер откажется."
        )
    if not spotify_login_saved():
        return (
            "Client ID записан, а входа нет: нет папки ~/.spotify-mcp. Вход делает "
            "мастер пакета (npx … init), он открывает браузер — эта программа "
            "браузер не открывает. Трек не включится, пока не войдёшь. По README "
            "пакета Premium нужен и для входа в кабинет разработчика, и для "
            "воспроизведения; подписку мост не проверяет."
        )
    if not spotify_app_installed():
        return (
            "Вход есть, но приложения Spotify на этом компьютере нет: по README "
            "пакета управлять воспроизведением можно только запущенным "
            "приложением. Поиск и плейлист через Web API работают."
        )
    return ""



#: Помощники Claude берём из лаунчера: окно настройки и мост обязаны искать
#: программу ОДИНАКОВО, иначе окно скажет «не найдена» при работающем мосте.
CLAUDE_MIN_VERSION = (2, 1, 259)


def claude_find():
    """Итог поиска CLI Claude: путь, источник и причина, если не нашлась."""
    import claude_bridge_launcher
    return claude_bridge_launcher.find_claude_detail()


def claude_version_of(exe: str):
    """Версия CLI Claude. None — не прочиталась."""
    import claude_bridge_launcher
    return claude_bridge_launcher.claude_version(exe)


def claude_compatible(version) -> bool:
    """Подходит ли версия под минимальную."""
    import claude_bridge_launcher
    return claude_bridge_launcher.compatible(version)


def claude_auth_state(exe: str) -> tuple[str, str]:
    """Проверка входа: есть / нет / не проверилось. Команда входа не идёт."""
    import claude_bridge_launcher
    return claude_bridge_launcher.auth_state(exe)


def claude_app_installed() -> bool:
    """Стоит ли само приложение Claude, даже если CLI не найдена."""
    import claude_bridge_launcher
    return common._app_installed(claude_bridge_launcher.CLAUDE_SPEC.app_paths)



# ---------------------------------------------------------------------------
# Автоустановка CLI при подключении моста. Решение человека 15.10.2026.
#
# Команды взяты из документации программ, а не придуманы здесь:
#   * Claude Code — winget-пакет из docs.claude.com (раздел установки);
#   * Cursor CLI  — команда из cursor.com/docs/cli/installation.
#
# ГЛАВНОЕ ПРАВИЛО: установка живёт здесь и вызывается только при подключении
# моста. Функции *_ready() только читают состояние и никогда ничего не ставят.
# Иначе прогон самопроверки, который зовёт эти функции, установил бы программы
# на машину — проверка изменила бы то, что проверяет.
# ---------------------------------------------------------------------------

AUTO_INSTALL = {
    "claude": {
        "label": "Claude Code",
        "argv": ["winget", "install", "-e", "--id", "Anthropic.ClaudeCode",
                 "--accept-source-agreements", "--accept-package-agreements"],
        "shown": "winget install -e --id Anthropic.ClaudeCode",
    },
    "cursor": {
        "label": "Cursor CLI",
        "argv": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", "irm 'https://cursor.com/install?win32=true' | iex"],
        "shown": "irm 'https://cursor.com/install?win32=true' | iex",
    },
}

#: Флаг для проверок и самопроверки. Пока он стоит, установка невозможна
#: ни при каких обстоятельствах: ни один автопрогон не должен ставить софт.
NO_INSTALL_ENV = "OPENCODE_NO_AUTO_INSTALL"


def auto_install_allowed() -> bool:
    """Можно ли сейчас ставить CLI. Тесты выставляют запрет через переменную."""
    return os.environ.get(NO_INSTALL_ENV, "") == ""


def install_cli(server_id: str, timeout: int = 900) -> tuple[bool, str]:
    """Ставит CLI программы. Возвращает (получилось, текст для человека).

    Повторный вызов, когда программа уже есть, ничего не делает: сначала
    проверяем наличие тем же поиском, которым мост будет её искать.
    """
    spec_def = AUTO_INSTALL.get(server_id)
    if spec_def is None:
        return False, "Для этого моста автоустановка не описана."
    if not auto_install_allowed():
        return False, (f"Установка {spec_def['label']} запрещена переменной "
                       f"{NO_INSTALL_ENV}: её выставили проверки.")

    ready = {"claude": claude_ready, "cursor": cursor_ready}[server_id]
    ok, note = ready()
    if ok:
        return False, f"{spec_def['label']} уже на месте, установка не нужна."

    print(f"[автоустановка] ставлю {spec_def['label']}: {spec_def['shown']}",
          file=sys.stderr, flush=True)
    import subprocess as _sub  # локальный импорт: нужен только здесь

    startupinfo = None
    if os.name == "nt":
        startupinfo = _sub.STARTUPINFO()
        startupinfo.dwFlags |= _sub.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = _sub.SW_HIDE
    try:
        done = _sub.run(
            spec_def["argv"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            startupinfo=startupinfo,
        )
    except subprocess.TimeoutExpired:
        return False, (f"Установка {spec_def['label']} не закончилась за "
                       f"{timeout} секунд.")
    except OSError as exc:
        return False, f"Установщик не запустился: {exc}"

    tail = ((done.stdout or "") + (done.stderr or "")).strip()[-400:]
    ok, note = ready()
    if ok:
        return True, f"{spec_def['label']} установлена. {note}"
    detail = f": {tail}" if tail else ""
    return False, (f"{spec_def['label']} не появилась после установки "
                   f"(код {done.returncode}){detail}")


def codex_login_state(exe: str) -> tuple[bool | None, str]:
    """Есть ли вход в Codex. Только чтение: `login status` ничего не пишет.

    Проверено 15.10.2026 обеими сторонами: с пустой папкой CODEX_HOME команда
    отвечает `Not logged in` и кодом 1, со своей настоящей — `Logged in using
    ChatGPT` и кодом 0. None в первом элементе — «спросить не вышло», и это
    не то же самое, что «входа нет».
    """
    code, text = common.probe_command([exe, "login", "status"], timeout=20)
    if code is None:
        return None, "команда статуса не ответила"
    if code == 0:
        return True, (text.splitlines() or ["Logged in"])[-1].strip()
    if "not logged in" in text.lower():
        return False, (text.splitlines() or ["Not logged in"])[-1].strip()
    return None, (text.splitlines() or [f"код {code}"])[-1].strip()[:200]


def codex_gap(exe: str) -> str:
    """Чего не хватает именно для ответа. Запись моста этим не блокируется."""
    logged, text = codex_login_state(exe)
    if logged is False:
        return (
            f"Команда {exe} есть, а входа нет: {text}. Войди сам — codex login. "
            "Пароль программа не спрашивает и сайт не открывает. Мост включится, "
            "но ответы Codex не придут, пока не войдёшь."
        )
    if logged is None:
        return (
            f"Команда {exe} есть, вход не подтвердился: {text}. "
            "Проверь сам: codex login status."
        )
    return ""


#: Предупреждение о безопасности — постоянное свойство, а не реакция на запрос.
CLAUDE_SAFETY = (
    "Файлы модель не правит инструментами, но абсолютной защиты от "
    "изменений нет."
)


def claude_ready() -> tuple[bool, str]:
    """Можно ли вписать мост Claude, и что человек должен сделать.

    Пять состояний, а не два: CLI нет, CLI сломана, проверка входа упала,
    входа нет и вход есть. Иначе человеку скажут «войди» там, где программа
    просто не запускается. Отсутствие входа запись не блокирует: лаунчер
    без входа стартует, а отказ приходит на первом запросе.
    """
    found = claude_find()
    exe = found.path or None
    if not exe:
        if claude_app_installed():
            return False, (
                "Приложение Claude стоит, но Claude Code CLI не найдена. "
                "Установка — на https://docs.claude.com/en/docs/claude-code/setup. "
                f"Подробности: {found.reason}"
            )
        return False, (
            "Claude Code CLI не найдена. Поставь Claude Code: "
            "https://docs.claude.com/en/docs/claude-code/setup. "
            "Сайт отсюда не открывается."
        )
    version = claude_version_of(exe)
    if version is None:
        return False, (
            f"Найдена команда {exe}, но версию прочитать не удалось. "
            "Мост не включаю: ограничения проверить нечем."
        )
    found_text = ".".join(str(x) for x in version)
    need_text = ".".join(str(x) for x in CLAUDE_MIN_VERSION)
    if not claude_compatible(version):
        return False, (
            f"Claude Code версии {found_text}, а нужно {need_text} или новее. "
            "Обнови: без этого мост не может включить ограничения, "
            f"о которых говорит. {CLAUDE_SAFETY}"
        )
    state, note = claude_auth_state(exe)
    if state == "есть":
        return True, f"Найдена команда {exe}, версия {found_text}. {note}. {CLAUDE_SAFETY}"
    if state == "нет":
        return True, (
            f"Найдена команда {exe}, версия {found_text}. {note}. "
            f"Мост включится, но ответы не придут, пока не войдёшь. {CLAUDE_SAFETY}"
        )
    return True, (
        f"Найдена команда {exe}, версия {found_text}. {note}. "
        f"Проверь сам: claude auth status. {CLAUDE_SAFETY}"
    )


def claude_gap(exe: str) -> str:
    """Что мешает, если CLI уже есть, — одной строкой."""
    if not exe:
        return "Claude Code CLI не найдена."
    state, note = claude_auth_state(exe)
    return f"{note} {CLAUDE_SAFETY}".strip()


def codex_ready() -> tuple[bool, str]:
    """Можно ли вписать мост, и что человек должен сделать.

    Отсутствие входа запись не блокирует: лаунчер без входа запускается, а
    отказ приходит на первом запросе. Поэтому пишем мост и говорим, что
    ответов не будет, пока не войдёшь.
    """
    exe = common.resolve_exe("codex")
    if not exe:
        return False, (
            "Команда codex не найдена. Её ставит winget OpenAI.Codex. "
            "Потом нужен свой вход: codex login. Пароль эта программа не спрашивает "
            "и сайт не открывает."
        )
    logged, text = codex_login_state(exe)
    tail = (
        "По умолчанию песочница только на чтение. danger-full-access не передаётся."
    )
    if logged is True:
        return True, f"Найдена команда {exe}. Вход есть: {text}. {tail}"
    if logged is False:
        return True, (
            f"Найдена команда {exe}. Входа нет: {text}. Войди сам — codex login. "
            f"Мост включится, но ответы не придут, пока не войдёшь. {tail}"
        )
    return True, (
        f"Найдена команда {exe}. Вход не проверялся: {text}. "
        f"Проверь сам: codex login status. {tail}"
    )


def cursor_ready() -> tuple[bool, str]:
    """Можно ли вписать мост, и что человек должен сделать.

    Вход проверяется тем же, что и у Codex: `agent status` только читает
    состояние. Команда и слова отказа взяты из документации Cursor CLI
    (cursor.com/docs/cli/reference/authentication, 15.10.2026): вход — это
    `agent login` с браузером или ключ CURSOR_API_KEY. Отсутствие входа
    запись не блокирует: лаунчер без входа запускается.
    """
    exe = common.resolve_exe("agent")
    if not exe:
        return False, (
            "Команда agent не найдена. Это Cursor CLI, не любой файл с таким именем. "
            "Установка описана на https://cursor.com/docs/cli/installation. "
            "Сайт отсюда не открывается."
        )
    tail = "--force не ставится, пока явно не попросят правки."
    code, text = common.probe_command([exe, "status"], timeout=20)
    if code == 0:
        who = (text.splitlines() or ["agent status ответил кодом 0"])[-1].strip()
        return True, f"Найдена команда {exe}. Вход подтверждён: {who[:120]}. {tail}"
    if code is None:
        return True, (
            f"Найдена команда {exe}. Вход не проверялся: команда status не ответила. "
            f"Проверь сам: agent status. {tail}"
        )
    reason = (text.splitlines() or [f"код {code}"])[-1].strip()[:160]
    return True, (
        f"Найдена команда {exe}. Входа нет или ключ не принят: {reason}. "
        f"Войди сам: agent login — он открывает браузер. Или запиши ключ "
        f"в {CURSOR_NAME}. {tail}"
    )


def cursor_gap(exe: str) -> str:
    """Чего не хватает именно для ответа. Запись моста этим не блокируется."""
    code, text = common.probe_command([exe, "status"], timeout=20)
    if code == 0:
        return ""
    if code is None:
        return (
            f"Команда {exe} есть, вход не подтвердился: команда status не ответила. "
            "Проверь сам: agent status."
        )
    reason = (text.splitlines() or [f"код {code}"])[-1].strip()[:160]
    return (
        f"Команда {exe} есть, а входа нет: {reason}. Войди сам — agent login, "
        f"он открывает браузер. Или запиши ключ в {CURSOR_NAME}."
    )
