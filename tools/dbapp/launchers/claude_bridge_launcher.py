"""Мост к Claude Code CLI.

Новый чат — `claude -p`. Продолжение — тот же вызов плюс `--resume`.
Вход делает человек сам (`claude auth login`): мост запускает только
проверку `claude auth status` и никогда — саму команду входа.

Ограничения, которые собираются заново на КАЖДЫЙ вызов:
  * `--permission-mode plan` — модель не правит исходные файлы;
  * `--permission-prompts none` — хост не опрашивается и не ждётся;
  * `--disallowedTools` и четыре имени ПЯТЬЮ отдельными аргументами argv.

Честно о границе: ограничения сужают набор действий, но НЕ дают полной
защиты от изменения файлов. Команды оболочки с перенаправлением, `find
-delete` и подпроцессы Claude Code по документации не проверяет. Мост
поэтому никогда не говорит, что папка защищена, и предупреждает об этом
постоянно, а не только когда запрос «явно про правку».

`--bare` не передаём: в этом режиме Claude Code не читает OAuth и работает
только по ANTHROPIC_API_KEY, то есть мы потеряли бы вход по подписке.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_argv  # noqa: E402
import bridge_common as common  # noqa: E402
import mcp_stdio  # noqa: E402

PREFIX = "claude-bridge"
TIMEOUT = 600
#: Слишком длинный ответ обрезаем: в ответ MCP столько не влезет.
DETAIL_LIMIT = 2000
#: Версия, начиная с которой есть `--permission-prompts none`. Ниже неё
#: ограничения оказались бы слабее заявленных, поэтому мост не запускает вызов.
MIN_VERSION = (2, 1, 259)

#: Инструменты правки. Список отдельными аргументами, НЕ через запятую:
#: документация показывает либо несколько отдельных имён, либо одну маску.
#: Форма «четыре имени через запятую» не встречается, и если CLI посчитает её
#: одним именем, запрет молча не сработает.
DENIED_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")

CLAUDE_SPEC = common.ProgramSpec(
    name="claude",
    exe_names=("claude",),
    extra_globs=(r"%LOCALAPPDATA%\Programs\claude\claude.exe",
                 r"%LOCALAPPDATA%\Programs\Claude\claude.exe",
                 r"%ProgramFiles%\Claude\claude.exe"),
    app_paths=(r"%LOCALAPPDATA%\Claude", r"%APPDATA%\Claude"),
)

SECRET_MARK = "[скрыто]"


@dataclass
class CallResult:
    """Один внутренний формат на всё: ответ, журнал и строка таблицы."""

    status: str = "ок"
    exit_code: int | None = None
    text: str = ""
    detail: str = ""
    session_id: str = ""
    reason: str = ""

    @property
    def failed(self) -> bool:
        return self.status != "ок"


def find_claude_detail() -> common.ProgramFound:
    return common.find_cli(CLAUDE_SPEC)


def find_claude() -> str | None:
    return common.find_cli_path(CLAUDE_SPEC)


def claude_argv(exe: str, prompt: str, resume: str = "") -> list[str]:
    """Собирает полный набор ограничений заново, на каждый вызов.

    Первым идёт абсолютный путь к найденному .exe: если передать имя,
    prepare_argv снова пройдёт PATH и может выбрать .cmd, который мост
    только что отверг.
    """
    argv = [exe, "-p", prompt, "--output-format", "json",
            "--permission-mode", "plan",
            "--permission-prompts", "none"]
    argv.append("--disallowedTools")
    argv.extend(DENIED_TOOLS)
    if resume:
        argv.extend(["--resume", resume])
    return argv


def claude_version(exe: str) -> tuple[int, ...] | None:
    """Версия CLI. None — не прочиталась, и это НЕ «совместимая версия»."""
    code, text = common.probe_command([exe, "--version"], timeout=15)
    if code != 0 or not text:
        return None
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not found:
        return None
    return tuple(int(part) for part in found.groups())


def compatible(version: tuple[int, ...] | None) -> bool:
    if version is None:
        return False
    width = max(len(version), len(MIN_VERSION))
    left = tuple(version) + (0,) * (width - len(version))
    right = MIN_VERSION + (0,) * (width - len(MIN_VERSION))
    return left >= right


# ---------------------------------------------------------------------------
# Фильтр секретов. Отказоустойчивый: лучше не показать диагностику, чем
# показать её неотфильтрованной.
# ---------------------------------------------------------------------------


def secret_representations(secret: str) -> list[str]:
    """Все формы, в которых секрет может встретиться в тексте."""
    if not secret:
        return []
    forms = [secret, urllib.parse.quote(secret, safe=""),
             urllib.parse.quote_plus(secret)]
    forms.append(secret.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;"))
    out = []
    for form in forms:
        if form and form not in out:
            out.append(form)
    return out


def filter_secrets(text: str, secrets: list[str]) -> str:
    """Заменяет секрет во всех его формах. Не строки — возвращает пусто."""
    if not isinstance(text, str):
        return ""
    for secret in secrets:
        for form in secret_representations(secret):
            if form and form in text:
                text = text.replace(form, SECRET_MARK)
    return text


def known_secret() -> str:
    """Значение ключа, если оно есть. В журнал не пишется никогда."""
    values = common.parse_kv(common.read_text(common.settings_dir() / "mcp-claude.txt"))
    return (values.get("CLAUDE_SECRET") or values.get("ANTHROPIC_API_KEY")
            or "").strip()


# ---------------------------------------------------------------------------
# Разбор ответа. Шесть вещей разбираются раздельно.
# ---------------------------------------------------------------------------


def parse_claude(stdout: str) -> tuple[dict | None, str, str]:
    """Возвращает (json, result, session_id). JSON только из корректного."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None, "", ""
    if not isinstance(data, dict):
        return None, "", ""
    result = data.get("result")
    session = data.get("session_id")
    return data, (str(result) if isinstance(result, str) else ""), (
        str(session) if isinstance(session, str) else "")


