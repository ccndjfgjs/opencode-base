"""Разбор настроек opencode для ревьюера: какие провайдеры подключены.

Что это. Единственная работа модуля — прочитать один файл, `opencode.jsonc`
рядом с настройками opencode, и сказать: какие провайдеры там есть, какие
из них говорят с миром на языке OpenAI, какие у них модели и какие имена
переменных окружения с ними связаны.

Почему отдельный файл. Настройки opencode — чужой кусок кода, и разбирать
их приходится с оговорками: файл написан в jsonc, то есть с комментариями
`//`; у провайдера адрес и ключ лежат во вложенном `options`, а не рядом с
именем; ключ записан либо строкой, либо ссылкой `{env:ИМЯ}`. Всё это нужно
знать читателю файла, а не тому, кто его запускает, поэтому разбор и
живёт отдельно.

Границы. Модуль только читает: сам он ничего не пишет, ничего не запускает,
ни про Qwen Code, ни про git не знает — это всё забота вызывающего. И ключ
наружу не отдаётся: в `providers()` его нет вовсе, а `provider_key` отдаёт
его ровно одному — вызывающему, чтобы положить в окружение процесса; в
команды, журналы и окно значение не попадает никогда. Вместо значения
наружу идёт маска: `mask_key` показывает первые 4 символа и длину, а
`mask_text` вычищает ключ из чужого текста — провайдер в ответе на 401
любит цитировать присланный ключ целиком, и без этого он уезжал бы в
журнал и окно ошибок. Откуда взят ключ, словами без значения говорит
`provider_key_info`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Пакеты, которыми провайдер говорит на языке OpenAI.
OPENAI_PACKAGES = (
    "@ai-sdk/openai",
    "@ai-sdk/openai-compatible",
    "@ai-sdk/azure",
    "@ai-sdk/deepseek",
    "@ai-sdk/groq",
    "@ai-sdk/xai",
    "@ai-sdk/cerebras",
    "@ai-sdk/togetherai",
    "@ai-sdk/fireworks",
    "@ai-sdk/perplexity",
    "@ai-sdk/deepinfra",
    "@ai-sdk/baseten",
    "@ai-sdk/llamacpp",
    "@openrouter/ai-sdk-provider",
    "ollama-ai-provider",
    "ai-sdk-ollama",
)

#: Пакеты, которые с Qwen Code напрямую не заговорят.
NON_OPENAI_PACKAGES = (
    "@ai-sdk/anthropic",
    "@ai-sdk/google",
    "@ai-sdk/google-vertex",
    "@ai-sdk/amazon-bedrock",
    "@ai-sdk/mistral",
    "@ai-sdk/cohere",
    "@ai-sdk/vertex",
)


def _config(dest: Path) -> Path:
    return Path(dest) / "opencode.jsonc"


def _provider_block(text: str) -> str:
    """Кусок текста настроек с записями провайдеров."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    bounds = opencode_caps.find_key_object(text, "provider")
    if bounds is None:
        return ""
    return text[bounds[0] : bounds[1]]


def _entry_text(text: str, name: str) -> str:
    """Текст одной записи провайдера."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    block = _provider_block(text)
    if not block:
        return ""
    bounds = opencode_caps.find_key_object(text, name, text.find(block))
    if bounds is None:
        return ""
    return text[bounds[0] : bounds[1]]


def _options_text(text: str) -> str:
    """Текст вложенного объекта options записи провайдера."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    bounds = opencode_caps.find_key_object(text, "options")
    if bounds is None:
        return ""
    return text[bounds[0] : bounds[1]]


def _str_field(text: str, key: str) -> str:
    """Строковое поле записи (первое вхождение)."""
    match = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    return match.group(1) if match else ""


def _env_names(text: str) -> list[str]:
    """Имена переменных окружения из поля env записи провайдера.

    Список имён, а не значений: сами значения лежат в окружении, и в
    настройках их нет — их туда положил человек.
    """
    match = re.search(r'"env"\s*:\s*\[([^\]]*)\]', text)
    if not match:
        return []
    return re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))


def _models(text: str) -> list[str]:
    """Имена моделей из записи провайдера, по порядку."""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    bounds = opencode_caps.find_key_object(text, "models")
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
            match = re.match(r'"((?:[^"\\]|\\.)*)"\s*:', chunk[i:])
            if match and depth == 1:
                names.append(match.group(1))
            in_str = True
            i += 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return names


def providers(dest: Path) -> list[dict]:
    """Провайдеры, уже подключённые в opencode, с их моделями.

    Каждый — словарь: id, npm, base_url, models, env_names, ok (годится ли
    для ревьюера), why (словами, если не годится). Ключ сюда не попадает:
    он читается отдельно и живёт только в окружении запуска.
    """
    try:
        text = _config(dest).read_text(encoding="utf-8")
    except OSError:
        return []
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    # Файл написан в jsonc, а комментарии `//` внутри блока провайдеров
    # сбивали границы: запись читалась не до конца. Поэтому комментарии
    # снимаются ДО того, как искать в файле объекты, а не после.
    text = opencode_caps.strip_jsonc(text)
    bounds = opencode_caps.find_key_object(text, "provider")
    if bounds is None:
        return []
    names = _provider_names(text)
    found: list[dict] = []
    for name in names:
        entry = _entry_text(text, name)
        if not entry:
            continue
        npm = _str_field(entry, "npm")
        # Адрес лежит во вложенном options. Раньше он брался первым
        # вхождением по всему тексту записи, и это работало случайно —
        # стоило options переехать, и адрес пропал бы молча.
        base = _str_field(_options_text(entry), "baseURL")
        models = _models(entry)
        env_names = _env_names(entry)
        ok, why = provider_fits(npm, base, models)
        found.append({
            "id": name,
            "npm": npm,
            "base_url": base,
            "models": models,
            "env_names": env_names,
            "ok": ok,
            "why": why,
        })
    return found


