# -*- coding: utf-8 -*-
"""Возможности базы для opencode — установка по выбору.

Простыми словами: ставит в настройки opencode команду /голос, мост ПК,
мост памяти и 12 агентов — только то, что отметил человек. Убрал галочку —
файлы и записи убираются, чужое не трогается.

Правила (как везде в окне):
  * перед правкой opencode.jsonc — копия в _previous-version;
  * чужое не затираем: файлы без нашей метки пропускаем с сообщением;
  * что поставили — записываем в манифест, по нему же удаляем;
  * настоящий ~/.config/opencode трогаем только из окна, проверки —
    всегда во временной папке.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent  # tools/dbapp -> tools -> база

#: Что можно поставить: (имя, подпись для окна).
CAPS = (
    ("voice", "Команда /голос"),
    ("pc", "Мост ПК"),
    ("ncp", "Мост памяти"),
    ("agents", "12 агентов"),
)

MANIFEST = ".opencode-base-caps.json"
VOICE_MARK = "{{VOICE_DIR}}"

BEGIN_TPL = "// == OpenCode_Base: {name} =="
END_TPL = "// == OpenCode_Base: конец {name} =="


def opencode_dir() -> Path:
    """Папка настроек opencode (настоящая)."""
    import core  # noqa: PLC0415 — рядом лежит, круга нет

    return core.PROGRAMS_BY_ID["opencode"].config_dir()


def find_python() -> str:
    """Чем запускать мосты: тот же поиск, что у окна, иначе текущий."""
    try:
        import core  # noqa: PLC0415

        found = core.find_python()
        if found is not None:
            return str(found)
    except Exception:
        pass
    return sys.executable


# ------------------------------------------------------------------ JSONC


def strip_jsonc(text: str) -> str:
    """Убирает // и /* */ комментарии, строки в кавычках не трогает."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    escape = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def check_jsonc(text: str) -> bool:
    """Файл — целый JSON после снятия комментариев."""
    try:
        json.loads(strip_jsonc(text))
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def find_key_object(text: str, key: str, start: int = 0) -> tuple[int, int] | None:
    """Границы объекта "key": {...} — индексы скобок. Строки уважаем."""
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*:')
    match = pattern.search(text, start)
    if not match:
        return None
    i = match.end()
    while i < len(text) and text[i] not in "{":
        if text[i] in "[]":
            return None
        i += 1
    if i >= len(text):
        return None
    depth = 0
    in_str = False
    escape = False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return (i, j)
    return None


def has_entry(obj_text: str, name: str) -> bool:
    """Есть ли ключ "name": внутри куска объекта."""
    return re.search(r'"' + re.escape(name) + r'"\s*:', obj_text) is not None


def find_key_array(text: str, key: str, start: int = 0) -> tuple[int, int] | None:
    """Границы массива "key": [...] — индексы [ и ]. Строки уважаем."""
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*:')
    match = pattern.search(text, start)
    if not match:
        return None
    i = match.end()
    while i < len(text) and text[i] != "[":
        if text[i] in "{}":
            return None
        i += 1
    if i >= len(text):
        return None
    depth = 0
    in_str = False
    escape = False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return (i, j)
    return None


def ensure_object(text: str, key: str) -> str:
    """Гарантирует пустой объект "key": {} в корне (перед последней })."""
    if find_key_object(text, key) is not None:
        return text
    stripped = text.rstrip()
    assert stripped.endswith("}"), "корень opencode.jsonc — объект"
    inner = stripped[:-1].rstrip()
    comma = "," if inner and not inner.endswith("{") and not inner.endswith("[") else ""
    return inner + comma + f'\n  "{key}": {{}}\n}}\n'


