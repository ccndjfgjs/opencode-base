# -*- coding: utf-8 -*-
r"""Версии мостов: что стоит, что вышло у автора, что можно обновить.

**Что это.** Единый слой для вкладки «Обновление»: по таблице
`данные/bridge-versions.json` спрашивает у издателя пакета последнюю
версию и сравнивает с той, что стоит. Ничего не меняет — только
показывает; установка — отдельное действие с подтверждением.

**Откуда «у автора».** Только официальные каналы, которыми эти же мосты
и ставятся: PyPI для Python-пакетов, npm registry для Node-пакетов.
Это тот же принцип, что в omniroute_update (версия у источника автора,
установка закреплённым номером), только канал другой: у пакетов без
меток GitHub канал публикации — реестр пакетов, и он же пользуется
самим мостом при запуске (uvx тянет с PyPI, npx — с npm). Разрешённые
хосты — белый список, как в update_source: только HTTPS, только
pypi.org и registry.npmjs.org. Чужой адрес в таблице — отказ, а не
запрос.

**Почему «стоит» берётся из закрепления, а не из кэша.** У uvx-сервера
нет постоянного окружения: версия моста — это пин в коде программы
(«==10.3.0»), и именно он говорит, что встанет при следующем запуске.
Спрашивать кэш uv — значит спорить с таблицей, которая уже записана.

**Fail-closed.** Сеть не ответила или лимит — «не проверено» с причиной,
никогда не «устарел». Обновлять по молчанию нельзя: молчаливая
проверка хуже отсутствующей.

**Почему закреплённые мосты не обновляются кнопкой.** Пин существует
потому, что мост ломается с несовместимой версией (Unity, TikTok, Godot:
найдено живьём и записано в фактах). Смена пина — правка кода с
прогоном тестов, а не нажатие кнопки. Поэтому для закреплённых мост
показывает «стоит / у автора», а действие говорит, что пин меняется
в коде. Обновление кнопкой разрешено только мостам без закрепления — и
после установки версия перечитывается заново: «поставил» не считается
доказательством.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "launchers"))

import bridge_common as common  # noqa: E402
import bridge_versions as bv  # noqa: E402

TIMEOUT = 30

#: Белый список хостов. Это каналы публикации самих авторов: пакет
#: ставится ровно с этих серверов, когда мост запускается через uvx/npx,
#: поэтому проверка версии у того же хоста не расширяет доверие.
HOSTS = ("pypi.org", "registry.npmjs.org")


def say(text: str) -> None:
    print(f"[bridge-updates] {text}", file=sys.stderr, flush=True)


def _get_json(url: str, timeout: int = TIMEOUT) -> tuple[dict | None, str]:
    """GET с белым списком хостов. (данные, причина). Пусто — не вышло."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in (
            "pypi.org", "registry.npmjs.org"):
        return None, f"адрес не из белого списка: {parsed.netloc}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "opencode-base"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return json.loads(answer.read().decode("utf-8")), ""
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return None, str(exc)


def pypi_latest(package: str) -> tuple[str, str]:
    """Последняя версия пакета на PyPI. (версия, причина). Пусто — нет."""
    data, why = _get_json(f"https://pypi.org/pypi/{package}/json")
    if data is None:
        return "", why or "PyPI не ответил"
    version = str((data.get("info") or {}).get("version") or "")
    return version, "" if version else "PyPI не назвал версию"


def npm_latest(package: str) -> tuple[str, str]:
    """Последняя версия пакета в npm registry. (версия, причина)."""
    data, why = _get_json(f"https://registry.npmjs.org/{package}/latest")
    if data is None:
        return "", why or "npm registry не ответил"
    version = str((data or {}).get("version") or "")
    return version, "" if version else "npm не назвал версию"


