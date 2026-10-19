"""Ни один запуск внешней программы в программе не открывает окно консоли.

Запуск: python tools/dbapp/test_no_console_windows.py

Что тут проверяется. 19.10.2026 человек нажал «Настроить автоматически»
у моста OBS — и у него открылось чёрное окно консоли. Оказалось, таких
мест не одно: ловушка на `subprocess.Popen` показала за один прогон

    [окно] tasklist /FI IMAGENAME eq obs64.exe   ← bridges.obs_running
    [окно] rtk.exe --version                     ← rtk
    [окно] greenlight.exe --version             ← greenlight
    [окно] go.exe version                        ← greenlight

А первые окна, которые он увидел, выбрал строку OmniRoute в списке
мостов: состояние строки зовёт `status_text()`, а тот дважды запускает
CLI моста.

**Почему окно вообще появляется.** Программа работает на pythonw — у неё
самой консоли нет. Windows на каждый запуск консольной программы без
специальной просьбы создаёт ей новое окно. Просьба называется
`core.hidden_startupinfo()`: STARTUPINFO со SW_HIDE.

**Почему не CREATE_NO_WINDOW.** Измерено ранее: с CREATE_NO_WINDOW
ребёнок отрабатывает, но вывод в подставленную трубу теряется, а
программа читает вывод почти везде — версии, ответы `--json`, статусы.

**Чего проверка не умеет.** Само окно на живой машине изнутри программы
не измерить. Поэтому проверка смотрит, что флаг скрытия стоит у
КАЖДОГО запуска, и делает живые запуски, чтобы убедиться, что они
отработали. Окна на экране смотреть самому.

**Про `**kwargs`.** Флаги иногда лежат в словаре: `Popen(argv, **kwargs)`
по аргументам самого вызова неразличим с голым. Поэтому такой вызов
считается годным, если в окрестностях строки есть хоть одно из трёх
имён — `startupinfo`, `creationflags`, `start_new_session`. Это честная
граница: не видно — не объявляем поломку.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402

passed = 0
failed = 0

#: Имена флагов, которыми окно прячется или консоль отцепляется.
HIDING_NAMES = ("startupinfo", "creationflags", "start_new_session")

#: Сколько строк вокруг вызова смотрим при `**kwargs`.
SPREAD_WINDOW = 25

#: Что не проверяем.
#:
#: `core.py` — там сам помощник, и `selftest.py` с `test_*` — это
#: проверки, а не программа: они запускаются из консоли человеком
#: намеренно, и прятать им окно незачем.
SKIP = {"core.py", "selftest.py"}

LAUNCHERS = {"bridge_common.py", "dbhub_bridge_launcher.py"}


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


def targets():
    """Модули программы, которые запускают внешние программы."""
    files = sorted(p for p in HERE.glob("*.py")
                   if p.name not in SKIP and not p.name.startswith("test_"))
    files += sorted(p for p in (HERE / "launchers").glob("*.py")
                    if p.name not in SKIP and not p.name.startswith("test_"))
    return files


def _read(path: Path) -> str:
    """Прочитать файл модуля.

    Именно `utf-8-sig`: в программе есть файлы с BOM (перенос из
    старой копии оставил его), и обычный `utf-8` оставляет в начале
    невидимый U+FEFF — после него `ast.parse` падает на первой же
    строке, и проверка не доходит до сути.
    """
    return path.read_text(encoding="utf-8-sig")


def all_calls(path: Path):
    """Все вызовы subprocess в модуле — и годные, и нет."""
    source = _read(path)
    tree = ast.parse(source)
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr in ("run", "Popen", "call", "check_output")]


def naked_calls(path: Path):
    """Запуски без флага скрытия: список строк с текстом."""
    source = _read(path)
    tree = ast.parse(source)
    lines = source.splitlines()
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
                and func.attr in ("run", "Popen", "call", "check_output")):
            continue
        names = {kw.arg for kw in node.keywords}
        if any(name in names for name in HIDING_NAMES):
            continue
        if None in names:  # **kwargs — флаги внутри словаря
            low = max(0, node.lineno - SPREAD_WINDOW)
            high = min(len(lines), node.lineno + SPREAD_WINDOW)
            window = "\n".join(lines[low:high])
            if any(name in window for name in HIDING_NAMES):
                continue
            found.append((node.lineno, "**kwargs без флага поблизости",
                          lines[node.lineno - 1].strip()))
            continue
        found.append((node.lineno, "флага нет вовсе",
                      lines[node.lineno - 1].strip()))
    return found


def main() -> int:
    # --- сам помощь скрывает окно правильным способом
    info = core.hidden_startupinfo()
    if sys.platform == "win32":
        check(info is not None
              and info.dwFlags & subprocess.STARTF_USESHOWWINDOW,
              "core.hidden_startupinfo() возвращает STARTUPINFO со SW_HIDE")
        check(info is not None and info.wShowWindow == subprocess.SW_HIDE,
              "и окно именно скрыто, а не только помечено флагом")
    else:
        check(info is None,
              "на другой системе STARTUPINFO нет и возвращается None")

    # --- у каждого запуска в программе флаг скрытия стоит
    total = 0
    broken: list[str] = []
    for path in targets():
        # Считаем ВСЕ вызовы, а не только голые: иначе проверка на
        # исправной программе рапортовала «все 0 запусков», и по этому
        # тексту нельзя было понять, что она вообще что-то проверяла.
        total += len(all_calls(path))
        found = naked_calls(path)
        for lineno, why, text in found:
            where = (f"{path.parent.name}/{path.name}"
                     if path.parent.name == "launchers" else path.name)
            broken.append(f"{where}:{lineno} ({why}) — {text[:54]}")

    check(total > 0,
          f"проверка вообще нашла запуски внешних программ: {total}")
    check(not broken,
          f"все {total} запусков внешних программ идут со скрытием окна"
          if not broken else
          "запуски без скрытия окна: " + "; ".join(broken[:8])
          + (f"; и ещё {len(broken) - 8}" if len(broken) > 8 else ""))

    # --- помощник есть в каждом модуле, где он нужен
    without_helper = []
    for path in targets():
        source = _read(path)
        if "hidden_startupinfo" not in source:
            continue
        has_local = ("def _hidden_startupinfo(" in source
                     or "def hidden_startupinfo(" in source
                     or "from core import hidden_startupinfo" in source
                     or "import core" in source)
        if not has_local:
            without_helper.append(path.name)
    check(not without_helper,
          "везде, где пишут про скрытие окна, есть и сам помощник"
          + ("" if not without_helper else ": " + ", ".join(without_helper)))

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())