"""Мост к официальному API ChatGPT, не к сайту chatgpt.com.

Создаёт ответ и продолжает его через previous_response_id.
Адрес только https://api.openai.com/v1/responses. Браузер, куки и
вход в чужой аккаунт сюда не входят.

Ключ и имя модели лежат в mcp-chatgpt.txt. В stderr их нет.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402
import mcp_stdio  # noqa: E402

PREFIX = "chatgpt-bridge"
API_URL = "https://api.openai.com/v1/responses"
KEY_NAME = "OPENAI_API_KEY"
MODEL_NAME = "OPENAI_MODEL"


def settings_file() -> Path:
    return common.settings_dir() / "mcp-chatgpt.txt"


def load_settings() -> tuple[str, str]:
    values = common.parse_kv(common.read_text(settings_file()))
    return values.get(KEY_NAME, "").strip(), values.get(MODEL_NAME, "").strip()


def build_body(model: str, text: str, previous: str = "") -> dict:
    body: dict = {"model": model, "input": text, "store": True}
    if previous:
        body["previous_response_id"] = previous
    return body


def output_text(data: dict) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("output_text", "text"):
                parts.append(str(block.get("text") or ""))
    return "\n".join(part for part in parts if part).strip()


def redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "[скрыто]")
    return text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_response(key: str, body: dict, opener=None) -> tuple[bool, str]:
    raw = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=raw,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    if opener is None:
        opener = urllib.request.build_opener(_NoRedirect).open
    open_url = opener
    try:
        with open_url(request, timeout=120) as response:
            payload = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return False, redact(f"API ответил {exc.code}: {detail}", key)
    except Exception as exc:  # noqa: BLE001
        return False, redact(f"запрос не дошёл: {exc}", key)
    if status >= 300:
        return False, redact(f"API ответил {status}", key)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False, "ответ API не разобрался"
    if not isinstance(data, dict):
        return False, "ответ API пустой"
    text = output_text(data)
    response_id = str(data.get("id") or "")
    if not text:
        text = "Текст ответа пустой."
    if len(text) > 8000:
        text = text[:8000] + "\n…обрезано"
    return True, f"id: {response_id}\n\n{text}"


TOOLS = [
    {
        "name": "chatgpt_new_chat",
        "description": "Новый ответ в официальном API. Это не чат на сайте chatgpt.com.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "chatgpt_continue",
        "description": "Продолжить ответ по id предыдущего. Сайт ChatGPT не открывается.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "previous_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["previous_id", "text"],
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    key, model = load_settings()
    if not key or not model:
        raise RuntimeError(
            f"Нет ключа или модели в {settings_file()}. "
            "Сайт chatgpt.com этот мост не открывает."
        )
    text = str(args.get("text") or "").strip()
    if not text:
        return "Пустую команду не отправляю."
    previous = str(args.get("previous_id") or "").strip()
    if name == "chatgpt_continue" and not previous:
        return "Нужен previous_id прошлого ответа."
    if name not in ("chatgpt_new_chat", "chatgpt_continue"):
        return "Такого инструмента нет."
    ok, note = post_response(
        key, build_body(model, text, previous if name == "chatgpt_continue" else ""),
    )
    if not ok:
        raise RuntimeError(note)
    return note


def main() -> int:
    key, model = load_settings()
    if not key or not model:
        common.say(PREFIX, f"нет ключа или модели: {settings_file()}")
        common.say(PREFIX, "Две строки: OPENAI_API_KEY и OPENAI_MODEL.")
        common.say(PREFIX, "Значения в журнал не пишу. Сайт chatgpt.com не открываю.")
        return 1
    common.say(PREFIX, "ключ прочитан, в журнал не пишу")
    common.say(PREFIX, "адрес только api.openai.com, живой запрос при старте не делаю")
    return mcp_stdio.serve("chatgpt-api", TOOLS, call_tool)


if __name__ == "__main__":
    sys.exit(main())
