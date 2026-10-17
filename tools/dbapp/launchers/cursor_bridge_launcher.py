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


#: Где может лежать Cursor CLI. Тот же порядок: сначала кандидат проверяется
#: запуском `--version`, и только рабочий берётся. Пакетные файлы не берём.
AGENT_SPEC = common.ProgramSpec(
    name="agent",
    exe_names=("agent",),
    extra_globs=(r"%LOCALAPPDATA%\Programs\cursor\bin\agent.exe",
                 r"%LOCALAPPDATA%\Programs\Cursor\bin\agent.exe",
                 r"%ProgramFiles%\cursor\bin\agent.exe"),
    app_paths=(r"%LOCALAPPDATA%\Programs\cursor",),
)


#: Cursor CLI на Windows ставится так: в %LOCALAPPDATA%\cursor-agent лежат
#: пакетные обёртки agent.cmd и agent.ps1, а настоящая программа — node.exe с
#: index.js в подпапке версии. Мы идём прямо к настоящей программе: обёртки
#: трогать нельзя, через cmd.exe текст запроса разбирается заново.
CURSOR_AGENT_HOME = r"%LOCALAPPDATA%\cursor-agent"
CURSOR_INDEX = "index.js"


def cursor_agent_program() -> tuple[list[str] | None, str]:
    """Настоящая программа Cursor CLI: [node.exe, index.js]. Нет — причина.

    Папку версий выбираем по имени: в имени дата версии, поэтому
    лексикографически больший путь и есть самая свежая. Сортировка по времени
    изменения файла здесь была бы произвольной — установщик мог дописать
    файлы в старую папку.
    """
    import os as _os
    home = Path(_os.path.expandvars(CURSOR_AGENT_HOME))
    versions = home / "versions"
    if not versions.is_dir():
        return None, (f"Cursor CLI не установлена: папки {versions} нет. "
                      "Установил бы мост сам при подключении.")
    candidates = sorted((p for p in versions.iterdir() if p.is_dir()),
                        key=lambda p: p.name, reverse=True)
    for folder in candidates:
        index = folder / CURSOR_INDEX
        if not index.is_file():
            continue
        node = common.resolve_exe("node")
        if not node:
            return None, ("Cursor CLI установлена, но node не найден: без него "
                          "запустить её нечем.")
        # Проверяем запуском: найти файл и уметь его запустить — разное.
        good, _checked, why = common.probe_candidate(node, False)
        if not good:
            return None, f"node не запускается: {why}"
        return [node, str(index)], f"Cursor CLI {folder.name}"
    return None, "В папке версий Cursor CLI нет index.js."


def find_agent_detail() -> common.ProgramFound:
    """Подробный итог поиска: путь, источник и что отвергли."""
    found = common.find_cli(AGENT_SPEC)
    program, why = cursor_agent_program()
    if program:
        # Настоящая программа найдена — она важнее любого файла в PATH.
        found.path = program[0]
        found.from_source = "папка cursor-agent"
        found.checked = True
        found.reason = why
    elif found.path:
        found.reason = ("найден файл в PATH, но он не нативный: " + why)
    else:
        found.reason = why
    return found


def find_agent() -> str | None:
    """Программа запуска: список из файла и, если нужно, скрипта.

    None — CLI нет. Прежние вызовы ждали строку, поэтому возвращается первый
    элемент, а полный список берётся функцией agent_program().
    """
    program, _why = cursor_agent_program()
    if program:
        return program[0]
    return common.find_cli_path(AGENT_SPEC)


def agent_program() -> list[str] | None:
    """Полная команда запуска или None."""
    program, _why = cursor_agent_program()
    if program:
        return program
    return [p for p in [common.find_cli_path(AGENT_SPEC)] if p]


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    values = common.parse_kv(common.read_text(settings_file()))
    key = values.get("CURSOR_API_KEY", "").strip()
    if key:
        env["CURSOR_API_KEY"] = key
    return env


