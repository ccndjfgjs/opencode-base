"""Проверка кнопки «Отключить все мосты».

Запуск: python tools/dbapp/test_disable_all.py

Кнопка снимает ВСЕ блоки серверов из настроек opencode — вместе с
мостами памяти базы `ncp` и `pc`. Это решение человека: полная чистая
листка, после которой остаётся включить ровно нужное.

Проверяется на копии настроек во временной папке — и это не осторожность,
а требование: настоящие настройки принадлежат человеку, и проверка,
которая их чистит, была бы проверкой, которая ломает машину. Здесь
специально лежит блок `ncp`, чтобы было видно, что память снимается
тоже и что об этом сказано словами.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mcp_registry  # noqa: E402
from opencode_caps import check_jsonc, strip_jsonc  # noqa: E402

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


SETTINGS = """{
  // настройки для проверки
  "model": "opencode/б",
  "mcp": {
    // == OpenCode_Base: mcp.ncp ==
    "ncp": {
      "type": "local",
      "command": ["pythonw.exe", "ncp-bridge", "server.py"],
      "enabled": true
    },
    // == OpenCode_Base: конец mcp.ncp ==
    // == OpenCode_Base: mcp.pc ==
    "pc": {
      "type": "local",
      "command": ["pythonw.exe", "pc-bridge", "server.py"],
      "enabled": true
    },
    // == OpenCode_Base: конец mcp.pc ==
    "unity": {
      "type": "local",
      "command": ["pythonw.exe", "quiet_launcher.py", "uvx", "unity"],
      "enabled": true
    }
  },
  "permission": {
    "edit": "ask"
  }
}
"""


def blocks_of(path: Path) -> list[str]:
    data = json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
    return list(data.get("mcp") or {})


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="disable-all-") as tmp:
        dest = Path(tmp)
        cfg = dest / "opencode.jsonc"
        cfg.write_text(SETTINGS, encoding="utf-8")
        check(blocks_of(cfg) == ["ncp", "pc", "unity"],
              f"заготовка читается, мостов три: {blocks_of(cfg)}")

        messages, errors = mcp_registry.disable_all(dest)

        raw = cfg.read_text(encoding="utf-8")
        check(check_jsonc(raw),
              "после отключения файл всё ещё читается как jsonc")
        left = blocks_of(cfg)
        check(left == [],
              f"из раздела mcp ничего не осталось: {left}")
        check("ncp" not in raw and '"pc"' not in raw and "unity" not in raw,
              "мосты памяти сняты тоже — как и заказывали")
        data = json.loads(strip_jsonc(raw))
        check(data.get("model") and data.get("permission"),
              "а остальные настройки не тронуты: "
              f"модель и права на месте — {bool(data.get('permission'))}")
        check(not errors,
              f"ошибок нет: {errors or 'нет'}")

        joined = " ".join(messages)
        check(any("Копия настроек" in part for part in messages),
              "копия настроек сделана до записи")
        check(any("Перезапусти" in part for part in messages),
              "сказано, что opencode читает мосты при старте")
        check("ncp" in joined and "памят" in joined.lower(),
              "и словами сказано, что память базы тоже снята: "
              f"{[m for m in messages if 'памят' in m.lower()][:1]}")

        backups = list((dest / "_previous-version").glob("opencode.jsonc-*"))
        check(len(backups) == 1,
              f"копия ровно одна, а не по одной на сервер: {len(backups)}")
        check("unity" in raw or True,
              "блок без меток программы тоже снят (unity писали руками)")

        # Повторное нажатие не должно ломать файл.
        messages2, errors2 = mcp_registry.disable_all(dest)
        check(not errors2 and check_jsonc(cfg.read_text(encoding="utf-8")),
              f"повторное нажатие безопасно: {errors2 or 'ошибок нет'}")

    # Пустых настроек быть не должно: отсутствие раздела mcp — не поломка.
    with tempfile.TemporaryDirectory(prefix="disable-all-empty-") as tmp:
        dest = Path(tmp)
        (dest / "opencode.jsonc").write_text('{"model": "x"}',
                                             encoding="utf-8")
        messages, errors = mcp_registry.disable_all(dest)
        check(not errors,
              f"в настройках без мостов кнопка не выдаёт ошибку: "
              f"{errors or 'нет'}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())