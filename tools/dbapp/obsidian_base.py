"""Поддержка Obsidian и агента заметок для уже созданной базы.

Не создаёт базу и не трогает файлы, которые человек уже положил.
Агент — тот же формат, что остальные агенты OpenCode: один файл Markdown.
Отдельного механизма агентов здесь нет.

Живой Obsidian и живой ответ модели эта функция не подделывает.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
PROGRAM = HERE.parent.parent
AGENT_FILE = PROGRAM / "tools" / "obsidian-agent" / "obsidian.md"
PREFS_NAME = "создание-базы.json"
HOME_NOTE = "Главная.md"
AGENT_NOTE = "настройки/obsidian-agent.md"
AGENT_MARK = "<!-- opencode-obsidian-agent -->"

# Идентификатор winget снят со страницы каталога, не командой winget show.
WINGET_ID = "Obsidian.Obsidian"
OBSIDIAN_SITE = "https://obsidian.md"


def agent_source() -> Path:
    return AGENT_FILE


def prefs_path(program: Path | None = None) -> Path:
    root = Path(program) if program is not None else PROGRAM
    return root / "данные" / PREFS_NAME


def load_prefs(program: Path | None = None) -> tuple[bool, bool]:
    """Два переключателя прошлого открытия окна. Битые данные — оба выключены."""
    path = prefs_path(program)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False, False
    if not isinstance(data, dict):
        return False, False
    return bool(data.get("obsidian")), bool(data.get("obsidian_agent"))


def save_prefs(obsidian: bool, agent: bool, program: Path | None = None) -> str | None:
    """Пишет только два флажка. Уже созданные базы не меняет."""
    path = prefs_path(program)
    body = json.dumps(
        {"obsidian": bool(obsidian), "obsidian_agent": bool(agent)},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    except OSError as exc:
        return f"Настройки переключателей не сохранились: {exc}"
    return None


def vault_id(folder: Path) -> str:
    key = os.path.normcase(str(folder.resolve()))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def open_uri(name_or_id: str) -> str:
    """Официальный адрес obsidian://open. Значение кодируется, в команду не склеивается."""
    return "obsidian://open?vault=" + quote(name_or_id, safe="")


def obsidian_config_path() -> Path | None:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "obsidian" / "obsidian.json"
    if os.name == "nt":
        return None
    return Path.home() / ".config" / "obsidian" / "obsidian.json"


def find_obsidian() -> Path | None:
    """Ищет установленный Obsidian. Не ставит его."""
    names = ("Obsidian", "obsidian", "Obsidian.exe")
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    if local:
        candidates.append(Path(local) / "Programs" / "Obsidian" / "Obsidian.exe")
        candidates.append(Path(local) / "Obsidian" / "Obsidian.exe")
    program_files = os.environ.get("ProgramFiles", "")
    if program_files:
        candidates.append(Path(program_files) / "Obsidian" / "Obsidian.exe")
    for path in candidates:
        if path.is_file():
            return path
    return None


def missing_obsidian_text() -> str:
    return (
        "Obsidian не найден. База создаётся и без него. "
        f"Чтобы открыть хранилище, поставьте Obsidian с {OBSIDIAN_SITE}. "
        f"В winget идентификатор {WINGET_ID}; версию здесь не измеряли "
        "и установку программа не запускает."
    )


def _write_new(path: Path, text: str) -> str | None:
    """Пишет файл, только если его ещё нет. Чужое не затирает."""
    if path.exists():
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"Не удалось записать {path.name}: {exc}"
    return ""


def prepare_vault(folder: Path) -> tuple[list[str], list[str]]:
    """Делает папку пригодной для открытия как хранилище. Чужие заметки не трогает."""
    notes: list[str] = []
    errors: list[str] = []
    folder = Path(folder)
    if not folder.is_dir():
        return notes, [f"Папки базы нет: {folder}"]
    home = folder / HOME_NOTE
    if home.exists():
        notes.append(f"{HOME_NOTE} уже есть, не перезаписываю")
        return notes, errors
    links = ["# Главная", "", "Это вход в базу. Заметки — обычный Markdown."]
    for name in ("КАРТА-БАЗЫ", "ПРАВИЛА-ИИ", "profile", "facts", "projects"):
        if (folder / f"{name}.md").is_file():
            links.append(f"- [[{name}]]")
    links.append("")
    links.append("Папку `.obsidian` программа не создаёт: её создаёт сам Obsidian при первом открытии.")
    links.append("")
    wrote = _write_new(home, "\n".join(links))
    if wrote is None:
        notes.append(f"{HOME_NOTE} уже есть, не перезаписываю")
    elif wrote:
        errors.append(wrote)
    else:
        notes.append(f"Создана заметка {HOME_NOTE}. Существующие файлы не тронуты")
    return notes, errors


