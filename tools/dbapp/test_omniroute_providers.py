"""Проверка подключения бесплатных провайдеров OmniRoute.

Запуск: python tools/dbapp/test_omniroute_providers.py

Что тут проверяется. 19.10.2026 кнопка «Запустить» у OmniRoute
заканчивалась красной строкой:

    Не подключились: duckduckgo-web (⚠ PORT in …\\.env); …

И это было три неправды подряд:

1. **Причину показывали не ту.** «Invalid provider» — ответ самого
   OmniRoute (в этой версии провайдера добавить нельзя), а программа
   показывала предупреждение про `.env` из stderr вместо ответа из
   stdout.
2. **Итог судили по коду возврата, а не по результату.** CLI OmniRoute
   на Windows падает при выходе с утверждением libuv
   (`Assertion failed: src\\win\\async.c`), даже когда провайдера
   добавил. Код возврата здесь — не показатель.
3. **Отказ одного провайдера выглядел как поломка моста.** Если
   провайдеры без ключа уже подключены и мост отвечает, то отказ
   добавить ещё один — сведения, а не беда. Красной строкой это
   называть было неправдой.

Проверка работает с настоящим модулем программы. Всё, что связано с
запуском CLI, подменяется: настоящий OmniRoute на машине трогать нельзя.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))

import omniroute  # noqa: E402

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


CATALOG = {
    "providers": [
        {"id": "aihorde", "category": "noauth", "hasFree": True},
        {"id": "opencode", "category": "noauth", "hasFree": True},
        {"id": "duckduckgo-web", "category": "noauth", "hasFree": True},
        {"id": "needs-key", "category": "apikey", "hasFree": True},
    ]
}


def main() -> int:
    # --- разбор причины ---------------------------------------------------
    why = omniroute._why("✖ Invalid provider\n⚠ PORT in …\\.env is ignored")
    check("отказал" in why and "версии" in why,
          f"«Invalid provider» переводится словами: {why}")
    check("PORT" not in why,
          "и предупреждение про .env не выдаётся за причину")

    with tempfile.TemporaryDirectory(prefix="omniroute-prov-") as tmp:
        dest = Path(tmp)

        was_run = omniroute._run
        was_catalog = omniroute.catalog
        was_have = omniroute.configured_providers
        was_health = omniroute.health

        try:
            omniroute.health = lambda *a, **k: (True, {"status": "ok"}, "")

            # --- случай 1: CLI падает, но провайдер подключён ----------
            # До попытки подключения провайдера в списке нет; после —
            # есть. Так и выглядит «CLI упал на выходе, а дело сделал».
            before = {"aihorde", "opencode"}
            after = {"aihorde", "opencode", "duckduckgo-web"}
            calls = {"have": 0}

            def have_list(*a, **k):
                calls["have"] += 1
                return (set(before) if calls["have"] == 1 else set(after)), ""

            def run_crash(args, *a, **k):
                if args[:2] == ["providers", "available"]:
                    return 0, str(CATALOG), ""
                if args[:2] == ["providers", "list"]:
                    return 0, '{"providers": [%s]}' % ", ".join(
                        '{"provider": "%s", "name": "%s"}' % (n, n)
                        for n in sorted(after)), ""
                # add: OmniRoute напечатал ответ и упал при выходе
                return 3221226505, "✖ Invalid provider", "Assertion failed"

            omniroute._run = run_crash
            omniroute.catalog = lambda *a, **k: (
                [dict(p) for p in CATALOG["providers"]
                 if p["category"] == "noauth"],
                [dict(p) for p in CATALOG["providers"]
                 if p["category"] != "noauth"],
                "",
            )
            omniroute.configured_providers = have_list

            messages, errors = omniroute.sync_free_providers(dest)
            check(not errors,
                  f"падение CLI при выходе не считается отказом: {errors[:1]}")
            joined = " ".join(messages)
            check("duckduckgo-web" in joined,
                  f"и провайдер, который всё-таки подключился, назван: "
                  f"{joined[:130]}")

            # --- случай 2: провайдер действительно не подключился -----
            connected2 = {"aihorde", "opencode"}

            def run_fail(args, *a, **k):
                if args[:2] == ["providers", "list"]:
                    return 0, '{"providers": [%s]}' % ", ".join(
                        '{"provider": "%s", "name": "%s"}' % (n, n)
                        for n in sorted(connected2)), ""
                return 3221226505, "✖ Invalid provider", "Assertion failed"

            omniroute._run = run_fail
            omniroute.configured_providers = lambda *a, **k: (
                set(connected2), "")

            messages, errors = omniroute.sync_free_providers(dest)
            joined = " ".join(messages)
            check(not errors,
                  f"отказ одного провайдера при живом мосте — не ошибка: "
                  f"{errors[:1]}")
            check("не влияет" in joined,
                  f"и сказано, что на мост это не влияет: {joined[:140]}")
            check("отказал" in joined,
                  f"и причина названа по-человечески: {joined[:140]}")
        finally:
            omniroute._run = was_run
            omniroute.catalog = was_catalog
            omniroute.configured_providers = was_have
            omniroute.health = was_health

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
