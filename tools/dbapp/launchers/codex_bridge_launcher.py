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


def find_codex() -> str | None:
    return common.resolve_exe("codex")


def run_codex(argv: list[str], folder: str | None) -> tuple[int, str, str]:
    prepared = common.prepare_argv(argv)
    try:
        done = subprocess.run(
            prepared,
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return 1, "", f"Codex не ответил за {TIMEOUT} секунд."
    except OSError as exc:
        return 1, "", f"Codex не запустился: {exc}"
    return done.returncode, done.stdout or "", done.stderr or ""


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
    exe = find_codex()
    if not exe:
        return "Команда codex не найдена. Её ставит winget OpenAI.Codex, вход — codex login."
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
        if not final:
            final = (stderr or stdout or "Codex не вернул текст.").strip()[:2000]
        head = f"thread_id: {thread_id or 'нет в ответе'}\nкод: {code}\n\n"
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
    if not find_codex():
        common.say(PREFIX, "команда codex не найдена")
        common.say(PREFIX, "winget id OpenAI.Codex, затем codex login. Пароль программа не спрашивает.")
        return 1
    common.say(PREFIX, "codex найден. danger-full-access и --yolo не передаю")
    common.say(PREFIX, "живой запрос при старте не делаю")
    return mcp_stdio.serve("codex-cli", TOOLS, call_tool)


if __name__ == "__main__":
    sys.exit(main())
