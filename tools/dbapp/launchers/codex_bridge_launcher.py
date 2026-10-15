"""Мост к официальной команде Codex CLI.

Новый чат — `codex exec`. Сообщение в уже открытый — `codex queue`.
Вход делает сам Codex (`codex login`), эта программа пароль не просит
и сайт не открывает.

Флаги danger-full-access и --yolo не передаются. По умолчанию песочница
только на чтение.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_argv  # noqa: E402
import bridge_common as common  # noqa: E402
import mcp_stdio  # noqa: E402

PREFIX = "codex-bridge"
TIMEOUT = 600


#: Где может лежать CLI Codex. Источники перебираются по очереди, кандидат
#: проверяется запуском `--version`, берётся первый рабочий — а не первый
#: найденный. Пакетные файлы не берём: текст запроса пишет модель.
CODEX_SPEC = common.ProgramSpec(
    name="codex",
    exe_names=("codex",),
    extra_globs=(r"%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe",),
    config_hint=".codex/config.toml:CODEX_CLI_PATH",
    app_paths=(r"%LOCALAPPDATA%\OpenAI\Codex",),
)


def find_codex_detail() -> common.ProgramFound:
    """Подробный итог поиска: путь, источник и что отвергли."""
    return common.find_cli(CODEX_SPEC)


def find_codex() -> str | None:
    """Только путь. None — CLI нет (как и раньше у resolve_exe)."""
    return common.find_cli_path(CODEX_SPEC)


def run_codex(argv: list[str], folder: str | None) -> tuple[int, str, str]:
    """Запускает команду Codex и возвращает код, вывод и ошибки.

    stdin у ребёнка закрыт намеренно. `codex exec` печатает «Reading
    additional input from stdin...» и, получив открытый канал, читает его
    до конца. Без закрытия он съедал поток протокола MCP: вызов висел до
    таймаута, а сообщения opencode терялись. Проверено живьём 15.10.2026 —
    с открытым каналом процесс жил и через 25 секунд.
    """
    code, stdout, stderr, status = common.run_capture(
        argv, cwd=folder, timeout=TIMEOUT)
    if status:
        # Таймаут и неудачная остановка — разные статусы, а не одна строка:
        # во втором случае какие-то процессы могли остаться работать.
        note = common.stop_status_text(status, "Codex", TIMEOUT)
        return code if code is not None else 1, "", note or stderr
    return code, stdout, stderr


def parse_exec(stdout: str) -> tuple[str, str]:
    thread_id = ""
    messages: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started":
            thread_id = str(event.get("thread_id") or thread_id)
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = str(item.get("text") or "").strip()
            if text:
                messages.append(text)
    final = messages[-1] if messages else ""
    return thread_id, final


#: Признаки отказа во входе в тексте самой программы. Не выдуманы: сняты
#: с живого ответа codex 15.10.2026 после `codex login status`.
AUTH_MARKS = (
    "invalid_refresh_token",
    "please log out and sign in again",
    "failed to refresh token",
    "could not parse your authentication token",
)


def login_hint(text: str) -> str:
    """Человеческая строка, если текст пахнет отказом во входе."""
    low = text.lower()
    if any(mark in low for mark in AUTH_MARKS):
        return "Вход в Codex не сработал. Войди сам: codex login."
    return ""


TOOLS = [
    {
        "name": "codex_new_chat",
        "description": "Новый неинтерактивный чат Codex CLI. Сайт не открывается.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "sandbox": {"type": "string", "enum": ["read-only", "workspace-write"]},
                "workspace": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "codex_send",
        "description": "Поставить текст в уже существующий чат Codex. Ответ не ждётся.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["thread_id", "message"],
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    detail = find_codex_detail()
    exe = detail.path or None
    if not exe:
        return ("Команда codex не найдена. Её ставит winget OpenAI.Codex, "
                f"вход — codex login. Подробности: {detail.reason}")
    folder = agent_argv.workspace_dir(str(args.get("workspace") or ""))
    if str(args.get("workspace") or "").strip() and folder is None:
        return "Папка workspace не существует. Чужой путь не подставляю."
    if name == "codex_new_chat":
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return "Пустую команду не отправляю."
        if len(prompt) > 8000:
            return "Команда длиннее 8000 символов. Сократи."
        argv = agent_argv.codex_exec_argv(
            exe, prompt, str(args.get("sandbox") or "read-only"),
        )
        code, stdout, stderr = run_codex(argv, folder)
        thread_id, final = parse_exec(stdout)
        hint = login_hint(f"{stdout}\n{stderr}")
        if not final:
            final = (stderr or stdout or "Codex не вернул текст.").strip()[:2000]
        head = f"thread_id: {thread_id or 'нет в ответе'}\nкод: {code}\n\n"
        if hint:
            head = hint + "\n\n" + head
        return head + final[:8000]
    if name == "codex_send":
        thread_id = str(args.get("thread_id") or "").strip()
        message = str(args.get("message") or "").strip()
        if not agent_argv.plain_id(thread_id) or not agent_argv.plain_prompt(message):
            return "Нужны thread_id без пробелов и текст без дефиса в начале."
        argv = agent_argv.codex_queue_argv(exe, thread_id, message)
        code, stdout, stderr = run_codex(argv, folder)
        if code != 0:
            return (stderr or stdout or "Codex не принял сообщение.").strip()[:2000]
        return (
            "Сообщение поставлено в чат. Ответ этой командой не ждётся: "
            "так устроена официальная команда codex queue."
        )
    return "Такого инструмента нет."


def main() -> int:
    detail = find_codex_detail()
    exe = detail.path or None
    if not exe:
        common.say(PREFIX, "команда codex не найдена")
        common.say(PREFIX, f"подробности: {detail.reason}")
        common.say(PREFIX, "winget id OpenAI.Codex, затем codex login. Пароль программа не спрашивает.")
        return 1
    common.say(PREFIX, f"codex найден: {exe} (источник: {detail.from_source})")
    common.say(PREFIX, "danger-full-access и --yolo не передаю")
    # `login status` только читает состояние: ни входа, ни запроса к модели.
    code, text = common.probe_command([exe, "login", "status"], timeout=20)
    if code == 0:
        common.say(PREFIX, f"вход есть: {(text.splitlines() or ['Logged in'])[-1].strip()}")
    elif code is not None and "not logged in" in text.lower():
        common.say(PREFIX, "входа нет. Ответы не придут, пока не войдёшь: codex login")
    else:
        common.say(PREFIX, "состояние входа команда не подтвердила")
    common.say(PREFIX, "живой запрос к модели при старте не делаю")
    return mcp_stdio.serve("codex-cli", TOOLS, call_tool)


if __name__ == "__main__":
    sys.exit(main())