def build_result(code: int | None, stdout: str, stderr: str,
                 status: str, program: str = "Claude") -> CallResult:
    """Единый результат вызова. Ни одна ошибка не выглядит как ответ модели."""
    if status and status != "не_запустился":
        detail = common.stop_status_text(status, program, TIMEOUT)
        return CallResult(status=status, exit_code=code, text=detail,
                          detail=detail,
                          reason=("процесс остановлен принудительно" if status == "таймаут"
                                  else "процесс мог остаться работать"))

    text = (stderr or stdout or "").strip()
    if status == "не_запустился":
        return CallResult(status="не_запустился", exit_code=None,
                          text=text or f"{program} не запустился.",
                          detail=text, reason="запуск не удался")

    data, result, session = parse_claude(stdout or "")

    if code == 0 and data is not None:
        if result:
            return CallResult(status="ок", exit_code=code, text=result,
                              session_id=session)
        return CallResult(status="ошибка_разбора", exit_code=code,
                          text=f"{program} не вернул текст.",
                          session_id=session,
                          reason="поле result пустое")

    if code == 0:
        return CallResult(status="ошибка_разбора", exit_code=code,
                          text="Ответ не разобрался: это не JSON.",
                          detail=text[:DETAIL_LIMIT],
                          reason="stdout не является корректным JSON")

    # Код ненулевой. Корректный JSON разбираем, но успехом это не считаем.
    note = f"{program} ответил кодом {code}."
    parts = []
    if data is not None and result:
        parts.append("текст из результата:\n" + result[:DETAIL_LIMIT])
    if stderr.strip():
        parts.append("из stderr:\n" + stderr.strip()[:DETAIL_LIMIT])
    if stdout.strip():
        parts.append("из stdout:\n" + stdout.strip()[:DETAIL_LIMIT])
    # Обрезаем итог, а не куски: склейка частей снова дала бы строку
    # длиннее лимита, а лимит в 2000 символов — это про ответ целиком.
    detail = "\n\n".join(parts)[:DETAIL_LIMIT]
    return CallResult(status="ошибка_процесса", exit_code=code, text=note,
                      detail=detail, session_id=session,
                      reason="программа завершилась с ненулевым кодом")


def auth_state(exe: str) -> tuple[str, str]:
    """Проверка входа. Команда входа не запускается никогда.

    Код 1 — это «входа нет». Любой другой ненулевой код и нечитаемый вывод —
    «проверка упала», и это НЕ то же самое: иначе человек получит «войди»
    там, где CLI просто сломана.
    """
    code, text = common.probe_command([exe, "auth", "status"], timeout=20)
    if code == 0:
        method = ""
        match = re.search(r"authMethod[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_.-]+)", text)
        if match:
            method = f" (вход: {match.group(1)})"
        return "есть", f"вход есть{method}"
    if code == 1:
        return "нет", "входа нет, войди сам: claude auth login"
    return "неизвестно", "вход проверить не удалось: команда не ответила как ожидалось"


