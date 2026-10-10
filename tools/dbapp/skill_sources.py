"""Обновление скилов, пришедших от авторов.

Скилы в программе — адаптированные переводы чужих наборов, поэтому
автоматически заменять их оригиналами нельзя: оригинал английский, и
он стёр бы перевод. Модуль поэтому ничего не применяет молча. Он
умеет одно: сказать, что у автора появилось, и показать разницу.

Что где лежит:

— `данные/скилы-источники.json` — список источников. Его правят руками,
  потому что программа не знает, откуда взялся скил, поставленный вне её.

— `skills/.источники.json` в базе — что уже проверено: последний
  известный коммит автора по каждому скилу. Отдельный файл, а не поле
  в манифесте установки: манифест описывает, что ставилось, и трогать
  его формат нельзя, иначе старые базы перестанут читаться.

Проверка идёт по дате последнего коммита автора. Это честно и дёшево:
один запрос на скилл, без скачивания архивов. Плата за простоту —
`git commit --amend` без смены даты мы не увидим.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import core

#: Файл со списком источников. Лежит рядом с реестром серверов, потому
#: что это такой же набор данных программы: читается при запуске, не
#: генерится.
SOURCES_NAME = "скилы-источники.json"

#: Файл с тем, что уже проверено. В папке скиллов базы, рядом с ними:
#: это состояние установленных скилов, а не настройки программы.
STATE_NAME = ".источники.json"

#: GitHub отдаёт не более 60 запросов в час без токена. На двадцать
#: скилов хватает с запасом, а вот перебор без нужды загоняет нас в
#: лимит — поэтому задержка между запросами и никаких повторов.
REQUEST_GAP_SEC = 0.3
GITHUB_API = "https://api.github.com"
USER_AGENT = "OpenCodeBase-skill-check"

#: Состояния, которые панель показывает по скилу. Отдельный перечислитель,
#: а не строки на месте: их читает интерфейс и проверяет самопроверка.
ST_UNKNOWN = "источник неизвестен"
ST_FRESH = "совпадает с авторским"
ST_BEHIND = "у автора появилось"
ST_NO_NET = "не проверилось: нет сети"


def sources_path(base: Path) -> Path:
    return Path(base) / "данные" / SOURCES_NAME


def state_path(base: Path) -> Path:
    return Path(base) / "skills" / STATE_NAME


def load_sources(base: Path) -> list[dict]:
    """Список источников. Пустой список — не ошибка, а «ещё не заполнено»."""
    path = sources_path(base)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    raw = data.get("sources")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()
        repo = str(item.get("repo") or "").strip()
        if not skill or not repo:
            continue
        out.append({
            "skill": skill,
            "repo": repo,
            "path": str(item.get("path") or "").strip(),
            "license": str(item.get("license") or "").strip(),
        })
    return out


def load_state(base: Path) -> dict:
    """Что уже проверено. Отсутствие файла — пустое состояние."""
    try:
        data = json.loads(state_path(base).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(base: Path, state: dict) -> None:
    """Записать проверенное. Ошибку проглатываем: потеря метки означает
    лишь повторную проверку в следующий раз."""
    path = state_path(base)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError:
        pass


def check_repo(repo: str, sub_path: str = "") -> tuple[str, str]:
    """Последний коммит автора по папке. Возвращает (дата, sha) или ("", "")."""
    if not _good_repo(repo):
        return "", ""
    url = f"{GITHUB_API}/repos/{repo}/commits?per_page=1"
    if sub_path:
        url += f"&path={urllib.parse.quote(sub_path)}"
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return "", ""
    if not isinstance(payload, list) or not payload:
        return "", ""
    first = payload[0]
    if not isinstance(first, dict):
        return "", ""
    commit = first.get("commit") or {}
    when = str(((commit.get("committer") or commit.get("author") or {}).get("date")) or "")
    return when, str(first.get("sha") or "")


def _good_repo(repo: str) -> bool:
    """Адрес проверен так же, как адрес программы: только owner/name
    без путей, без «..», без пробелов."""
    if repo.count("/") != 1:
        return False
    owner, _, name = repo.partition("/")
    for part in (owner, name):
        if not part or len(part) > 60:
            return False
        if not all(ch.isalnum() or ch in "-._" for ch in part):
            return False
    return True


def _sleep() -> None:
    import time

    time.sleep(REQUEST_GAP_SEC)


def check_updates(base: Path, progress=None) -> tuple[list[dict], list[str]]:
    """Проверить список источников.

    Возвращает (строки состояния, строки ошибок). Ничего не применяет
    и перезаписывает только файл проверенного: переводы скилов не
    трогаются в любом случае.
    """
    sources = load_sources(base)
    if not sources:
        return [], ["Список источников пуст. Заполни "
                    f"данные\\{SOURCES_NAME}."]
    state = load_state(base)
    rows: list[dict] = []
    errors: list[str] = []
    for index, src in enumerate(sources):
        if callable(progress):
            progress(f"Проверяю {src['skill']}…")
        known = state.get(src["skill"]) or {}
        was = str(known.get("date") or "")
        when, sha = check_repo(src["repo"], src["path"])
        if not when:
            rows.append({"skill": src["skill"], "state": ST_NO_NET,
                         "repo": src["repo"], "date": "", "sha": ""})
            errors.append(f"{src['skill']}: не проверилось, нет сети "
                          "или адрес не прошёл проверку")
            _sleep()
            continue
        if not was:
            status = ST_UNKNOWN
        elif when == was:
            status = ST_FRESH
        else:
            status = ST_BEHIND
        rows.append({"skill": src["skill"], "state": status,
                     "repo": src["repo"], "date": when, "sha": sha})
        if status != ST_FRESH:
            # Запоминаем только когда уверены: метка «проверено» не должна
            # опережать реальность, иначе расхождение потеряется.
            state[src["skill"]] = {"date": when, "sha": sha,
                                   "repo": src["repo"], "path": src["path"]}
        _sleep()
    save_state(base, state)
    return rows, errors


def local_skill_text(base: Path, skill: str) -> str:
    """Наш файл скила — тот, что с переводом."""
    for folder in (Path(base) / "skills", core.current_base("opencode") / "skills"):
        path = folder / skill / core.SKILL_MARKER
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def fetch_original(src: dict) -> str:
    """Скачать оригинал автора. Пустая строка — не получилось."""
    repo = src.get("repo") or ""
    sub_path = src.get("path") or ""
    if not _good_repo(repo):
        return ""
    url = f"{GITHUB_API}/repos/{repo}/contents/{sub_path}/{core.SKILL_MARKER}"
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github.raw"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return ""


def save_original(folder: Path, text: str) -> Path | None:
    """Положить оригинал рядом с нашим файлом, не трогая его самого."""
    if not text:
        return None
    target = Path(folder) / f"{core.SKILL_MARKER}.оригинал"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError:
        return None
    return target


def diff_lines(ours: str, theirs: str) -> list[str]:
    """Построчная разница. Возвращает строки отчёта, а не сырой diff:
    отчёт человек читает, а машина его показывает."""
    import difflib

    ours_lines = (ours or "").splitlines()
    theirs_lines = (theirs or "").splitlines()
    out: list[str] = []
    for line in difflib.unified_diff(ours_lines, theirs_lines,
                                     fromfile="у нас", tofile="у автора",
                                     lineterm="", n=1):
        out.append(line)
    if not out:
        out.append("Различий нет.")
    return out