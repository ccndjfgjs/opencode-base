# -*- coding: utf-8 -*-
"""Реестр MCP-серверов: что известно, что готово, что можно включить.

Модуль отдельный от core.py намеренно. Здесь три вещи, которые не должны
размазываться по программе: чтение реестра, живая проверка требований и
включение/выключение сервера в настройках opencode.

Про проверку требований. Реестр честно предупреждает: поле ready_here —
снимок на дату checked, а не обещание, и верить ему нельзя. Поэтому
состояние сервера считается здесь, на живой машине, а снимок из реестра
показывается рядом и помечен как устаревший. Иначе программа будет
врать пользователю про свою же готовность.

Программа ничего не устанавливает из интернета и не покупает подписки.
Она только проверяет, вписывает блок в настройки и честно говорит, чего
не хватает.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import winreg
from dataclasses import dataclass, field
from pathlib import Path

#: Имя файла реестра. Лежит в корне базы и едет с ней.
REGISTRY_NAME = "mcp-registry.json"

#: Куда искать программу, если её нет в PATH. Ключ — имя файла,
#: значение — ветка реестра Windows, где записан полный путь.
PROGRAMS_IN_REGISTRY = {
    "excel.exe": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
    "blender.exe": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\blender.exe",
}

#: Сколько ждать ответа команды проверки, секунд. Проверка должна быть
#: мгновенной; если зависла — значит это не проверка версии.
CHECK_TIMEOUT = 8

#: Сколько ждать прогрева кэша npx. Холодная скачка пакета занимает до
#: минуты; если за это время не уложились, кэш считаем прогретым и
#: продолжаем: opencode всё равно попробует сам.
WARM_UP_TIMEOUT = 180


@dataclass
class Requirement:
    """Одно требование сервера и результат его проверки."""

    what: str
    kind: str = "manual"          # command | program | manual
    value: str = ""               # команда или имя программы
    args: list[str] = field(default_factory=list)
    min_version: int = 0
    note: str = ""
    blocks: bool = False         # ручное требование, без которого сервер бессмыслен
    ok: bool = False
    detail: str = ""              # что именно найдено, для показа


@dataclass
class Server:
    """Один сервер из реестра вместе с живым состоянием."""

    id: str
    name: str
    raw: dict
    requirements: list[Requirement] = field(default_factory=list)
    installed: bool = False       # вписан ли в настройки opencode
    has_connection: bool = False  # есть ли что вписывать

    @property
    def missing(self) -> list[Requirement]:
        """Чего объективно не хватает: то, что программа умеет проверить."""
        return [r for r in self.requirements if not r.ok and r.kind != "manual"]

    @property
    def blocking_manual(self) -> list[Requirement]:
        """Ручные требования, без которых сервер работать не будет.

        Пример — приложения Adobe: сервер формально подключается, но
        отвечает отказом на всё. Отличать их надо, иначе программа
        предложит включить заведомо бесполезное.
        """
        return [r for r in self.requirements if r.kind == "manual" and r.blocks]

    @property
    def manual(self) -> list[Requirement]:
        """Ручные требования, которые человек проверяет сам."""
        return [r for r in self.requirements if r.kind == "manual" and not r.blocks]

    @property
    def ready(self) -> bool:
        """Можно ли включить.

        Обычные ручные требования НЕ мешают. Например, права
        администратора: без них сервер запускается, просто часть
        инструментов откажет. Если запретить включение из-за
        недоказанного, пользователь не сможет включить вполне рабочий
        сервер. А вот помеченные как blocks — мешают: без них сервер
        бесполезен, и честнее сказать об этом, чем вписать его зря.
        """
        return not self.missing and not self.blocking_manual and self.has_connection

    @property
    def license(self) -> str:
        return str(self.raw.get("license") or "—")

    @property
    def tools_count(self) -> str:
        value = self.raw.get("tools_count")
        return f"{value} инстр." if value else "—"

    @property
    def source(self) -> str:
        return str(self.raw.get("source") or "")


# ------------------------------------------------------------------ чтение


def registry_path(base: Path) -> Path:
    return Path(base) / REGISTRY_NAME


def load_registry(base: Path) -> dict:
    """Читает реестр. При беде возвращает пустой — программа не падает."""
    try:
        data = json.loads(registry_path(base).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------- проверки


def _run(command: str, args: list[str]) -> tuple[bool, str]:
    """Запускает команду проверки. Ничего не устанавливает и не меняет.

    Отдельно про .cmd и .bat: на Windows такую обёртку нельзя выполнить
    напрямую, CreateProcess её не берёт — нужен cmd.exe. Наивный запуск
    «npx» молча падает, хотя npx на месте. Поэтому ищем настоящий файл
    и, если он пакетный, идём через cmd.
    """
    exe = shutil.which(command) or command
    argv = [exe, *args]
    if exe.lower().endswith((".cmd", ".bat")):
        argv = [os.environ.get("COMSPEC") or "cmd.exe", "/c", exe, *args]
    try:
        done = subprocess.run(
            argv,
            capture_output=True, text=True, timeout=CHECK_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    out = (done.stdout or "").strip() or (done.stderr or "").strip()
    return done.returncode == 0, out


def find_program(name: str) -> str:
    """Ищет исполняемый файл: сначала PATH, потом ветка реестра Windows."""
    found = shutil.which(name)
    if found:
        return found
    key = PROGRAMS_IN_REGISTRY.get(name.lower())
    if not key:
        return ""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "")
        except OSError:
            continue
        path = str(value or "").strip()
        # Реестр отдаёт укороченный путь вида C:\PROGRA~2\... — он рабочий,
        # но показывать его пользователю неудобно, приводим к нормальному.
        if path and Path(path).exists():
            return str(Path(path).resolve())
    return ""


def _version_tuple(text: str) -> tuple[int, ...]:
    """Первая последовательность чисел в строке: v24.18.0 -> (24, 18, 0)."""
    match = re.search(r"(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def check_requirement(spec: dict) -> Requirement:
    """Проверяет одно требование и возвращает его с результатом."""
    req = Requirement(
        what=str(spec.get("what") or ""),
        kind=str(spec.get("type") or "manual").strip().lower(),
        value=str(spec.get("check") or ""),
        args=[str(a) for a in (spec.get("args") or [])],
        min_version=int(spec.get("min_version") or 0),
        note=str(spec.get("note") or ""),
        blocks=bool(spec.get("blocks")),
    )
    if not req.what:
        return req

    if req.kind == "manual":
        # Такое программа проверить не может: галочка в Excel, оплаченная
        # подписка, установленное приложение. Говорим прямо, а не угадываем.
        req.ok = False
        req.detail = "проверяется вручную"
        return req

    if req.kind == "program":
        path = find_program(req.value)
        req.ok = bool(path)
        req.detail = path or "не найден"
        return req

    # kind == "command"
    command = req.value
    if not command:
        req.detail = "нечего проверять"
        return req
    args = req.args or ["--version"]
    ok, out = _run(command, args)
    if not ok and not shutil.which(command):
        # Команды нет в PATH. На Windows npx/npm лежат .cmd-обёртками, и
        # shutil.which их находит, а вот запуск без расширения может
        # не сработать — пробуем с расширением .cmd.
        if shutil.which(command + ".cmd"):
            ok, out = _run(command + ".cmd", args)
    if not ok:
        req.ok = False
        req.detail = "не найден" if not out else f"не сработала: {out[:40]}"
        return req
    version = _version_tuple(out)
    if req.min_version and version and version[0] < req.min_version:
        req.ok = False
        req.detail = f"нужно {req.min_version}+, найдено {version[0]}"
        return req
    req.ok = True
    req.detail = out.splitlines()[0][:40] if out else "есть"
    return req


def load_servers(base: Path) -> list[Server]:
    """Читает реестр и проверяет требования каждого сервера."""
    data = load_registry(base)
    result: list[Server] = []
    for spec in data.get("servers") or []:
        if not isinstance(spec, dict):
            continue
        conn = spec.get("connection")
        server = Server(
            id=str(spec.get("id") or ""),
            name=str(spec.get("name") or ""),
            raw=spec,
            has_connection=isinstance(conn, dict) and bool(
                conn.get("command") or conn.get("url")
            ),
        )
        for item in spec.get("requires") or []:
            if isinstance(item, dict):
                server.requirements.append(check_requirement(item))
        result.append(server)
    return result


# ---------------------------------------------------------- блок настроек


def build_block(server: Server) -> str:
    """Кусок JSONC для секции mcp в opencode.jsonc. Пусто, если нечего.

    Формат ровно как у ncp_server_block: insert_entry ждёт готовую
    запись целиком — с именем сервера и запятой в конце, — а не только
    значение. Иначе в настройках появится лишняя скобка и файл
    перестанет читаться.
    """
    conn = server.raw.get("connection")
    if not isinstance(conn, dict):
        return ""
    url = str(conn.get("url") or "").strip()
    if url:
        body = {"type": "remote", "url": url, "enabled": True}
    else:
        command = [str(part) for part in (conn.get("command") or [])]
        if not command:
            return ""
        body = {"type": "local", "command": command, "enabled": True}
    inner = json.dumps(body, ensure_ascii=False, indent=2).splitlines()
    # Первая строка — «{», последняя — «}». Их не берём: свои скобки мы
    # ставим сами, вместе с именем сервера. Если взять и их, в настройках
    # получится «"имя": { { … }, }» и файл перестанет читаться.
    body_lines = "\n".join("    " + line for line in inner[1:-1])
    return f'"{server.id}": {{\n{body_lines}\n  }},'


def is_installed(dest: Path, server_id: str) -> bool:
    """Есть ли уже такой сервер в настройках opencode.

    has_entry ждёт текст самого объекта mcp, а не всего файла, поэтому
    сначала вырезаем объект по его границам.
    """
    from opencode_caps import find_key_object, has_entry  # локальный импорт

    cfg = Path(dest) / "opencode.jsonc"
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    bounds = find_key_object(text, "mcp")
    if bounds is None:
        return False
    return has_entry(text[bounds[0]:bounds[1]], server_id)


def _write_config(dest: Path, text: str) -> str:
    """Пишет настройки, предварительно сделав копию. Возвращает путь копии."""
    import time  # только для метки времени

    cfg = Path(dest) / "opencode.jsonc"
    if not cfg.is_file():
        cfg.write_text(
            '{\n  "$schema": "https://opencode.ai/config.json"\n}\n', encoding="utf-8"
        )
    backup_dir = Path(dest) / "_previous-version"
    backup_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"opencode.jsonc-{stamp}"
    shutil.copy2(cfg, backup)
    cfg.write_text(text, encoding="utf-8")
    return str(backup)


def warm_up(server: Server, progress=None) -> str:
    """Прогревает кэш npx: скачивает пакет заранее, до вписывания блока.

    Зачем это. Первый запуск через npx качает пакет около минуты, а
    opencode на старт сервера даёт 30 секунд и показывает «Не удалось».
    То есть платить за скачивание должен тот, кто его инициирует, а не
    opencode при следующем запуске. Здесь команда стартует, успевает
    скачать и тут же останавливается — кэш прогрет, дальше старт 2–3 с.

    Возвращает пустую строку, если прогрев не нужен или не удался:
    отсутствие прогрева не повод отказывать во включении.
    """
    conn = server.raw.get("connection")
    if not isinstance(conn, dict) or not conn.get("warm_up"):
        return ""
    command = [str(part) for part in (conn.get("command") or [])]
    if not command:
        return ""

    def say(text: str) -> None:
        if progress:
            progress(text)

    say(f"Первый запуск «{server.name}»: скачиваю пакет, это до минуты…")
    exe = shutil.which(command[0]) or command[0]
    argv = [exe, *command[1:]]
    if exe.lower().endswith((".cmd", ".bat")):
        argv = [os.environ.get("COMSPEC") or "cmd.exe", "/c", exe, *command[1:]]
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        return f"Прогрев не запустился: {exc}"
    try:
        try:
            proc.wait(timeout=WARM_UP_TIMEOUT)
        except subprocess.TimeoutExpired:
            # Сервер успешно стартовал и молча ждёт команды — значит
            # пакет уже скачан. Останавливаем, как и планировали.
            proc.kill()
        say(f"Пакет «{server.name}» скачан, кэш прогрет.")
        return ""
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def enable(dest: Path, server: Server, progress=None) -> tuple[list[str], list[str]]:
    """Включает сервер. Возвращает (сообщения, ошибки).

    Порядок именно такой: сначала проверка требований, потом запись.
    Вписать сервер, который не запустится, хуже, чем не вписать его и
    объяснить, чего не хватает.
    """
    from opencode_caps import check_jsonc, ensure_object, insert_entry

    messages: list[str] = []
    errors: list[str] = []
    if not server.has_connection:
        return ([], ["В реестре нет команды подключения — включать нечем."])
    missing = server.missing
    if missing:
        return ([], [f"Не хватает: {', '.join(r.what for r in missing)}"])
    if server.blocking_manual:
        return ([], [
            "Сервер без этого работать не будет: "
            + ", ".join(r.what for r in server.blocking_manual)
        ])
    block = build_block(server)
    if not block:
        return ([], ["Команда подключения пустая — проверь реестр."])

    # Прогрев до вписывания: иначе opencode на своём старте не дождётся
    # скачивания и покажет «Не удалось».
    note = warm_up(server, progress)
    if note:
        errors.append(note)

    cfg = Path(dest) / "opencode.jsonc"
    try:
        text = cfg.read_text(encoding="utf-8") if cfg.is_file() else "{}"
    except (OSError, UnicodeDecodeError) as exc:
        return ([], [f"Настройки не прочитались: {exc}"])
    try:
        text = ensure_object(text, "mcp")
        text = insert_entry(text, "mcp", server.id, block)
    except ValueError as exc:
        return ([], [f"Настройки сломаны — правь вручную: {exc}"])
    if not check_jsonc(text):
        return ([], ["После вставки файл перестал читаться — не пишу его."])
    try:
        backup = _write_config(dest, text)
    except OSError as exc:
        return ([], [f"Не записались настройки: {exc}"])
    messages.append(f"Сервер «{server.name}» вписан в настройки opencode")
    messages.append(f"Копия настроек: {backup}")
    if server.manual:
        messages.append(
            "Проверь вручную: "
            + "; ".join(f"{r.what} — {r.note}" for r in server.manual)
        )
    messages.append("Перезапусти opencode: серверы читаются при старте.")
    return messages, errors


def disable(dest: Path, server: Server) -> tuple[list[str], list[str]]:
    """Выключает сервер: убирает его блок из настроек."""
    from opencode_caps import check_jsonc, remove_entry

    messages: list[str] = []
    errors: list[str] = []
    cfg = Path(dest) / "opencode.jsonc"
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ([], [f"Настройки не прочитались: {exc}"])
    if server.id not in text:
        return ([f"Сервер «{server.name}» и так не вписан."], [])
    try:
        text = remove_entry(text, "mcp", server.id)
    except ValueError as exc:
        return ([], [f"Настройки сломаны — правь вручную: {exc}"])
    if not check_jsonc(text):
        return ([], ["После удаления файл перестал читаться — не пишу его."])
    try:
        backup = _write_config(dest, text)
    except OSError as exc:
        return ([], [f"Не записались настройки: {exc}"])
    messages.append(f"Сервер «{server.name}» убран из настроек")
    messages.append(f"Копия настроек: {backup}")
    return messages, errors


def mark_installed(servers: list[Server], dest: Path) -> None:
    for server in servers:
        server.installed = is_installed(dest, server.id)
