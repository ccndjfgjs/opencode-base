"""Проверки записи файлов мостов. Редакторы и сеть не нужны.

    python tools/dbapp/test_engine_setup.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine_setup as setup  # noqa: E402


def check(ok: bool, text: str) -> None:
    print(("  ok  " if ok else "  FAIL  ") + text)
    if not ok:
        raise SystemExit(1)


def engine_setup_port(root: Path) -> int:
    """Порт из настроек моста.

    Отдельная функция, чтобы проверка читала ровно то, что читает программа
    при сборке адреса, а не то, что записала минуту назад.
    """
    return setup.read_unreal_port(root)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="engine-setup-"))
    project = root / "MyGame"
    (project / "Plugins" / "EngineWire").mkdir(parents=True)
    (project / "MyGame.uproject").write_text("{}", encoding="utf-8")

    ok, note = setup.save_unreal(root, str(project / "нет-такой"))
    check(not ok and "существующ" in note, "чужой путь Unreal не записывается")

    bare = root / "без-плагина"
    bare.mkdir()
    ok, note = setup.save_unreal(root, str(bare))
    check(not ok and "EngineWire" in note, "без плагина 0.6 путь не записывается")
    check(not (root / setup.UNREAL_NAME).exists(), "файл при отказе не появляется")

    ok, note = setup.save_unreal(root, str(project / "MyGame.uproject"))
    # Обещание в заметке изменилось вместе с мостом: отдельной версии
    # сервера и capability-токена больше нет — сервер живёт внутри плагина.
    # Значит и обещание другое: мост работает, пока открыт редактор.
    check(ok and "редактор" in note.lower(),
          f"путь .uproject записан, ограничение названо: {note}")
    text = (root / setup.UNREAL_NAME).read_text(encoding="utf-8")
    check(f"project={project}" in text, "в файле папка проекта, не файл .uproject")
    check("token" not in text.lower() and "secret" not in text.lower(),
          "и в файле нет ни токена, ни секрета: там только путь проекта")

    # Порт сервера: названный принимается, битый и вылезающий — нет.
    ok_port, note_port = setup.save_unreal_port(root, "3210")
    check(ok_port and engine_setup_port(root) == 3210,
          f"названный порт читается обратно: {note_port}")
    bad_port, note_bad = setup.save_unreal_port(root, "не число")
    check(not bad_port and "не число" in note_bad,
          f"битый порт отвергнут словами: {note_bad}")
    far_port, note_far = setup.save_unreal_port(root, "70000")
    check(not far_port and "65535" in note_far,
          f"порт за пределами сети отвергнут: {note_far}")
    blank_port, note_blank = setup.save_unreal_port(root, "")
    check(blank_port and not note_blank,
          f"пустой порт — это «оставить как есть», а не ошибка: {note_blank}")
    check(engine_setup_port(root) == 3210,
          "и после пустого значения остался прежний порт")

    ok, note = setup.save_godot(root, "{\"command\": [\"uvx\", \"godot-ai\"]}")
    check(not ok and "attach" in note, "Godot без attach отвергается")
    ok, note = setup.save_godot(root, "[\"uvx\", \"godot-ai\", \"attach\", \"--port\", \"1\"]")
    check(ok, "список argv принимается")
    saved = json.loads((root / setup.GODOT_NAME).read_text(encoding="utf-8"))
    check(saved["command"][-2:] == ["--port", "1"], "argv сохранён целиком")
    check("--port" not in note, "аргументы команды в ответ человеку не попали")

    ok, note = setup.save_tiktok(root, "", "app")
    check(not ok, "пустой токен не записывается")
    ok, note = setup.save_tiktok(root, "secret-token", "123")
    check(ok and "secret-token" not in note, "токен записан и в ответ не попал")
    body = (root / setup.TIKTOK_NAME).read_text(encoding="utf-8")
    check("TIKTOK_ACCESS_TOKEN=secret-token" in body, "в файле токен есть")
    check("TIKTOK_APP_ID=123" in body, "в файле App ID есть")

    check(setup.gap(root, "tiktok") == "", "после записи дырки нет")
    check("secret-token" not in setup.gap(root, "tiktok"), "дырка не содержит токен")
    empty = root / "пусто"
    empty.mkdir()
    gap = setup.gap(empty, "unreal")
    check("mcp-unreal.txt" in gap and "secret" not in gap, "без файла Unreal дырка названа")

    registry = HERE.parent.parent / "данные" / "mcp-registry.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in data["servers"]}
    order = list(by_id)
    # В нашем реестре ldplayer последним быть не обязан: после него стоят
    # dbhub, browsers, omniroute и lmarena, их добавили позже. Проверяем
    # смысл, а не былое «последний»: вставка мостов не должна была
    # ни выкинуть ldplayer, ни встать после него.
    check("ldplayer" in by_id, "ldplayer на месте после вставки мостов")
    check(order.index("ldplayer") > max(order.index(sid) for sid in setup.IDS),
          "новые мосты встали перед ldplayer, а не после него")
    check(all(sid in by_id for sid in ("dbhub", "browsers", "omniroute", "lmarena")),
          "и серверы, добавленные позже, не потерялись: "
          f"{order[order.index('ldplayer') + 1:]}")
    for sid in setup.IDS:
        steps = by_id[sid].get("setup_steps") or []
        check(len(steps) >= 3, f"у {sid} есть шаги в реестре")
        check(any("Настроить автоматически" in step for step in steps),
              f"шаги {sid} говорят про кнопку окна")

    ok, note = setup.save_capcut(root, "http://127.0.0.1:9001/mcp", "secret")
    check(not ok and "https" in note, "локальный http CapCut отвергается")
    ok, note = setup.save_capcut(root, "https://www.capcut.com/mcp", "secret")
    check(not ok and "CapCut" in note, "сайт CapCut не принимается за MCP")
    check("secret" not in note, "отказ не печатает токен")
    ok, note = setup.save_capcut(root, "https://192.168.1.20/mcp")
    check(not ok and "не интернет" in note, "частная сеть не считается интернетом")
    ok, note = setup.save_capcut(
        root, "https://mcp.example.com/mcp?token=secret", "other"
    )
    check(not ok and "секрет" in note.lower(), "секрет в адресе отвергается")
    ok, note = setup.save_capcut(root, "https://mcp.example.com/mcp", "capcut-secret")
    check(ok and "capcut-secret" not in note and "example.com" in note,
          "адрес записан, токен в ответ не попал")
    saved = json.loads((root / setup.CAPCUT_NAME).read_text(encoding="utf-8"))
    check(saved["url"] == "https://mcp.example.com/mcp", "в файле ровно адрес")
    check(saved["headers"]["Authorization"] == "Bearer capcut-secret",
          "токен лежит только в файле")
    check(setup.capcut_gap(root) == "", "после записи дырки CapCut нет")
    ok, note = setup.save_capcut(root, "https://mcp.example.com/mcp", "")
    check(ok and "capcut-secret" not in note, "пустой токен не затирает старый и не печатает его")
    kept = json.loads((root / setup.CAPCUT_NAME).read_text(encoding="utf-8"))
    check(kept["headers"]["Authorization"] == "Bearer capcut-secret",
          "прежний заголовок остался в файле")
    ok, note = setup.save_spotify(root, "client secret")
    check(not ok and "secret" not in note, "Client ID с пробелом не записывается")
    ok, note = setup.save_spotify(root, "spotify-client")
    check(ok and "spotify-client" not in note, "Client ID записан и в ответ не попал")
    check("SPOTIFY_CLIENT_ID=spotify-client" in (root / setup.SPOTIFY_NAME).read_text(encoding="utf-8"),
          "Client ID лежит только в файле")

    ok, note = setup.save_chatgpt(root, "sk-live-key", "model from dash")
    check(not ok and "sk-live-key" not in note, "модель с пробелом не записывается")
    ok, note = setup.save_chatgpt(root, "sk-live-key", "model-from-dash")
    check(ok and "sk-live-key" not in note and "model-from-dash" not in note,
          "ключ и модель записаны и в ответ не попали")
    saved_chat = (root / setup.CHATGPT_NAME).read_text(encoding="utf-8")
    check("OPENAI_API_KEY=sk-live-key" in saved_chat, "ключ лежит только в файле")
    check(setup.gap(root, "chatgpt") == "", "после записи дырки ChatGPT нет")

    ok, note = setup.save_cursor(root, "")
    check(ok and "ключ" in note.lower(), "пустой ключ Cursor допустим")
    ok, note = setup.save_cursor(root, "cursor-key")
    check(ok and "cursor-key" not in note, "ключ Cursor в ответ не попал")

    names = [item.get("name") for item in data.get("excluded") or []]
    check("VK Музыка" in names and "Яндекс.Музыка" in names,
          "VK и Яндекс.Музыка записаны как исключённые, не как мосты")
    check("spotify" in by_id and "chatgpt" in by_id and "codex" in by_id and "cursor" in by_id,
          "четыре новых моста есть в реестре")
    raw = registry.read_text(encoding="utf-8")
    check("{PROGRAM}" in raw, "плейсхолдер {PROGRAM} на месте")
    for sid in ("spotify", "chatgpt", "codex", "cursor"):
        command = by_id[sid]["connection"].get("command") or []
        joined = " ".join(command)
        check("danger-full-access" not in joined and "--yolo" not in joined and "--force" not in joined,
              f"команда {sid} не содержит опасный флаг")
    # Вход Codex: окно и таблица должны говорить «войди», а не молчать.
    # Команда статуса на машине читателя может быть любой, поэтому подменяем
    # её: проверка должна работать везде, где есть Python.
    saved_exe = setup.common.resolve_exe
    saved_probe = setup.common.probe_command

    def fake_exe(name: str) -> str | None:
        return r"C:\путь\codex.exe" if name == "codex" else None

    try:
        setup.common.resolve_exe = fake_exe
        setup.common.probe_command = lambda argv, timeout=15: (1, "Not logged in")
        ok, note = setup.codex_ready()
        check(ok and "codex login" in note and "Входа нет" in note,
              "входа нет: мост вписать можно, окно просит войти")
        check("Войди сам" in setup.gap(root, "codex"),
              "таблица называет отсутствие входа, а не молчит")

        setup.common.probe_command = lambda argv, timeout=15: (0, "Logged in using ChatGPT")
        ok, note = setup.codex_ready()
        check(ok and "Вход есть" in note, "вход подтверждён — окно не пугает зря")
        check(setup.gap(root, "codex") == "", "с входом дырки в таблице нет")

        setup.common.probe_command = lambda argv, timeout=15: (None, "")
        ok, note = setup.codex_ready()
        check(ok and "не проверялся" in note,
              "молчание команды статуса не выдаётся за вход")
        check("не подтвердился" in setup.gap(root, "codex"),
              "таблица тоже не выдаёт молчание за вход")

        setup.common.resolve_exe = lambda name: None
        ok, note = setup.codex_ready()
        check(not ok and "winget" in note and "codex login" in note,
              "нет команды — окно прямо говорит, что ставить и как войти")
    finally:
        setup.common.resolve_exe = saved_exe
        setup.common.probe_command = saved_probe

    # Cursor CLI на машине читателя может стоять, а может нет. Поэтому
    # ставим заглушку: она говорит ровно то, что документирует Cursor
    # (docs/cli/reference/authentication) — «Not authenticated» и код 1.
    saved_path = os.environ.get("PATH", "")
    stub_dir = Path(tempfile.mkdtemp(prefix="cursor-stub-"))
    stub_dir.joinpath("agent.cmd").write_text(
        "@echo off\r\n"
        "if \"%1\"==\"status\" (echo Not authenticated & exit /b 1)\r\n"
        "echo заглушка, это не настоящий Cursor CLI\r\n",
        encoding="utf-8",
    )
    os.environ["PATH"] = str(stub_dir) + os.pathsep + saved_path
    try:
        ok, note = setup.cursor_ready()
        check(ok and "agent login" in note and "Not authenticated" in note,
              "входа нет — окно называет и причину, и как войти")
        check("agent login" in setup.gap(root, "cursor"),
              "таблица Cursor тоже говорит про вход, а не молчит")
        stub_dir.joinpath("agent.cmd").write_text(
            "@echo off\r\nif \"%1\"==\"status\" (echo Logged in as tester & exit /b 0)\r\n",
            encoding="utf-8",
        )
        ok, note = setup.cursor_ready()
        check(ok and "Вход подтверждён" in note, "вход подтверждён — окно не пугает зря")
        check(setup.gap(root, "cursor") == "", "с входом дырки в таблице нет")
    finally:
        os.environ["PATH"] = saved_path

    # Spotify: файл с Client ID — это половина, вход пакета — вторая.
    spotify_dir = root / "spotify"
    spotify_dir.mkdir()
    check("mcp-spotify.txt" in setup.gap(spotify_dir, "spotify"),
          "без файла дырка Spotify называет файл")
    setup.save_spotify(spotify_dir, "client-id")
    saved_login = setup.spotify_login_saved
    saved_app = setup.spotify_app_installed
    try:
        setup.spotify_login_saved = lambda: False
        setup.spotify_app_installed = lambda: True
        check("входа нет" in setup.gap(spotify_dir, "spotify"),
              "файл записан, а входа нет — дырка всё равно есть")
        ok, note = setup.save_spotify(spotify_dir, "client-id")
        check("Premium" in note,
              "кнопка после записи говорит про Premium, как в README пакета")
        setup.spotify_login_saved = lambda: True
        setup.spotify_app_installed = lambda: False
        check("приложения Spotify" in setup.gap(spotify_dir, "spotify"),
              "вход есть, но приложения нет — про это тоже сказано прямо")
        setup.spotify_app_installed = lambda: True
        check(setup.gap(spotify_dir, "spotify") == "",
              "с файлом, входом и приложением дырки нет")
    finally:
        setup.spotify_login_saved = saved_login
        setup.spotify_app_installed = saved_app
    check(isinstance(setup.spotify_app_installed(), bool),
          "проверка приложения Spotify отвечает, а не падает")

    print("настройка мостов: проверки прошли")


if __name__ == "__main__":
    main()
