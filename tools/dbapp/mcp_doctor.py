"""Смотритель мостов: кто из серверов MCP жив и — главное — почему нет.

Зачем он. Когда opencode показывает красную строку, непонятно куда смотреть.
Сегодня это стоило времени дважды: у `windows-admin` команда была записана
как `npx`, без `.cmd`, и мост падал с `WinError 2` — а выглядело это как
«медленный старт»; у `unityMCP` блок лежал во ВТОРОМ файле настроек
(`opencode.json`), куда программа не пишет, и о нём никто не знал.

Поэтому проверка двухшаговая:

1. **Быстрый осмотр** — команда найдена? файлы лаунчера на месте? порт
   слушается? Это занимает секунды и отвечает словами сразу. Именно он
   ловит «файл не найден» раньше, чем человек успевает решить, что сервер
   просто медленный.
2. **Живая проверка** — только если быстрый осмотр прошёл: поднимаем
   сервер, шлём `initialize`, `notifications/initialized`, `tools/list` и
   считаем инструменты.

Осторожные серверы. Те, что живут внутри другой программы (плагин в
редакторе, встроенный сервер студии), по умолчанию живой проверкой **не
трогаются**: лишний клиент к тому же редактору может занять единственное
место и сломать то, что мы проверяем. Для них делается пассивная проверка,
а полная — только по явному запросу (`live=True`). Проверять, что второй
клиент безопасен, можно отдельно и честно: запустить проверку дважды
вручную.

Про два файла настроек. `opencode.jsonc` — главный, в него пишет
программа. `opencode.json` — второй, и он тоже читается opencode. Если
одно имя описано в обоих, главным считается `opencode.jsonc`, а
противоречие показывается в списке: иначе слепота повторится в новом
виде.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

try:  # разбор jsonc уже есть в программе — свой дубль не нужен
    from opencode_caps import strip_jsonc  # type: ignore
except Exception:  # pragma: no cover — мост запускается из своей папки
    def strip_jsonc(text: str) -> str:  # type: ignore
        out: list[str] = []
        i, n = 0, len(text)
        in_str = False
        escape = False
        while i < n:
            ch = text[i]
            if in_str:
                out.append(ch)
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                out.append(ch)
                i += 1
                continue
            if ch == "/" and i + 1 < n:
                nxt = text[i + 1]
                if nxt == "/":
                    while i < n and text[i] != "\n":
                        i += 1
                    continue
                if nxt == "*":
                    i += 2
                    while i + 1 < n and not (text[i] == "*"
                                             and text[i + 1] == "/"):
                        i += 1
                    i += 2
                    continue
            out.append(ch)
            i += 1
        return "".join(out)


MAIN_CONFIG = "opencode.jsonc"
EXTRA_CONFIG = "opencode.json"
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT = 90

# Серверы, которые живут внутри другой программы. Живая проверка для них
# по умолчанию выключена — см. модуль.
EDITOR_BACKED = frozenset({
    "unity", "roblox-studio", "unreal", "godot", "ghidra-mcp",
    "obs", "blender",
})

_PATH_SUFFIXES = {".exe", ".py", ".cmd", ".bat", ".ps1", ".js", ".mjs"}


@dataclass
class Entry:
    """Один сервер MCP так, как он записан в настройках."""

    name: str
    kind: str = "local"
    command: list[str] = field(default_factory=list)
    url: str = ""
    enabled: bool = True
    source: str = MAIN_CONFIG
    conflict: str = ""


@dataclass
class Check:
    """Результат проверки одного сервера.

    `skipped` — третий исход, важный для честности: «не проверено» и
    «не работает» это разные вещи. Внешний адрес мы не опрашиваем, а
    сервер внутри редактора по умолчанию не запускаем — и называть их
    сломанными было бы враньём.
    """

    name: str
    ok: bool
    reason: str = ""
    detail: str = ""
    kind: str = "quick"
    tools: int = 0
    prompts: int = 0
    resources: int = 0
    elapsed_ms: int = 0
    skipped: bool = False


# ---------------------------------------------------------------- настройки


def _read_mcp(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        data = json.loads(strip_jsonc(text))
    except (ValueError, TypeError):
        return {}
    mcp = data.get("mcp") if isinstance(data, dict) else None
    return mcp if isinstance(mcp, dict) else {}


def _entry(name: str, block: dict, source: str) -> Entry:
    kind = str(block.get("type") or "local").lower()
    command = block.get("command")
    return Entry(
        name=name,
        kind="remote" if kind == "remote" else "local",
        command=[str(part) for part in command] if isinstance(command, list)
        else [],
        url=str(block.get("url") or ""),
        enabled=block.get("enabled") is not False,
        source=source,
    )


def read_entries(dest: Path) -> list[Entry]:
    """Все серверы из обоих файлов настроек. Главный — opencode.jsonc."""
    dest = Path(dest)
    main = {name: _entry(name, block, MAIN_CONFIG)
            for name, block in _read_mcp(dest / MAIN_CONFIG).items()
            if isinstance(block, dict)}
    extra = {name: _entry(name, block, EXTRA_CONFIG)
             for name, block in _read_mcp(dest / EXTRA_CONFIG).items()
             if isinstance(block, dict)}
    for name, item in extra.items():
        if name in main:
            first, second = main[name], item
            other = (f"ещё описан в {EXTRA_CONFIG}: "
                     + (second.url if second.kind == "remote"
                        else " ".join(second.command)))
            main[name].conflict = other
        else:
            main[name] = item
    return sorted(main.values(), key=lambda item: item.name.lower())


# ------------------------------------------------------------ быстрый осмотр


def _is_path_part(part: str) -> bool:
    """Похоже ли это на путь к файлу или папке.

    Слеша в части мало: у пакета npm вроде `@sbroenne/mcp-server-excel`
    он тоже есть, и такой сервер объявлялся сломанным из-за имени
    пакета. Поэтому путь — это буква диска, ведущий разделитель или
    известное расширение.
    """
    if not part or part.startswith("-"):
        return False
    if part[0] in "\\/" or (len(part) > 1 and part[1] == ":"):
        return True
    return Path(part).suffix.lower() in _PATH_SUFFIXES


def _resolve_part(part: str) -> tuple[str, str]:
    """Найти, что означает эта часть команды. Пусто — значит на месте."""
    if os.path.exists(part):
        return part, ""
    if _is_path_part(part):
        if os.path.isdir(part) or not Path(part).suffix:
            return "", f"папка не найдена: {part}"
        return "", f"файл не найден: {part}"
    found = shutil.which(part)
    if found:
        return found, ""
    return "", f"команда не найдена в PATH: {part}"


def command_parts(command: list[str]) -> tuple[list[str], list[str]]:
    """Разделить команду на исполняемое и остальное.

    Команда моста выглядит так: `pythonw quiet_launcher.py npx -y ...`.
    Настоящая программа — не первая часть, а та, что идёт после скрипта
    лаунчера. Если считать каждое слово без слеша командой, то `run` и
    `--empty` из аргументов тоже начнут искаться в PATH, и проверка
    объявит живой сервер мёртвым.
    """
    if not command:
        return [], []
    head = command[0]
    if not Path(head).name.lower().startswith("python"):
        return [head], command[1:]
    rest = command[1:]
    position = 0
    while position < len(rest):
        part = rest[position]
        if part.startswith("-") or Path(part).suffix.lower() != ".py":
            break
        position += 1
    if position >= len(rest) or rest[position].startswith("-"):
        # Дальше только скрипт и его аргументы: отдельной программы нет,
        # и запускает всё тот же Python.
        return [], rest
    return [rest[position]], rest[position + 1:]


def _port_of(url: str) -> int | None:
    parsed = urlparse(url)
    try:
        return int(parsed.port or (443 if parsed.scheme == "https" else 80))
    except ValueError:
        return None


def _is_local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0", ""}


def quick_check(entry: Entry) -> Check:
    """Осмотр без запуска сервера: команда, файлы, порт."""
    if entry.kind == "remote":
        if not entry.url:
            return Check(entry.name, False, "в настройках нет адреса")
        port = _port_of(entry.url)
        if port is None:
            return Check(entry.name, False, "в адресе нет порта",
                         entry.url)
        host = urlparse(entry.url).hostname or ""
        if not _is_local_host(host):
            return Check(entry.name, False,
                         f"внешний адрес {host} — наружу не ходим, "
                         f"состояние неизвестно", entry.url, skipped=True)
        with socket.socket() as sock:
            sock.settimeout(1.0)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return Check(entry.name, False,
                             f"на порту {port} никто не слушает", entry.url)
        return Check(entry.name, True, "", f"порт {port} отвечает",
                     kind="quick")

    if not entry.command:
        return Check(entry.name, False, "в настройках нет команды запуска")
    # Сначала всё, что выглядит путём: файлы лаунчеров и скриптов.
    for part in entry.command:
        if not _is_path_part(part):
            continue
        _, problem = _resolve_part(part)
        if problem:
            return Check(entry.name, False, problem,
                         "команда: " + " ".join(entry.command))
    # Потом настоящая программа — и только она ищется в PATH.
    programs, _ = command_parts(entry.command)
    for part in programs:
        _, problem = _resolve_part(part)
        if problem:
            return Check(entry.name, False, problem,
                         "команда: " + " ".join(entry.command))
    found = (_resolve_part(programs[0])[0] if programs
             else _resolve_part(entry.command[0])[0])
    return Check(entry.name, True, "",
                 "команда найдена: " + os.path.basename(found
                                                       or entry.command[0]),
                 kind="quick")


# ------------------------------------------------------------ живая проверка


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


class _Session:
    """Разговор по MCP через стандартные потоки."""

    def __init__(self, argv: list[str], timeout: float):
        self.timeout = timeout
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=_no_window())
        self.lines: queue.Queue[str] = queue.Queue()
        self.errors: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            text = line.strip()
            if text:
                self.errors.append(text)

    def send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except OSError:
            pass

    def take(self, answer_id: object, deadline: float) -> dict | None:
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.2)
            except queue.Empty:
                if self.proc.poll() is not None:
                    return None
                continue
            text = line.strip()
            if not text.startswith("{"):
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if msg.get("id") == answer_id:
                return msg
        return None

    def close(self) -> None:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except OSError:
            pass
        if self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid),
                                "/T", "/F"], capture_output=True,
                               creationflags=_no_window(), check=False)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def error_hint(self) -> str:
        """Выбирает из журнала строку, в которой названа причина.

        Строка с причиной не всегда одна и та же: у моста chatgpt она
        ПЕРВАЯ («нет ключа или модели»), у моста android-emulator —
        ПОСЛЕДНЯЯ («No devices connected»), а между ними идут служебные
        строки вроде «adb: C:\\...». Взять первую или последнюю — значит
        показать человеку не то.

        Поэтому строка выбирается по смыслу: где есть слова о нехватке
        или поломке — там и причина. Если таких строк нет, берётся
        последняя: у многих мостов именно там итог.
        """
        tail = self.errors[-8:]
        if not tail:
            return ""
        for line in reversed(tail):
            if "не запустилось" in line or "Error" in line or "error" in line:
                return line[:160]
        for line in tail:
            if _looks_like_problem(line):
                return line[:160]
        return tail[-1][:160]


#: Слова, по которым строка журнала читается как объяснение причины.
#: Список намеренно простой: он ловит «нет», «не найден», «ошибка» и
#: английские «not found», «missing», «failed» — то, чем мосты на самом
#: деле пишут о нехватке.
PROBLEM_WORDS = (
    "нет ", "нет:", "не найден", "не установлен", "не запустил", "не подключ",
    "не работает", "не отвечает", "ошибка", "нужен", "нужна", "требуется",
    "не хватает", "не внесен", "не задан", "нет ключа", "нет токена",
    "not found", "not installed", "missing", "failed", "no devices",
    "connection refused", "timed out",
)


def _looks_like_problem(line: str) -> bool:
    """Похоже ли строка на объяснение причины, а не на служебную запись."""
    low = line.lower()
    return any(word in low for word in PROBLEM_WORDS)


def _count(items: object) -> int:
    return len(items) if isinstance(items, list) else 0


def _live_probe(entry: Entry, timeout: float) -> Check:
    started = time.monotonic()
    deadline = started + timeout
    session = _Session(entry.command, timeout)
    try:
        session.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": PROTOCOL_VERSION,
                                 "capabilities": {},
                                 "clientInfo": {"name": "mcp-doctor",
                                                "version": "1.0"}}})
        init = session.take(1, deadline)
        if init is None:
            hint = session.error_hint()
            reason = (f"не ответил за {int(timeout)} сек — сервер молчит"
                      + (f": {hint}" if hint else ""))
            return Check(entry.name, False, reason, "", kind="live")
        if init.get("error"):
            return Check(entry.name, False,
                         "ответил ошибкой: "
                         + json.dumps(init["error"], ensure_ascii=False)[:160],
                         "", kind="live")
        result = init.get("result") or {}
        info = result.get("serverInfo") or {}
        name = str(info.get("name") or "")
        version = str(info.get("version") or "")

        session.send({"jsonrpc": "2.0", "method": "notifications/initialized",
                      "params": {}})
        session.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                      "params": {}})
        listed = session.take(2, deadline)
        if listed is None:
            hint = session.error_hint()
            return Check(entry.name, False,
                         "ответил на initialize, но не отдал инструменты"
                         + (f": {hint}" if hint else ""),
                         f"{name} {version}".strip(), kind="live")
        tools = _count(((listed.get("result") or {}).get("tools")))
        caps = result.get("capabilities") or {}
        prompts = resources = 0
        if not tools:
            # Пустой список — не приговор: у сервера могут быть промпты или
            # ресурсы, и называть его мёртвым при этом неправда.
            if isinstance(caps.get("prompts"), dict):
                session.send({"jsonrpc": "2.0", "id": 3,
                              "method": "prompts/list", "params": {}})
                answer = session.take(3, deadline)
                prompts = _count(((answer or {}).get("result")
                                  or {}).get("prompts"))
            if isinstance(caps.get("resources"), dict):
                session.send({"jsonrpc": "2.0", "id": 4,
                              "method": "resources/list", "params": {}})
                answer = session.take(4, deadline)
                resources = _count(((answer or {}).get("result")
                                    or {}).get("resources"))
        if not (tools or prompts or resources):
            return Check(entry.name, False,
                         "отвечает, но не отдал ни инструментов, ни промптов, "
                         "ни ресурсов", f"{name} {version}".strip(),
                         kind="live")
        spent = (time.monotonic() - started)
        parts = [p for p in (name, version) if p]
        detail = " ".join(parts)
        if tools:
            detail += f", инструментов {tools}"
        if prompts:
            detail += f", промптов {prompts}"
        if resources:
            detail += f", ресурсов {resources}"
        if not tools:
            detail += " (инструментов нет)"
        return Check(entry.name, True, "", detail, kind="live",
                     tools=tools, prompts=prompts, resources=resources,
                     elapsed_ms=int(spent * 1000))
    finally:
        session.close()


def live_check(entry: Entry, timeout: int = DEFAULT_TIMEOUT,
               force: bool = False) -> Check:
    """Полная проверка. Сначала осмотр, и только потом запуск."""
    quick = quick_check(entry)
    if not quick.ok:
        return quick
    if entry.name in EDITOR_BACKED and not force:
        quick.detail = (quick.detail + " — живая проверка не выполняется: "
                        "сервер живёт внутри редактора, лишний клиент может "
                        "занять единственное место; по запросу "
                        "(live=True) проверка пойдёт").strip(" —")
        quick.skipped = True
        return quick
    if entry.kind == "remote":
        # Удалённый сервер проверяется связью, а не запуском: поднимать
        # чужой сервер из чужой машины нельзя.
        return quick
    return _live_probe(entry, float(timeout))


# ------------------------------------------------------------------- отчёты


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def format_list(entries: list[Entry]) -> str:
    if not entries:
        return "В настройках нет ни одного сервера MCP."
    lines = ["Серверы MCP из настроек opencode:", ""]
    for entry in entries:
        kind = "удалённый" if entry.kind == "remote" else "мост"
        state = "включён" if entry.enabled else "выключен"
        lines.append(f"  {_mark(entry.enabled)} {entry.name} — {kind}, "
                     f"{state}, запись в {entry.source}")
        if entry.conflict:
            lines.append(f"      ⚠ конфликт: {entry.conflict}; главным "
                         f"считается {MAIN_CONFIG}")
    return "\n".join(lines)


def format_checks(checks: list[Check]) -> str:
    if not checks:
        return "Проверять нечего: серверов в настройках нет."
    live_ok = [item for item in checks if item.ok and item.kind == "live"]
    quick_ok = [item for item in checks
                if item.ok and item.kind == "quick" and not item.skipped]
    skipped = [item for item in checks if item.skipped]
    dead = [item for item in checks if not item.ok and not item.skipped]

    lines = [f"Из {len(checks)} серверов: отвечают {len(live_ok)}, "
             f"прошли только осмотр {len(quick_ok)}, "
             f"не работают {len(dead)}, не проверено {len(skipped)}.", ""]

    if dead:
        lines.append("Не работают (найдено сразу, без запуска сервера):")
        for item in dead:
            lines.append(f"  {_mark(False)} {item.name} — {item.reason}")
        lines.append("")
    if live_ok:
        lines.append("Живая проверка — отвечают:")
        for item in live_ok:
            spent = f", {item.elapsed_ms} мс" if item.elapsed_ms else ""
            tail = f" — {item.detail}" if item.detail else ""
            lines.append(f"  {_mark(True)} {item.name}{tail}{spent}")
        lines.append("")
    if quick_ok:
        lines.append("Прошли быстрый осмотр (сервер не запускался):")
        for item in quick_ok:
            lines.append(f"  · {item.name} — {item.detail or item.reason}")
        lines.append("")
    if skipped:
        lines.append("Не проверено:")
        for item in skipped:
            lines.append(f"  · {item.name} — {item.reason or item.detail}")
    return "\n".join(lines).rstrip()


# ------------------------------------------------------------------- запуск


def _allowed_live(entry: Entry, live_editor: bool) -> bool:
    return live_editor or entry.name not in EDITOR_BACKED


def check_all(entries: list[Entry], concurrency: int = DEFAULT_CONCURRENCY,
              timeout: int = DEFAULT_TIMEOUT,
              live_editor: bool = False) -> list[Check]:
    """Проверить всех. Осмотр — сразу, живая проверка — параллельно.

    Один сервер даёт один результат: если живая проверка состоялась, она
    заменяет осмотр, а не дописывается к нему. Иначе в отчёте сервер
    оказывался бы двумя строками, и «живых 6 из 6» считало бы не
    серверы, а строки.
    """
    if not entries:
        return []
    workers = max(1, min(int(concurrency), len(entries)))
    results: dict[str, Check] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        quick_jobs = {entry.name: pool.submit(quick_check, entry)
                      for entry in entries}
        alive: list[Entry] = []
        for entry in entries:
            found = quick_jobs[entry.name].result()
            results[entry.name] = found
            if found.ok and entry.kind == "local" \
                    and _allowed_live(entry, live_editor):
                alive.append(entry)
        live_jobs = {entry.name: pool.submit(live_check, entry, timeout)
                     for entry in alive}
        for entry in alive:
            results[entry.name] = live_jobs[entry.name].result()
    return [results[entry.name] for entry in entries]