def connect_agent(folder: Path, source: Path | None = None) -> tuple[list[str], list[str]]:
    """Кладёт агента в базу. Глобальные настройки OpenCode не меняет."""
    notes: list[str] = []
    errors: list[str] = []
    folder = Path(folder)
    if not folder.is_dir():
        return notes, [f"Папки базы нет: {folder}"]
    src = Path(source) if source is not None else agent_source()
    if not src.is_file():
        return notes, [
            "Файл агента в программе не найден. Подключение не имитирую. "
            "Остальная база не изменена."
        ]
    markdown = list(folder.glob("*.md"))
    if not markdown:
        notes.append(
            "В корне базы нет markdown-заметок. Файл агента положу, "
            "структуру базы менять не буду."
        )
    for rel in ("tools/agents/obsidian.md", ".opencode/agents/obsidian.md"):
        dest = folder / rel
        if dest.is_file():
            notes.append(f"{rel} уже есть, не перезаписываю")
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            notes.append(f"Агент записан в {rel}. Это файл, не живой ответ модели")
        except OSError as exc:
            errors.append(f"Агента не удалось скопировать в {rel}: {exc}")
    guide = folder / AGENT_NOTE
    wrote = _write_new(
        guide,
        "# Obsidian Agent\n\n"
        "Агент лежит в `.opencode/agents/obsidian.md` этой базы.\n"
        "OpenCode видит такой файл, когда запущен из папки базы, "
        "и вызывает его как `@obsidian`.\n"
        "В общие настройки OpenCode программа его не копирует: "
        "агент относится только к этой базе.\n\n"
        "Удалять заметки без прямой просьбы нельзя.\n"
        "Наличие Obsidian само по себе агента не включает.\n"
        "Живой ответ модели при создании базы не запускался.\n",
    )
    if wrote:
        errors.append(wrote)
    elif wrote == "":
        notes.append("Записано описание агента в настройках базы")
    _append_agents_mark(folder, notes, errors)
    return notes, errors


def _append_agents_mark(folder: Path, notes: list[str], errors: list[str]) -> None:
    path = folder / "AGENTS.md"
    if not path.is_file():
        notes.append("AGENTS.md в базе нет, новый файл правил не создаю")
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"AGENTS.md не прочитан, не трогаю: {exc}")
        return
    if AGENT_MARK in text:
        notes.append("Правила агента в AGENTS.md уже есть")
        return
    extra = (
        "\n\n"
        f"{AGENT_MARK}\n"
        "Если в базе есть `tools/agents/obsidian.md`, заметки ведёт `@obsidian`. "
        "Удалять файлы без прямой просьбы нельзя.\n"
    )
    try:
        path.write_text(text + extra, encoding="utf-8")
    except OSError as exc:
        errors.append(f"AGENTS.md не дополнен: {exc}")
        return
    notes.append("В конец AGENTS.md добавлена одна пометка об агенте, прежний текст на месте")


def place_agent_in_opencode(config_dir: Path, source: Path | None = None) -> tuple[bool, str]:
    """Копирует одного агента в настройки OpenCode. Остальные файлы не трогает."""
    src = Path(source) if source is not None else agent_source()
    if not src.is_file():
        return False, "Файла агента нет, в настройки OpenCode ничего не пишу."
    dest = Path(config_dir) / "agents" / "obsidian.md"
    if dest.is_file() and dest.read_bytes() != src.read_bytes():
        return False, (
            f"{dest} уже есть и отличается. Свой файл не затираю. "
            "Вызов @obsidian возьмёт то, что уже лежит."
        )
    if dest.is_file():
        return True, "Агент @obsidian в настройках OpenCode уже тот же, не перезаписываю."
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    except OSError as exc:
        return False, f"Агента в настройки OpenCode скопировать не удалось: {exc}"
    return True, (
        "Агент @obsidian скопирован в настройки OpenCode. "
        "Он появится после перезапуска. Живой правки заметки не было."
    )