def _provider_names(text: str) -> list[str]:
    """Имена записей провайдеров верхнего уровня."""
    block = _provider_block(text)
    if not block:
        return []
    names: list[str] = []
    depth = 0
    in_str = False
    escape = False
    i = 0
    while i < len(block):
        ch = block[i]
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
            match = re.match(r'"((?:[^"\\]|\\.)*)"\s*:\s*\{', block[i:])
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


def provider_fits(npm: str, base_url: str, models: list[str]) -> tuple[bool, str]:
    """Годится ли провайдер для ревьюера. (да/нет, причина словами).

    Qwen Code говорит с провайдером на языке OpenAI. Пакет-обёртка и адрес
    из настроек opencode говорят нам, на каком языке говорит провайдер:
    если это не OpenAI — ревьюер не подойдёт, и подставлять наугад нельзя.
    """
    if not models:
        return False, "у провайдера нет списка моделей — выбирать нечего"
    if npm in OPENAI_PACKAGES:
        return True, ""
    if npm in NON_OPENAI_PACKAGES:
        return False, (
            f"провайдер работает не через OpenAI-совместимый интерфейс "
            f"({npm}) — Qwen Code с ним не заговорит"
        )
    if base_url:
        return False, (
            "провайдер со своим адресом, но без известного OpenAI-совместимого "
            "пакета — программа не берётся угадывать; если он совместим, "
            "поставь ему npm @ai-sdk/openai-compatible"
        )
    return False, "не видно, что провайдер говорит на языке OpenAI"


def mask_key(key: str) -> str:
    """Маска ключа вместо значения: безопасная по построению.

    Ключ в ответах на 401 провайдер часто цитирует целиком, и без маски
    он уезжал бы в журнал, консоль и окно ошибок — так однажды уже
    случилось. Поэтому наружу отдаётся только маска. Короткие ключи
    (до 8 символов) не показываем даже частично: первые 4 символа
    короткого ключа — это почти весь ключ, и маска перестала бы быть
    маской.
    """
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return f"*** (длина {len(key)})"
    return f"{key[:4]}… (длина {len(key)})"


def mask_text(text: str, key: str) -> str:
    """Вычищает значение ключа из чужого текста: вывод, ошибки, журнал."""
    key = (key or "").strip()
    if not key or key not in text:
        return text
    return text.replace(key, mask_key(key))


def provider_key_info(dest: Path, provider_id: str) -> tuple[str, str]:
    """Ключ провайдера и словами, откуда он взят.

    Значение не печатается и не пишется в наши файлы: в состояние попадает
    лишь имя провайдера и модель, а наружу вместо значения идёт маска.

    Порядок получения жёсткий: сначала переменная окружения по именам из
    поля env провайдера, потом ссылка на переменную в apiKey («{env:ИМЯ}»
    у opencode, «${ИМЯ}» — второй вид, который когда-то разбирали в
    одиночку), и только потом литерал в файле. Итого переменная окружения
    всегда сильнее литерала: ключ можно сменить, не трогая настройки.

    Источник возвращается словами и без значения: «переменная окружения
    X», «ссылка {env:X}», «литерал в opencode.jsonc (первые 4 символа:
    dah…)». Пустая пара — записи нет или apiKey не задан вовсе.
    """
    try:
        text = _config(dest).read_text(encoding="utf-8")
    except OSError:
        return "", ""
    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    # Комментарии снимаются до поиска записи — так же, как в providers():
    # иначе комментарий с несбалансированной { внутри записи смещал
    # границы, и ключ читался не оттуда.
    text = opencode_caps.strip_jsonc(text)
    entry = _entry_text(text, provider_id)
    if not entry:
        return "", ""
    # 1) Переменная окружения по именам из поля env провайдера.
    env_names = _env_names(entry)
    for name in env_names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"переменная окружения {name}"
    raw = _str_field(entry, "apiKey").strip()
    # 2) Ссылка на переменную окружения в самом apiKey.
    if raw.startswith("{env:") and raw.endswith("}"):
        name = raw[5:-1].strip()
        return os.environ.get(name, "").strip(), f"ссылка {{env:{name}}}"
    if raw.startswith("${") and raw.endswith("}"):
        name = raw[2:-1].strip()
        return os.environ.get(name, "").strip(), f"переменная окружения {name}"
    # 3) Литерал в файле: наружу отдаём как есть, а показывают его маской.
    if raw:
        return raw, "литерал в opencode.jsonc (первые 4 символа: " + raw[:4] + "…)"
    if env_names:
        return "", "переменная окружения " + ", ".join(env_names) + " — не задана"
    return "", ""


def provider_key(dest: Path, provider_id: str) -> str:
    """Ключ провайдера из настроек — только для окружения запуска.

    Значение не печатается и не пишется в наши файлы: в состояние попадает
    лишь имя провайдера и модель. Порядок получения (переменная окружения
    → ссылка → литерал) и слова об источнике — в provider_key_info.
    """
    return provider_key_info(dest, provider_id)[0]