def insert_entry(text: str, obj_key: str, name: str, entry: str) -> str:
    """Вставляет запись с метками сразу после открывающей скобки объекта.
    Запятая — только если дальше есть содержимое: в пустом объекте
    висячая запятая ломает JSON."""
    bounds = find_key_object(text, obj_key)
    if bounds is None:
        raise ValueError(f"нет объекта {obj_key}")
    opening = bounds[0]
    entry_text = entry.rstrip()
    rest = text[opening + 1 :]
    needs_comma = not rest.lstrip().startswith("}")
    if needs_comma and not entry_text.endswith(","):
        entry_text += ","
    elif not needs_comma and entry_text.endswith(","):
        entry_text = entry_text[:-1]
    block = (
        "\n    " + BEGIN_TPL.format(name=obj_key + "." + name)
        + "\n    " + entry_text
        + "\n    " + END_TPL.format(name=obj_key + "." + name) + "\n"
    )
    return text[: opening + 1] + block + text[opening + 1 :]


def remove_entry(text: str, obj_key: str, name: str) -> str:
    """Убирает наш блок с метками; висячие запятые чистит."""
    begin = BEGIN_TPL.format(name=f"{obj_key}.{name}")
    end = END_TPL.format(name=f"{obj_key}.{name}")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\s*,?\s*", re.DOTALL)
    text = pattern.sub("", text)
    # Висячая запятая перед закрывающей скобкой: ",\n  }" -> "\n  }".
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def fix_trailing_commas(text: str) -> str:
    """Убирает висячие запятые перед } и ]: наши вставки всегда кончаются
    запятой, а если запись оказалась последней в объекте — это ошибка JSON."""
    return re.sub(r",(\s*[}\]])", r"\1", text)


def merge_caps(
    text: str,
    servers: dict[str, str],
    permissions: dict[str, str],
) -> str:
    """Дописывает наши MCP-серверы и права. Чужое не трогает."""
    if not check_jsonc(text):
        raise ValueError("opencode.jsonc сломан — правим руками, не автоматом")
    text = ensure_object(text, "mcp")
    text = ensure_object(text, "permission")
    for name, entry in servers.items():
        bounds = find_key_object(text, "mcp")
        assert bounds is not None
        if not has_entry(text[bounds[0] : bounds[1]], name):
            text = insert_entry(text, "mcp", name, entry)
    for name, value in permissions.items():
        bounds = find_key_object(text, "permission")
        assert bounds is not None
        if not has_entry(text[bounds[0] : bounds[1]], name):
            text = insert_entry(text, "permission", name, f'"{name}": {value}')
    text = fix_trailing_commas(text)
    if not check_jsonc(text):
        raise ValueError("после вставки файл не читается — откат")
    return text


def unmerge_caps(text: str, names: list[str]) -> str:
    """Убирает наши записи из mcp и permission."""
    for name in names:
        text = remove_entry(text, "mcp", name)
        text = remove_entry(text, "permission", name)
    if not check_jsonc(text):
        raise ValueError("после удаления файл не читается — откат")
    return text


def set_instructions(text: str, base: Path) -> str:
    """Переписывает массив instructions в файле на пути этой базы.

    Всё остальное — провайдеры, права, другие серверы mcp — остаётся
    как было. Возвращает новый текст; если файл не читается или в нём
    нет массива instructions — бросает ValueError.
    """
    if not check_jsonc(text):
        raise ValueError("opencode.jsonc сломан — правим руками, не автоматом")
    import core  # noqa: PLC0415 — рядом лежит

    bounds = find_key_array(text, "instructions")
    if bounds is None:
        raise ValueError("в opencode.jsonc нет массива instructions")
    opening, closing = bounds
    base_posix = str(base).replace("\\", "/")
    lines = ["["]
    for name in core.INSTRUCTION_TARGETS:
        lines.append(f'    "{base_posix}/{name}",')
    lines[-1] = lines[-1][:-1]
    lines.append("  ]")
    fixed = text[:opening] + "\n".join(lines) + text[closing + 1 :]
    if not check_jsonc(fixed):
        raise ValueError("после замены instructions файл не читается — откат")
    return fixed