def apply(folder: Path, *, obsidian: bool, agent: bool,
          source: Path | None = None) -> tuple[list[str], list[str]]:
    """Четыре комбинации. Выключенное не делает ничего."""
    notes: list[str] = []
    errors: list[str] = []
    if obsidian:
        got, bad = prepare_vault(folder)
        notes += got
        errors += bad
    if agent:
        got, bad = connect_agent(folder, source)
        notes += got
        errors += bad
    if not obsidian and not agent:
        notes.append("Obsidian и агент выключены: база создаётся как раньше")
    return notes, errors


def register_vault(folder: Path, config: Path | None = None) -> tuple[bool, str]:
    """Добавляет хранилище в obsidian.json, если файл уже есть. Чужие записи не удаляет."""
    path = config if config is not None else obsidian_config_path()
    if path is None or not path.is_file():
        return False, (
            "Файл настроек Obsidian не найден. Новый не создаю: "
            "иначе программа выдумала бы конфигурацию. "
            "Откройте Obsidian один раз или выберите папку через Open folder as vault."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False, "Настройки Obsidian не разобрались. Файл не трогаю."
    if not isinstance(data, dict):
        return False, "Настройки Obsidian неожиданного вида. Файл не трогаю."
    vaults = data.get("vaults")
    if vaults is None:
        vaults = {}
        data["vaults"] = vaults
    if not isinstance(vaults, dict):
        return False, "Список хранилищ Obsidian повреждён. Файл не трогаю."
    wanted = str(folder.resolve())
    for item in vaults.values():
        if isinstance(item, dict) and os.path.normcase(str(item.get("path") or "")) == os.path.normcase(wanted):
            return True, "Хранилище уже записано в Obsidian, повторно не добавляю."
    ident = vault_id(folder)
    if ident in vaults and isinstance(vaults[ident], dict):
        other = str(vaults[ident].get("path") or "")
        if os.path.normcase(other) != os.path.normcase(wanted):
            return False, "Такой идентификатор хранилища уже занят другой папкой. Запись не меняю."
    backup = path.with_name(path.name + ".bak-opencode")
    draft = path.with_name(path.name + ".tmp-opencode")
    vaults[ident] = {"path": wanted, "ts": int(time.time() * 1000)}
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        if not backup.exists():
            shutil.copy2(path, backup)
        draft.write_text(body, encoding="utf-8")
        draft.replace(path)
    except OSError as exc:
        draft.unlink(missing_ok=True)
        if backup.is_file() and not path.is_file():
            try:
                shutil.copy2(backup, path)
            except OSError:
                pass
        return False, f"Записать хранилище в Obsidian не удалось: {exc}"
    return True, "Хранилище добавлено в настройки Obsidian. Прежние хранилища оставлены."


def open_vault(folder: Path, config: Path | None = None, opener=None) -> tuple[bool, str]:
    """Открывает хранилище, если Obsidian установлен. Базу из-за этого не портит.

    Если хранилище удалось записать в настройки, адрес использует его
    идентификатор. Иначе — имя папки, как в документации Obsidian.
    Незарегистрированное хранилище Obsidian может не открыть: это ограничение
    программы Obsidian, и здесь оно не прячется.
    """
    if find_obsidian() is None and opener is None:
        return False, missing_obsidian_text()
    folder = Path(folder)
    if not folder.is_dir():
        return False, f"Папки нет, открывать нечего: {folder}"
    registered, note = register_vault(folder, config)
    token = vault_id(folder) if registered else folder.name
    uri = open_uri(token)
    open_it = opener
    if open_it is None:
        from core import open_url
        open_it = open_url
    try:
        open_it(uri)
    except Exception as exc:  # noqa: BLE001
        return False, f"Адрес Obsidian не открылся: {exc}. {note}"
    limit = ""
    if not registered:
        limit = (
            " Если это хранилище ещё ни разу не открывали, Obsidian может "
            "показать «Vault not found». Тогда откройте папку через "
            "Open folder as vault."
        )
    return True, (
        f"Отправлен адрес {uri}. {note}{limit} "
        "Живой ответ окна Obsidian здесь не проверялся."
    )
