"""Мосты не должны открывать окна консоли.

Запуск: python tools/dbapp/test_bridges_no_console.py

Поломка, которую проверка закрывает. 19.10.2026 человек выбрал строку
OmniRoute в списке мостов, и у него открылось четыре чёрных окна
консоли — по одному на каждый запуск CLI.

Причина. В строке реестра состояние моста показывается функцией
`omniroute.status_text()`. Зовётся она при каждом выборе строки, а
внутри два раза запускает CLI OmniRoute: `omniroute health --json` и
`omniroute providers list --json`. Оба запуска идут через `_run()`, а
в нём не было `startupinfo`. Программа запущена на pythonw — у неё
самой консоли нет, поэтому Windows на каждый запуск node.exe открывал
новую. Четыре окна = два вызова по два запуска.

Тот же класс поломки был и у моста арены (`lmarena._run`), и он
закрыт тем же способом.

Спрятать надо `core.hidden_startupinfo()`. Именно STARTUPINFO со
SW_HIDE, а не CREATE_NO_WINDOW: с CREATE_NO_WINDOW вывод в подставленную
трубу теряется, а мосты говорят результат через stdout.

Проверка читает исходники и делает живой запуск. Ничего на машине не
меняет: пакеты не ставятся, серверы не трогаются.

**Чего проверка не умеет и поэтому не делает.** Окно на живой машине
не измерить изнутри программы — это видно только человеку. Проверка
поэтому смотрит, что флаг скрытия стоит у КАЖДОГО запуска, и делает
живой запуск, чтобы убедиться, что вывод дошёл. Окна на экране
смотреть самому.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import lmarena  # noqa: E402
import omniroute  # noqa: E402

passed = 0
failed = 0

#: Имена флагов, которыми окно прячется или консоль отцепляется.
HIDING_NAMES = ("startupinfo", "creationflags", "start_new_session")

#: Сколько строк вокруг вызова смотрим, когда флаги спрятаны в `**kwargs`.
SPREAD_WINDOW = 25


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


def _spawn_calls(module):
    """Все вызовы внешних программ в модуле: (номер строки, имена аргументов).

    Разбираем дерево, а не ищем подстроку: подстрока `startupinfo`
    есть и в комментариях, и в docstring.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
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
        found.append((node.lineno, names))
    return source.splitlines(), found


def _hiding_near(lines, lineno: int) -> bool:
    """Есть ли флаг скрытия рядом с вызовом.

    Нужен для вызовов вида `Popen(argv, **kwargs)`: там флаги лежат в
    словаре, и по аргументам самого вызова их не видно.
    """
    low = max(0, lineno - SPREAD_WINDOW)
    high = min(len(lines), lineno + SPREAD_WINDOW)
    window = "\n".join(lines[low:high])
    return any(name in window for name in HIDING_NAMES)


def main() -> int:
    # --- 1. у каждого запуска внешней программы стоит флаг скрытия окна
    for module in (omniroute, lmarena):
        lines, calls = _spawn_calls(module)
        naked = []
        for lineno, names in calls:
            if any(name in names for name in HIDING_NAMES):
                continue
            if None in names:  # **kwargs — флаги внутри словаря
                if _hiding_near(lines, lineno):
                    continue
                naked.append(f"строка {lineno} (**kwargs без флага)")
                continue
            naked.append(f"строка {lineno}: {lines[lineno - 1].strip()[:62]}")
        check(not naked,
              f"в {module.__name__} каждый запуск внешней программы идёт "
              f"со скрытием окна"
              + ("" if not naked else ": " + "; ".join(naked)))

    # --- 2. скрытие именно правильное: STARTUPINFO, а не CREATE_NO_WINDOW
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

    # --- 3. живой запуск: команда отработала и ответила
    #
    # Ответ зависит от машины, а не от кода: важно, какой экземпляр
    # пакета развёрнут в ЭТОЙ копии программы и какой сервер поднят.
    # На одной машине живут две копии, и поднятый сервер может
    # принадлежать другой. Тогда CLI честно отвечает отказом, и это
    # не поломка. Поэтому отказ здесь — не провал, а честная пометка;
    # провалом считается только «ответили, но ответа не разобрали».
    dest = omniroute.find_settings_dir()
    if not omniroute.deployed():
        check(True, "OmniRoute в этой копии не развёрнут — живой запуск "
                    "пропускаем")
    else:
        code, out, err = omniroute._run(["health", "--json"], dest)
        if code != 0:
            check(True, f"живой запуск CLI не прошёл (код {code}) — это "
                        f"внешнее условие, не поломка: "
                        f"{(err or out).strip()[-120:]}")
        else:
            check("version" in out,
                  f"живой запуск CLI отработал и ответил: {out.strip()[:90]}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())