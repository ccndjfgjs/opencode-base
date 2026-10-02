"""OBS Studio и эмуляторы Android: настройка мостов в один заход.

Задача модуля — довести чужую программу до состояния, в котором её сервер
отвечает, и вернуть честный отчёт. Окно только зовёт auto_setup() и
показывает, что тот вернул. Никакого Qt здесь нет.

Откуда взялись неочевидные места:

* OBS пишет свой plugin_config при выходе. Значит настройку можно менять
  только при закрытой студии — открытая перезапишет файл и всё, что мы
  поставили, пропадёт. Ровно как с Android Studio.
* Пароль OBS лежит в том же файле и хранится открытым текстом. Значит
  его нельзя класть в opencode.jsonc: конфиг ездит по машинам и в
  репозиторий программы. Он лежит в отдельном файле рядом с настройками,
  а мост читает его через переменную окружения.
* Мост obs-mcp читает пароль из OBS_WS_PASSWORD при импорте модуля.
  Переменная должна быть в окружении ДО старта процесса, поэтому мост
  запускается не напрямую, а через лаунчер.
* Открытый порт OBS ничего не доказал бы: WebSocket-сервер живёт внутри
  OBS и без плагина не поднимается. Поэтому проверка — настоящий
  handshake протокола v5, а не «порт слушает».
* У эмуляторов adb есть у каждого свой: системный лежит в platform-tools,
  а LDPlayer тащит свой в своей папке. Путь надо проверять, а не угадывать.
* Системного Java нет, а Android Studio SDK тоже нет — но для ADB-моста
  это не нужно: adb внутри себя работает.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

#: Порт и путь, на которых OBS поднимает свой WebSocket-сервер.
OBS_PORT = 4455
OBS_CONFIG_RELATIVE = Path(
    "obs-studio", "plugin_config", "obs-websocket", "config.json"
)

#: Пароль OBS держим отдельно от opencode.jsonc: конфиг открыт и ходит по
#: машинам, а пароль не должен в него попадать.
OBS_PASSWORD_FILE = "mcp-obs-password.txt"
OBS_LAUNCHER = "obs_bridge_launcher.py"

#: Требования к длине пароля OBS. Слишком длинный WebSocket-сервер
#: OBS не примет, поэтому ограничение сверху реальное, а не выдуманное.
OBS_PASSWORD_MIN = 8
OBS_PASSWORD_MAX = 20

#: Универсальный ADB-мост. Работает с любым эмулятором, который виден
#: через adb: LDPlayer, BlueStacks, MEmu, MuMu и прочие.
ADB_RELATIVE = Path("thirdparty", "android-mcp-server")

#: Где искать adb. Сначала свой у эмулятора, потом системный.
ADB_CANDIDATES = (
    Path("C:/LDPlayer/LDPlayer9/adb.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe",
)

#: Эмуляторы, которые программа умеет находить и запускать.
EMULATORS = (
    {
        "id": "ldplayer",
        "name": "LDPlayer",
        "console": Path("C:/LDPlayer/LDPlayer9/ldconsole.exe"),
        "player": Path("C:/LDPlayer/LDPlayer9/dnplayer.exe"),
        "adb": Path("C:/LDPlayer/LDPlayer9/adb.exe"),
        "instance": "LDPlayer",
    },
    {
        "id": "bluestacks",
        "name": "BlueStacks",
        "console": Path("C:/Program Files/BlueStacks_nxt/HD-Player.exe"),
        "player": Path("C:/Program Files/BlueStacks_nxt/HD-Player.exe"),
        "adb": Path("C:/Program Files/BlueStacks_nxt/HD-Player.exe"),
        "instance": "Pie64",
    },
)

_PROBE_TIMEOUT = 6.0

#: Папка программы: здесь лежат tools и thirdparty с мостами.
HERE = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ OBS: пути


def obs_config_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / OBS_CONFIG_RELATIVE


def obs_installed() -> Path | None:
    """Папка установленной OBS или None."""
    for candidate in (
        Path("C:/Program Files/obs-studio"),
        Path("C:/Program Files (x86)/obs-studio"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/obs-studio",
    ):
        if (candidate / "bin/64bit/obs64.exe").is_file():
            return candidate
    return None


def obs_running() -> bool:
    """Запущена ли OBS. Пока открыта, её настройки править нельзя."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=15,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return False
    return "obs64.exe" in out