def update_block(text: str, obj_key: str, name: str, entry: str) -> tuple[str, bool]:
    """Переписывает наш блок в объекте. Чужого не трогает.

    Наши блоки живут между метками. Если меток нет, а запись с таким
    именем уже есть (чужая) — пропускаем и возвращаем False. Если записи
    нет вовсе — вставляем свою. Возвращает (текст, изменено ли).
    """
    begin = BEGIN_TPL.format(name=f"{obj_key}.{name}")
    end = END_TPL.format(name=f"{obj_key}.{name}")
    bounds = find_key_object(text, obj_key)
    if bounds is None:
        text = ensure_object(text, obj_key)
        bounds = find_key_object(text, obj_key)
    assert bounds is not None
    b = text.find(begin)
    if b == -1:
        if has_entry(text[bounds[0] : bounds[1]], name):
            return text, False
        return insert_entry(text, obj_key, name, entry), True
    e = text.find(end, b)
    if e == -1:
        raise ValueError(f"метка {begin} не закрыта — правим руками")
    # Есть ли внутри объекта реальное содержимое после нашего блока.
    rest_after = text[e + len(end) : bounds[1]]
    needs_comma = re.search(r'"[^":\n]+"\s*:', rest_after) is not None
    entry_text = entry.rstrip()
    if entry_text.endswith(","):
        entry_text = entry_text[:-1].rstrip()
    if needs_comma:
        entry_text += ","
    # Сдвигаем начало замены до перевода строки перед меткой — иначе
    # каждая перепрошивка оставляет лишнюю пустую строку перед блоком.
    b0 = text.rfind("\n", 0, b)
    if b0 < 0:
        b0 = 0
    block = f"\n    {begin}\n    {entry_text}\n    {end}"
    fixed = text[:b0] + block + text[e + len(end) :]
    fixed = fix_trailing_commas(fixed)
    if not check_jsonc(fixed):
        raise ValueError("после обновления файл не читается — откат")
    return fixed, True


def rewire_config(dest: Path, base: Path) -> list[str]:
    """Переводит opencode.jsonc в папке настроек на эту базу.

    Меняет массив instructions и блоки мостов ncp/pc с правами, чтобы
    всё указывало на новую базу. Чужие серверы и провайдеры не трогает.
    Возвращает список сообщений. Бросает ValueError, если файл не читается.
    """
    messages: list[str] = []
    cfg = dest / "opencode.jsonc"
    if not cfg.is_file():
        raise ValueError("нет opencode.jsonc — мосты подключать некуда")
    text = cfg.read_text(encoding="utf-8")
    if not check_jsonc(text):
        raise ValueError("opencode.jsonc сломан — правим руками, не автоматом")
    text = set_instructions(text, base)
    python = find_python()
    for obj_key, name, entry in (
        ("mcp", "ncp", ncp_server_block(base, python)),
        ("mcp", "pc", pc_server_block(base, python)),
        ("permission", "ncp_*", '"ncp_*": "ask"'),
        ("permission", "pc_*", '"pc_*": "ask"'),
    ):
        text, changed = update_block(text, obj_key, name, entry)
        if changed:
            messages.append(f"В настройки вписан блок: {obj_key}.{name}")
    cfg.write_text(text, encoding="utf-8")
    messages.append("Пути, мосты ncp/pc и права переведены на эту базу")
    return messages


