"""qwen-review — второй агент-ревьюер: вторая пара глаз на изменения кода.

Что это. Qwen Code (автор QwenLM, лицензия Apache-2.0) — открытый консольный
агент с headless-режимом: команда `qwen -p "запрос"` работает без интерфейса,
принимает запрос по pipe, умеет отдавать ответ в JSON и имеет режим «только
чтение» (`--approval-mode plan`). Здесь он работает вторым ревьюером: читает
`git diff` изменений и возвращает замечания, ничего не правя.

Как устроено:

    tools/agents/retsenzent-qwen.md     агент для opencode (ставится тем же
                                        механизмом, что двенадцать основных)
    tools/dbapp/qwen_review.py          этот модуль: развёртывание, выбор
                                        провайдера, запуск ревью и спора
    <настройки opencode>/qwen-review-data/   наш дом Qwen Code: настройки,
                                        журнал, ход спора
    <настройки opencode>/qwen-review-data/qwen-home/   QWEN_HOME: settings.json
                                        и рабочие файлы qwen — так мы не трогаем
                                        личный ~/.qwen пользователя

Модель ревьюера выбирается из провайдеров, уже подключённых в opencode:
программа читает `opencode.jsonc`, берёт провайдеров формата OpenAI
(`@ai-sdk/openai*` и родственные пакеты либо свой `baseURL`) вместе с их
списком моделей, а ключ передаёт самому qwen через окружение процесса —
в команды, журналы и окно ключ не попадает.

Чего программа не делает: не устанавливает Node.js и не ставит Qwen Code без
нажатия кнопки; не трогает личный `~/.qwen`; не запускает ревью у провайдера
не в формате OpenAI — вместо этого честно говорит, что он не подходит;
не даёт ревьюеру права править файлы (`--approval-mode plan`) и не решает
за человека, кто прав в споре.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
# Консоль Windows по умолчанию живёт в однобайтовой кодировке (cp1251),
# и в ней нет, например, знака рубля. Ответ провайдера с ценой приходил
# с символом \u20bd, print() падал с UnicodeEncodeError — и вместо внятной
# ошибки человек получал traceback. Под pythonw sys.stdout равен None, там
# .reconfigure() не существует: проверяем и это (найдено живьём).
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
from pathlib import Path

#: Откуда берётся ревьюер и по какой лицензии.
SOURCE = "https://github.com/QwenLM/qwen-code"
SOURCE_NOTE = "консольный агент QwenLM, версия 0.25.0 от 07.10.2026"
LICENSE = "Apache-2.0"
PACKAGE = "@qwen-code/qwen-code"
NODE_MIN = 22

#: Где живут наши данные, как называется отметка в манифесте и агент opencode.
DATA_NAME = "qwen-review-data"
MANIFEST_KEY = "qwen-review"
AGENT_NAME = "retsenzent-qwen"
AGENT_NOTE = "агент opencode, который зовёт ревьюера"

#: Сколько раундов спора по умолчанию и сколько вообще разрешено.
DEFAULT_ROUNDS = 3
MAX_ROUNDS = 5

#: Установка словами README автора (Linux/macOS, Windows — тем же npm).
INSTALL_HINT = (
    "по README автора Qwen Code ставится скриптом установки с их сайта, "
    "через npm — `npm install -g @qwen-code/qwen-code@latest` (нужен Node.js "
    "22 или новее) — или через Homebrew. Программа умеет поставить его "
    "в свою папку кнопкой «Развернуть Qwen Code»: та же команда npm, только "
    "без -g и в наши данные"
)

#: Оговорки, которые видны и в окне, и в журнале.
COST_WARNING = (
    "Ревьюер и спор тратят токены: каждая проверка — запрос к выбранной "
    "модели, а спор — ещё и по запросу на раунд. На бесплатных моделях это "
    "упирается в лимиты. Код из `git diff` уходит выбранному провайдеру."
)
LMARENA_WARNING = (
    "Выбран мост LMArena: код изменений уйдёт на публичную площадку арены. "
    "Приватный код и секреты через него отправлять нельзя."
)
DEBATE_WARNING = (
    "«Спор» — отдельный режим: ревьюер и основная модель обмениваются "
    "доводами, но не больше заданного числа раундов. Если за это время "
    "согласия нет, программа не решает сама: она показывает оба довода и "
    "спорный фрагмент, а решает человек."
)

# ------------------------------------------------------------------ режимы

#: Режимы ревьюера — единый список данных. Из него строятся галочка «спор»
#: в окне, командная строка и будущее окно выбора режима (задача 5 плана).
#: Поля:
#:   id          — стабильное имя режима (для кода и командной строки);
#:   name        — короткое человеческое имя;
#:   description — что делает режим (подсказка галочки в окне, help в CLI);
#:   flag        — состояние старой галочки «спор», дающее этот режим
#:                 (галочка одна, режимов пока два: снята — once);
#:   label       — подпись галочки в окне; у once своей галочки нет;
#:   requires    — что нужно режиму, человеческими словами.
MODES: list[dict] = [
    {
        "id": "once",
        "name": "Одна проверка",
        "description": (
            "Ревьюер один раз смотрит git diff и присылает замечания. "
            "Возражений и раундов нет: следующий запуск начинает счёт заново."
        ),
        "flag": False,
        "label": "одна проверка — ревьюер без спора",
        "requires": [
            "отмеченная галочка qwen-review",
            "одна модель ревьюера: выбраны провайдер и модель",
        ],
    },
    {
        "id": "debate",
        "name": "Спор",
        "description": (
            "Отдельный режим, по умолчанию выключен. Ревьюер присылает "
            "замечания, основной агент возражает с обоснованием, ревьюер "
            "отвечает — и так не больше заданного числа раундов. Если "
            "согласия нет, программа не решает сама: она показывает оба "
            "довода и спорный фрагмент, а решает человек"
        ),
        "flag": True,
        "label": "спор — ревьюер против модели",
        "requires": [
            "отмеченная галочка qwen-review",
            "включённый переключатель «спор»",
            "две стороны: модель ревьюера и основная модель агента",
            "возражение основного агента для каждого раунда после первого",
            f"число раундов от 1 до {MAX_ROUNDS}",
        ],
    },
]

#: Идентификаторы режимов: на них смотрят окно и командная строка.
MODE_ONCE = str(MODES[0]["id"])
MODE_DEBATE = next(str(mode["id"]) for mode in MODES if mode.get("flag"))


def mode_by_id(mode_id: str) -> dict | None:
    """Режим по идентификатору. Незнакомое значение — None, а не падение."""
    wanted = str(mode_id or "").strip().lower()
    for mode in MODES:
        if str(mode.get("id")) == wanted:
            return mode
    return None


def mode_from_flag(on: bool) -> str:
    """Старая галочка режима → идентификатор режима из MODES.

    Галочка «спор» в окне остаётся той же, но её смысл теперь живёт в
    общем списке режимов, а не в хардкоде вызывающего кода: включена —
    «debate», снята — «once». Соответствие берётся по полю flag.
    """
    for mode in MODES:
        if bool(mode.get("flag")) == bool(on):
            return str(mode["id"])
    return str(MODES[0]["id"])


def mode_ids() -> list[str]:
    """Все идентификаторы режимов — по порядку списка."""
    return [str(mode["id"]) for mode in MODES]


def mode_requires(mode_id: str) -> list[str]:
    """Что нужно режиму. Незнакомый режим — пустой список."""
    mode = mode_by_id(mode_id)
    if mode is None:
        return []
    return [str(item) for item in mode.get("requires") or []]


def _hidden_startupinfo():
    """Окно консоли не показывать. Подробности — в core.hidden_startupinfo."""
    try:
        from core import hidden_startupinfo

        return hidden_startupinfo()
    except Exception:
        return None


def _run_quiet(cmd: list[str], cwd: Path | None = None, env: dict | None = None,
               timeout: int = 120) -> tuple[int, str, str]:
    """Запуск без окна: (код, stdout, stderr). Молчит про внутренние ошибки.

    Имя функции обещало ровно то, чего код не делал: окно не пряталось.
    Проверка qwen-review запускает qwen.cmd и node --version, и каждая
    такая проверка на миг показывала чёрное окно прямо во время сборки
    главного окна. capture_output подставляет трубы явно, поэтому
    STARTUPINFO со скрытием безопасен и ничего не рвёт.
    """
    try:
        done = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
            startupinfo=_hidden_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)
    return done.returncode, done.stdout or "", done.stderr or ""


# ------------------------------------------------------------------ пути

def program_root() -> Path:
    """Папка программы (в ней tools/agents)."""
    import core  # noqa: PLC0415 — рядом лежит, круга нет

    return core.program_root()


def agent_file() -> Path:
    """Файл агента, который едет в настройки opencode тем же механизмом,
    что двенадцать основных агентов."""
    return program_root() / "tools" / "agents" / f"{AGENT_NAME}.md"


def data_dir(dest: Path) -> Path:
    """Наши данные рядом с настройками opencode."""
    return Path(dest) / DATA_NAME


def home_dir(dest: Path) -> Path:
    """QWEN_HOME ревьюера: личный ~/.qwen пользователя не трогаем."""
    return data_dir(dest) / "qwen-home"


def node_dir(dest: Path) -> Path:
    """Куда кнопка «Развернуть» ставит пакет Qwen Code."""
    return data_dir(dest) / "node"


def log_file(dest: Path) -> Path:
    """Журнал проверок и споров."""
    return data_dir(dest) / "qwen-review.log"


def settings_file(dest: Path) -> Path:
    """settings.json самого Qwen Code — в нашем доме, а не в ~/.qwen."""
    return home_dir(dest) / "settings.json"


def state_file(dest: Path) -> Path:
    """Наш выбор провайдера и модели (без ключа)."""
    return data_dir(dest) / "reviewer.json"


def debate_file(dest: Path) -> Path:
    """Ход спора: раунды, доводы и расход токенов."""
    return data_dir(dest) / "debate.json"


# ------------------------------------------------------------------ бинарник

def binary_names() -> list[str]:
    """Как называется исполняемый файл qwen на этой системе."""
    return ["qwen.cmd", "qwen.exe", "qwen"] if os.name == "nt" else ["qwen"]


def find_binary(dest: Path | None = None) -> tuple[Path | None, str]:
    """Готовый qwen: сперва из PATH, потом наша папка. (путь, откуда)."""
    for name in binary_names():
        found = shutil.which(name)
        if found:
            return Path(found), "PATH"
    if dest is not None:
        local = node_dir(dest) / "node_modules" / ".bin"
        for name in binary_names():
            if (local / name).is_file():
                return local / name, "развёрнут"
    return None, ""


def find_npm() -> str | None:
    """npm из PATH (нужен только для развёртывания)."""
    for name in ("npm.cmd", "npm") if os.name == "nt" else ("npm",):
        found = shutil.which(name)
        if found:
            return found
    return None


def find_node() -> str | None:
    """node из PATH."""
    return shutil.which("node")


def node_version(node: str | None = None) -> str:
    """Версия Node.js строкой или пусто."""
    node = node or find_node()
    if not node:
        return ""
    code, out, err = _run_quiet([node, "--version"], timeout=60)
    text = (out or err).strip().splitlines()
    return text[0] if code == 0 and text else ""


def node_ok(node: str | None = None) -> bool:
    """Node.js 22 или новее — требование автора (engines в package.json)."""
    version = node_version(node).lstrip("v")
    head = version.split(".")[0]
    return head.isdigit() and int(head) >= NODE_MIN


def binary_version(binary: Path | None = None, dest: Path | None = None) -> tuple[bool, str]:
    """Отвечает ли qwen на `--version`. Живая проверка до записи."""
    if binary is None:
        binary, _where = find_binary(dest)
    if binary is None:
        return False, "qwen не найден"
    if not Path(binary).is_file():
        return False, f"файла нет: {binary}"
    code, out, err = _run_quiet([str(binary), "--version"], timeout=120,
                                env=run_env(dest) if dest else None)
    lines = ((out or "") + (err or "")).strip().splitlines()
    if code != 0 or not lines:
        return False, f"ответил кодом {code}"
    return True, lines[0].strip()


# ------------------------------------------------------------------ окружение и дом

def run_env(dest: Path | None = None, extra: dict | None = None) -> dict:
    """Окружение для qwen: свой QWEN_HOME, без интерактива, без телеметрии.

    Ключ провайдера добавляется здесь же — и только в окружение процесса:
    в командной строке его не видно.
    """
    env = dict(os.environ)
    if dest is not None:
        env["QWEN_HOME"] = str(home_dir(dest))
    env.setdefault("QWEN_DEFAULT_AUTH_TYPE", "openai")
    env["QWEN_TELEMETRY"] = "false"
    env["QWEN_USAGE_STATISTICS_ENABLED"] = "false"
    env["QWEN_CODE_NO_RELAUNCH"] = "1"
    if extra:
        env.update(extra)
    return env


def ensure_home(dest: Path) -> Path:
    """Дом Qwen Code внутри наших данных."""
    folder = home_dir(dest)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ------------------------------------------------------------------ выбор модели

#: Списки пакетов живут в qwen_providers. Тут они отдаются наружу как
#: реэкспорт: снаружи на них смотрят, а второй раз определёнными быть
#: не должны — иначе списки разъедутся.
_REEXPORTED = ("OPENAI_PACKAGES", "NON_OPENAI_PACKAGES")


def __getattr__(name: str):
    """Отдаём наружу списки пакетов из qwen_providers, не импортируя его
    на импорте: qwen_review читают раньше, чем кладут папку в sys.path."""
    if name in _REEXPORTED:
        import qwen_providers  # noqa: PLC0415 — рядом лежит, круга нет

        return getattr(qwen_providers, name)
    raise AttributeError(f"модуль qwen_review не знает имени {name!r}")


def providers(dest: Path) -> list[dict]:
    """Провайдеры, уже подключённые в opencode, с их моделями.

    Разбор живёт в qwen_providers — там снимаются комментарии jsonc,
    оттуда же берутся адрес из вложенных options и имена переменных
    окружения. Здесь только тонкая обёртка: имена и подписи те же.
    """
    import qwen_providers  # noqa: PLC0415 — рядом лежит, круга нет

    return qwen_providers.providers(dest)


def provider_fits(npm: str, base_url: str, models: list[str]) -> tuple[bool, str]:
    """Годится ли провайдер для ревьюера. (да/нет, причина словами)."""
    import qwen_providers  # noqa: PLC0415 — рядом лежит, круга нет

    return qwen_providers.provider_fits(npm, base_url, models)


def provider_key(dest: Path, provider_id: str) -> str:
    """Ключ провайдера из настроек — только для окружения запуска."""
    import qwen_providers  # noqa: PLC0415 — рядом лежит, круга нет

    return qwen_providers.provider_key(dest, provider_id)


def provider_key_info(dest: Path, provider_id: str) -> tuple[str, str]:
    """Ключ и словами, откуда он взят: имя переменной окружения, ссылка
    {env:ИМЯ} или литерал с маской. Само значение наружу не выходит."""
    import qwen_providers  # noqa: PLC0415 — рядом лежит, круга нет

    return qwen_providers.provider_key_info(dest, provider_id)


def mask_key(key: str) -> str:
    """Маска ключа: первые 4 символа и длина вместо значения."""
    import qwen_providers  # noqa: PLC0415 — рядом лежит, круга нет

    return qwen_providers.mask_key(key)


def mask_text(text: str, key: str) -> str:
    """Вычищает значение ключа из чужого текста: вывод, ошибки, журнал."""
    import qwen_providers  # noqa: PLC0415 — рядом лежит, круга нет

    return qwen_providers.mask_text(text, key)


# ------------------------------------------------------------------ проверка моделей

#: Живая проверка доступности моделей. Один запрос на модель — минимальный:
#: промпт из одного символа, максимум один токен в ответе, потому что
#: проверка стоит реальных денег. Четыре потока — чтобы щадить провайдера,
#: потолок 120 запросов за прогон — чтобы случайное нажатие кнопки не
#: разорило человека, кэш на сутки — чтобы повторный прогон не бил по API.

CHECK_WORKERS = 4          # потока одновременно — не больше
CHECK_MAX_MODELS = 120     # потолок запросов за один прогон
CHECK_CACHE_HOURS = 24     # сколько живёт кэш проверки
CHECK_TIMEOUT = 30         # секунд на один запрос

CHECK_OK = "ok"            # ✔ модель отвечает
CHECK_NO = "no"            # ✘ точно нет: 401, 404 — окончательный отказ
CHECK_UNKNOWN = "unknown"  # ? не знаю: 429, таймаут, сетевой сбой
CHECK_SYMBOL = {CHECK_OK: "✔", CHECK_NO: "✘", CHECK_UNKNOWN: "?"}

CHECK_CACHE_FILE = "model-check.json"


def check_cache_file(dest: Path) -> Path:
    """Кэш проверки моделей — рядом с остальными данными ревьюера."""
    return data_dir(dest) / CHECK_CACHE_FILE


def state_from_http(code: int) -> str:
    """Состояние по коду ответа провайдера: ✔, ✘ или ?.

    Три состояния, не два: 401 и 404 — окончательный отказ (ключа нет или
    модели нет), а вот 429 — НЕ отказ. Лимит провайдера не имеет права
    превращать половину моделей в «недоступные»: не знаем — так и пишем.
    """
    if 200 <= code < 300:
        return CHECK_OK
    if code in (401, 404):
        return CHECK_NO
    return CHECK_UNKNOWN


def probe_model(base_url: str, model: str, key: str,
                timeout: int = CHECK_TIMEOUT) -> tuple[str, str]:
    """Один минимальный запрос к провайдеру. (состояние, сырая причина).

    Промпт из одного символа, максимум один токен: проверка идёт по всем
    моделям и стоит реальных денег. Сетевые сбои и таймауты — «не знаю»,
    а не отказ: по ответу 500 нельзя сказать, жива ли модель.
    """
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "1"}],
        "max_tokens": 1,
    }).encode("utf-8")
    request = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        }, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            return CHECK_OK, ""
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:300].strip()
        except OSError:
            detail = ""
        return state_from_http(exc.code), f"HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, OSError) as exc:
        return CHECK_UNKNOWN, f"сеть или таймаут: {exc}"


def _load_check_cache(dest: Path) -> dict:
    """Кэш проверок с диска. Пустой словарь — файла нет или он битый."""
    try:
        data = json.loads(check_cache_file(dest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("providers"), dict):
        return data
    return {}


def _save_check_cache(dest: Path, cache: dict) -> None:
    """Пишет кэш. Ошибка записи не смертельна: проверка ценнее журнала."""
    try:
        data_dir(dest).mkdir(parents=True, exist_ok=True)
        check_cache_file(dest).write_text(
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _cache_entry_fresh(entry: dict, cache_hours: float) -> bool:
    """Свежа ли запись кэша: ей меньше заданных часов."""
    at = entry.get("at") if isinstance(entry, dict) else None
    return isinstance(at, (int, float)) and (time.time() - at) < cache_hours * 3600.0


def check_provider_models(dest: Path, provider_id: str, progress=None,
                          probe=None, max_models: int = CHECK_MAX_MODELS,
                          workers: int = CHECK_WORKERS,
                          cache_hours: float = CHECK_CACHE_HOURS,
                          ) -> tuple[dict, list[str]]:
    """Доступность моделей провайдера: {модель: (состояние, причина)}.

    Состояния три: ✔ отвечает, ✘ точно нет (401/404), ? не знаю (429,
    таймаут, сеть). Причина — текст ошибки провайдера, вычищенный через
    mask_text: провайдер любит цитировать присланный ключ, и без маски он
    уезжал бы в кэш, окно и журнал.

    Потолок — не больше max_models запросов за прогон: если моделей
    больше, проверяются первые по алфавиту, и об остальных сказано
    словами. Повторный прогон в те же сутки читает кэш и не бьёт по API.
    Параметр probe подменяется в самопроверке: там сети быть не должно.
    """
    dest = Path(dest)
    probe = probe or probe_model
    chosen = next((p for p in providers(dest) if p["id"] == provider_id), None)
    if chosen is None:
        return {}, [f"Провайдера «{provider_id}» в настройках opencode нет."]
    if not chosen["ok"]:
        return {}, [f"Провайдер «{provider_id}» не подходит: {chosen['why']}."]

    notes: list[str] = []
    models = sorted(chosen["models"])
    key, key_source = provider_key_info(dest, provider_id)
    if not key:
        # Без ключа в провайдера ходить нельзя — и не надо: вместо сети
        # честный отказ по каждой модели, ни одного запроса. Деньги и
        # лимиты провайдера тут ни при чём, поэтому это ✘, а не ?.
        detail = "ключ не найден: " + (key_source or "в настройках нет apiKey")
        return {m: (CHECK_NO, detail) for m in models}, notes

    cache = _load_check_cache(dest)
    stored = cache.setdefault("providers", {}).setdefault(provider_id, {})
    stored = stored.setdefault("models", {})

    limited = models
    if len(models) > max_models:
        limited = models[:max_models]
        notes.append(
            f"Моделей {len(models)}: проверены первые {max_models} по алфавиту, "
            f"остальные {len(models) - max_models} не проверялись "
            f"(потолок {max_models} запросов за прогон).")

    results: dict[str, tuple[str, str]] = {}
    todo: list[str] = []
    cached = 0
    for model in limited:
        entry = stored.get(model)
        if isinstance(entry, dict) and _cache_entry_fresh(entry, cache_hours):
            results[model] = (str(entry.get("state") or CHECK_UNKNOWN),
                              str(entry.get("reason") or ""))
            cached += 1
        else:
            todo.append(model)
    if cached:
        notes.append(
            f"Из кэша (свежесть {cache_hours:g} ч): {cached} моделей — "
            "по API не били.")

    if todo:
        done_count = 0
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
            jobs = {pool.submit(probe, chosen["base_url"], model, key): model
                    for model in todo}
            for job in as_completed(jobs):
                model = jobs[job]
                state, raw = job.result()
                reason = mask_text(raw, key)
                results[model] = (state, reason)
                stored[model] = {"state": state, "reason": reason,
                                 "at": time.time()}
                done_count += 1
                if progress:
                    progress(f"Проверено {done_count + cached} из "
                             f"{len(limited)}: {model} "
                             f"{CHECK_SYMBOL.get(state, '?')}")
        _save_check_cache(dest, cache)
    return results, notes


def choose(dest: Path, provider_id: str, model: str,
           progress=None) -> tuple[list[str], list[str]]:
    """Запоминает выбор провайдера и модели и пишет настройки Qwen Code.

    Пишем ровно то, что нужно самому Qwen Code (`security.auth.selectedType`,
    `model.name`, `model.baseUrl`) — в свой дом QWEN_HOME. Ключ сюда не
    попадает: он передаётся при запуске через окружение.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    dest = Path(dest)
    list_ = providers(dest)
    chosen = next((p for p in list_ if p["id"] == provider_id), None)
    if chosen is None:
        return messages, [f"Провайдера «{provider_id}» в настройках opencode нет."]
    if not chosen["ok"]:
        return messages, [
            f"Провайдер «{provider_id}» для ревьюера не подходит: {chosen['why']}."
        ]
    model = (model or "").strip()
    if not model:
        return messages, ["Не выбрана модель ревьюера."]
    if model not in chosen["models"]:
        return messages, [
            f"У провайдера «{provider_id}» нет модели «{model}». Есть: "
            + ", ".join(chosen["models"][:8]) + ("…" if len(chosen["models"]) > 8 else "")
        ]

    folder = ensure_home(dest)
    settings = {
        "security": {"auth": {"selectedType": "openai"}},
        "model": {"name": model},
    }
    base = chosen["base_url"]
    if base:
        settings["model"]["baseUrl"] = base
    try:
        settings_file(dest).write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state_file(dest).write_text(json.dumps({
            "provider": provider_id,
            "model": model,
            "base_url": base,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return messages, [f"Настройки ревьюера не записались: {exc}"]

    say(f"Ревьюер настроен: провайдер «{provider_id}», модель «{model}».")
    if base:
        say(f"Адрес для Qwen Code взят из настроек opencode: {base}")
    say(f"Настройки Qwen Code лежат в нашем доме: {folder} (личный ~/.qwen не тронут).")
    say("Ключ провайдера в настройки не записан: он уедет в окружение процесса при запуске.")
    _key, _source = provider_key_info(dest, provider_id)
    if _source:
        say(f"Ключ возьмётся из: {_source}.")
    if provider_id == "lmarena":
        say(LMARENA_WARNING)
    say(COST_WARNING)
    return messages, errors


def chosen(dest: Path) -> dict:
    """Что выбрано сейчас. Пустой словарь — ещё не выбирали."""
    try:
        return json.loads(state_file(dest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ состояние

def check(dest: Path) -> dict:
    """Что готово для ревью. Ничего не меняет."""
    dest = Path(dest)
    binary, where = find_binary(dest)
    works, version = binary_version(binary, dest) if binary else (False, "")
    selection = chosen(dest)
    agent = agent_file()
    npm = find_npm()
    node = find_node()

    missing: list[str] = []
    if binary is None:
        if npm:
            missing.append(
                "Qwen Code не развёрнут — нажми «Развернуть Qwen Code» (npm найден), "
                "или поставь его по README: " + INSTALL_HINT
            )
        else:
            missing.append(
                "Qwen Code не развёрнут, и npm не найден: " + INSTALL_HINT
            )
    elif not works:
        missing.append(f"qwen нашёлся ({binary}), но не отвечает: {version}")
    if not node:
        missing.append("Node.js не найден — Qwen Code написан на нём и без Node.js не поедет")
    elif not node_ok(node):
        missing.append(f"Node.js {node_version(node)} старее нужного (нужен {NODE_MIN}+)")
    if not selection.get("model"):
        missing.append("модель ревьюера ещё не выбрана — выбери провайдера и модель в окне")
    if not agent.is_file():
        missing.append(f"нет файла агента {agent} — ревьюер не поедет в настройки opencode")

    return {
        "binary": binary,
        "binary_where": where,
        "binary_ok": works,
        "version": version,
        "npm": npm or "",
        "node": node or "",
        "node_version": node_version(node) if node else "",
        "agent": agent,
        "selection": selection,
        "ready": not missing,
        "missing": missing,
    }


def status_text(dest: Path) -> str:
    """Строка состояния словами — для окна и командной строки."""
    dest = Path(dest)
    data = check(dest)
    parts: list[str] = []
    if data["binary"] and data["binary_ok"]:
        parts.append(f"Qwen Code есть ({data['binary_where']}: {data['binary']}), {data['version']}")
    elif data["binary"]:
        parts.append(f"Qwen Code есть, но не отвечает: {data['version']}")
    else:
        parts.append("Qwen Code не развёрнут")
    parts.append(f"Node.js: {data['node_version']}" if data["node"] else "Node.js не найден")
    selection = data["selection"]
    if selection.get("model"):
        parts.append(f"ревьюер: {selection.get('provider')} / {selection.get('model')}")
    else:
        parts.append("модель ревьюера не выбрана")
    parts.append("файл агента на месте" if data["agent"].is_file() else "файла агента нет")
    text = "; ".join(parts) + "."
    if data["ready"]:
        return "Готово: " + text
    return "Не готово: " + "; ".join(data["missing"]) + ". (" + text + ")"


# ------------------------------------------------------------------ развёртывание

def deploy_command(dest: Path, npm: str | None = None) -> list[str]:
    """Команда развёртывания: та же установка npm, что в README автора,
    только без -g и в нашу папку."""
    npm = npm or find_npm()
    if not npm:
        return []
    return [npm, "install", "--prefix", str(node_dir(dest)), "--no-audit",
            "--no-fund", f"{PACKAGE}@latest"]


def deploy(dest: Path, progress=None, command: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Ставит Qwen Code в нашу папку. Node.js и npm программа не ставит.

    Установка идёт из npm — тем же пакетом, что и в README автора. Живая
    проверка до записи: без ответа на `--version` развёртывание не считается
    сделанным.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    dest = Path(dest)
    npm = find_npm()
    node = find_node()
    if not npm:
        return messages, [
            "npm не найден: он ставится вместе с Node.js. " + INSTALL_HINT
        ]
    if node and not node_ok(node):
        return messages, [
            f"Node.js {node_version(node)} старее нужного: автор требует "
            f"{NODE_MIN} или новее. Обнови Node.js и повтори."
        ]
    cmd = command or deploy_command(dest, npm)
    if not cmd:
        return messages, ["Команда развёртывания не собралась: нет npm."]

    say(f"Ставлю Qwen Code в свою папку: {node_dir(dest)}")
    say("Команда та же, что в README автора, только без -g и в наши данные.")
    log = _open_log(dest, "развёртывание Qwen Code")
    tail: list[str] = []
    code = -1
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
            env=run_env(dest),
            startupinfo=_hidden_startupinfo(),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            clean = line.rstrip("\n")
            tail.append(clean)
            tail = tail[-40:]
            if log:
                log.write(clean + "\n")
                log.flush()
            say(clean)
        code = proc.wait()
    except OSError as exc:
        return messages, [f"Развёртывание не запустилось: {exc}"]
    finally:
        if log:
            log.write(f"===== развёртывание: код {code} =====\n")
            log.close()

    if code != 0:
        errors.append(f"Развёртывание прервалось, код {code}. Последние строки:")
        errors += [f"  {line}" for line in tail[-6:]]
        errors.append(f"Полный вывод — в файле {log_file(dest)}.")
        return messages, errors

    ok, version = binary_version(dest=dest)
    if not ok:
        return messages, [f"Пакет поставлен, но qwen не отвечает: {version}"]
    say(f"Qwen Code готов: {version}")
    return messages, errors


def installed(dest: Path) -> bool:
    """Включён ли ревьюер — по отметке в манифесте."""
    manifest, _bad = _manifest(dest)
    return bool(manifest.get(MANIFEST_KEY))


def install(dest: Path, progress=None) -> tuple[list[str], list[str]]:
    """Включает ревьюера: живая проверка до записи, потом отметка."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    dest = Path(dest)
    data = check(dest)
    if not data["ready"]:
        return messages, list(data["missing"])

    manifest, bad_manifest = _manifest(dest)
    if bad_manifest:
        return messages, [bad_manifest]
    selection = data["selection"]
    manifest[MANIFEST_KEY] = {
        "source": "QwenLM/qwen-code",
        "provider": selection.get("provider"),
        "model": selection.get("model"),
        "version": data["version"],
    }
    bad = _write_manifest(dest, manifest)
    if bad:
        return messages, [bad]
    say(f"Ревьюер включён: {selection.get('provider')} / {selection.get('model')}.")
    say("Ключ в манифест не попал: он передаётся только в окружение запуска.")
    say(COST_WARNING)
    if selection.get("provider") == "lmarena":
        say(LMARENA_WARNING)
    return messages, errors


def remove(dest: Path, progress=None) -> tuple[list[str], list[str]]:
    """Выключает ревьюера: снимается только наша отметка."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    dest = Path(dest)
    manifest, bad_manifest = _manifest(dest)
    if bad_manifest:
        return messages, [bad_manifest]
    if MANIFEST_KEY not in manifest:
        say("Ревьюер и так выключен — отметки в манифесте нет.")
        return messages, errors
    manifest.pop(MANIFEST_KEY)
    bad = _write_manifest(dest, manifest)
    if bad:
        return messages, [bad]
    say("Ревьюер выключен: отметка снята.")
    say(
        f"Развёрнутый Qwen Code ({DATA_NAME}) и ход споров остались на диске — "
        "их убирает человек, если захочет."
    )
    return messages, errors


# ------------------------------------------------------------------ ревью и спор

REVIEW_PROMPT = (
    "Ты — второй ревьюер. Ниже изменения кода (git diff). Проверь их и "
    "верни замечания по важности: сначала ломающее, потом мелочи. Каждое "
    "замечание — файл, место, что не так и как лучше. Ничего не правь, "
    "файлы не меняй. Отвечай по-русски, коротко, без похвал."
)
DEBATE_PROMPT = (
    "Ты — второй ревьюер в споре с основным агентом. Ниже изменения кода и "
    "ход спора: твои замечания, возражения основного агента с обоснованием. "
    "Ответь по существу: либо согласись и скажи, что именно было не так в "
    "твоём замечании, либо объясни, почему возражение неверно и на чём это "
    "основано. Не правь файлы, только доводы. Отвечай по-русски, коротко."
)
NO_AGREEMENT = (
    "Спор дошёл до предела раундов, а согласия нет. Решение за человеком: "
    "покажи оба довода и спорный фрагмент кода — программа сама решать "
    "не будет."
)


def _open_log(dest: Path, title: str = ""):
    """Журнал. None — открыть не удалось (это не смертельно)."""
    folder = data_dir(dest)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = open(log_file(dest), "a", encoding="utf-8", errors="replace")
    except OSError:
        return None
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log.write(f"\n===== {stamp}{' | ' + title if title else ''} =====\n")
    log.flush()
    return log


def collect(project: Path, base: str = "") -> tuple[dict, str]:
    """Собирает изменения для ревью: diff, статистика и имена новых файлов."""
    project = Path(project)
    if not (project / ".git").exists():
        return {}, f"Это не git-репозиторий: {project}. Ревьюеру нужен git diff."
    cmd = ["git", "-C", str(project), "diff", "--patch"]
    if base:
        cmd.append(base)
    code, out, err = _run_quiet(cmd, timeout=120)
    if code != 0:
        return {}, f"git diff не отработал: {(err or out).strip()[:200]}"
    stat_code, stat_out, _ = _run_quiet(
        ["git", "-C", str(project), "diff", "--stat"], timeout=60)
    status_code, status_out, _ = _run_quiet(
        ["git", "-C", str(project), "status", "--porcelain"], timeout=60)
    untracked = [
        line[3:].strip() for line in (status_out or "").splitlines()
        if line.startswith("??")
    ] if status_code == 0 else []
    if not out.strip() and not untracked:
        return {}, "Нечего показывать: изменений нет"
    return {
        "diff": out,
        "stat": stat_out if stat_code == 0 else "",
        "untracked": untracked,
        "base": base or "HEAD (рабочее дерево)",
    }, ""


def build_prompt(data: dict, extra: str = "") -> str:
    """Текст запроса: статистика, имена новых файлов и сам diff.

    Новые файлы перечисляются именами: содержимое в git diff не попадает,
    и говорить об этом честно важнее, чем молча его терять.
    """
    head = "Изменения (git diff, база: " + data.get("base", "HEAD") + ")\n"
    if data.get("stat"):
        head += "Статистика:\n" + data["stat"].strip() + "\n"
    if data.get("untracked"):
        head += ("Новые файлы (в diff их содержимого нет): "
                 + ", ".join(data["untracked"][:20]) + "\n")
    tail = data.get("diff", "")
    if extra:
        tail += "\n\nХод спора и возражение основного агента:\n" + extra
    return head + "\n" + tail


def run(dest: Path, project: Path, prompt: str, diff_text: str,
        progress=None, command: list[str] | None = None,
        timeout: int = 900) -> tuple[list[str], list[str], dict]:
    """Запускает Qwen Code в headless-режиме и разбирает его ответ.

    Режим — только чтение (`--approval-mode plan`): ревьюер не правит файлы
    и не запускает команды. Ответ забирается в JSON: оттуда же берётся
    расход токенов. Ключ уезжает окружением процесса, а не аргументом.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    dest = Path(dest)
    selection = chosen(dest)
    binary, _where = find_binary(dest)
    if binary is None:
        return messages, ["Qwen Code не развёрнут и не найден в PATH."], {}
    if not selection.get("model"):
        return messages, ["Модель ревьюера не выбрана — выбери её в окне."], {}

    if command is None:
        cmd = [
            str(binary), "-p", prompt, "-o", "json",
            "--approval-mode", "plan", "--auth-type", "openai",
            "-m", str(selection["model"]),
        ]
    else:
        cmd = command
    say("Запускаю ревьюера: " + " ".join(cmd[:4]) + " …")
    log = _open_log(dest, "ревью")
    env = run_env(dest)
    provider_id = str(selection.get("provider") or "")
    key, key_source = provider_key_info(dest, provider_id)
    if not key:
        # Раньше запуск уходил в провайдера без ключа и тот отвечал 401
        # «Invalid API key» — выглядело так, будто сломан ревьюер. Дешевле
        # и честнее сказать сразу, где ключа нет: имя переменной окружения
        # называется по имени, само значение не печатается.
        detail = key_source or "в настройках opencode не задан apiKey"
        if log:
            log.write("Запуск без ключа: у провайдера «"
                      + (provider_id or "?") + "» — " + detail + ".\n")
            log.close()
        return messages, [
            "У провайдера «" + (provider_id or "?") + "» нет ключа: "
            + detail + ". Ревью не запускалось."
        ], {}
    env["OPENAI_API_KEY"] = key
    base = str(selection.get("base_url") or "")
    if base:
        env["OPENAI_BASE_URL"] = base
    env["OPENAI_MODEL"] = str(selection["model"])

    code = -1
    out = err = ""
    try:
        done = subprocess.run(
            cmd, input=diff_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env, timeout=timeout,
            startupinfo=_hidden_startupinfo(),
        )
        code = done.returncode
        # Провайдер в ответе на 401 любит цитировать присланный ключ
        # целиком — без маскирования он уехал бы в журнал и в окно
        # ошибок (так однажды случилось с ключом dahl).
        out = mask_text(done.stdout or "", key)
        err = mask_text(done.stderr or "", key)
    except (OSError, subprocess.SubprocessError) as exc:
        if log:
            log.close()
        return messages, [f"Qwen Code не запустился: {exc}"], {}

    if log:
        log.write("$ " + " ".join(cmd) + "\n")
        if err:
            log.write(err if err.endswith("\n") else err + "\n")
        log.write(f"===== код {code} =====\n")
        log.close()

    result = _parse(out)
    if result.get("error"):
        errors.append("Ревьюер ответил ошибкой: " + result["error"])
        if err.strip():
            errors.append("Строки ошибки: " + err.strip()[:300])
        return messages, errors, result

    text = result.get("text") or ""
    if not text.strip():
        errors.append(f"Ревьюер ответил без текста (код {code}). Полный вывод — в {log_file(dest)}.")
        return messages, errors, result

    say(text.strip())
    usage = result.get("usage") or {}
    if usage:
        say(
            f"Расход за раунд: вход {usage.get('input_tokens', '?')}, "
            f"выход {usage.get('output_tokens', '?')}, "
            f"всего {usage.get('total_tokens', '?')} токенов."
        )
    return messages, errors, result


def _parse(raw: str) -> dict:
    """Разбирает JSON-вывод qwen. Событий может быть несколько."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        events = json.loads(raw)
    except ValueError:
        return {"text": raw}  # не JSON — отдаём как есть
    if isinstance(events, dict):
        events = [events]
    text = ""
    usage: dict = {}
    error = ""
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            if event.get("is_error"):
                error = str(event.get("result") or event.get("subtype") or "ошибка")
            else:
                text = str(event.get("result") or "")
            usage = event.get("usage") or usage
        elif event.get("type") == "assistant" and not text:
            message = event.get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                text = "".join(
                    str(part.get("text", "")) for part in content
                    if isinstance(part, dict)
                )
            elif isinstance(content, str):
                text = content
    return {"text": text, "usage": usage, "error": error}


def debate_state(dest: Path) -> dict:
    """Ход спора с диска. Пустой словарь — спора не было."""
    try:
        return json.loads(debate_file(dest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_debate(dest: Path, state: dict) -> None:
    """Пишет ход спора. Ключа и кода здесь нет — только доводы и числа."""
    try:
        data_dir(dest).mkdir(parents=True, exist_ok=True)
        debate_file(dest).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def review(dest: Path, project: Path, base: str = "", reply: str = "",
           rounds: int = DEFAULT_ROUNDS, progress=None,
           command: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Ревью изменений; в режиме спора — ещё один раунд с возражением.

    Без `reply` это обычная проверка: замечания к `git diff`. С `reply`
    (возражение основного агента с обоснованием) начинается следующий раунд
    спора, и их число ограничено: за пределом раундов программа не зовёт
    ревьюера снова, а отдаёт развилку человеку.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    dest = Path(dest)
    limit = max(1, min(int(rounds or DEFAULT_ROUNDS), MAX_ROUNDS))
    if not installed(dest):
        return messages, [
            "Ревьюер выключен: отметь галочку «Qwen Code — второй ревьюер» "
            "на вкладке opencode."
        ]

    data, bad = collect(Path(project), base)
    if bad:
        return messages, [bad]

    state = debate_state(dest) if reply else {}
    round_no = int(state.get("round") or 0) + 1
    if reply and round_no > limit:
        say(NO_AGREEMENT)
        if state.get("transcript"):
            say("Ход спора:")
            for item in state["transcript"][-limit:]:
                say(f"  раунд {item.get('round')}: {item.get('who')} — "
                    f"{(item.get('text') or '')[:200]}")
        return messages, [
            "Предел раундов исчерпан — программа дальше не спорит. Реши, кто прав, сам."
        ]

    if reply:
        state.setdefault("transcript", []).append({
            "round": round_no, "who": "основной агент", "text": reply})
        say(f"Раунд спора {round_no} из {limit}: передаю возражение ревьюеру.")
    else:
        state = {
            "project": str(Path(project)),
            "base": data.get("base"),
            "round": 0,
            "limit": limit,
            "rounds_spent": [],
            "transcript": [],
        }
        say(f"Проверка изменений: {data.get('base')}. Раундов в запасе: {limit}.")

    extra = ""
    if reply:
        extra = "Твои прежние замечания и ход спора:\n"
        for item in state.get("transcript", []):
            extra += f"[раунд {item.get('round')} — {item.get('who')}]: " \
                     f"{(item.get('text') or '')[:1500]}\n"
    prompt = DEBATE_PROMPT if reply else REVIEW_PROMPT
    _m, errs, result = run(dest, Path(project), prompt, build_prompt(data, extra),
                           progress=progress, command=command)
    if errs:
        return messages, errs

    state["round"] = round_no
    state.setdefault("transcript", []).append({
        "round": round_no, "who": "ревьюер",
        "text": result.get("text") or ""})
    state.setdefault("rounds_spent", []).append(result.get("usage") or {})
    state["limit"] = limit
    if len(state["rounds_spent"]) >= limit:
        state["agreement"] = False
    _save_debate(dest, state)

    total = sum(int((item or {}).get("total_tokens") or 0)
                for item in state.get("rounds_spent", []))
    say(f"Раундов пройдено: {state['round']} из {limit}; токенов за спор: {total}.")
    if state["round"] >= limit:
        say(NO_AGREEMENT)
    return messages, errors


def clear_debate(dest: Path) -> tuple[list[str], list[str]]:
    """Забывает ход спора: следующий запуск начнёт счёт заново."""
    dest = Path(dest)
    try:
        debate_file(dest).unlink(missing_ok=True)
    except OSError as exc:
        return [], [f"Ход спора не убрался: {exc}"]
    return ["Ход спора забыт: следующий запуск начнёт счёт раундов заново."], []


# ------------------------------------------------------------------ манифест

def _manifest(dest: Path) -> tuple[dict, str]:
    """Наш манифест установки. Второе — текст ошибки или пусто."""
    try:
        import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

        return opencode_caps.read_manifest(Path(dest)), ""
    except Exception as exc:  # noqa: BLE001 — сломанный манифест не должен ронять окно
        return {}, f"Манифест не прочитался: {exc}"


def _write_manifest(dest: Path, data: dict) -> str:
    """Пишет манифест. Возвращает текст ошибки или пусто."""
    try:
        import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

        opencode_caps.write_manifest(Path(dest), data)
        return ""
    except Exception as exc:  # noqa: BLE001
        return f"Манифест не записался: {exc}"


# ------------------------------------------------------------------ командная строка

def _say(text: str) -> None:
    print(text)


def _config_dir(argv_dest: str = "") -> Path:
    """Папка настроек opencode: как у остальных модулей."""
    if argv_dest:
        return Path(argv_dest)
    for env in ("OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME"):
        raw = os.environ.get(env)
        if raw:
            candidate = Path(raw)
            if candidate.name == ".config":
                candidate = candidate / "opencode"
            return candidate
    return Path.home() / ".config" / "opencode"


def _main(argv: list[str]) -> int:
    """Командная строка — то же, что кнопки в окне."""
    import argparse  # noqa: PLC0415 — нужен только здесь

    shown: list[str] = []

    def say(text: str) -> None:
        """Как _say, но запоминаем напечатанное: понадобится в done()."""
        shown.append(text)
        _say(text)

    def done(errors: list[str]) -> int:
        """Код возврата и страховка от молчаливого отказа.

        Ошибка, возвращённая из команды, по замыслу ещё не показана:
        команды сообщают через progress (say), а этот список — то,
        что до сих пор никто не вывел на экран. Раньше он просто
        терялся: галочка ревьюера снята, git diff не собрался или
        провайдер вернул 401 — и всё это выглядело как «код 1 и
        ни одного слова». Печатаем только то, чего ещё не было видно,
        чтобы не задваивать уже показанное.

        Строка возврата ниже написана в обход подмены в _main: если
        вписать её раньше, замена накрыла бы её же и вышла рекурсия.
        """
        for item in errors:
            if item not in shown:
                _say(item)
        return 1 if errors else 0

    parser = argparse.ArgumentParser(
        description="qwen-review — второй агент-ревьюер (Qwen Code) над git diff.",
    )
    sub = parser.add_subparsers(dest="what", required=True)

    for name, help_text in (
        ("status", "что готово и чего не хватает"),
        ("check", "то же, что status"),
        ("providers", "провайдеры opencode и их модели"),
        ("install", "включить отметку ревьюера"),
        ("remove", "снять отметку"),
        ("deploy", "развернуть Qwen Code в свою папку"),
        ("forget", "забыть ход спора"),
    ):
        p = sub.add_parser(name, help=help_text)
        if name == "providers":
            p.add_argument("--all", action="store_true",
                           help="показать и тех, кто не подходит")
        if name in ("status", "check", "install", "remove", "deploy", "forget"):
            p.add_argument("--dest", default="", help="папка настроек opencode")

    p_choose = sub.add_parser("choose", help="выбрать провайдера и модель")
    p_choose.add_argument("provider")
    p_choose.add_argument("model")
    p_choose.add_argument("--dest", default="")

    p_check = sub.add_parser("check-models",
                             help="живая проверка доступности моделей провайдера")
    p_check.add_argument("provider")
    p_check.add_argument("--dest", default="")

    p_review = sub.add_parser("review", help="проверить изменения проектом")
    p_review.add_argument("project")
    p_review.add_argument("--base", default="", help="с чем сравнивать (по умолчанию рабочее дерево)")
    p_review.add_argument("--reply", default="", help="возражение основного агента (раунд спора)")
    p_review.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    # Режим строится из общего списка MODES. Пустое значение по умолчанию —
    # прежнее поведение: без --reply это одна проверка, с --reply — раунд
    # спора. Старые вызовы CLI не передают --mode и работают как раньше.
    p_review.add_argument(
        "--mode", default="", choices=[""] + mode_ids(),
        help="режим ревьюера: "
             + "; ".join(f"{mode['id']} — {mode['name']}" for mode in MODES)
             + " (без указания решает --reply: есть возражение — спор)")
    p_review.add_argument("--dest", default="")

    args = parser.parse_args(argv)
    dest = _config_dir(getattr(args, "dest", ""))

    if args.what in ("status", "check"):
        _say(status_text(dest))
        return 0 if check(dest)["ready"] else 1
    if args.what == "providers":
        found = providers(dest)
        if not found:
            _say("В настройках opencode нет ни одного провайдера.")
            return 1
        for item in found:
            mark = "подходит" if item["ok"] else "не подходит: " + item["why"]
            _say(f"{item['id']} ({item['npm'] or 'пакет не указан'}): {mark}")
            if item["models"]:
                _say("    модели: " + ", ".join(item["models"][:10]))
        return 0
    if args.what == "choose":
        messages, errors = choose(dest, args.provider, args.model, progress=say)
        return done(errors)
    if args.what == "check-models":
        results, notes = check_provider_models(dest, args.provider, progress=say)
        if not results:
            _say("Проверка не состоялась.")
            return done(notes)
        counts = {CHECK_OK: 0, CHECK_NO: 0, CHECK_UNKNOWN: 0}
        for model in sorted(results):
            state, reason = results[model]
            counts[state] = counts.get(state, 0) + 1
            _say(f"{CHECK_SYMBOL.get(state, '?')} {model}: "
                 f"{reason or 'отвечает'}")
        _say(f"Итог: {counts.get(CHECK_OK, 0)} ✔, "
             f"{counts.get(CHECK_NO, 0)} ✘, {counts.get(CHECK_UNKNOWN, 0)} ? "
             f"(всего {len(results)}).")
        for note in notes:
            _say(note)
        return done([])
    if args.what == "deploy":
        messages, errors = deploy(dest, progress=say)
        return done(errors)
    if args.what == "install":
        messages, errors = install(dest, progress=say)
        return done(errors)
    if args.what == "remove":
        messages, errors = remove(dest, progress=say)
        return done(errors)
    if args.what == "forget":
        messages, errors = clear_debate(dest)
        return done(errors)
    if args.what == "review":
        # Явный режим из общего списка. Несовместимая пара «once + возражение»
        # отвергается словами: в разовой проверке возражений не бывает.
        mode = str(getattr(args, "mode", "") or "")
        if mode:
            _mode_name = (mode_by_id(mode) or {}).get("name") or mode
            if mode == MODE_ONCE and args.reply:
                _say(f"В режиме «{_mode_name}» возражений не бывает: "
                     "убери --reply или выбери режим " + MODE_DEBATE + ".")
                return 1
        messages, errors = review(
            dest, Path(args.project), args.base, reply=args.reply,
            rounds=args.rounds, progress=say,
        )
        return done(errors)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
