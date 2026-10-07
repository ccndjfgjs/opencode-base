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
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
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


def _bridge_anywhere(plugins_root: Path) -> bool:
    """Есть ли библиотека вебсокета, если дана папка плагинов OBS.

    `plugins_root` — это `.../data/obs-plugins`. Настоящая установка
    OBS 32 кладёт библиотеку в `obs-plugins/64bit/` от корня программы,
    то есть на два уровня выше. Отдельный плагин 5.x лежит в
    `data/obs-plugins/obs-websocket/bin/64bit/`, то есть на уровень ниже.
    Проверяются оба места: раньше проверялось только второе, и на машине с
    полностью установленным OBS ответ был «библиотеки нет ни в одной
    папке». Считать корнем программы можно только когда структура
    знакомая — на искусственном дереве проверок её нет, и тогда остаётся
    проверка отданного пути, как и была.
    """
    root = Path(plugins_root)
    if root.name == "obs-plugins" and root.parent.name == "data":
        if plugin_library(root.parent.parent) is not None:
            return True
    return (root / WANTED_DIR / Path(*PLUGIN_DLL)).is_file()


def obs_plugin_scan(root: Path) -> dict:
    """Считает плагины в папке плагинов OBS.

    Отдельная функция с параметром-папкой не для красоты: настоящая папка
    в Program Files закрыта для записи, и сломанный счётчик на ней не
    отличить от рабочего — он всё равно вернёт те же числа. Искусственное
    дерево проходит по тем же строкам кода, поэтому поломку видно.

    Возвращает:
        dirs     сколько папок создал установщик
        plugins  сколько из них настоящие плагины
        helpers  сколько содержат только вспомогательные модули
        bridge   есть ли библиотека вебсокета

    Почему плагин — это bin/64bit, а не любая .dll. Захват экрана и
    виртуальная камера кладут свои модули прямо в папку плагина:
    `win-capture/graphics-hook64.dll`, `win-dshow/obs-virtualcam-module64.dll`.
    Это не плагины OBS. Первая версия проверки считала их плагинами и
    выдавала «из 25 плагинов с библиотекой 2» при OBS без единого
    плагина — враньё в сторону «всё почти работает».
    """
    root = Path(root)
    if not root.is_dir():
        return {"dirs": 0, "plugins": 0, "helpers": 0, "bridge": False}
    dirs = [d for d in root.iterdir() if d.is_dir()]
    plugins = [d for d in dirs if any((d / "bin" / "64bit").glob("*.dll"))]
    helpers = [d for d in dirs if d not in plugins
               and any(f.suffix.lower() == ".dll" for f in d.rglob("*.dll"))]
    return {"dirs": len(dirs), "plugins": len(plugins),
            "helpers": len(helpers),
            # Библиотеку ищем от корня OBS, а не от папки плагинов: при
            # установке через установщик она лежит в `obs-plugins/64bit/`,
            # и от папки плагинов этот путь не виден вовсе. Корневая папка
            # вычисляется по имени — на искусственном дереве проверок её
            # нет, и тогда остаётся только вторая раскладка, как раньше.
            "bridge": _bridge_anywhere(root)}