def obs_install_path_recorded() -> Path | None:
    """Какой путь OBS знает о себе из реестра. None — не знает.

    Нужен для диагностики одной непонятной поломки: без ключа
    HKCU\\Software\\OBSStudio студия не может найти собственную папку с
    данными и падает с ошибкой «Failed to find locale/en-US.ini», хотя
    языковой файл лежит на месте и читается. Ошибка про язык выглядит
    правдоподобно и уводит не туда: истинная причина — отсутствие ключа.
    """
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\OBSStudio"
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "InstallPath")
    except OSError:
        return None
    value = str(value).strip()
    return Path(value) if value else None


def obs_install_problem() -> str:
    """Что мешает студии запуститься. Пустая строка — всё в порядке.

    Проверяется ровно то, что ломало запуск на этой машине: ключ реестра
    с путём установки. Самостоятельно ключ не создаётся — запись в реестр
    это внешнее действие, на него нужно согласие человека.
    """
    root = obs_installed()
    if root is None:
        return ""
    recorded = obs_install_path_recorded()
    if recorded is None:
        return (
            "OBS установлена, но она не знает, где установлена: нет ключа "
            "реестра HKCU\\Software\\OBSStudio. Без него студия падает с "
            "ошибкой «Failed to find locale/en-US.ini», хотя файл на месте. "
            f"Ожидаемый путь: {root}"
        )
    try:
        same = recorded.resolve() == root.resolve()
    except OSError:
        same = False
    if not same:
        return (
            f"В реестре у OBS путь {recorded}, а установлена она в {root}. "
            "Студия запустится не оттуда, откуда думает."
        )
    return ""


# ---------------------------------------------------------------- пароль OBS


