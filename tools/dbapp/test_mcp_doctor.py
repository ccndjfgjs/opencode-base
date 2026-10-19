"""Проверки смотрителя мостов.

Запуск: python tools/dbapp/test_mcp_doctor.py

Проверяется не «красиво ли», а семь вещей, каждая из которых уже стоила
времени:

1. смотритель видит сервер из ВТОРОГО файла настроек (opencode.json),
   а не только из того, куда пишет программа;
2. одно имя в двух файлах — виден конфликт и сказано, какой файл главнее;
3. отсутствующая команда называется словами сразу, а не после ожидания;
4. команда без расширения (npx/uvx) находится — это и была поломка
   windows-admin;
5. живая проверка отдаёт имя сервера и число инструментов;
6. сервер без инструментов, но с промптами, не объявляется мёртвым;
7. проверка всех идёт параллельно, а не по очереди;
8. серверы, живущие внутри редактора, по умолчанию не трогаются.

Поддельный сервер здесь настоящий: он говорит по тому же протоколу MCP,
поэтому проверка достаёт до слоя, где ломается настоящий.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mcp_doctor  # noqa: E402

PROGRAM_ROOT = HERE.parent.parent

passed = 0
failed = 0


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


# Настоящий MCP-сервер на стандартных потоках. Ничего не знает про
# программу — только протокол. Задержка нужна для проверки параллельности.
FAKE_SERVER = r'''
import json, sys, time

delay = 0.0
empty = False
for arg in sys.argv[1:]:
    if arg.startswith("--delay="):
        delay = float(arg.split("=", 1)[1])
    elif arg == "--empty":
        empty = True

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method = msg.get("method")
    ident = msg.get("id")
    if method == "initialize":
        if delay:
            time.sleep(delay)
        print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "FAKE-MCP", "version": "9.9"},
            "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
        }}), flush=True)
    elif method == "tools/list":
        tools = [] if empty else [{"name": "tool_one"}, {"name": "tool_two"}]
        print(json.dumps({"jsonrpc": "2.0", "id": ident,
                          "result": {"tools": tools}}), flush=True)
    elif method == "prompts/list":
        print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": {
            "prompts": [{"name": "p1"}, {"name": "p2"}]}}), flush=True)
    elif method == "resources/list":
        print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": {
            "resources": [{"name": "r1"}]}}), flush=True)
'''


def write_server(folder: Path, name: str = "fake_server.py") -> str:
    path = Path(folder) / name
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return str(path)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mcp-doctor-") as tmp:
        tmp_path = Path(tmp)
        dest = tmp_path / "settings"
        dest.mkdir()

        # --- два файла настроек и конфликт между ними -------------------
        (dest / "opencode.jsonc").write_text(
            '{\n  // живой файл, его пишет программа\n'
            '  "mcp": {\n'
            '    "alpha": {"type": "local", "command": ["alpha.exe"],'
            ' "enabled": true},\n'
            '    "gamma": {"type": "local", "command": ["gamma.exe"],'
            ' "enabled": true}\n  }\n}\n',
            encoding="utf-8")
        (dest / "opencode.json").write_text(
            json.dumps({"$schema": "x", "mcp": {
                "beta": {"type": "local", "command": ["beta.exe"],
                         "enabled": True},
                "gamma": {"type": "remote", "url": "http://127.0.0.1:8080/mcp",
                          "enabled": True},
            }}, ensure_ascii=False, indent=2),
            encoding="utf-8")

        entries = mcp_doctor.read_entries(dest)
        names = {entry.name: entry for entry in entries}

        check("beta" in names,
              f"сервер из второго файла (opencode.json) виден: "
              f"{sorted(names)}")
        check(names.get("beta") is not None
              and names["beta"].source == "opencode.json",
              f"и источник назван верно: "
              f"{names['beta'].source if 'beta' in names else 'нет'}")

        gamma = names.get("gamma")
        check(gamma is not None and gamma.source == "opencode.jsonc",
              "при конфликте главным считается opencode.jsonc — тот, куда "
              "пишет программа")
        check(gamma is not None and "opencode.json" in (gamma.conflict or ""),
              f"а конфликт назван прямо: {gamma.conflict if gamma else 'нет'}")
        text = mcp_doctor.format_list(entries)
        check("конфликт" in text.lower(),
              "в самом списке конфликт виден человеку, а не только в данных")

        # --- быстрая проверка: команда не найдена ------------------------
        missing = mcp_doctor.Entry(name="нет-такого", kind="local",
                                   command=["program-kotory-net-takoy.exe"],
                                   url="", enabled=True,
                                   source="opencode.jsonc", conflict="")
        started = time.monotonic()
        res = mcp_doctor.quick_check(missing)
        spent = time.monotonic() - started
        check(not res.ok and "найден" in res.reason.lower(),
              f"отсутствующая команда названа словами: {res.reason}")
        check(spent < 1.0,
              f"и сказано сразу, без запуска и ожидания: {spent:.2f} сек")

        # --- команда без расширения (npx/uvx) ----------------------------
        fake_dir = tmp_path / "bin"
        fake_dir.mkdir()
        (fake_dir / "faketool.cmd").write_text("@echo off\r\n",
                                              encoding="utf-8", newline="")
        old_path = sys.path and None  # noqa: F841 — подсказка для читателя
        import os

        saved = os.environ.get("PATH", "")
        os.environ["PATH"] = str(fake_dir) + os.pathsep + saved
        bare = mcp_doctor.Entry(name="faketool", kind="local",
                                command=["faketool", "run"], url="",
                                enabled=True, source="opencode.jsonc",
                                conflict="")
        res = mcp_doctor.quick_check(bare)
        check(res.ok,
              f"команда без расширения найдена — та самая поломка npx: "
              f"{res.reason or res.detail}")
        os.environ["PATH"] = saved

        # --- удалённый сервер на закрытом порту -------------------------
        remote = mcp_doctor.Entry(
            name="закрытый", kind="remote", command=[],
            url=f"http://127.0.0.1:{free_port()}/mcp", enabled=True,
            source="opencode.jsonc", conflict="")
        res = mcp_doctor.quick_check(remote)
        check(not res.ok and "слушает" in res.reason.lower(),
              f"закрытый порт назван словами: {res.reason}")

        # --- живая проверка настоящего поддельного сервера ----------------
        server = write_server(tmp_path)
        live = mcp_doctor.Entry(name="живой", kind="local",
                                command=[sys.executable, server], url="",
                                enabled=True, source="opencode.jsonc",
                                conflict="")
        res = mcp_doctor.live_check(live, timeout=30)
        check(res.ok and res.tools == 2,
              f"живой сервер опознан, инструментов {res.tools}: {res.reason}")
        check("FAKE-MCP" in res.detail,
              f"имя сервера показано, а не только «жив»: {res.detail}")

        # --- нет инструментов, но есть промпты --------------------------
        empty = mcp_doctor.Entry(name="без-инструментов", kind="local",
                                 command=[sys.executable, server, "--empty"],
                                 url="", enabled=True,
                                 source="opencode.jsonc", conflict="")
        res = mcp_doctor.live_check(empty, timeout=30)
        check(res.ok,
              f"сервер без инструментов не объявлен мёртвым: ok={res.ok}")
        check("промпт" in res.detail.lower(),
              f"а сказано, что есть промпты: {res.detail}")

        # --- сервер не запускается: причина, а не таймаут -----------------
        res = mcp_doctor.live_check(missing, timeout=30)
        check(not res.ok and "найден" in res.reason.lower(),
              f"живая проверка мёртвой команды тоже называет причину, а не "
              f"таймаут: {res.reason}")

        # --- параллельность проверки всех ---------------------------------
        slow = [
            mcp_doctor.Entry(name=f"медленный-{i}", kind="local",
                             command=[sys.executable, server, "--delay=2"],
                             url="", enabled=True,
                             source="opencode.jsonc", conflict="")
            for i in range(3)
        ]
        started = time.monotonic()
        checks = mcp_doctor.check_all(slow, concurrency=4, timeout=30)
        elapsed = time.monotonic() - started
        check(all(item.ok for item in checks) and len(checks) == 3,
              f"три сервера по 2 секунды проверены все: "
              f"{[item.ok for item in checks]}")
        check(elapsed < 4.5,
              f"и параллельно, а не по очереди: {elapsed:.1f} сек вместо 6")

        # --- серверы внутри редактора по умолчанию не трогаются -----------
        check("unity" in mcp_doctor.EDITOR_BACKED
              and "roblox-studio" in mcp_doctor.EDITOR_BACKED,
              "в списке осторожных есть unity и roblox-studio: "
              f"{sorted(mcp_doctor.EDITOR_BACKED)}")
        careful = mcp_doctor.Entry(name="unity", kind="local",
                                  command=[sys.executable, server,
                                           "--delay=5"],
                                  url="", enabled=True,
                                  source="opencode.jsonc", conflict="")
        started = time.monotonic()
        res = mcp_doctor.live_check(careful, timeout=30, force=False)
        spent = time.monotonic() - started
        check(spent < 2.0,
              f"по умолчанию живая проверка осторожного сервера не "
              f"запускается: {spent:.2f} сек вместо 5")
        check("по запросу" in (res.reason + res.detail).lower(),
              f"и сказано, как получить полный ответ: {res.reason} / "
              f"{res.detail}")
        res = mcp_doctor.live_check(careful, timeout=30, force=True)
        check(res.ok and res.tools == 2,
              f"а по явному запросу проверка идёт и отвечает: ok={res.ok}, "
              f"инструментов {res.tools}")

        # --- выбор строки с причиной ------------------------------------
        # Строка с причиной не всегда одна и та же: у chatgpt она
        # ПЕРВАЯ, у android-emulator — ПОСЛЕДНЯЯ, а между ними идут
        # служебные строки. 19.10.2026 доктор показывал у chatgpt
        # «Значения в журнал не пишу» — то есть последнюю строку вместо
        # «нет ключа или модели».
        def _hint(lines):
            s = mcp_doctor._Session.__new__(mcp_doctor._Session)
            s.errors = list(lines)
            return s.error_hint()

        hint_first = _hint([
            "[chatgpt-bridge] нет ключа или модели: C:\\Users\\x\\mcp-chatgpt.txt",
            "[chatgpt-bridge] Две строки: OPENAI_API_KEY и OPENAI_MODEL.",
            "[chatgpt-bridge] Значения в журнал не пишу.",
        ])
        check("нет ключа" in hint_first,
              f"причина берётся из первой строки, когда она первая: {hint_first}")

        hint_last = _hint([
            "[android-bridge] adb: C:\\LDPlayer\\LDPlayer9\\adb.exe",
            "[android-bridge] запускаю мост: python server.py",
            "No devices connected. Please connect a device and try again.",
        ])
        check("No devices" in hint_last,
              f"и из последней, когда причина в конце: {hint_last}")

        hint_error = _hint(["что-то", "ModuleNotFoundError: No module named 'mcp'"])
        check("ModuleNotFoundError" in hint_error,
              f"а настоящая ошибка всегда важнее прочих строк: {hint_error}")

        # --- отчёт ------------------------------------------------------
        report = mcp_doctor.format_checks(checks + [res])
        first = report.splitlines()[0] if report.splitlines() else ""
        check(first.startswith(f"Из {len(checks) + 1} серверов:")
              and "не проверено" in first,
              f"сводка различает «не работает» и «не проверено»: {first}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())