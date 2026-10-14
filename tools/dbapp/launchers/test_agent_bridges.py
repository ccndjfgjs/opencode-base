"""Проверки мостов Spotify, ChatGPT, Codex и Cursor. Сеть и CLI не нужны.

    python tools/dbapp/launchers/test_agent_bridges.py
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent_argv  # noqa: E402
import chatgpt_bridge_launcher as chatgpt  # noqa: E402
import codex_bridge_launcher as codex  # noqa: E402
import spotify_bridge_launcher as spotify  # noqa: E402


def check(ok: bool, text: str) -> None:
    print(("  ok  " if ok else "  FAIL  ") + text)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    check(spotify.PACKAGE == "@xavifabregat/spotify-mcp@0.1.2",
          "Spotify закреплён на 0.1.2, не на @latest")
    check("@latest" not in spotify.PACKAGE, "в пакете Spotify нет @latest")

    body = chatgpt.build_body("model-from-user", "привет")
    check("tools" not in body and body["input"] == "привет",
          "новый ответ не включает чужие инструменты")
    check("previous_response_id" not in body, "новый ответ не тащит старый id")
    continued = chatgpt.build_body("model-from-user", "ещё", "resp_1")
    check(continued["previous_response_id"] == "resp_1",
          "продолжение использует previous_response_id")

    secret = "sk-test-secret"

    def opener(request, timeout=0):
        check(request.full_url == chatgpt.API_URL, "адрес только api.openai.com")
        sent = json.loads(request.data.decode("utf-8"))
        check("tools" not in sent, "в запросе нет tools")
        check(secret not in request.data.decode("utf-8"), "ключ не в теле")
        return io.BytesIO('{"id":"resp_9","output_text":"ok"}'.encode("utf-8"))

    class _Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def good(request, timeout=0):
        opener(request, timeout)
        return _Response('{"id":"resp_9","output_text":"ok"}'.encode("utf-8"))

    ok, note = chatgpt.post_response(secret, body, opener=good)
    check(ok and "resp_9" in note and secret not in note,
          "ответ API разобран, ключ в текст не попал")

    def bad(request, timeout=0):
        raise urllib.error.HTTPError(
            chatgpt.API_URL, 401, "no", None,
            io.BytesIO(f"rejected {secret}".encode("utf-8")),
        )

    ok, note = chatgpt.post_response(secret, body, opener=bad)
    check(not ok and secret not in note, "ошибка API не содержит ключ")

    argv = agent_argv.codex_exec_argv("codex", "посмотри файл", "danger-full-access")
    check("danger-full-access" not in argv and "read-only" in argv,
          "опасная песочница Codex заменяется на чтение")
    check("--yolo" not in argv and "--full-auto" not in argv,
          "у Codex нет --yolo и --full-auto")
    check(agent_argv.codex_queue_argv("codex", "th_1", "дальше")[:2] == ["codex", "queue"],
          "сообщение в старый чат идёт через codex queue")

    thread, text = codex.parse_exec(
        '{"type":"thread.started","thread_id":"th_2"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"сделано"}}\n'
    )
    check(thread == "th_2" and text == "сделано", "JSONL Codex разбирается")

    ask = agent_argv.cursor_send_argv("agent", "chat_1", "объясни", "ask", True)
    check("--force" not in ask and "--yolo" not in ask,
          "режим ask не получает --force, даже если правки попросили")
    edit = agent_argv.cursor_send_argv(
        "agent", "chat_1", "поправь", "agent", True, "/tmp",
    )
    check("--force" in edit and "--yolo" not in edit and "--workspace" in edit,
          "правки Cursor только в режиме агента и по явной просьбе")
    check(agent_argv.cursor_create_argv("agent") == ["agent", "create-chat"],
          "новый чат Cursor — create-chat, без --force")
    check(not agent_argv.plain_prompt("-rf /"), "команда с дефиса не уходит в CLI")
    check(not agent_argv.plain_id("-id"), "идентификатор с дефиса отвергается")
    print("мосты чатов и Spotify: проверки прошли")


if __name__ == "__main__":
    main()
