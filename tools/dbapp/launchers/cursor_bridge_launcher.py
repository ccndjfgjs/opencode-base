"""Мост к официальной команде Cursor CLI `agent`.

Новый чат — `agent create-chat`. Команда в него — `agent -p --resume`.
Без явной просьбы править файлы флаг --force не ставится. --yolo нет.
Ключ, если он записан, уходит в переменную, не в командную строку и не в журнал.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_argv  # noqa: E402
import bridge_common as common  # noqa: E402
import mcp_stdio  # noqa: E402

PREFIX = "cursor-bridge"
TIMEOUT = 600


def settings_file() -> Path:
    return common.settings_dir() / "mcp-cursor.txt"


def find_agent() -> str | None:
    return common.resolve_exe("agent")


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    values = common.parse_kv(common.read_text(settings_file()))
    key = values.get("CURSOR_API_KEY", "").strip()
    if key:
        env["CURSOR_API_KEY"] = key
    return env


def run_agent(argv: list[str], folder: str | None) -> tuple[int, str, str]:
    prepared = common.prepare_argv(argv)
    try:
        done = subprocess.run(
            prepared,
            cwd=folder,
            env=child_env(),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return 1, "", f"Cursor не ответил за {TIMEOUT} секунд."
    except OSError as exc:
        return 1, "", f"Cursor не запустился: {exc}"
    return done.returncode, done.stdout or "", done.stderr or ""


TOOLS = [
    {
        "name": "cursor_new_chat",
        "description": "Создать пустой чат Cursor CLI и вернуть его id.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "cursor_send",
        "description": "Отправить текст в чат Cursor. Правка файлов только по явной просьбе.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "prompt": {"type": "string"},
                "mode": {"type": "string", "enum": ["ask", "plan", "agent"]},
                "allow_edits": {"type": "boolean"},
                "workspace": {"type": "string"},
            },
            "required": ["chat_id", "prompt"],
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    exe = find_agent()
    if not exe:
        return "Команда agent не найдена. Это Cursor CLI, не любой agent.exe."
    if name == "cursor_new_chat":
        code, stdout, stderr = run_agent(agent_argv.cursor_create_argv(exe), None)
        chat_id = stdout.strip().splitlines()[-1].strip() if stdout.strip() else ""
        if code != 0 or not chat_id:
            return (stderr or stdout or "Пустой чат не создался.").strip()[:2000]
        return f"chat_id: {chat_id}"
    if name == "cursor_send":
        chat_id = str(args.get("chat_id") or "").strip()
        prompt = str(args.get("prompt") or "").strip()
        if not agent_argv.plain_id(chat_id) or not agent_argv.plain_prompt(prompt):
            return "Нужны chat_id без пробелов и текст без дефиса в начале."
        folder = agent_argv.workspace_dir(str(args.get("workspace") or ""))
        if str(args.get("workspace") or "").strip() and folder is None:
            return "Папка workspace не существует."
        argv = agent_argv.cursor_send_argv(
            exe, chat_id, prompt,
            str(args.get("mode") or "ask"),
            bool(args.get("allow_edits")),
            folder or "",
        )
        code, stdout, stderr = run_agent(argv, folder)
        text = (stdout or stderr or "Cursor не вернул текст.").strip()
        if len(text) > 8000:
            text = text[:8000] + "\n…обрезано"
        return f"код: {code}\n\n{text}"
    return "Такого инструмента нет."


def main() -> int:
    if not find_agent():
        common.say(PREFIX, "команда agent не найдена")
        common.say(PREFIX, "Это Cursor CLI. Установка описана на cursor.com/docs/cli/installation.")
        return 1
    values = common.parse_kv(common.read_text(settings_file()))
    if values.get("CURSOR_API_KEY", "").strip():
        common.say(PREFIX, "ключ прочитан, в журнал и в командную строку не пишу")
    else:
        common.say(PREFIX, "ключа в файле нет, Cursor возьмёт свой вход, если он уже есть")
    common.say(PREFIX, "--yolo не передаю. --force только если явно попросили правки")
    return mcp_stdio.serve("cursor-cli", TOOLS, call_tool)


if __name__ == "__main__":
    sys.exit(main())
