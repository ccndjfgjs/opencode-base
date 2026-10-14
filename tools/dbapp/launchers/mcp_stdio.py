"""Минимальный stdio-сервер MCP. Только то, что нужно своим лаунчерам.

Сообщения — JSON на строку. Если клиент прислал старый заголовок
Content-Length, он тоже читается. Журнал в stdout не пишется: там протокол.
"""

from __future__ import annotations

import json
import sys
from typing import Callable


def read_message() -> dict | None:
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    if line.lower().startswith(b"content-length:"):
        length = int(line.split(b":", 1)[1].strip() or b"0")
        while True:
            header = sys.stdin.buffer.readline()
            if header in (b"\r\n", b"\n", b""):
                break
        body = sys.stdin.buffer.read(length)
        data = json.loads(body.decode("utf-8"))
        return data if isinstance(data, dict) else None
    text = line.decode("utf-8").strip()
    if not text:
        return read_message()
    data = json.loads(text)
    return data if isinstance(data, dict) else None


def write_message(payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def reply(request_id: object, result: object) -> None:
    write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def fail(request_id: object, message: str) -> None:
    write_message({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32000, "message": message},
    })


def tool_result(text: str, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def serve(name: str, tools: list[dict],
          call: Callable[[str, dict], str]) -> int:
    """Крутит протокол, пока stdin не закроется."""
    while True:
        try:
            message = read_message()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            continue
        if message is None:
            return 0
        method = str(message.get("method") or "")
        request_id = message.get("id")
        if request_id is None:
            continue
        if method == "initialize":
            reply(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": name, "version": "1.0.0"},
            })
            continue
        if method == "tools/list":
            reply(request_id, {"tools": tools})
            continue
        if method == "tools/call":
            params = message.get("params") or {}
            tool = str(params.get("name") or "")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            try:
                text = call(tool, args)
                reply(request_id, tool_result(text, False))
            except Exception as exc:  # noqa: BLE001 — клиенту нужна ошибка, не падение
                reply(request_id, tool_result(str(exc), True))
            continue
        fail(request_id, f"метод не поддерживается: {method}")
