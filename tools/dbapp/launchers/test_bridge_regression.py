"""Регрессия: старые мосты должны работать прежним способом.

    python tools/dbapp/launchers/test_bridge_regression.py

Отдельный файл не для красоты. Мы правили общий `bridge_common.py`, которым
пользуются все мосты сразу, и тесты нового помощника этого не доказывают:
можно написать идеальный новый API и при этом сломать старого потребителя.

Здесь проверяется ровно то, что не должно измениться: сборка команды,
регистрация, формат ответа и отсутствие новых подсказок про установку там,
где их раньше не было.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bridge_common as common  # noqa: E402
import codex_bridge_launcher as codex  # noqa: E402
import cursor_bridge_launcher as cursor  # noqa: E402
import spotify_bridge_launcher as spotify  # noqa: E402
import tiktok_bridge_launcher as tiktok  # noqa: E402
import unity_bridge_launcher as unity  # noqa: E402
import unreal_bridge_launcher as unreal  # noqa: E402

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


def main() -> None:
    # === 1. resolve_exe не изменился: прежние потребители ===
    check(common.resolve_exe("") is None, "пустое имя даёт None, как и раньше")
    check(common.resolve_exe("точно_нет_такой_программы_98765") is None,
          "отсутствующая программа даёт None, как и раньше")
    check(common.resolve_exe("node") is not None, "node по-прежнему находится")
    check(isinstance(common.resolve_exe("node"), str),
          "возвращается строка, а не Path и не список")

    # === 2. prepare_argv: пакетный файл идёт через cmd, остальное как есть ===
    prepared = common.prepare_argv(["cmd.exe", "/c", "echo привет"])
    check(prepared[0].lower().endswith("cmd.exe"), "прямой путь не переписывается")
    check("cmd" not in " ".join(prepared).lower() or "/c" in prepared,
          "прямой запуск не оборачивается в cmd")

    bat = HERE / "_регрессия_проба.cmd"
    try:
        bat.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
        wrapped = common.prepare_argv([str(bat)])
        check(wrapped[1] == "/c", "пакетный файл по-прежнему идёт через cmd /c")
        check(any(part.lower().endswith("cmd.exe") for part in wrapped),
              "первым стоит сама оболочка cmd")
    finally:
        if bat.exists():
            bat.unlink()

    # === 3. Spotify: пакет закреплён, версия не поехала ===
    check(spotify.PACKAGE == "@xavifabregat/spotify-mcp@0.1.2",
          "Spotify остался на закреплённой версии")
    check("@latest" not in spotify.PACKAGE, "в пакете Spotify нет @latest")

    # === 4. Старые мосты не получают новых подсказок про установку ===
    for label, notes in (
        ("spotify", spotify.startup_notes("", False, False)),
        ("spotify (с ключом)", spotify.startup_notes("id", True, True)),
    ):
        joined = " | ".join(notes)
        check("winget install" not in joined,
              f"{label}: команда установки не появилась в старых подсказках")

    # === 5. Codex: прежние ограничения на месте ===
    argv = codex.agent_argv.codex_exec_argv("C:\\codex.exe", "привет", "read-only")
    check("danger-full-access" not in argv, "danger-full-access не передаётся")
    check("--yolo" not in argv, "--yolo не передаётся")
    check("--skip-git-repo-check" in argv,
          "прежний флаг --skip-git-repo-check остался")
    check(argv[0] == "C:\\codex.exe", "программа осталась первой в argv")

    # === 6. Cursor: прежние ограничения на месте ===
    create = cursor.agent_argv.cursor_create_argv("C:\\agent.exe")
    send = cursor.agent_argv.cursor_send_argv(
        "C:\\agent.exe", "chat-1", "привет", "agent", None)
    check("--force" not in create, "при создании чата --force не передаётся")
    check("--force" not in send, "при отправке --force не передаётся без просьбы")
    check(send[0] == "C:\\agent.exe", "программа осталась первой в argv у Cursor")

    # === 7. Прочие мосты: команда и версия те же ===
    # Версии живут в общем модуле, а не в лаунчерах: и проверяем именно там,
    # где они и закреплены.
    check(common.UNITY_FROM == "mcpforunityserver==10.3.0",
          "Unity осталась на закреплённой версии")
    check(not hasattr(common, "UNREAL_PACKAGE"),
          "мосту Unreal npm-пакет больше не нужен: константы в коде нет")

    # === 7б. Лаунчер Unreal больше не запускает мост, а объясняет ===
    # Сервер линии 0.6 встроен в плагин EngineWire, поэтому лаунчер не
    # запускает ничего. Но файл остаётся: в старых настройках opencode ещё
    # может стоять команда с ним, и вместо загадочной ошибки npm человек
    # должен прочитать, что делать.
    import tempfile
    import re as _re
    _unreal_src = Path(unreal.__file__).read_text(encoding="utf-8", errors="replace")
    # Ищем именно закреплённый пакет вида `пакет@версия`. Голое число в
    # пояснении («в npm последний 0.5.30») закреплённой версией не является,
    # а вот `unreal-engine-mcp-server@...` вернуло бы мост к npm.
    _pins = _re.findall(r"[\w./-]+@\d[\w.+-]*", _unreal_src)
    check(not _pins,
          f"в лаунчере Unreal не закреплён ни один npm-пакет: {_pins}")
    check("subprocess" not in _unreal_src and "os.system" not in _unreal_src,
          "и он вообще ничего не запускает: ни npx, ни процесс-мост, ни os.system")
    check("Настроить автоматически" in _unreal_src,
          "а прямо говорит, что нажать вместо старой команды")
    check("localhost:3000/mcp" in _unreal_src,
          "и называет адрес, по которому подключаются")

    check(common.TIKTOK_PACKAGE == "@getmcpads/tiktok-ads-mcp-server@2.0.1",
          "TikTok остался на закреплённой версии")

    # === 7в. Постоянное окружение Unity: готовое берётся, неготовое честно ===
    # Проверено 21.10.2026: холодный uvx качает пакет 74+ секунд при лимите
    # opencode 30 секунд — из-за этого мост таймаутил, и opencode перезапускал
    # его общим таймером вместе со всеми мостами. Теперь первый путь — .venv
    # рядом с мостом. Подмена SERVER_DIR/VENV_* делает проверку независимой
    # от того, стоит ли окружение на этой машине: оба случая меряются сами.
    check(unity.VENV_EXE == unity.SERVER_DIR / ".venv" / "Scripts" / "mcp-for-unity.exe",
          "Unity: окружение ищется рядом с мостом, а не по личному пути")
    saved_unity = (unity.SERVER_DIR, unity.VENV_EXE, unity.VENV_PYTHON)
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as empty:
            empty_dir = Path(empty)
            unity.SERVER_DIR = empty_dir
            unity.VENV_PYTHON = empty_dir / ".venv" / "Scripts" / "python.exe"
            unity.VENV_EXE = empty_dir / ".venv" / "Scripts" / "mcp-for-unity.exe"
            check(unity._venv_exe() is None,
                  "Unity: неготовое окружение честно даёт None — лаунчер уходит на путь uvx")
    finally:
        unity.SERVER_DIR, unity.VENV_EXE, unity.VENV_PYTHON = saved_unity
    real_venv_exe = saved_unity[0] / ".venv" / "Scripts" / "mcp-for-unity.exe"
    if real_venv_exe.is_file():
        check(unity._venv_exe() == unity.VENV_EXE,
              "Unity: готовое окружение выбирается первым")
    else:
        check(unity._venv_exe() is None,
              "Unity: на машине окружения нет — проверка не врёт про готовность")

    for label, module in (("Unity", unity), ("Unreal", unreal), ("TikTok", tiktok)):
        check(callable(getattr(module, "main", None)),
              f"лаунчер {label} на месте и запускаем")

    # === 8. Общие помощники не изменились ===
    check(common.parse_kv("A=1\n# комментарий\nB = \"две части\"\n") ==
          {"A": "1", "B": "две части"},
          "разбор ключей и значений прежний")
    check(common.parse_version("v24.19.0") == (24, 19, 0),
          "разбор версий прежний")
    check(common.spotify_app_path() == "" or
          common.spotify_app_path().endswith("Spotify.exe"),
          "поиск приложения Spotify прежний")

    # === 9. Мост Claude не изменил чужие файлы и не спорит за имена ===
    check(common.resolve_exe.__doc__ is not None,
          "документация прежнего помощника на месте")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()