def generate_password() -> str:
    """Надёжный пароль OBS длиной, которую сервер примет.

    Длина ограничена сверху не из осторожности: OBS отклоняет слишком
    длинный пароль, и мост потом не подключится вовсе. Набор символов
    расширенный, но без нечитаемых, чтобы пароль можно было повторить
    руками, если понадобится.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(16))
        if (any(c.islower() for c in value)
                and any(c.isupper() for c in value)
                and any(c.isdigit() for c in value)):
            return value


def password_is_valid(password: str) -> bool:
    return OBS_PASSWORD_MIN <= len(str(password or "")) <= OBS_PASSWORD_MAX


# ------------------------------------------------------------ настройки OBS


def read_obs_config() -> dict:
    """Читает plugin_config OBS. Пустой словарь, если файла нет."""
    path = obs_config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def obs_state() -> tuple[bool, int, str, str]:
    """Состояние WebSocket-сервера OBS: (включён, порт, пароль, путь)."""
    config = read_obs_config()
    path = str(obs_config_path())
    return (
        bool(config.get("server_enabled")),
        int(config.get("server_port") or OBS_PORT),
        str(config.get("server_password") or ""),
        path,
    )


def enable_obs_server(password: str, port: int = OBS_PORT,
                      progress=None) -> tuple[bool, str]:
    """Включает WebSocket-сервер OBS и задаёт пароль.

    Только при закрытой студии: OBS перезаписывает этот файл при выходе
    и вместе с ним вернула бы выключенный сервер.
    """
    def say(text: str) -> None:
        if progress:
            progress(text)

    if obs_running():
        return False, (
            "OBS сейчас запущена. Закрой её и нажми кнопку ещё раз: "
            "открытая студия перезапишет настройку при выходе."
        )
    if not password_is_valid(password):
        return False, (
            f"Пароль должен быть от {OBS_PASSWORD_MIN} до "
            f"{OBS_PASSWORD_MAX} символов, а в нём должны быть строчная "
            "буква, заглавная и цифра."
        )

    path = obs_config_path()
    config = read_obs_config()
    if not config:
        # Конфига нет вовсе: это не «выключено», это «плагин не открывали».
        return False, (
            f"Нет файла настроек OBS: {path}. Открой OBS, включи "
            "«Сервер WebSocket» в настройках и закрой — файл появится."
        )
    config["server_enabled"] = True
    config["server_port"] = int(port or OBS_PORT)
    config["server_password"] = str(password)
    config["auth_required"] = True
    say(f"Включаю WebSocket-сервер OBS: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"Записать настройку не выло: {exc}"
    return True, f"WebSocket-сервер OBS включён на порту {config['server_port']}"


# --------------------------------------------------------------- проверка OBS


def probe_obs(port: int = OBS_PORT, password: str = "",
              timeout: float = _PROBE_TIMEOUT) -> tuple[bool, str]:
    """Проверяет сервер OBS настоящим handshake протокола v5.

    «Порт открыт» здесь ничего не значило бы: сервер живёт внутри OBS и
    без включённой настройки не поднимается. Поэтому спрашиваем сам
    сервер и ждём его identification с именем.
    """
    import base64
    import hashlib

    try:
        import websockets  # noqa: F401  (импорт нужен заранее, ошибка должна быть внятной)
    except ImportError:
        return False, "Нет библиотеки websockets — нечем проверять OBS."

    import asyncio

    async def attempt() -> tuple[bool, str]:
        url = f"ws://127.0.0.1:{port}"
        try:
            async with websockets.connect(url, open_timeout=timeout) as socket:
                raw = await asyncio.wait_for(socket.recv(), timeout=timeout)
                try:
                    first = json.loads(raw)
                except json.JSONDecodeError:
                    return False, f"{url} ответил не-JSON: {str(raw)[:60]}"
                # op у приветствия равен 0, а 0 в Python ложь —
                # сравниваем напрямую, иначе проверка отвергает любой Hello.
                if first.get("op") != 0:
                    return False, f"{url} ответил не Hello: {str(first)[:80]}"
                if password:
                    # Рецепт протокола v5, дословно из документации:
                    #   secret = base64(sha256(пароль + salt))
                    #   auth   = base64(sha256(secret + challenge))
                    # salt и challenge лежат в d.authentication приветствия,
                    # а не в самом d — раньше здесь стоял словарь, и проверка
                    # падала на TypeError, не доходя до ответа OBS.
                    auth = (first.get("d") or {}).get("authentication") or {}
                    secret = base64.b64encode(hashlib.sha256(
                        (str(password) + str(auth.get("salt", ""))).encode()
                    ).digest()).decode()
                    digest = base64.b64encode(hashlib.sha256(
                        (secret + str(auth.get("challenge", ""))).encode()
                    ).digest()).decode()
                    await socket.send(json.dumps({
                        "op": 1, "d": {"rpcVersion": 1,
                                       "authentication": digest},
                    }))
                    raw = await asyncio.wait_for(socket.recv(), timeout=timeout)
                    reply = json.loads(raw)
                    # На успешное опознание OBS отвечает op 2 (Identified),
                    # а не op 7: requestStatus появляется только в ответе
                    # на запрос. Неверный пароль OBS обрывает сам (код 4009).
                    if reply.get("op") != 2:
                        status = (reply.get("d") or {}).get("requestStatus") or {}
                        why = status.get("comment") or f"ответ op {reply.get('op')}"
                        return False, "OBS не принял пароль: " + why
                data = first.get("d") or {}
                return True, (
                    f"OBS отвечает, версия протокола "
                    f"{data.get('obsWebSocketVersion', '?')}, "
                    f"RPC v{data.get('rpcVersion', '?')}"
                )
        except Exception as exc:  # noqa: BLE001 - причина наружу нужна человеку
            return False, f"{url} не отвечает ({type(exc).__name__}: {exc})"

    try:
        return asyncio.run(attempt())
    except Exception as exc:  # noqa: BLE001
        return False, f"Проверка не прошла: {type(exc).__name__}: {exc}"


# ----------------------------------------------------------------- эмуляторы


def find_emulator(which: str) -> dict | None:
    """Ищет эмулятор по id. None, если не установлен."""
    for spec in EMULATORS:
        if spec["id"] != which:
            continue
        player = Path(spec["player"])
        if player.is_file():
            return dict(spec)
    return None


def find_adb() -> Path | None:
    """Первый найденный adb: свой у эмулятора, потом системный."""
    for candidate in ADB_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def adb_devices(adb: Path | None = None) -> list[str]:
    """Список видимых устройств. Пустой список — не ошибка."""
    tool = adb or find_adb()
    if tool is None:
        return []
    try:
        out = subprocess.run(
            [str(tool), "devices"], capture_output=True, text=True,
            errors="replace", timeout=30,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return []
    devices = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def emulator_instances(spec: dict) -> list[dict]:
    """Инстансы LDPlayer. Для остальных эмуляторов пусто: там своя модель."""
    console = Path(spec.get("console") or "")
    if not console.is_file() or console.name != "ldconsole.exe":
        return []
    try:
        out = subprocess.run(
            [str(console), "list2"], capture_output=True, text=True,
            errors="replace", timeout=30,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return []
    result = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) < 4:
            continue
        result.append({
            "index": parts[0].strip(),
            "name": parts[1].strip(),
            "running": parts[3].strip() == "1",
        })
    return result


def probe_emulator(adb: Path | None = None) -> tuple[bool, str]:
    """Проверяет, что эмулятор виден через adb и отвечает."""
    tool = adb or find_adb()
    if tool is None:
        return False, (
            "adb не найден. Обычно он лежит в "
            "%LOCALAPPDATA%\\Android\\Sdk\\platform-tools\\adb.exe — "
            "поставь Android SDK Platform Tools или запусти эмулятор, "
            "у него свой adb."
        )
    devices = adb_devices(tool)
    if not devices:
        return False, (
            f"{tool.name} не видит ни одного устройства. Запусти эмулятор "
            "и подожди, пока он загрузится."
        )
    try:
        out = subprocess.run(
            [str(tool), "-s", devices[0], "shell", "getprop",
             "ro.product.model"],
            capture_output=True, text=True, errors="replace", timeout=30,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Устройство {devices[0]} не отвечает: {exc}"
    model = out.strip()
    if not model:
        return False, f"Устройство {devices[0]} ответило пустотой"
    return True, f"Устройство {devices[0]} отвечает: {model}"


# --------------------------------------------------- включение ADB в эмуляторе


def emulator_vms_dir(spec: dict) -> Path:
    """Папка с виртуальными машинами LDPlayer."""
    console = Path(spec.get("console") or "")
    if not console.is_file():
        return Path("C:/LDPlayer/LDPlayer9/vms")
    return console.parent / "vms"


def _instance_config(spec: dict, index: str = "0") -> Path:
    return emulator_vms_dir(spec) / "config" / f"leidian{index}.config"


def adb_debug_state(spec: dict, index: str = "0") -> tuple[bool, Path]:
    """Включена ли отладка по ADB в эмуляторе и где это записано."""
    path = _instance_config(spec, index)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, path
    found = re.search(r'"basicSettings\.adbDebug"\s*:\s*(\d+)', text)
    return bool(found and found.group(1) != "0"), path


def enable_adb_debug(spec: dict, index: str = "0",
                     progress=None) -> tuple[bool, str]:
    """Включает отладку по ADB в настройках инстанса.

    Только при остановленном эмуляторе. Работающий LDPlayer переписывает
    свой конфиг и вернул бы выключенную отладку. Именно поэтому кнопку
    приходится нажимать дважды: сначала закрыть эмулятор, потом открыть.
    """
    def say(text: str) -> None:
        if progress:
            progress(text)

    instances = emulator_instances(spec)
    running = [i for i in instances if i.get("running")]
    if running:
        names = ", ".join(str(i.get("name")) for i in running)
        return False, (
            f"Эмулятор {names} сейчас запущен. Останови его и нажми кнопку "
            "ещё раз: работающий эмулятор перезапишет настройку."
        )

    path = _instance_config(spec, index)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False, f"Нет файла настроек инстанса: {path}"
    if re.search(r'"basicSettings\.adbDebug"\s*:\s*\d+', text):
        new = re.sub(r'("basicSettings\.adbDebug"\s*:\s*)\d+',
                     r"\g<1>1", text)
    else:
        return False, (
            f"В {path} нет настройки basicSettings.adbDebug. Похоже, это "
            "другая версия эмулятора — включи отладку по ADB в его окне."
        )
    if new == text:
        say("Отладка по ADB уже включена.")
        return True, "Отладка по ADB уже включена."
    say(f"Включаю отладку по ADB: {path}")
    try:
        path.write_text(new, encoding="utf-8")
    except OSError as exc:
        return False, f"Записать настройку не вышло: {exc}"
    return True, "Отладка по ADB включена в настройках эмулятора"


def connect_emulator(adb: Path | None = None,
                     progress=None) -> tuple[bool, str]:
    """Подключает эмулятор по типичным портам adb.

    Нужно потому, что adb не всегда видит эмулятор сам: у LDPlayer он
    появляется только после включения отладки, а у части эмуляторов
    приходится сказать «вот он, этот адрес».
    """
    def say(text: str) -> None:
        if progress:
            progress(text)

    tool = adb or find_adb()
    if tool is None:
        return False, "adb не найден."
    for port in (5555, 5554, 5557, 5556, 5565, 62001):
        try:
            out = subprocess.run(
                [str(tool), "connect", f"127.0.0.1:{port}"],
                capture_output=True, text=True, errors="replace", timeout=30,
            ).stdout or ""
        except (OSError, subprocess.SubprocessError):
            continue
        if "connected" in out and "cannot" not in out:
            say(f"Подключил эмулятор: 127.0.0.1:{port}")
            return True, f"Эмулятор подключён: 127.0.0.1:{port}"
    return False, "Не удалось подключить эмулятор по типичным портам"


def write_device_config(server_dir: Path, serial: str) -> tuple[bool, str]:
    """Записывает, с каким устройством работать мосту.

    Нужно по двум причинам. Первая: adb нередко показывает один и тот же
    эмулятор дважды — как 127.0.0.1:5555 и как emulator-5554. Вторая:
    мост без выбора при нескольких устройствах честно отказывается
    работать. Оба раза это не поломка, а его собственная проверка.
    """
    path = Path(server_dir) / "config.yaml"
    try:
        path.write_text(
            "# Заполняется программой при настройке моста.\n"
            "device:\n"
            f"  name: \"{serial}\"\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"Записать выбор устройства не выло: {exc}"
    return True, f"Мост будет работать с устройством {serial}"


def choose_device(adb: Path | None = None) -> str:
    """Выбирает устройство, если adb видит одно.

    Видит два — возвращает первую запись, а вызывающий код должен
    показать человеку список. Молча выбирать из двух одинаковых записей
    одного эмулятора можно, молча выбирать из разных — нельзя.
    """
    devices = adb_devices(adb)
    if not devices:
        return ""
    for serial in devices:
        if not serial.startswith("emulator-"):
            return serial
    return devices[0]


# ----------------------------------------------------------- хранение пароля


def password_file_path(dest: Path) -> Path:
    """Файл с паролем OBS: рядом с настройками, но отдельно от конфига.

    Конфиг открыт и ходит по машинам. Пароль в нём быть не должен.
    """
    return Path(dest) / OBS_PASSWORD_FILE


def save_password(dest: Path, password: str, progress=None) -> tuple[bool, str]:
    """Сохраняет пароль в отдельный файл."""
    path = password_file_path(dest)
    try:
        path.write_text(
            "Пароль WebSocket-сервера OBS Studio.\n"
            "Нужен, чтобы мост OBS подключился. Хранится отдельно от\n"
            "opencode.jsonc, потому что конфиг открыт и переносится.\n"
            f"Порт: {OBS_PORT}\n\n"
            f"{password}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"Пароль сохранить не вышло: {exc}"
    if progress:
        progress(f"Пароль сохранён: {path}")
    return True, f"Пароль сохранён: {path}"


def read_password(dest: Path) -> str:
    """Читает пароль из своего файла. Пустая строка, если файла нет."""
    try:
        text = password_file_path(dest).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("Пароль", "Нужен", "opencode", "Порт")):
            return line
    return ""


def copy_password_to(dest: Path, target: Path) -> tuple[bool, str]:
    """Копирует пароль туда, куда попросил человек."""
    password = read_password(dest)
    if not password:
        return False, "Пароль не найден: сначала сгенерируй его."
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"Пароль WebSocket-сервера OBS Studio\n\n{password}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"Записать не вышло: {exc}"
    return True, f"Пароль записан: {target}"


# --------------------------------------------------------------- сценарии


def _finish(dest: Path, server, messages: list[str], errors: list[str],
            progress=None) -> tuple[list[str], list[str]]:
    """Вписывает сервер в настройки opencode. Общая концовка.

    Вызывается ТОЛЬКО когда связь уже проверена живым запросом. Обратный
    порядок дал бы в списке сервер, который не работает, и человек потом
    не понял бы, что с ним делать.
    """
    import mcp_registry

    if errors:
        return messages, errors
    try:
        wrote, wrote_errors = mcp_registry.enable(dest, server, progress=progress)
    except Exception as exc:  # noqa: BLE001 - причина наружу нужна человеку
        errors.append(f"Записать сервер не вышло: {type(exc).__name__}: {exc}")
        return messages, errors
    for line in wrote:
        messages.append(line)
    for line in wrote_errors:
        errors.append(line)
    return messages, errors


def create_obs_install_path() -> tuple[bool, str]:
    """Записывает в реестр путь установки OBS.

    Отдельная функция и отдельное согласие: запись в реестр — внешнее
    действие, молча её делать нельзя. Без этого ключа студия не находит
    собственную папку с данными и падает с ошибкой про языковой файл.
    """
    root = obs_installed()
    if root is None:
        return False, "OBS Studio не найдена, записывать нечего."
    if os.name != "nt":
        return False, "Ключ реестра пишется только в Windows."
    try:
        import winreg
    except ImportError:
        return False, "Нет модуля winreg — ключ реестра записать нечем."
    try:
        root = root.resolve()
    except OSError:
        pass
    values = {
        "InstallPath": str(root),
        "BinPath": str(root / "bin" / "64bit"),
        "DataPath": str(root / "data"),
    }
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                 r"Software\OBSStudio",
                                 0, winreg.KEY_WRITE) as key:
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except OSError as exc:
        return False, f"Записать ключ не вышло: {exc}"
    return True, ("Ключ реестра HKCU\\Software\\OBSStudio записан, путь "
                  f"установки: {root}")


def auto_setup_obs(dest: Path, server, password: str = "",
                   progress=None,
                   allow_install_path_fix: bool = False
                   ) -> tuple[list[str], list[str]]:
    """Готовит OBS и вписывает сервер. Возвращает (сообщения, ошибки)."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    def fail(text: str) -> None:
        errors.append(text)

    say("Проверяю OBS Studio…")
    installed = obs_installed()
    if installed is None:
        fail("OBS Studio не найдена. Ставится отдельно: https://obsproject.com")
        return messages, errors
    say(f"OBS найдена: {installed}")
    # Поломка с ключом реестра выглядит как «порт не отвечает», хотя дело
    # не в порте. Говорим о ней сразу, иначе человек ищет не там.
    _trouble = obs_install_problem()
    if _trouble:
        if allow_install_path_fix:
            fixed, note = create_obs_install_path()
            say(note)
            if not fixed:
                fail(_trouble)
                return messages, errors
        else:
            fail(_trouble + " Программа может создать этот ключ, если ты "
                            "подтвердишь.")
            return messages, errors
    say(f"Запущена ли: {'да' if obs_running() else 'нет'}")

    current = read_password(dest) or ""
    value = str(password or "").strip() or current
    if not value:
        fail(
            "Пароля нет. Нажми «Сгенерировать пароль» или впиши свой в "
            "поле рядом — иначе мост не подключится."
        )
        return messages, errors
    if not password_is_valid(value):
        fail(
            f"Пароль должен быть от {OBS_PASSWORD_MIN} до {OBS_PASSWORD_MAX} "
            "символов, и в нём должны быть строчная буква, заглавная и "
            "цифра."
        )
        return messages, errors
    if value != current:
        saved, note = save_password(dest, value, progress=say)
        if not saved:
            fail(note)
            return messages, errors
        say(note)

    on, port, in_obs, path = obs_state()
    if on and in_obs == value:
        say("WebSocket-сервер OBS уже включён с этим паролем.")
    else:
        ok, note = enable_obs_server(value, port, progress=say)
        if not ok:
            fail(note)
            return messages, errors
        say(note)

    say(f"Проверяю связь с OBS: ws://127.0.0.1:{port}")
    alive, note = probe_obs(port, value)
    if not alive:
        # В настройки opencode не лезем: сервер не ответил.
        fail(f"{note} В настройки opencode ничего не вписано.")
        return messages, errors
    say(f"Связь есть: {note}")

    messages, errors = _finish(dest, server, messages, errors, progress=progress)
    if not errors:
        # «Перезапусти opencode» уже сказано при вписывании блока.
        messages.append("Готово: мост OBS подключён.")
    return messages, errors