def obs_install_completeness(base=None, root=None) -> dict:
    """Что на самом деле с установкой OBS. Возвращает честный статус.

    Ключи:
        installed     OBS найдена
        dirs          сколько папок плагинов создал установщик
        with_dll      сколько из них настоящие плагины с библиотекой
        helpers       сколько содержат только вспомогательные модули
        complete      плагины на месте и вебсокет есть
        bridge_ready  есть ли библиотека, без которой не поднимется мост
        can_write     можно ли докачать плагин прямо в папку; None —
                      папка подставлена снаружи, проба не делалась
        message       человекочитаемый вывод
        user_action   что человеку делать, если не готово

    Про base и root. Их можно подставить: настоящая папка закрыта для
    записи, и поломку этой проверки на ней не увидеть. Свои пути нужны,
    чтобы проверить саму проверку.
    """
    own = base is None and root is None
    if base is None:
        base = obs_installed()
    out = {"installed": base is not None, "dirs": 0, "with_dll": 0,
           "helpers": 0, "complete": False, "bridge_ready": False,
           "can_write": None, "message": "", "user_action": ""}
    if base is None and root is None:
        out["message"] = "OBS не установлена"
        out["user_action"] = "Установите OBS Studio, потом мост"
        return out

    if root is None:
        root = Path(base) / "data" / "obs-plugins"
    if not Path(root).is_dir():
        out["message"] = "OBS установлена, но папки плагинов нет"
        out["user_action"] = ("Переустановите OBS с полным набором "
                              "компонентов")
        return out

    scan = obs_plugin_scan(root)
    out["dirs"] = scan["dirs"]
    out["with_dll"] = scan["plugins"]
    out["helpers"] = scan["helpers"]
    out["bridge_ready"] = scan["bridge"]
    if own:
        # Проба записи делается только на своей машине: подставленная
        # папка трогать нельзя, а «можно ли тут писать» к ней не имеет
        # отношения.
        out["can_write"] = can_write_here(Path(base))[0]

    if out["bridge_ready"] and out["with_dll"]:
        out["complete"] = True
        out["message"] = (f"установка полная: плагинов с библиотекой "
                          f"{out['with_dll']} из {out['dirs']}")
        return out

    if out["with_dll"] == 0:
        out["message"] = (f"OBS запустится, но плагинов нет: папок "
                          f"{out['dirs']}, библиотеки нет ни в одной")
    else:
        out["message"] = (f"часть плагинов на месте: {out['with_dll']} "
                          f"из {out['dirs']}")
    if out["helpers"]:
        out["message"] += f", из них вспомогательных модулей {out['helpers']}"
    if out["with_dll"] == 0:
        out["message"] += (". Не работает ни запись экрана, ни "
                           "браузерный источник, ни вебсокет")
    out["message"] += (". Мост поднимется" if out["bridge_ready"]
                       else ". Мост не поднимется")

    if out["bridge_ready"]:
        return out
    if out["can_write"] is True:
        out["user_action"] = ("Докачайте плагин obs-websocket — без него "
                              "мост не поднимется")
    elif out["can_write"] is False:
        out["user_action"] = ("Докачать не выйдет: папка плагинов "
                              "принадлежит установщику Windows, запись "
                              "запрещена даже с повышенными правами. "
                              "Переустановите OBS с полным набором "
                              "компонентов.")
    return out


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


# ------------------------------------------------------- докачка плагина OBS
#
# Мост OBS говорит с программой через вебсокет, а его даёт плагин
# obs-websocket. Проверено 06.10.2026: OBS 32.2.2 стоит, папок
# плагинов двадцать пять, а библиотеки нет ни в одной — студия
# из-за этого не грузит локаль и не поднимает вебсокет. Чинить
# вручную нечем: obs-websocket.dll нет нигде на машине.

#: Официальный адрес релиза. Собирается из версии, чтобы нельзя было
#: увести загрузку на чужой домен.
RELEASE_URL = ("https://github.com/obsproject/obs-studio/releases/download/"
               "{version}/OBS-Studio-{version}-Windows-x64.zip")

#: Что именно нужно вытащить из архива. Остальное не трогаем: лишние
#: плагины OBS не требуются, а распаковывать всё — значит менять
#: установленную программу целиком.
WANTED_DIR = "obs-websocket"

#: На что смотрим, чтобы сказать «плагин стоит», а не «папка на месте».
#: Это раскладка ОТДЕЛЬНОГО плагина obs-websocket 5.x — туда и
#: `install_plugin_from_zip` кладёт скачанное, и OBS такую раскладку грузит.
PLUGIN_DLL = ("bin", "64bit", "obs-websocket.dll")

#: А вот куда кладёт библиотеку САМ установщик OBS. Измерено на живой
#: OBS 32.2.2 07.10: `C:\Program Files\obs-studio\obs-plugins\64bit\
#: obs-websocket.dll` существует, OBS её грузит, а плагин в перечне папок
#: установщика стоит как `obs-websocket` — просто с языками.
#:
#: Почему это было поломкой, а не мелочью. Проверка смотрела только на
#: `PLUGIN_DLL` и потому **не могла сойтись ни при какой установке**:
#: на машине с OBS и плагином она рапортовала «в папке плагинов папок, а
#: библиотеки нет ни в одной», отказывалась докачивать и называла
#: причиной установщик Windows. На деле всё было на месте. Из этого
#: выросли и запрет докачивать, и несрабатывавшая §15.1.
BUNDLED_DLL = ("obs-plugins", "64bit", "obs-websocket.dll")

