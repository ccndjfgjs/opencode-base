"""Мост Unreal больше не запускает npm: сервер живёт в плагине EngineWire.

Регрессия ловит возврат старой схемы: если кто-то снова закрепит версию
npm-пакета Unreal в коде, мост начнёт требовать Node.js и пакет, которого
в npm нет (там последний — 0.5.30, а линия плагина 0.6).
"""
from pathlib import Path

import bridge_common as common

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


def main() -> int:
    source = Path(__file__).resolve().parent / "unreal_bridge_launcher.py"
    body = source.read_text(encoding="utf-8", errors="replace")

    check(not hasattr(common, "UNREAL_PACKAGE"),
          "мосту Unreal больше не нужен npm-пакет: константы в коде нет")
    check("npx" not in body, "лаунчер Unreal не запускает npx")
    check("unreal-engine-mcp-server@" not in body,
          "и версии npm-пакета в нём не зашито")
    check("localhost:3000/mcp" in body,
          "лаунчер называет адрес, по которому подключаются")
    check("редактор" in body.lower(),
          "и напоминает, что нужен открытый редактор с плагином")
    check("Настроить автоматически" in body,
          "и говорит, что делать вместо старой команды")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