#: Слово «Not authenticated» взято из документации Cursor CLI
#: (cursor.com/docs/cli/reference/authentication, раздел Troubleshooting), а
#: не придумано здесь. Остальное правило структурное: ищем в тексте «auth»
#: или «login», а не готовую фразу, которой у программы может не быть.
def login_hint(text: str) -> str:
    """Человеческая строка, если текст говорит про вход."""
    low = (text or "").lower()
    if any(word in low for word in ("auth", "login", "log in")):
        return (
            "Вход в Cursor не сработал. Войди сам: agent login — он открывает "
            "браузер. Ключ можно записать в mcp-cursor.txt."
        )
    return ""


def _as_list(exe) -> list[str]:
    """Программа запуска как список. Прежние вызовы давали строку."""
    return list(exe) if isinstance(exe, (list, tuple)) else [exe]


#: Слова отказа во входе. Проверяются по ТЕКСТУ, а не по коду: живая
#: проверка 15.10.2026 показала, что `agent status` возвращает код 0 и
#: одновременно пишет «Not logged in». Код 0 сам по себе не доказывает вход —
#: иначе мост писал бы «вход подтверждён» про отсутствие входа.
LOGIN_DENIED_MARKS = ("not logged in", "not authenticated", "no logged in")


def login_note(exe: str) -> str:
    """Строка журнала о входе. `agent status` только читает состояние."""
    code, text = common.probe_command([*_as_list(exe), "status"], timeout=20)
    low = (text or "").lower()
    if any(mark in low for mark in LOGIN_DENIED_MARKS):
        return "входа нет: команда status сказала прямо, что входа нет"
    if code == 0:
        tail = (text.splitlines() or ["agent status ответил кодом 0"])[-1].strip()
        return f"вход подтверждён: {tail[:120]}"
    if code is None:
        return "состояние входа команда не подтвердила"
    return (
        f"входа нет или ключ не принят: {(text.splitlines() or [f'код {code}'])[-1].strip()[:160]}. "
        "Войди сам: agent login — он открывает браузер. Или запиши ключ в mcp-cursor.txt"
    )


def run_agent(argv: list[str], folder: str | None) -> tuple[int, str, str]:
    """Запускает Cursor CLI и возвращает код, вывод и ошибки.

    stdin у ребёнка закрыт: у codex exec проверено живьём 15.10.2026, что
    без этого он читает канал протокола MCP и вызов виснет до таймаута. У
    Cursor CLI живого запуска ещё не было — закрываем stdin preemptively,
    текст команды идёт аргументом и от канала не зависит.
    """
    code, stdout, stderr, status = common.run_capture(
        argv, cwd=folder, timeout=TIMEOUT, env=child_env())
    if status:
        note = common.stop_status_text(status, "Cursor", TIMEOUT)
        return code if code is not None else 1, "", note or stderr
    return code, stdout, stderr


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
    exe = agent_program() or find_agent()
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
        if not (stdout or stderr):
            text = ("Cursor не вернул ни слова. Проверь вход: agent status, "
                    "а войти — agent login.")
        hint = login_hint(f"{stdout}\n{stderr}")
        if len(text) > 8000:
            text = text[:8000] + "\n…обрезано"
        head = f"код: {code}\n\n"
        if hint:
            head = hint + "\n\n" + head
        return head + text
    return "Такого инструмента нет."


def main() -> int:
    exe = agent_program() or find_agent()
    if not exe:
        common.say(PREFIX, "команда agent не найдена")
        common.say(PREFIX, "Это Cursor CLI. Установка описана на cursor.com/docs/cli/installation.")
        return 1
    common.say(PREFIX, login_note(exe))
    values = common.parse_kv(common.read_text(settings_file()))
    if values.get("CURSOR_API_KEY", "").strip():
        common.say(PREFIX, "ключ прочитан, в журнал и в командную строку не пишу")
    else:
        common.say(PREFIX, "ключа в файле нет, Cursor возьмёт свой вход, если он уже есть")
    common.say(PREFIX, "--yolo не передаю. --force только если явно попросили правки")
    return mcp_stdio.serve("cursor-cli", TOOLS, call_tool)


if __name__ == "__main__":
    sys.exit(main())