#: Та же библиотека, но положенная отдельным плагином. Путь считается от
#: корня программы, а не от папки плагина: `PLUGIN_DLL` сам по себе
#: задаёт только хвост `bin/64bit/…`, и склеенный с корнем OBS он
#: указывал на `OBS/bin/64bit/`, где лежит всё подряд и ничего похожего.
STANDALONE_DLL = ("data", "obs-plugins", WANTED_DIR) + PLUGIN_DLL

# Только ASCII: заголовки HTTP кодируются в latin-1, и кириллица в
# User-Agent обрывает попытку ещё до отправки. Первая версия писала здесь
# по-русски — и падала на ровном месте, не дойдя до сети.
UA = "opencode-base/1.0 (obs plugin fetch)"

#: Ограничение: официальный архив около 180 МБ, но качать вообще всё
#: нельзя — иначе это уже не докачка плагина, а скачивание программы.
MAX_BYTES = 400 * 1024 * 1024


def plugin_dir(obs_path: Path) -> Path:
    return Path(obs_path) / "data" / "obs-plugins" / WANTED_DIR


def plugin_library(obs_path: Path) -> Path | None:
    """Где лежит библиотека вебсокета. None — нигде.

    Проверяются обе раскладки, потому что обе настоящие: установщик OBS
    кладёт плагин в `obs-plugins/64bit/`, а отдельный плагин 5.x — в
    `data/obs-plugins/obs-websocket/bin/64bit/`. На какой машине какая,
    неизвестно, и одна проверка на обеих машинах врала в одну сторону.
    """
    base = Path(obs_path)
    for layout in (BUNDLED_DLL, STANDALONE_DLL):
        candidate = base.joinpath(*layout)
        if candidate.is_file():
            return candidate
    return None


def plugin_installed_in(root: Path) -> bool:
    """Есть ли библиотека вебсокета. `root` — корень программы OBS."""
    return plugin_library(Path(root)) is not None


def plugin_present(obs_path: Path) -> bool:
    """Стоит ли плагин. Проверяется библиотека, а не папка: папка
    создаётся установщиком даже тогда, когда библиотеки нет."""
    return plugin_library(obs_path) is not None


def _obs_version() -> str:
    """Версия OBS из установки: она нужна для адреса архива.

    Берётся из имени папки плагинов, где лежит версия: `obs-websocket.dll`
    живёт рядом с текстовым файлом версии. Если версию узнать не удалось,
    качать нельзя — подставлять «последнюю» значит скачать не то.
    """
    for folder in (Path("C:/Program Files/obs-studio"),
                   Path("C:/Program Files (x86)/obs-studio")):
        ini = folder / "data" / "obs-studio" / "version.ini"
        if ini.is_file():
            for line in ini.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
                if line.lower().startswith("version_info"):
                    return line.split("=", 1)[1].strip()
        dll = folder / "bin" / "64bit" / "obs64.exe"
        if dll.is_file():
            # Запасной путь: версию сообщит сам файл.
            return _version_from_binary(dll)
    return ""


def _version_from_binary(exe: Path) -> str:
    """Читает версию из числового ресурса файла.

    Ресурс хранит четыре числа: `MS` — старшие два (старшая, младшая),
    `LS` — младшие два (сборка, патч). Измерено 06.10.2026 на obs64.exe:
    MS = 0x00200002, LS = 0x00020000, то есть 32.2.2 — патч нулевой, а
    пара dec ─�� разбор берёт патч вместо сборки и выдаёт 32.2.0. Поэтому
    сборка — это `LS >> 16`, а не `LS & 0xFFFF`.

    Строковое поле «32.2.2» надёжнее, но `pywin32` на этой машине его не
    отдаёт: `VarFileInfo` пуст. Поэтому берём числовой ресурс и разбираем
    его правильно, а не подгоняем под ожидаемое число.
    """
    try:
        import win32api  # type: ignore
    except ImportError:
        return ""
    try:
        info = win32api.GetFileVersionInfo(str(exe), "\\")
        ms = info["FileVersionMS"]
        ls = info["FileVersionLS"]
        return "%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16)
    except Exception:
        return ""


