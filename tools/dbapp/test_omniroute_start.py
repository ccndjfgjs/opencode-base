"""Проверка запуска OmniRoute: «уже запущен» — это не отказ.

Запуск: python tools/dbapp/test_omniroute_start.py

Поломка, которую проверка закрывает. 19.10.2026 человек нажал «Запустить»
у OmniRoute и получил:

    Запуск OmniRoute не удался (код 1): Another OmniRoute is most likely
    already serving there, so open http://localhost:20128 before starting
    a second one.
    В настройки opencode ничего не вписано.

Сервер при этом был живой: `GET /api/health` отвечал `{"status":"ok"}`.
Причина была в гонке — программа спросила здоровье с таймаутом 5 секунд,
не дождалась ответа (сервер был занят) и решила, что сервера нет, после
чего попыталась поднять второй. OmniRoute справедливо отказал: второй
экземпляр на том же порту не нужен.

Правильное поведение: отказ команды — ещё не отказ моста. Если после
неудачного запуска API отвечает «ok», мост живой, и работа продолжается.
Проверяется живым запросом, а не кодом возврата.

Проверка работает с настоящим модулем программы и настоящим живым
запросом к API. Ничего не запускает и не останавливает: OmniRoute на
машине может работать, и трогать его нельзя.
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="omniroute-start-") as tmp:
        dest = Path(tmp)

        # --- сервер живой: запускать не надо, и отказа быть не должно.
        #
        # Живым считается не только отвечающий API, но и развёрнутый
        # пакет. На одной машине могут жить сразу две копии программы:
        # сервер поднят из одной, а проверка идёт из другой, где пакета
        # нет. Тогда API отвечает, а «Запустить» честно говорит «не
        # развёрнут» — и это правильное поведение, а не отказ.
        # Первая версия проверки смотрела только на API и ругалась на
        # правильный отказ.
        ok, _data, note = omniroute.health(dest, timeout=10)
        if not omniroute.deployed():
            check(True, "пакет OmniRoute в этой копии не развёрнут — живую "
                        "ветку пропускаем")
            live = False
        elif not ok:
            check(True, f"OmniRoute на этой машине не отвечает — ветку «живого "
                        f"сервера» пропускаем ({note[:80]})")
            live = False
        else:
            live = True
            check(True, "OmniRoute развёрнут и отвечает на живой запрос: «ок»")

        if live:
            messages, errors = omniroute.start(dest)
            check(not errors,
                  f"«Запустить» при живом сервере — не отказ: {errors[:2]}")
            joined = " ".join(messages)
            check("уже" in joined.lower() or "не поднимаю" in joined.lower()
                  or "уже был" in joined.lower(),
                  f"и сказано словами, что второй экземпляр не поднимается: "
                  f"{joined[:140]}")
            check("ничего не вписано" not in joined.lower(),
                  "и в настройки opencode не вписано «ничего не вписано» — "
                  "мост живой, значит и писать можно")

        # --- сервера нет: честный отказ, и в сообщении есть причина.
        #
        # Подменяется и `deployed`, а не только `health`. Иначе проверка
        # мерила состояние машины, а не логику: в рабочей копии программы
        # (Downloads\opencode-base-main) OmniRoute не развёрнут, и она
        # падала на «не развёрнут», не доходя до проверки отказа.
        was_health = omniroute.health
        was_run = omniroute._run
        was_deployed = omniroute.deployed
        try:
            omniroute.deployed = lambda: True
            omniroute.health = lambda *a, **k: (
                False, {}, "API OmniRoute не ответил: подставная проверка")
            omniroute._run = lambda *a, **k: (
                1, "", "Another OmniRoute is most likely already serving there")
            messages, errors = omniroute.start(dest)
        finally:
            omniroute.health = was_health
            omniroute._run = was_run
            omniroute.deployed = was_deployed
        check(bool(errors),
              "при мёртвом сервере и отказе команды — честная ошибка")
        check(any("код 1" in e for e in errors),
              f"и в ней назван код возврата: {errors[:2]}")
        check(any("живая проверка" in e.lower() or "не прошла" in e.lower()
                  for e in errors),
              f"и сказано, что живая проверка не прошла: {errors[:2]}")
        check(not any("ничего не вписано" in e.lower() for e in errors),
              "и НЕ сказано про настройки: кнопка запуска в них не пишет, "
              "и человек не должен читать это как поломку")
        check(any("не поднят" in e.lower() for e in errors),
              f"а сказано, что сервер не поднят: {errors[:2]}")

        # --- ровно тот случай, что случился у человека 19.10.2026:
        # сервер живой, но первый вопрос не успел, и команда отказала
        # поднимать второй. Отказ команды — не отказ моста.
        #
        # Здесь НЕ нужен живой сервер: подменяется ровно то, что
        # требовалось для сбоя, — первый вопрос не успел, второй
        # ответил «ok». Привязка к живой машине делала проверку
        # зависимой от того, развёрнут ли мост в этой копии программы.
        calls = {"health": 0}

        def flaky_health(*a, **k):
            calls["health"] += 1
            if calls["health"] == 1:
                return False, {}, "API OmniRoute не ответил: сервер занят"
            return True, {"status": "ok", "timestamp": "2026-10-19T00:00:00Z"}, ""

        was_health = omniroute.health
        was_run = omniroute._run
        was_deployed = omniroute.deployed
        try:
            omniroute.deployed = lambda: True
            omniroute.health = flaky_health
            omniroute._run = lambda *a, **k: (
                1, "", "Another OmniRoute is most likely already serving there")
            messages, errors = omniroute.start(dest)
        finally:
            omniroute.health = was_health
            omniroute._run = was_run
            omniroute.deployed = was_deployed
        check(not errors,
              f"гонка «сервер занят, потом отказ команды» — не отказ: "
              f"{errors[:2]}")
        check(any("уже был запущен" in m or "работа продолжаю" in m
                  for m in messages),
              f"и сказано, что сервер уже был: {messages[:2]}")
        check(calls["health"] >= 2,
              f"и программа переспросила API, а не поверила коду возврата: "
              f"запросов {calls['health']}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
