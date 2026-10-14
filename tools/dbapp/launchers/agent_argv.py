"""Аргументы для официальных команд Codex и Cursor.

Список, не строка оболочки. Опасные флаги сюда не попадают, даже если
их попросили: --yolo, --force по умолчанию и danger-full-access.
"""

from __future__ import annotations

from pathlib import Path

CODEX_SANDBOXES = ("read-only", "workspace-write")
CURSOR_MODES = ("ask", "plan", "agent")


def workspace_dir(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    folder = Path(raw)
    if not folder.is_dir():
        return None
    return str(folder)


def plain_id(text: str) -> bool:
    """Идентификатор чата, не флаг и не несколько аргументов."""
    value = (text or "").strip()
    if not value or value.startswith("-") or any(ch.isspace() for ch in value):
        return False
    return True


def plain_prompt(text: str) -> bool:
    """Текст команды. С дефиса не начинается: CLI принял бы его за флаг."""
    value = (text or "").strip()
    return bool(value) and not value.startswith("-") and len(value) <= 8000


def codex_exec_argv(exe: str, prompt: str, sandbox: str) -> list[str]:
    mode = sandbox if sandbox in CODEX_SANDBOXES else "read-only"
    return [exe, "exec", "--json", "--sandbox", mode, prompt]


def codex_queue_argv(exe: str, thread_id: str, message: str) -> list[str]:
    return [
        exe, "queue", "--thread", thread_id, "--message", message,
    ]


def cursor_create_argv(exe: str) -> list[str]:
    return [exe, "create-chat"]


def cursor_send_argv(exe: str, chat_id: str, prompt: str, mode: str,
                     allow_edits: bool, workspace: str = "") -> list[str]:
    picked = mode if mode in CURSOR_MODES else "ask"
    argv = [
        exe, "-p", "--trust", "--resume", chat_id,
        "--mode", picked, "--output-format", "text", prompt,
    ]
    # Правка файлов только если человек явно попросил режим агента и правки.
    if allow_edits and picked == "agent":
        argv.insert(2, "--force")
    if workspace:
        argv[1:1] = ["--workspace", workspace]
    return argv