def can_write_here(obs_path: Path) -> tuple[bool, str]:
    """Можно ли писать в папку плагинов. Проверяется настоящей записью.

    Зачем пробовать запись, а не смотреть права. Разрешения на папку и
    фактическая возможность записи — разные вещи: права могут быть
    выданы, а политика безопасности запрет, или наоборот. Надёжна
    только попытка.

    Зачем это до скачивания. Первая версия качала архив на 179 МБ и
    только потом упиралась в запрет — время и место потрачены впустую.
    Проверка права стоит миллисекунды и честно отвечает заранее.
    """
    probe_dir = plugin_dir(obs_path)
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return False, ("в папку плагинов не записать: она принадлежит "
                       "установщику Windows, и повышение прав не помогает. "
                       "Такую установку лечит переустановка OBS.")
    except OSError as exc:
        return False, f"в папку плагинов не записать: {exc}"
    probe = probe_dir / ".проба-записи"
    try:
        probe.write_bytes(b"")
        return True, ""
    except PermissionError:
        return False, ("файл в папке плагинов создать нельзя: папка "
                       "принадлежит установщику Windows, повышение прав "
                       "не помогает. Нужна переустановка OBS.")
    except OSError as exc:
        return False, f"в папке плагинов не записать: {exc}"
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            # Проба не удалилась — это само по себе неприятно, но не
            # повод выдавать запись за успешную.
            pass


def install_plugin_from_zip(archive: Path,
                            obs_path: Path) -> tuple[bool, str]:
    """Кладёт плагин из уже скачанного архива.

    Отдельная функция не для порядка в коде: сетевую часть не проверить
    без 179 МБ и без сети, а разбор архива — можно, на маленьком файле,
    собранном руками. На настоящем архиве проверять нечего: он меняется
    с каждой версией OBS, и любое измерение устареет к следующему
    релизу.

    Раскладка измерена на архиве OBS 32.2.2:
        obs-plugins/64bit/obs-websocket.dll        библиотека
        data/obs-plugins/obs-websocket/locale/*.ini языки
    Первый вариант искал библиотеку по `obs-plugins/<имя>/bin/64bit/` —
    такого пути в архиве нет: там лежали только языки, докачка раскладывала
    57 файлов и рапортовала об успехе.
    """
    lib_entry = f"obs-plugins/64bit/{WANTED_DIR}.dll"
    loc_prefix = f"data/obs-plugins/{WANTED_DIR}/locale/"
    dest = plugin_dir(obs_path)
    files = 0

    try:
        with zipfile.ZipFile(archive) as zf:
            names = [i.filename.replace("\\", "/") for i in zf.infolist()]
            # Библиотеку ищем ДО того, как что-то пишем. Записи идут по
            # алфавиту, `data/...` читается раньше `obs-plugins/...`, и за
            # один проход функция успевала разложить 57 языковых файлов и
            # только потом сказать, что библиотеки нет. Правило: пока
            # нужного файла в архиве нет, на диск не пишем ничего.
            # Проверка идёт по каталогу архива и ничего не распаковывает.
            if lib_entry not in names:
                return False, (f"в архиве нет библиотеки {lib_entry} — "
                               f"плагин собран иначе, ставьте его из "
                               f"установщика OBS с полным набором "
                               f"компонентов")
            for name in names:
                # Запись с косой чертой на конце — каталог, а не файл. Без
                # этой проверки на месте папки появляется файл-заглушка,
                # и следующая папка уже не создаётся: так и вышло с
                # `locale`, он оказался файлом в 0 байт.
                if name.endswith("/"):
                    continue
                if name == lib_entry:
                    target = dest / Path(*PLUGIN_DLL)
                elif name.startswith(loc_prefix):
                    target = dest / "locale" / name[len(loc_prefix):]
                else:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
                files += 1
    except zipfile.BadZipFile as exc:
        return False, f"скачалось не архив: {exc}"
    except OSError as exc:
        return False, f"не получилось разложить архив: {exc}"

    langs = files - 1
    return True, (f"плагин {WANTED_DIR} поставлен"
                  + (f", языков {langs}" if langs > 0 else ""))