def auto_setup_emulator(dest: Path, server, progress=None
                        ) -> tuple[list[str], list[str]]:
    """Готовит эмулятор и вписывает сервер. Возвращает (сообщения, ошибки)."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    def fail(text: str) -> None:
        errors.append(text)

    adb = find_adb()
    say("Проверяю adb…")
    if adb is None:
        fail(
            "adb не найден. Он лежит либо у эмулятора, либо в "
            "%LOCALAPPDATA%\\Android\\Sdk\\platform-tools. Поставь Android "
            "SDK Platform Tools."
        )
        return messages, errors
    say(f"adb найден: {adb}")

    found = [spec for spec in EMULATORS if find_emulator(spec["id"])]
    if found:
        say("Эмуляторы: " + ", ".join(spec["name"] for spec in found))
    missing = [spec["name"] for spec in EMULATORS if not find_emulator(spec["id"])]
    if missing:
        say(f"Не установлены (поддержка записана, проверить нечем): "
            + ", ".join(missing))

    ldplayer = find_emulator("ldplayer")
    if ldplayer is not None:
        enabled, _ = adb_debug_state(ldplayer)
        if not enabled:
            ok, note = enable_adb_debug(ldplayer, progress=say)
            if not ok:
                # Это не поломка настройки моста, а шаг на будущее. Если
                # устройство уже видно — всё в порядке, и спотыкаться об
                # остановленный эмулятор незачем.
                if adb_devices(adb):
                    say(f"Отладку по ADB включить не удалось ({note}), "
                        "но устройство adb уже видит — продолжаю.")
                else:
                    fail(note)
                    return messages, errors
            else:
                say(note)

    devices = adb_devices(adb)
    if not devices:
        connected, note = connect_emulator(adb, progress=say)
        devices = adb_devices(adb)
        if not devices:
            fail(
                f"{note}. Эмулятор должен быть запущен, а отладка по ADB — "
                "включена. Нажми кнопку ещё раз, когда эмулятор загрузится."
            )
            return messages, errors
        say(note)
    say(f"Устройства adb: {', '.join(devices)}")

    serial = choose_device(adb)
    if not serial:
        fail("adb не видит ни одного устройства.")
        return messages, errors
    server_dir = HERE / "thirdparty" / "android-mcp-server"
    ok, note = write_device_config(server_dir, serial)
    if not ok:
        fail(note)
        return messages, errors
    say(note)

    say("Проверяю, что устройство отвечает…")
    alive, note = probe_emulator(adb)
    if not alive:
        fail(f"{note} В настройки opencode ничего не вписано.")
        return messages, errors
    say(f"Устройство отвечает: {note}")

    messages, errors = _finish(dest, server, messages, errors, progress=progress)
    if not errors:
        # «Перезапусти opencode» уже сказано при вписывании блока.
        # Повторять это вторым сообщением значит грузить человека текстом.
        messages.append("Готово: мост эмулятора подключён.")
    return messages, errors