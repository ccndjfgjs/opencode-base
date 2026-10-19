"""Проверка карточек мостов, которые программа ставит сама.

Запуск: python tools/dbapp/test_bridge_payload_cards.py

О чём речь. У мостов OmniRoute и LMArena нет отдельной программы: это
сам мост, и ставит его программа управления базой кнопкой «Развернуть».
Но карточка про них говорила «программа не ставится» — то есть молчала
о том, что человек и хочет узнать: развёрнут мост или нет, и почему он
не разворачивается.

Правила, которые проверка защищает:

1. **Карточка говорит о пакете моста, а не «нечем проверять».** Состояние
   приходит из настоящей проверки, а не из строки в реестре.
2. **Проверка умеет оба ответа.** Поисковик, всегда отвечающий
   «развёрнут», такую проверку бы не прошёл: подмена ответа обязана
   менять и строку в карточке.
3. **Требования моста остаются отдельными.** Даже когда пакет развёрнут,
   «сервер запущен» и «токен арены» не зеленеют вместе с карточкой:
   это разные вещи.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import program_cards as pc  # noqa: E402
import programs  # noqa: E402

PROGRAM_ROOT = HERE.parent.parent

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


def _card(base: Path, needle: str):
    for card in pc.cards(base):
        if needle in card.name:
            return card
    return None


def main() -> int:
    base = PROGRAM_ROOT
    card = _card(base, "OmniRoute")
    check(card is not None, "карточка OmniRoute есть")
    if card is None:
        print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
        return 1

    check("развёрнут" in (card.state_text or ""),
          f"карточка говорит о пакете моста, а не «нечем проверять»: "
          f"{card.state_text}")

    # --- подмена ответа: пакет есть, и пакета нет.
    import omniroute  # noqa: PLC0415 — рядом лежит

    was = omniroute.deployed
    try:
        omniroute.deployed = lambda: False
        missing = _card(base, "OmniRoute")
    finally:
        omniroute.deployed = was
    check(missing is not None and "не развёрнут" in (missing.state_text or ""),
          f"и честно говорит, когда пакета нет: "
          f"{missing.state_text if missing else 'нет карточки'}")
    check(missing is not None and "Развернуть" in (missing.state_text or ""),
          "и называет кнопку, которая его поставит")

    again = _card(base, "OmniRoute")
    # Настоящее состояние машины тут не годится: пакет развёрнут не в
    # каждой копии программы, и проверка обязана мерить логику, а не то,
    # что лежит на диске. Поэтому «пакет на месте» подставляется явно —
    # строкой ниже, а эта строка честно говорит, на каком основании
    # сделан вывод.
    import omniroute as _or_probe  # noqa: PLC0415

    if _or_probe.deployed():
        check(again is not None and "развёрнут" in (again.state_text or "")
              and "не развёрнут" not in (again.state_text or ""),
              f"а когда пакет на месте — говорит «развёрнут»: {again.state_text}")
    else:
        check(True, "пакета OmniRoute в этой копии нет — настоящее состояние "
                    "не проверяем, его проверяет подстановка ниже")

    # --- и то же самое с подменой: «пакет на месте» не должно зависеть
    # от того, развёрнут ли он в этой копии программы. Без подмены
    # проверка мерила состояние машины: в рабочей копии
    # (Downloads\opencode-base-main) пакета нет, и она ругалась на
    # правильный честный ответ.
    was = omniroute.deployed
    try:
        omniroute.deployed = lambda: True
        forced = _card(base, "OmniRoute")
    finally:
        omniroute.deployed = was
    check(forced is not None and "развёрнут" in (forced.state_text or "")
          and "не развёрнут" not in (forced.state_text or ""),
          f"и при подставленном «пакет на месте» тоже: "
          f"{forced.state_text if forced else 'нет карточки'}")

    # --- требования моста не зеленеют вместе с карточкой.
    check(again is not None and "сервер запущен" in (again.bridge_pending or []),
          "требование «сервер запущен» осталось отдельным: развёрнутый "
          "пакет не значит, что сервер поднят")

    # --- LMArena: тот же принцип.
    lma = _card(base, "LMArena")
    check(lma is not None and "развёрнут" in (lma.state_text or ""),
          f"карточка LMArena тоже говорит о пакете: "
          f"{lma.state_text if lma else 'нет карточки'}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