#: Предупреждение — постоянное свойство моста, а не реакция на текст запроса.
SAFETY_NOTE = (
    "Действую в ограниченном режиме: файлы не правлю инструментами, но "
    "абсолютной защиты от изменений нет."
)

TOOLS = [
    {
        "name": "claude_new_chat",
        "description": (
            "Новый неинтерактивный чат Claude Code CLI. " + SAFETY_NOTE +
            " Сайт не открывается."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "workspace": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "claude_send",
        "description": (
            "Продолжить уже начатый разговор Claude Code по его id. " +
            SAFETY_NOTE + " Продолжение доступно только если есть session_id."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "message": {"type": "string"},
                "workspace": {"type": "string"},
            },
            "required": ["session_id", "message"],
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    detail = find_claude_detail()
    if not detail.path:
        return ("Claude Code не найден. " + SAFETY_NOTE +
                f" Подробности: {detail.reason}")
    exe = detail.path

    version = claude_version(exe)
    if version is None:
        return ("Версию Claude Code прочитать не удалось, ограничения не "
                f"проверены, вызов не запускаю. {SAFETY_NOTE}")
    if not compatible(version):
        found = ".".join(str(x) for x in version)
        need = ".".join(str(x) for x in MIN_VERSION)
        return (f"Claude Code версии {found}, а нужно {need}: без этого мост "
                f"не может включить ограничения, о которых говорит. "
                f"{SAFETY_NOTE}")

    folder = agent_argv.workspace_dir(str(args.get("workspace") or ""))
    if str(args.get("workspace") or "").strip() and folder is None:
        return "Папка workspace не существует. Чужой путь не подставляю."

    prompt = str(args.get("message") if name == "claude_send"
                 else args.get("prompt") or "").strip()
    if not prompt:
        return "Пустую команду не отправляю."
    if len(prompt) > 8000:
        return "Команда длиннее 8000 символов. Сократи."

    resume = ""
    if name == "claude_send":
        resume = str(args.get("session_id") or "").strip()
        if not agent_argv.plain_id(resume):
            return "Нужен session_id без пробелов и без ведущего дефиса."
        if not agent_argv.plain_prompt(prompt):
            return "Текст не должен начинаться с дефиса."

    argv = claude_argv(exe, prompt, resume)
    code, stdout, stderr, status = common.run_capture(
        argv, cwd=folder, timeout=TIMEOUT)
    result = build_result(code, stdout, stderr, status)

    # Фильтр идёт ДО журнала: сырой stderr в журнал не пишется ни разу.
    secret = known_secret()
    secrets = [secret] if secret else []
    result.detail = filter_secrets(result.detail, secrets)
    result.text = filter_secrets(result.text, secrets)
    common.say(PREFIX, f"{name}: статус {result.status}, код {result.exit_code}")

    head = result.text
    if result.failed:
        head = f"{result.text}"
        if result.session_id:
            head += (f"\n\nдиагностика: id сессии {result.session_id} "
                     "вернулся, но разговор не считается созданным.")
        if result.detail:
            head += "\n\n" + result.detail
        return head[:8000]
    return (result.text + (f"\n\nsession_id: {result.session_id}"
                          if result.session_id else ""))[:8000]


def main() -> int:
    detail = find_claude_detail()
    exe = detail.path or None
    if not exe:
        common.say(PREFIX, "Claude Code не найден")
        common.say(PREFIX, f"подробности: {detail.reason}")
        common.say(PREFIX, "установку не делаю: поставь Claude Code сам, "
                          "официальные команды — в docs.claude.com")
        common.say(PREFIX, SAFETY_NOTE)
        return 1
    common.say(PREFIX, f"claude найден: {exe} (источник: {detail.from_source})")
    common.say(PREFIX, "bypassPermissions и --dangerously-skip-permissions "
                       "не передаю никогда")
    version = claude_version(exe)
    if version is None:
        common.say(PREFIX, "версию прочитать не удалось: ограничения не проверены")
    else:
        found = ".".join(str(x) for x in version)
        need = ".".join(str(x) for x in MIN_VERSION)
        common.say(PREFIX, f"версия {found}, нужно {need} или новее")
    state, note = auth_state(exe) if exe else ("неизвестно", "")
    common.say(PREFIX, f"вход: {state}; {note}")
    common.say(PREFIX, SAFETY_NOTE)
    return mcp_stdio.serve("claude-code", TOOLS, call_tool)


if __name__ == "__main__":
    sys.exit(main())