# ------------------------------------------------------------------ файлы


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(dest: Path) -> dict:
    try:
        data = json.loads((dest / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(dest: Path, data: dict) -> None:
    (dest / MANIFEST).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def server_entry(python: str, server_py: Path) -> str:
    cmd = json.dumps([python, str(server_py).replace("\\", "/")], ensure_ascii=False)
    return f'"command": {cmd}'


def pc_server_block(base: Path, python: str) -> str:
    return (
        '"pc": {\n'
        '      "type": "local",\n'
        f'      {server_entry(python, base / "tools" / "pc-bridge" / "server.py")},\n'
        '      "enabled": true\n'
        "    },"
    )


def ncp_server_block(base: Path, python: str) -> str:
    return (
        '"ncp": {\n'
        '      "type": "local",\n'
        f'      {server_entry(python, base / "tools" / "ncp-bridge" / "server.py")},\n'
        '      "enabled": true\n'
        "    },"
    )


#: Новые пресеты провайдеров: их нет среди встроенных в opencode,
#: окно дописывает их как custom-провайдеры. Формат — из официальной
#: документации opencode (npm @ai-sdk/openai-compatible).
#: (имя, подпись, ключ окружения или "", текст записи)
PROVIDER_PRESETS: dict[str, tuple[str, str, str]] = {
    "ollama": (
        "Ollama (локально, без ключа)",
        "",
        '"ollama": {\n'
        '      "npm": "@ai-sdk/openai-compatible",\n'
        '      "name": "Ollama (local)",\n'
        '      "options": {\n'
        '        "baseURL": "http://localhost:11434/v1"\n'
        "      },\n"
        '      "models": {\n'
        '        "qwen3": {"name": "Qwen3 (local)"},\n'
        '        "llama3.1": {"name": "Llama 3.1 (local)"}\n'
        "      }\n"
        "    },",
    ),
    "lmstudio": (
        "LM Studio (локально, без ключа)",
        "",
        '"lmstudio": {\n'
        '      "npm": "@ai-sdk/openai-compatible",\n'
        '      "name": "LM Studio (local)",\n'
        '      "options": {\n'
        '        "baseURL": "http://127.0.0.1:1234/v1"\n'
        "      },\n"
        '      "models": {\n'
        '        "local-model": {"name": "Модель из LM Studio (поправь id)"}\n'
        "      }\n"
        "    },",
    ),
}


def install_providers(
    dest: Path,
    selection: set[str],
    progress=None,
) -> tuple[list[str], list[str]]:
    """Дописывает выбранные пресеты в provider. Ключи не трогает и не просит:
    их человек вводит сам (/connect или переменные окружения)."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    unknown = set(selection) - set(PROVIDER_PRESETS)
    if unknown:
        errors.append(f"Не знаю таких провайдеров: {', '.join(sorted(unknown))}.")
        return messages, errors
    if not selection:
        return messages, errors

    dest.mkdir(parents=True, exist_ok=True)
    cfg = dest / "opencode.jsonc"
    if not cfg.is_file():
        cfg.write_text('{\n  "$schema": "https://opencode.ai/config.json"\n}\n', encoding="utf-8")
    backup_dir = dest / "_previous-version"
    backup_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        shutil.copy2(cfg, backup_dir / f"opencode.jsonc-{stamp}")
    except OSError as exc:
        errors.append(f"Не сохранилась копия настроек: {exc}")
        return messages, errors
    try:
        text = cfg.read_text(encoding="utf-8")
        if not check_jsonc(text):
            raise ValueError("opencode.jsonc сломан — правим руками, не автоматом")
        text = ensure_object(text, "provider")
        for name in sorted(selection):
            _title, _key, block = PROVIDER_PRESETS[name]
            bounds = find_key_object(text, "provider")
            assert bounds is not None
            if not has_entry(text[bounds[0] : bounds[1]], name):
                text = insert_entry(text, "provider", name, block)
        text = fix_trailing_commas(text)
        if not check_jsonc(text):
            raise ValueError("после вставки файл не читается — откат")
        cfg.write_text(text, encoding="utf-8")
        manifest = read_manifest(dest)
        have = manifest.get("providers", [])
        for name in sorted(selection):
            if name not in have:
                have.append(name)
        manifest["providers"] = have
        write_manifest(dest, manifest)
        say(f"В provider вписано: {', '.join(sorted(selection))}")
        for name in sorted(selection):
            _title, key, _block = PROVIDER_PRESETS[name]
            if key:
                say(f"{name}: ключ задай сам — переменная {key} (или /connect в opencode)")
            else:
                say(f"{name}: ключа не надо, запусти локальный сервер")
    except (OSError, ValueError) as exc:
        errors.append(f"Настройки не тронуты: {exc}")
    return messages, errors


def remove_providers(
    dest: Path,
    selection: set[str],
    progress=None,
) -> tuple[list[str], list[str]]:
    """Убирает пресеты из provider. Чужие записи не трогает."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    cfg = dest / "opencode.jsonc"
    if cfg.is_file() and selection:
        try:
            text = cfg.read_text(encoding="utf-8")
            for name in sorted(selection):
                text = remove_entry(text, "provider", name)
            if not check_jsonc(text):
                raise ValueError("после удаления файл не читается — откат")
            cfg.write_text(text, encoding="utf-8")
            manifest = read_manifest(dest)
            manifest["providers"] = [n for n in manifest.get("providers", []) if n not in selection]
            write_manifest(dest, manifest)
            say(f"Из provider убрано: {', '.join(sorted(selection))}")
        except (OSError, ValueError) as exc:
            errors.append(f"Настройки не тронуты: {exc}")
    return messages, errors


def providers_status(dest: Path) -> dict[str, bool]:
    """Какие пресеты сейчас стоят."""
    status = {name: False for name in PROVIDER_PRESETS}
    try:
        text = (dest / "opencode.jsonc").read_text(encoding="utf-8")
        bounds = find_key_object(text, "provider")
        if bounds is not None:
            chunk = text[bounds[0] : bounds[1]]
            for name in status:
                if has_entry(chunk, name):
                    status[name] = True
    except OSError:
        pass
    return status


# ------------------------------------------------------------------ установка


def install_caps(
    base: Path,
    dest: Path,
    selection: set[str],
    progress=None,
) -> tuple[list[str], list[str]]:
    """Ставит выбранное в папку настроек opencode. Возвращает (сообщения, ошибки)."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    unknown = set(selection) - {name for name, _ in CAPS}
    if unknown:
        errors.append(f"Не знаю таких возможностей: {', '.join(sorted(unknown))}.")
        return messages, errors
    if "agents" in selection and not (base / "tools" / "agents").is_dir():
        errors.append("В базе нет папки tools/agents — нечего ставить.")
        return messages, errors

    dest.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(dest)
    manifest.setdefault("files", {})
    manifest.setdefault("jsonc", [])

    # --- opencode.jsonc: копия, потом вставка
    if {"pc", "ncp"} & set(selection):
        cfg = dest / "opencode.jsonc"
        if not cfg.is_file():
            cfg.write_text('{\n  "$schema": "https://opencode.ai/config.json"\n}\n', encoding="utf-8")
            say("Создан пустой opencode.jsonc (его не было)")
        backup_dir = dest / "_previous-version"
        backup_dir.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(cfg, backup_dir / f"opencode.jsonc-{stamp}")
            say("Копия opencode.jsonc сохранена в _previous-version")
        except OSError as exc:
            errors.append(f"Не сохранилась копия настроек: {exc}")
            return messages, errors
        try:
            text = cfg.read_text(encoding="utf-8")
            servers: dict[str, str] = {}
            python = find_python()
            if "pc" in selection:
                servers["pc"] = pc_server_block(base, python)
            if "ncp" in selection:
                servers["ncp"] = ncp_server_block(base, python)
            permissions = {f"{n}_*": '"ask"' for n in ("pc", "ncp") if n in selection}
            cfg.write_text(merge_caps(text, servers, permissions), encoding="utf-8")
            for name in list(servers) + list(permissions):
                if name not in manifest["jsonc"]:
                    manifest["jsonc"].append(name)
            say(f"В opencode.jsonc вписано: {', '.join(sorted(set(servers) | set(permissions)))}")
        except (OSError, ValueError) as exc:
            errors.append(f"Настройки не тронуты: {exc}")
            return messages, errors

    # --- команда /голос
    if "voice" in selection:
        src = base / "tools" / "voice" / "voice.md"
        if not src.is_file():
            errors.append("В базе нет tools/voice/voice.md — команду ставить не из чего.")
        else:
            body = src.read_text(encoding="utf-8").replace(
                VOICE_MARK, str(base / "tools" / "voice").replace("\\", "/")
            )
            target = dest / "command" / "voice.md"
            if _place_file(target, body, manifest, say, errors, "Команда /голос"):
                say("Команда /голос поставлена (папка command)")

    # --- агенты
    if "agents" in selection:
        agents_dir = dest / "agents"
        agents_dir.mkdir(exist_ok=True)
        put, skipped = 0, 0
        for src in sorted((base / "tools" / "agents").glob("*.md")):
            target = agents_dir / src.name
            if _place_file(target, src.read_text(encoding="utf-8"), manifest, say, errors,
                           f"Агент {src.stem}", quiet=True):
                put += 1
            else:
                skipped += 1
        say(f"Агентов поставлено: {put}, пропущено (чужие): {skipped}")

    write_manifest(dest, manifest)
    if "pc" in selection or "ncp" in selection or "voice" in selection or "agents" in selection:
        say("Перезапустите opencode: настройки читаются при старте.")
    return messages, errors


def _place_file(
    target: Path,
    body: str,
    manifest: dict,
    say,
    errors: list[str],
    title: str,
    quiet: bool = False,
) -> bool:
    """Кладёт файл, чужой (не наш и не из манифеста) — не трогает.
    Хэш считаем по байтам на диске: Windows пишет \\r\\n, и хэш текста
    с \\n никогда бы не сошёлся при проверке."""
    record = manifest.get("files", {}).get(str(target))
    if target.is_file():
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = None
        if current == body:
            manifest.setdefault("files", {})[str(target)] = file_hash(target)
            return True
        if record is None:
            errors.append(f"{title}: файл уже есть и не наш — пропустил ({target.name}).")
            return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        manifest.setdefault("files", {})[str(target)] = file_hash(target)
        if not quiet:
            say(f"{title}: записан")
        return True
    except OSError as exc:
        errors.append(f"{title}: не записался ({exc}).")
        return False


def remove_caps(
    dest: Path,
    selection: set[str],
    progress=None,
) -> tuple[list[str], list[str]]:
    """Убирает выбранное. Чужие файлы и записи не трогает."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    manifest = read_manifest(dest)
    if {"pc", "ncp"} & set(selection):
        cfg = dest / "opencode.jsonc"
        if cfg.is_file():
            try:
                text = cfg.read_text(encoding="utf-8")
                names: list[str] = []
                if "pc" in selection:
                    names += ["pc", "pc_*"]
                if "ncp" in selection:
                    names += ["ncp", "ncp_*"]
                cfg.write_text(unmerge_caps(text, names), encoding="utf-8")
                manifest["jsonc"] = [n for n in manifest.get("jsonc", []) if n not in names]
                say(f"Из opencode.jsonc убрано: {', '.join(names)}")
            except (OSError, ValueError) as exc:
                errors.append(f"Настройки не тронуты: {exc}")

    paths: list[Path] = []
    if "voice" in selection:
        paths.append(dest / "command" / "voice.md")
    if "agents" in selection:
        paths += [dest / "agents" / src.name for src in (BASE / "tools" / "agents").glob("*.md")] if (BASE / "tools" / "agents").is_dir() else []
    for target in paths:
        record = manifest.get("files", {}).get(str(target))
        if not target.is_file():
            manifest.get("files", {}).pop(str(target), None)
            continue
        try:
            if record is not None and file_hash(target) != record:
                errors.append(f"Файл {target.name} меняли вручную — оставил как есть.")
                continue
            if record is None:
                errors.append(f"Файл {target.name} не из манифеста — не трогаю.")
                continue
            target.unlink()
            manifest.get("files", {}).pop(str(target), None)
            say(f"Убран файл {target.name}")
        except OSError as exc:
            errors.append(f"Не убрался {target.name}: {exc}")

    write_manifest(dest, manifest)
    return messages, errors


def caps_status(dest: Path) -> dict[str, bool]:
    """Что из возможностей сейчас стоит в папке настроек."""
    manifest = read_manifest(dest)
    status = {name: False for name, _ in CAPS}
    try:
        text = (dest / "opencode.jsonc").read_text(encoding="utf-8")
        for key in ("mcp",):
            bounds = find_key_object(text, key)
            if bounds is None:
                continue
            chunk = text[bounds[0] : bounds[1]]
            if has_entry(chunk, "pc"):
                status["pc"] = True
            if has_entry(chunk, "ncp"):
                status["ncp"] = True
    except OSError:
        pass
    if (dest / "command" / "voice.md").is_file():
        status["voice"] = True
    agents = list((dest / "agents").glob("*.md")) if (dest / "agents").is_dir() else []
    if agents:
        status["agents"] = True
    _ = manifest
    return status
