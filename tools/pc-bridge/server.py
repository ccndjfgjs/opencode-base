# -*- coding: utf-8 -*-
"""Мост ПК для opencode (MCP, stdio, только стандартная библиотека Python).

Простыми словами: даёт opencode глаза и руки — но пока только БЕЗОПАСНЫЕ:
читать файлы, смотреть список программ, делать скриншот. Ничего менять,
запускать или удалять этот мост НЕ умеет специально.

Инструменты (все только читают, ничего не меняют):
    pc_status      — состояние: папка, Python, размер экрана, время;
    pc_files_read  — прочитать текстовый файл (только внутри разрешённых папок);
    pc_apps_list   — список запущенных программ (как Диспетчер задач);
    pc_screenshot  — скриншот экрана в файл BMP (посмотреть глазами).

Запретные зоны (отказ всегда, даже если попросят):
    * папки-бэкапы (*бэкап*, *backup*), testmodhas, node_modules, npm;
    * чужие профили и системные папки Windows.

Запуск:
    server.py               — сервер MCP (так запускает opencode)
    server.py --selftest    — проверка на этом ПК
    server.py --print-config — кусок настроек для opencode.jsonc

Подключение в opencode.jsonc:
    "mcp": { "pc": { "type": "local",
        "command": ["python", "C:/.../Python/pc_bridge_server.py"],
        "enabled": true } },
    "permission": { "pc_*": "ask" }
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import struct
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

# Куда смотреть можно по умолчанию: только наша рабочая папка.
DEFAULT_ALLOWED = [str(HERE)]

# Подстроки в пути, при которых читаем отказ (регистр не важен).
DENIED_PARTS = (
    "бэкап", "backup", "testmodhas", "node_modules", ".git",
    "appdata\\roaming\\npm", "system32", "syswow64", "windows\\system",
)

MAX_FILE_BYTES = 200_000
MAX_FILE_LINES = 2000


def log(text: str) -> None:
    try:
        sys.stderr.write(f"[pc] {text}\n")
        sys.stderr.flush()
    except Exception:
        pass


class PcError(Exception):
    """Понятная ошибка — текст показывается человеку как есть."""


# ------------------------------------------------------------------ настройки


def read_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("server_name", "pc")
    data.setdefault("server_version", "0.1.0")
    data.setdefault("allowed_dirs", DEFAULT_ALLOWED)
    data.setdefault("shots_dir", str(HERE / "shots"))
    return _expand_placeholders(data)


# Пометки в config.json. В образце моста не должно быть чужих путей,
# поэтому там лежат пометки, а мост разворачивает их в свои папки.
# {{BASE}} — сама база (на уровень выше tools\pc-bridge), {{HERE}} — папка моста.
PLACEHOLDERS = {
    "{{BASE}}": HERE.parent.parent,
    "{{HERE}}": HERE,
}


def _expand_placeholders(data: dict) -> dict:
    """Разворачивает пометки в путях. Неизвестные оставляет как есть."""
    for key in ("allowed_dirs", "shots_dir"):
        raw = data.get(key)
        if isinstance(raw, list):
            data[key] = [_expand_path(str(item)) for item in raw]
        elif isinstance(raw, str):
            data[key] = _expand_path(raw)
    return data


def _expand_path(raw: str) -> str:
    for mark, real in PLACEHOLDERS.items():
        if mark in raw:
            return raw.replace(mark, str(real))
    return raw


def allowed_dirs(config: dict) -> list[Path]:
    out = []
    for raw in config.get("allowed_dirs") or []:
        try:
            out.append(Path(str(raw)).resolve())
        except OSError:
            continue
    return out


def check_path(path: Path, config: dict) -> Path:
    """Проверяет путь: существует, текст, внутри разрешённого, вне запретного."""
    try:
        real = path.resolve()
    except OSError as exc:
        raise PcError(f"Путь не читается: {path} ({exc})")
    low = str(real).casefold()
    for bad in DENIED_PARTS:
        if bad in low:
            raise PcError(f"Запретная зона ({bad}): {real}. Туда нельзя.")
    roots = allowed_dirs(config)
    inside = False
    for root in roots:
        try:
            real.relative_to(root)
            inside = True
            break
        except ValueError:
            continue
    if not inside:
        shown = ", ".join(str(r) for r in roots) or "—"
        raise PcError(f"Вне разрешённых папок: {real}. Можно только: {shown}.")
    if not real.is_file():
        raise PcError(f"Не файл: {real}.")
    size = real.stat().st_size
    if size > MAX_FILE_BYTES:
        raise PcError(f"Файл слишком большой ({size} байт, предел {MAX_FILE_BYTES}).")
    return real


# ------------------------------------------------------------------ действия


def screen_size() -> tuple[int, int]:
    try:
        user32 = ctypes.windll.user32
        return (int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)))
    except Exception:
        return (0, 0)


def do_status(config: dict) -> dict:
    w, h = screen_size()
    return {
        "ok": True,
        "cwd": str(Path.cwd()),
        "bridge": str(HERE),
        "python": sys.version.split()[0],
        "screen": {"width": w, "height": h},
        "allowed_dirs": [str(p) for p in allowed_dirs(config)],
        "now": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


# Декодер — decode_bytes() ниже: строгий UTF-8, метки BOM,
# для однобайтовых — голосование по числу русских букв.
# Только стандартная библиотека Python — без chardet и прочих пакетов.


def cyrillic_score(text: str) -> tuple[int, int]:
    """Пара (русских букв всего, из них строчных): по ней отличаем
    cp1251 от koi8-r и cp866. Чужой декодер даёт кракозябры со случайным
    регистром — строчных мало, правильный текст почти весь строчный."""
    cyr = sum(1 for c in text if "А" <= c <= "я" or c in "Ёё")
    low = sum(1 for c in text if "а" <= c <= "я" or c == "ё")
    return (cyr, low)


def decode_bytes(raw: bytes, encoding: str = "") -> tuple[str, str]:
    """Текст + имя кодировки. Пустая строка — автоопределение.
    Только стандартная библиотека: строгий UTF-8, метки BOM,
    для однобайтовых — голосование по числу русских букв."""
    if encoding:
        name = str(encoding).strip().lower().replace("_", "-")
        try:
            return raw.decode(name), name
        except (UnicodeDecodeError, LookupError) as exc:
            raise PcError(f"Не прочиталось как {name}: {exc}")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    if b"\x00" in raw:
        best16 = ("", "", (-1, -1))
        for name in ("utf-16-le", "utf-16-be"):
            try:
                text = raw.decode(name)
            except (UnicodeDecodeError, ValueError):
                continue
            score = cyrillic_score(text)
            if score > best16[2]:
                best16 = (text, "utf-16", score)
        if best16[2][0] >= 0:
            return best16[0], best16[1]
    best_text, best_name, best_score = "", "latin1", (-1, -1)
    for name in ("cp1251", "koi8-r", "cp866"):
        try:
            text = raw.decode(name)
        except (UnicodeDecodeError, ValueError):
            continue
        score = cyrillic_score(text)
        if score > best_score:
            best_text, best_name, best_score = text, name, score
    if best_score[0] > 0:
        return best_text, best_name
    return raw.decode("latin1"), "latin1"


def do_files_read(path_str: str, config: dict, encoding: str = "") -> dict:
    real = check_path(Path(str(path_str or "").strip()).expanduser(), config)
    raw = real.read_bytes()
    text, used = decode_bytes(raw, encoding)
    lines = text.splitlines()
    cut = len(lines) > MAX_FILE_LINES
    shown = "\n".join(lines[:MAX_FILE_LINES])
    return {
        "ok": True,
        "path": str(real),
        "bytes": len(raw),
        "encoding": used,
        "lines": len(lines),
        "truncated": cut,
        "text": shown,
    }


def do_apps_list(limit: int = 50) -> dict:
    try:
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PcError(f"Не смог спросить Windows о программах: {exc}")
    names: dict[str, int] = {}
    for line in (proc.stdout or "").splitlines():
        line = line.strip().strip('"')
        if not line:
            continue
        app = line.split('","')[0].strip('"')
        if app:
            names[app] = names.get(app, 0) + 1
    rows = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[: max(1, min(limit, 200))]
    return {"ok": True, "count": len(names), "apps": [{"name": n, "n": c} for n, c in rows]}


def do_screenshot(config: dict, name: str = "") -> dict:
    """Скриншот через WinAPI в BMP. Только стандартная библиотека."""
    try:
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
    except Exception:
        raise PcError("Скриншот работает только на Windows.")
    w, h = screen_size()
    if w <= 0 or h <= 0:
        raise PcError("Не узнал размер экрана.")
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, 0x00CC0020)
    row = ((w * 3 + 3) // 4) * 4
    buf = ctypes.create_string_buffer(row * h)
    bmi = struct.pack("<LllHHLLllLL", 40, w, -h, 1, 24, 0, row * h, 0, 0, 0, 0)
    got = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, bmi, 0)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    if not got:
        raise PcError("Windows не отдал картинку (GetDIBits).")
    shots = Path(str(config.get("shots_dir") or (HERE / "shots")))
    shots.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in (name or "shot") if c.isalnum() or c in "-_")[:30] or "shot"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = shots / f"{stamp}-{safe}.bmp"
    headers = struct.pack("<2sLHHL", b"BM", 54 + row * h, 0, 0, 54) + struct.pack(
        "<LllHHLLllLL", 40, w, -h, 1, 24, 0, row * h, 0, 0, 0, 0)
    out.write_bytes(headers + buf.raw)
    return {"ok": True, "path": str(out), "width": w, "height": h, "bytes": out.stat().st_size}


# ------------------------------------------------------------------ инструменты


TOOLS = [
    {
        "name": "pc_status",
        "description": (
            "Состояние ПК: папка, версия Python, размер экрана, время. "
            "Ничего не меняет. Вызывай первым."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pc_files_read",
        "description": (
            "Прочитать текстовый файл (до 200 КБ). Кодировка определяется сама "
            "(UTF-8, cp1251, koi8-r, cp866, UTF-16) или задаётся параметром. "
            "Только внутри разрешённых папок; бэкапы, testmodhas, системные папки — отказ. "
            "Ничего не меняет."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Путь к файлу"},
                "encoding": {"type": "string", "description": "Кодировка вручную (обычно не нужна)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "pc_apps_list",
        "description": (
            "Список запущенных программ Windows (имя и число окон). "
            "Ничего не меняет."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Сколько показать, по умолчанию 50"},
            },
        },
    },
    {
        "name": "pc_screenshot",
        "description": (
            "Скриншот всего экрана в файл BMP (папка shots/). Ничего не меняет, "
            "только смотрит."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Подпись к имени файла"},
            },
        },
    },
]


def tool_result(text: str, data: dict, is_error: bool = False) -> dict:
    body = text + "\n\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"
    return {"content": [{"type": "text", "text": body}], "isError": bool(is_error)}


def run_tool(params: dict, config: dict) -> dict:
    name = str(params.get("name") or "")
    args = params.get("arguments")
    if not isinstance(args, dict):
        args = {}
    try:
        if name == "pc_status":
            data = do_status(config)
            return tool_result(f"ПК на связи. Экран {data['screen']['width']}x{data['screen']['height']}.", data)
        if name == "pc_files_read":
            data = do_files_read(args.get("path") or "", config, str(args.get("encoding") or ""))
            tail = " (показан не весь — файл длинный)" if data["truncated"] else ""
            return tool_result(f"Прочитано: {data['path']}, кодировка {data['encoding']}, строк {data['lines']}{tail}.", data)
        if name == "pc_apps_list":
            data = do_apps_list(int(args.get("limit") or 50))
            top = ", ".join(f"{a['name']}×{a['n']}" for a in data["apps"][:10])
            return tool_result(f"Программ всего: {data['count']}. Крупнейшие: {top}.", data)
        if name == "pc_screenshot":
            data = do_screenshot(config, str(args.get("name") or ""))
            return tool_result(f"Скриншот сохранён: {data['path']} ({data['width']}x{data['height']}).", data)
        return tool_result(
            f"Неизвестный инструмент «{name}». Доступны: pc_status, pc_files_read, pc_apps_list, pc_screenshot.",
            {"ok": False, "reason": "неизвестный инструмент"}, is_error=True)
    except PcError as exc:
        return tool_result(str(exc), {"ok": False, "reason": str(exc)}, is_error=True)
    except Exception as exc:  # noqa: BLE001
        log("сбой инструмента:\n" + traceback.format_exc())
        return tool_result(f"Непредвиденная ошибка: {exc}", {"ok": False, "reason": repr(exc)}, is_error=True)


# ------------------------------------------------------------------ протокол


def pick_protocol(client_version: str) -> str:
    if client_version in PROTOCOL_VERSIONS:
        return client_version
    return PROTOCOL_VERSIONS[-1]


def reply(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def fail(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(message: dict, config: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        return reply(msg_id, {
            "protocolVersion": pick_protocol(str(params.get("protocolVersion") or "")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": config["server_name"], "version": config["server_version"]},
            "instructions": ("Мост ПК (только чтение): файлы внутри разрешённых папок, "
                             "список программ, скриншоты. Изменять систему не умеет. "
                             "Запретные зоны: бэкапы, testmodhas, системные папки."),
        })
    if method == "ping":
        return reply(msg_id, {})
    if method == "tools/list":
        return reply(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        return reply(msg_id, run_tool(params, config))
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return reply(msg_id, {key: []})
    return fail(msg_id, -32601, f"Метод не поддерживается: {method}")


def serve() -> int:
    config = read_config()
    log("мост ПК запущен")
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    for raw in source:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        try:
            answer = handle(message, config)
        except Exception:  # noqa: BLE001
            log("сбой обработки:\n" + traceback.format_exc())
            answer = fail(message.get("id"), -32603, "Внутренняя ошибка сервера") if message.get("id") is not None else None
        if answer is None:
            continue
        try:
            sink.write((json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8"))
            sink.flush()
        except (BrokenPipeError, OSError):
            return 0
    return 0


# ------------------------------------------------------------------ проверка


def mode_selftest() -> int:
    config = read_config()
    results: list[tuple[bool, str]] = []

    def check(good: bool, text: str) -> None:
        results.append((bool(good), text))
        print(f"[{'ОК  ' if good else 'СБОЙ'}] {text}")

    print("=" * 62)
    print(" Проверка моста ПК (только чтение, ничего не меняем)")
    print("=" * 62)

    def call(msg_id: int, name: str, arguments: dict) -> dict:
        answer = handle({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}}, config)
        return answer or {}

    def payload(answer: dict) -> dict:
        for block in (answer.get("result") or {}).get("content") or []:
            text = str(block.get("text") or "")
            if "```json" in text:
                try:
                    return json.loads(text.split("```json", 1)[1].rsplit("```", 1)[0])
                except json.JSONDecodeError:
                    return {}
        return {}

    hello = handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}, config) or {}
    check((hello.get("result") or {}).get("serverInfo", {}).get("name") == "pc", "рукопожатие: имя сервера pc")
    listing = handle({"jsonrpc": "2.0", "id": 0, "method": "tools/list"}, config) or {}
    names = [t["name"] for t in (listing.get("result") or {}).get("tools", [])]
    check(names == ["pc_status", "pc_files_read", "pc_apps_list", "pc_screenshot"], f"инструментов 4: {', '.join(names)}")

    data = payload(call(1, "pc_status", {}))
    check(data.get("ok") is True, "pc_status отвечает")
    check(data.get("screen", {}).get("width", 0) > 0, f"размер экрана: {data.get('screen')}")

    data = payload(call(2, "pc_files_read", {"path": str(HERE / "config.json")}))
    check(data.get("ok") is True and "server_name" in data.get("text", ""), "pc_files_read читает свой файл")

    tmp = Path(tempfile.gettempdir()) / "pc-bridge-probe.txt"
    data = payload(call(3, "pc_files_read", {"path": str(tmp)}))
    check(data.get("ok") is False, "вне разрешённых папок — отказ")

    data = payload(call(4, "pc_files_read", {"path": str(HERE / ".." / "voice" / "requirements-voice.txt")}))
    check(data.get("ok") is True, "путь с .. внутри разрешённого — можно")

    data = payload(call(5, "pc_apps_list", {"limit": 5}))
    check(data.get("ok") is True and data.get("count", 0) > 0, f"программ запущено: {data.get('count')}")

    data = payload(call(6, "pc_screenshot", {"name": "selftest"}))
    shot = Path(str(data.get("path") or ""))
    check(data.get("ok") is True and shot.is_file() and shot.stat().st_size > 1000, f"скриншот: {shot.name} ({shot.stat().st_size if shot.is_file() else 0} байт)")

    data = payload(call(7, "pc_nope", {}))
    check(data.get("ok") is False, "неизвестный инструмент — вежливый отказ")

    # ---- кодировки: кладём русские строки в cp1251 и cp866, читаем мостом
    # Фраза без ё и длинного тире: их нет в cp866, а проба должна писаться в обе.
    probe_text = "Проверка связи: ежик в тумане, 123"
    probes = {"probe-1251.txt": "cp1251", "probe-koi.txt": "koi8-r", "probe-866.txt": "cp866"}
    probe_paths = []
    try:
        for fname, enc in probes.items():
            probe = HERE / "shots" / fname
            probe.write_bytes(probe_text.encode(enc))
            probe_paths.append(probe)
            got = payload(call(70 + len(probe_paths), "pc_files_read", {"path": str(probe)}))
            good = got.get("ok") is True and probe_text in got.get("text", "") and got.get("encoding") == enc
            check(good, f"кодировка {enc}: угадана сама, текст цел")
        got = payload(call(80, "pc_files_read", {"path": str(probe_paths[0]), "encoding": "cp1251"}))
        check(got.get("ok") is True and probe_text in got.get("text", ""), "кодировка вручную: cp1251 принята")
        got = payload(call(81, "pc_files_read", {"path": str(probe_paths[0]), "encoding": "ascii"}))
        check(got.get("ok") is False, "строго ascii для русского файла — честный отказ")
    finally:
        for probe in probe_paths:
            try:
                probe.unlink()
            except OSError:
                pass

    failed = [t for ok, t in results if not ok]
    print("=" * 62)
    if failed:
        print(f" ИТОГ: провалено {len(failed)} из {len(results)}")
        return 1
    print(f" ИТОГ: все {len(results)} проверок пройдены")
    print("=" * 62)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Мост ПК для opencode (только чтение, MCP stdio).")
    parser.add_argument("--selftest", action="store_true", help="проверить 4 инструмента на этом ПК")
    parser.add_argument("--print-config", action="store_true", help="кусок настроек для opencode.jsonc")
    args = parser.parse_args(argv)
    if args.selftest:
        return mode_selftest()
    if args.print_config:
        snippet = {"mcp": {"pc": {"type": "local", "command": ["python", str(HERE / "server.py")], "enabled": True}},
                   "permission": {"pc_*": "ask"}}
        print(json.dumps(snippet, ensure_ascii=False, indent=2))
        return 0
    return serve()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
