"""Проверки поиска установленной программы. Сеть и чужие программы не нужны.

    python tools/dbapp/launchers/test_program_find.py

Рабочие заглушки — настоящий системный curl.exe: на `--version` он отвечает
кодом 0, и это единственный настоящий запуск в этих проверках. Битые
кандидаты — файлы с мусором внутри.

Чего эти проверки не доказывают: ветка таймаута проверяется подменой
subprocess.run, потому что по-настоящему зависший на `--version` процесс на
этой машине не воспроизводится. Притворяться, что воспроизводится, не нужно.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bridge_common as common  # noqa: E402

WORKING = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/curl.exe"

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


def working_copy(folder: Path, name: str) -> Path:
    target = folder / name
    target.write_bytes(WORKING.read_bytes())
    return target


def broken(folder: Path, name: str) -> Path:
    """Файл с расширением .exe, который не запускается."""
    target = folder / name
    target.write_bytes(b"not a program at all")
    return target


def batch_stub(folder: Path, name: str, marker: Path) -> Path:
    """Пакетный файл, который при запуске оставил бы след."""
    target = folder / name
    target.write_text(
        "@echo off\r\n" f"echo ran > \"{marker}\"\r\n" "exit /b 0\r\n",
        encoding="utf-8",
    )
    return target


def spec(name: str, **kwargs) -> common.ProgramSpec:
    return common.ProgramSpec(name=name, exe_names=(name,), **kwargs)


def find(s: common.ProgramSpec, home: Path, dirs: list[str], shortcuts=None,
         winget: list[Path] | None = None):
    # winget_roots=[] обязателен: иначе проверка искала бы настоящую машину
    # и результат зависел бы от того, что у человека установлено.
    return common.find_cli(
        s, path_dirs=dirs, home=home,
        winget_roots=[] if winget is None else winget,
        shortcut_targets={} if shortcuts is None else shortcuts)


def main() -> None:
    if not WORKING.is_file():
        print(f"  FAIL  нет рабочей заглушки {WORKING}")
        print("ИТОГ: 0 проверок, 1 провал")
        raise SystemExit(1)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Дома, в которых программы искаться не должна. Обязательно пустые:
        # общая папка с рабочей копией из первых проверок ломала отрицательные.
        blank = root / "blank_home"
        blank.mkdir()
        blank2 = root / "blank_home2"
        blank2.mkdir()
        none = str(root / "нет_такой_папки")

        # === 1. Каждый источник по отдельности ===
        p1 = root / "path1"
        p1.mkdir()
        exe1 = working_copy(p1, "prog.exe")
        r = find(spec("prog"), blank, [str(p1)])
        check(r.path == str(exe1), "источник 1: PATH")
        check(r.from_source == common.SOURCE_PATH, "источник 1 назван верно")
        check(r.checked, "источник 1: кандидат проверен настоящим запуском")

        cfg = blank / ".codex"
        cfg.mkdir()
        p2 = root / "path2"
        p2.mkdir()
        exe2 = working_copy(p2, "prog.exe")
        (cfg / "config.toml").write_text(
            'CODEX_CLI_PATH = "' + str(exe2) + '"\n', encoding="utf-8")
        r = find(common.ProgramSpec(
            name="prog", exe_names=("prog",),
            config_hint=".codex/config.toml:CODEX_CLI_PATH"), blank, [none])
        check(r.path == str(exe2), "источник 2: настройки программы")
        check(r.from_source == common.SOURCE_CONFIG, "источник 2 назван верно")

        app = root / "app" / "bin"
        (app / "1.0.0").mkdir(parents=True)
        (app / "2.0.0").mkdir(parents=True)
        old_exe = app / "1.0.0" / "prog.exe"
        new_exe = app / "2.0.0" / "prog.exe"
        old_exe.write_bytes(WORKING.read_bytes())
        new_exe.write_bytes(WORKING.read_bytes())
        now = time.time()
        os.utime(old_exe, (now - 10000, now - 10000))
        os.utime(new_exe, (now, now))
        r = find(common.ProgramSpec(
            name="prog", exe_names=("prog",),
            extra_globs=(str(app / "*" / "prog.exe"),)), blank, [none])
        check(r.path == str(new_exe), "источник 3: папка приложения, свежая сверху")
        check(r.from_source == common.SOURCE_APP, "источник 3 назван верно")

        user = blank / ".local" / "bin"
        user.mkdir(parents=True)
        exe4 = working_copy(user, "prog.exe")
        r = find(spec("prog"), blank, [none])
        check(r.path == str(exe4), "источник 4: папка пользователя")
        check(r.from_source == common.SOURCE_USER, "источник 4 назван верно")

        sc = root / "sc"
        sc.mkdir()
        exe5 = working_copy(sc, "prog.exe")
        r = find(spec("prog"), blank2, [none], {"prog": str(exe5)})
        check(r.path == str(exe5), "источник 5: ярлык «Пуск»")
        check(r.from_source == common.SOURCE_SHORTCUT, "источник 5 назван верно")

        # === Источник winget: пакеты лежат в WinGet\Packages, псевдоним в
        # PATH может не появиться ===
        # Домашняя папка тут blank2, а не blank: в blank мы выше положили
        # prog.exe в .local\bin, и нашёлся бы источник 4 — раньше winget.
        wk = root / "winget"
        pkg_a = wk / "Первый_Пакет_источник"
        pkg_b = wk / "Второй_Пакет_источник"
        pkg_a.mkdir(parents=True)
        pkg_b.mkdir(parents=True)
        wk_old = pkg_a / "prog.exe"
        wk_new = pkg_b / "prog.exe"
        working_copy(pkg_a, "prog.exe")
        working_copy(pkg_b, "prog.exe")
        os.utime(wk_old, (now - 10000, now - 10000))
        os.utime(wk_new, (now, now))
        r = find(spec("prog"), blank2, [none], winget=[wk])
        check(r.path == str(wk_new), "источник 5: папка winget, свежая сверху")
        check(r.from_source == common.SOURCE_WINGET,
              "источник 5 назван верно (winget)")
        r = find(spec("prog"), blank2, [none], winget=[wk / "нет-такой"])
        check(r.path == "", "пустая папка winget не выдумывает находку")
        check(r.from_source == common.SOURCE_NONE, "не найдено честно сказано")

        # Версия в имени манифеста: файл лежит на уровень глубже.
        deep = root / "winget2" / "Пакет_источник" / "1.2.3"
        deep.mkdir(parents=True)
        deep_exe = working_copy(deep, "prog.exe")
        r = find(spec("prog"), blank2, [none], winget=[root / "winget2"])
        check(r.path == str(deep_exe), "источник 5: версия во вложенной папке")

        # Чужое имя в папке winget мимо: "prog.exe" ищем, "agent.exe" нет.
        other = root / "winget3" / "Пакет_источник"
        other.mkdir(parents=True)
        working_copy(other, "agent.exe")
        r = find(spec("prog"), blank2, [none], winget=[root / "winget3"])
        check(r.path == "", "чужой файл в папке winget не подходит")

        # === 2. Порядок PATH, а не свежесть файла ===
        a_dir = root / "pathA"
        b_dir = root / "pathB"
        a_dir.mkdir()
        b_dir.mkdir()
        a_exe = working_copy(a_dir, "prog.exe")
        b_exe = working_copy(b_dir, "prog.exe")
        os.utime(a_exe, (now - 10000, now - 10000))
        os.utime(b_exe, (now, now))
        r = find(spec("prog"), blank, [str(a_dir), str(b_dir)])
        check(r.path == str(a_exe),
              "PATH не сортируется по дате: раньше в PATH значит раньше")

        # === 3. Первый кандидат не рабочий — берём следующий ===
        broken(a_dir, "prog.exe")
        r = find(spec("prog"), blank, [str(a_dir), str(b_dir)])
        check(r.path == str(b_exe), "нерабочий первый кандидат пропущен")
        tried = [x for x in r.attempts if x["path"] == str(a_exe)]
        check(bool(tried) and tried[0]["record"] == common.REC_PROBED,
              "нерабочий кандидат помечен как проверенный, а не отказ по типу")
        check(any("не запустилась" in x["result"] for x in tried),
              "причина «не запустилась» названа")

        # === 4. Порядок папок влияет на выбор ===
        r = find(spec("prog"), blank, [str(b_dir), str(a_dir)])
        check(r.path == str(b_exe), "поменяли порядок папок — поменялся ответ")

        # === 5. Два нерабочих подряд ===
        bad = root / "onlybad"
        bad.mkdir()
        broken(bad, "prog.exe")
        (bad / "prog.cmd").write_text("@echo off\r\nexit /b 3\r\n",
                                      encoding="utf-8")
        r = find(spec("prog"), blank2, [str(bad)])
        check(r.path == "", "нерабочие кандидаты не выданы за найденные")
        check(r.from_source == common.SOURCE_NONE, "итог назван «не найдено»")
        check(len(r.attempts) >= 2, "обе причины попали в attempts")
        check(any("отказ в допуске" in x["result"] for x in r.attempts),
              "отказ по типу файла виден отдельной строкой")
        check(bool(r.reason), "reason заполнен при пустом path")
        check(r.reason != common.SOURCE_NONE and len(r.reason) < 200,
              "reason короткий и это не маркер источника")

        # === 6. Нулевой размер ===
        z = root / "zero"
        z.mkdir()
        (z / "prog.exe").write_bytes(b"")
        r = find(spec("prog"), blank2, [str(z)])
        check(r.path == "", "файл нулевого размера не взят")
        check(any("нулевого размера" in x["result"] for x in r.attempts),
              "причина нулевого размера видна")
        check(all(x["record"] == common.REC_FOUND for x in r.attempts),
              "нулевой файл записан как отсев, а не как отказ по типу")

        # === 7. Пакетные файлы ===
        marker = root / "marker.txt"
        p4 = root / "path4"
        p4.mkdir()
        batch_stub(p4, "prog.cmd", marker)
        r = find(spec("prog"), blank2, [str(p4)])
        check(r.path == "", "в режиме агента .cmd не взят")
        check(not marker.exists(), "побочная команда не выполнилась")
        check(all(x["record"] == common.REC_DENIED for x in r.attempts),
              "отказ записан как отказ политикой типа файла")
        allowed = find(spec("prog"), blank2, [str(p4)],
                       None) if False else common.find_cli(
            spec("prog"), allow_batch=True, path_dirs=[str(p4)], home=blank2,
            shortcut_targets={})
        check(bool(allowed.path) or marker.exists(),
              "при allow_batch=True пакетный файл допускается к проверке")

        # === 8. Обёртка: None, а не пустая строка ===
        got = common.find_cli_path(spec("prog"), path_dirs=[none], home=blank2,
                                   shortcut_targets={})
        check(got is None, "find_cli_path отдаёт None при отсутствии программы")
        got = common.find_cli_path(spec("prog"), path_dirs=[str(p1)], home=blank,
                                   shortcut_targets={})
        check(got == str(exe1), "find_cli_path отдаёт путь при успехе")
        r = find(spec("prog"), blank2, [none])
        check(r.path == "" and bool(r.reason),
              "find_cli отдаёт ProgramFound с пустым path и непустым reason")

        # === 9. CODEX_CLI_PATH на битом, пустом и чужом TOML ===
        toml_home = root / "toml_home"
        (toml_home / ".claude").mkdir(parents=True)
        conf = toml_home / ".claude" / "config.toml"
        s_toml = common.ProgramSpec(
            name="prog", exe_names=("prog",),
            config_hint=".claude/config.toml:CLAUDE_CLI_PATH")
        for label, body in (
            ("битый", 'ключ без "значения\n[[[ nonsense\n'),
            ("пустой", ""),
            ("чужой", "# комментарий\nother_key = 1\n[раздел]\n"),
            ("без значения", "CLAUDE_CLI_PATH = \n"),
            ("только кавычки", 'CLAUDE_CLI_PATH = ""\n'),
        ):
            conf.write_text(body, encoding="utf-8")
            got = common.find_cli_path(s_toml, path_dirs=[none], home=toml_home,
                                       shortcut_targets={})
            check(got is None, "битый TOML не роняет поиск и не даёт путь: " + label)
        conf.write_text('CLAUDE_CLI_PATH = "' + str(exe1) + '"\n',
                        encoding="utf-8")
        got = common.find_cli_path(s_toml, path_dirs=[none], home=toml_home,
                                   shortcut_targets={})
        check(got == str(exe1), "нормальный TOML даёт путь")

        # === 10. Таймаут проверки ===
        real_run = common.subprocess.run

        def hanging(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="prog", timeout=15)

        common.subprocess.run = hanging
        try:
            good, checked, why = common.probe_candidate(str(exe1), False)
        finally:
            common.subprocess.run = real_run
        check(good is False and checked is True,
              "зависшая проверка не считается успехом")
        check("не ответил за 15 секунд" in why, "причина таймаута названа прямо")
        check(common.PROBE_TIMEOUT == 15, "таймаут проверки равен 15 секундам")

        # === 11. Прочее расширение ===
        other = root / "other"
        other.mkdir()
        ps1 = other / "prog.ps1"
        ps1.write_text("Write-Output 1\r\n", encoding="utf-8")
        good, checked, why = common.probe_candidate(str(ps1), False)
        check(good and not checked, "непроверяемый тип принят без запуска")
        check("проверять нечем" in why, "причина «проверять нечем» названа")

        # === 12. Ничего не нашлось ===
        r = find(common.ProgramSpec(
            name="prog", exe_names=("prog",), app_paths=("%APPDATA%\\Есть",)),
            blank2, [none])
        check(r.path == "" and r.from_source == common.SOURCE_NONE,
              "пустой результат оформлен правильно")
        check("не нашли ни одного кандидата" in r.reason,
              "при отсутствии сказано про отсутствие, а не про поломку")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()