def obs_plugin_state() -> tuple[bool, bool, str]:
    """Что с плагином OBS: стоит ли, можно ли докачать, что сказать.

    Три ответа, а не один, потому что человек должен получить все три ДО
    нажатия на кнопку: стоит ли уже, можно ли поставить, а если нельзя —
    почему. Кнопка без причины хуже отсутствующей кнопки: человек жмёт
    её второй раз и злится на программу, хотя поломка в чужой
    установке.

    Порядок проверки: сначала стоит ли, потом можно ли. Иначе на машине
    без OBS пришлось бы рассуждать о праве на запись в папку, которой
    ещё нет.
    """
    base = obs_installed()
    if base is None:
        return False, False, "OBS не установлена — плагин ставить некуда"
    if plugin_present(base):
        return True, False, "плагин obs-websocket на месте"

    full = obs_install_completeness()
    can_write = bool(full["can_write"])
    if full["with_dll"] == 0 and full["dirs"]:
        why = (f"в папке плагинов {full['dirs']} папок, а библиотеки нет "
               f"ни в одной: OBS стоит без плагинов, и мост не поднимется")
    else:
        why = "плагин obs-websocket не найден"
    if can_write:
        return False, True, why + ". Докачать можно"
    return False, False, (why + ". Докачать нельзя: папка плагинов "
                          "принадлежит установщику Windows, повышение прав "
                          "не помогает — нужна переустановка OBS с полным "
                          "набором компонентов")


def fetch_plugin(obs_path: Path, progress=None) -> tuple[bool, str]:
    """Качает и ставит плагин. Возвращает (получилось ли, сообщение)."""

    def say(text: str) -> None:
        if progress:
            progress(text)

    if plugin_present(obs_path):
        return True, "плагин уже стоит"

    version = _obs_version()
    if not version:
        return False, ("версию OBS узнать не удалось: качать нечего. "
                       "Плагин ставят вручную — из установщика OBS с "
                       "полным набором компонентов.")

    # Права проверяются ДО скачивания: сначала спросить, можно ли
    # положить файл, и только потом тратить 179 МБ. Первая версия делала
    # наоборот — качала, упиралась в запрет и отдавала это как ошибку
    # сети, хотя сеть была ни при чём.
    can_write, why = can_write_here(obs_path)
    if not can_write:
        return False, why

    url = RELEASE_URL.format(version=version)
    say(f"качаю официальный архив OBS {version}, это большой файл")

    tmp = Path(tempfile.mkdtemp(prefix="obs-plugin-"))
    archive = tmp / f"OBS-Studio-{version}-Windows-x64.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp, \
                archive.open("wb") as fh:
            got = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_BYTES:
                    return False, ("архив больше ожидаемого — загрузка "
                                   "остановлена, чтобы не съесть место")
                fh.write(chunk)
        ok, msg = install_plugin_from_zip(archive, obs_path)
        if not ok:
            return False, msg
    except urllib.error.HTTPError as exc:
        return False, f"сервер ответил {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, f"сеть не ответила: {exc.reason}"
    except zipfile.BadZipFile as exc:
        return False, f"скачалось не то: {exc}"
    except OSError as exc:
        # Сюда попадает и UnicodeEncodeError: адрес или заголовок с
        # нелатинскими символами. Отдельный except не нужен — причина
        # одна: обмен с сетью не состоялся.
        return False, f"не получилось: {exc}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not plugin_present(obs_path):
        return False, ("файл разложили, но библиотеки на месте нет — "
                       "в архиве она лежит не там, где ищет OBS")
    return True, f"плагин {WANTED_DIR} поставлен"


def ensure_plugin(obs_path: Path, progress=None) -> tuple[bool, str]:
    """Проверяет и при необходимости докачивает."""
    try:
        base = Path(obs_path)
    except TypeError:
        return False, "путь к OBS не передан"
    if not base.is_dir():
        return False, (f"OBS не установлена: {base} нет. Докачивать плагин "
                       f"некуда — ставьте OBS, потом плагин.")
    if plugin_present(base):
        return True, "плагин уже стоит"
    return fetch_plugin(base, progress=progress)


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