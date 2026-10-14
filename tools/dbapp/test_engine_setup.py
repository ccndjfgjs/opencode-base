"""Проверки записи файлов мостов. Редакторы и сеть не нужны.

    python tools/dbapp/test_engine_setup.py
"""

from __future__ import annotations

import json
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
    check(ok and "токен" in note.lower(), "путь .uproject записан, токен не обещан")
    text = (root / setup.UNREAL_NAME).read_text(encoding="utf-8")
    check(f"project={project}" in text, "в файле папка проекта, не файл .uproject")

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
    print("настройка мостов: проверки прошли")


if __name__ == "__main__":
    main()