def venv_version(venv_python: Path, package: str) -> str:
    """Версия пакета в окружении моста. Пусто — окружения или пакета нет."""
    if not Path(venv_python).is_file():
        return ""
    code = (
        "import importlib.metadata as m, sys\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "try:\n"
        f"    print(m.version({package!r}))\n"
        "except m.PackageNotFoundError:\n"
        "    sys.exit(1)\n"
    )
    code, out, err, status = common.run_capture(
        [str(venv_python), "-c", code], timeout=60)
    if status != "":
        return ""
    return (out or "").strip()


#: Мосты, чьё окружение лежит рядом с путём из файла настроек: в файле
#: назван исполняемый файл из .venv\Scripts, значит питон окружения —
#: рядом с ним. Для остальных uvx-мостов постоянного окружения нет.
CONFIG_EXE = {"kinocut": "mcp-kinocut.json"}


def venv_python_for(bridge_id: str, settings_home: Path | None) -> Path:
    """Питон постоянного окружения моста. Пустой путь — окружения нет.

    Окружение ищется только по файлу настроек (mcp-<имя>.json): в нём
    назван исполняемый файл из .venv\\Scripts, значит питон окружения —
    рядом с ним. Для uvx-мостов постоянного окружения нет, и выдумывать
    его нельзя.
    """
    name = CONFIG_EXE.get(bridge_id)
    if not name or settings_home is None:
        return Path()
    config = settings_home / name
    if not config.is_file():
        return Path()
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return Path()
    exe = str((data or {}).get("kino") or "")
    if exe.lower().endswith(".exe"):
        return Path(exe).parent / "python.exe"
    return Path()


def _pinned_version(spec: str) -> str:
    """Из закрепления берёт номер. Пусто — закрепления нет.

    Два формата: питон «pkg==1.2.3» и npm «@scope/pkg@2.0.1» — у npm
    пакет сам начинается с @, поэтому номер берётся после ПОСЛЕДНЕГО @.
    """
    if "==" in spec:
        tail = spec.split("==", 1)[1]
    elif "@" in spec[1:]:
        tail = spec.rsplit("@", 1)[1]
    else:
        return ""
    digits = ""
    for ch in tail:
        if ch.isdigit() or ch == ".":
            digits += ch
        else:
            break
    return digits


def installed_version(bridge_id: str, entry: dict,
                      settings_home: Path | None = None) -> str:
    """Что стоит. Пусто — не названа (это не ошибка, а честное «не знаю»).

    Для закреплённых — номер из закрепления: он и есть то, что встанет
    при следующем запуске. Для kinocut — из его окружения. Для npx
    без метки честно пусто: версия определяется при запуске.
    """
    server = entry.get("mcp_server") or {}
    spec = str(server.get("spec") or "")
    if server.get("pinned"):
        return _pinned_version(spec) or spec
    upd = entry.get("update") or {}
    if upd.get("family") == "pypi" and upd.get("venv_hint") == "config":
        return venv_version(venv_python_for(bridge_id, settings_home),
                            str(upd.get("package") or ""))
    return ""


def check_all(settings_home: Path | None = None,
              fetch=None) -> tuple[list[dict], list[str]]:
    """Отчёт по всем мостам с блоком update. Ничего не меняет.

    Возвращает (строки, причины). Каждая строка: мост, стоит, у автора,
    вывод словами. Сеть не ответила — «не проверено», никогда не «старый».
    """
    table, note = bv.load(None)
    if table is None:
        return [], [f"таблица версий не читается: {note}"]
    bridges = table.get("bridges") or {}
    report: list[dict] = []
    for bridge_id, entry in bridges.items():
        upd = entry.get("update") or {}
        if not isinstance(upd, dict) or not upd.get("package"):
            continue
        family = str(upd.get("family") or "")
        package = str(upd.get("package"))
        row = {
            "bridge": bridge_id, "family": family, "package": upd.get("package"),
            "installed": installed_version(bridge_id, entry, settings_home),
            "latest": "", "latest_why": "", "verdict": "",
        }
        if family == "pypi":
            version, why = pypi_latest(str(upd["package"]))
        elif family == "npm":
            version, why = npm_latest(str(upd["package"]))
        else:
            version, why = "", f"семейство {family} не проверяется"
        row["latest"] = version
        row["latest_why"] = why
        row["verdict"] = _verdict(bridge_id, entry, row)
        report.append(row)
    return report, []


def _verdict(bridge_id: str, entry: dict, row: dict) -> str:
    """Вывод словами. Молчание сети — «не проверено», никогда не «старый»."""
    latest = row["latest"]
    if not latest:
        return f"не проверено: {row['latest_why']}"
    installed = row["installed"]
    server = entry.get("mcp_server") or {}
    upd = entry.get("update") or {}
    if installed == latest:
        return "свежая"
    if server.get("pinned"):
        where = str(server.get("pinned_in") or "пин в коде")
        return (f"у автора {latest}; мост закреплён ({where}: "
                f"{installed or 'закрепление не названо'}) — смена пина "
                f"делается правкой кода с прогоном тестов, не кнопкой")
    if row["family"] == "npm":
        return (f"у автора {latest}; мост стартует через npx без метки — "
                f"свежая приедет при следующем запуске, закрепить можно "
                f"меткой в реестре")
    if installed:
        return f"стоит {installed}, у автора {latest} — можно обновить"
    return f"у автора {latest}; стоящая версия не названа"


def install(bridge_id: str, version: str, settings_home: Path | None,
            progress=None) -> tuple[list[str], list[str]]:
    """Ставит названную версию в окружение моста. Не трогает закреплённые.

    Путь только один, и он честный: у моста есть постоянное окружение
    (venv_hint = config), пакет ставится именно в него, глобальные папки
    не трогаются. После установки версия перечитывается из окружения —
    «команда отработала» не считается доказательством.
    """
    import shutil

    table, note = bv.load(None)
    if table is None:
        return [], [f"таблица версий не читается: {note}"]
    entry = (table.get("bridges") or {}).get(bridge_id) or {}
    upd = entry.get("update") or {}
    if not upd:
        return [], [f"{bridge_id}: в таблице нет способа обновления"]
    server = entry.get("mcp_server") or {}
    if server.get("pinned"):
        where = str(server.get("pinned_in") or "пин в коде")
        return [], [f"{bridge_id}: мост закреплён ({where}) — пин снимает "
                    f"правка кода с прогоном тестов, кнопкой не трогается"]
    if upd.get("family") != "pypi":
        return [], [f"{bridge_id}: обновление кнопкой сделано для "
                    f"окружений Python, для npm-мостов новая версия "
                    f"приезжает сама при следующем запуске"]
    venv_python = venv_python_for(bridge_id, settings_home)
    if not venv_python.is_file():
        return [], [f"{bridge_id}: постоянного окружения нет — обновлять "
                    f"нечем, установи мост заново"]
    package = str(upd.get("package") or "")
    if not package:
        return [], [f"{bridge_id}: в таблице не назван пакет"]
    uv = shutil.which("uv")
    if not uv:
        return [], ["uv не найден в PATH — чем ставить, неясно"]
    progress = progress or (lambda text: None)
    progress(f"ставлю {package}=={version} в окружение моста…")
    code, out, err, why = common.run_capture(
        ["uv", "pip", "install", "--python", str(venv_python),
         f"{package}=={version}"], timeout=600)
    if code != 0:
        tail = (err or out or why or "").strip().splitlines()
        reason = tail[-1] if tail else "без причины"
        return [], [f"{bridge_id}: установка не прошла ({why or code}): "
                    f"{reason}"]
    now = venv_version(venv_python, package)
    if version in now:
        return [f"{bridge_id}: поставлено {package}=={now}, версия перечитана "
                f"после установки"], []
    return [], [f"{bridge_id}: команда прошла, но в окружении {now or 'ничего'} "
                f"— установка не считается выполненной"]
