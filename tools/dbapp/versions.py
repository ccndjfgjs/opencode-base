# -*- coding: utf-8 -*-
"""Общие правила для версий и сборок: разбор номера, границы since/until,
выбор самой свежей подходящей сборки и хеш файла потоком.

Вынесено из `android_studio.py`, потому что правило «какая сборка подходит
под какую версию» нужно не одной студии. Тем же правилом пользуются мосты
эмуляторов, и по нему же вкладка «Программы» будет выбирать версионные
сборки компонентов для любой программы из реестра.

**Что сюда можно класть, а что нельзя.**

Можно: правила, у которых смысл не зависит от того, какая это программа.
Границы `since`/`until`, разбор номера версии, выбор самой свежей сборки.

Нельзя: разбор, привязанный к формату конкретной программы. В проекте
уже есть два разных `version_tuple`, и это не дубликаты:

* здесь `version_tuple` берёт **все** числа — им разбирают buildNumber
  вида `AI-261.25134.95.2612.15914620`;
* в `mcp_registry.py` свой разбор берёт **первую** последовательность
  чисел — им берут версию Node из строки `v24.18.0`.

Слить их в одну можно только с параметром режима. Пока это сделано, такой
параметр не заводили: лишняя абстракция опаснее дублирования.

**Хеш файла здесь считается потоком, а не целиком.** В `core.py` и
`opencode_caps.py` есть свои хеши, которые читают файл в память — это
быстро и годится для мелких файлов. Здесь файл может оказаться
установщиком на сотни мегабайт, и читать его целиком нельзя.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def version_tuple(text: str) -> tuple[int, ...]:
    """«261.25134.203» -> (261, 25134, 203).

    Именно числа, а не строки: строковое сравнение путает 263.9 и 263.10
    и выбирает не ту сборку.
    """
    parts: list[int] = []
    for chunk in str(text or "").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def platform_from_build(build_number: str) -> tuple[int, ...]:
    """Платформа из номера сборки: первые два числа.

    «AI-261.25134.95.2612.15914620» -> (261, 25134). Первое число — ветка,
    второе — номер внутри ветки. Именно эту пару сборка объявляет в since.
    """
    numbers = re.findall(r"\d+", str(build_number or ""))
    if not numbers:
        return ()
    return tuple(int(n) for n in numbers[:2])


def platform_text(platform: tuple[int, ...]) -> str:
    """Обратно в строку: (263, 5701) -> «263.5701»."""
    return ".".join(str(n) for n in platform)


def since_matches(since: str, platform: tuple[int, ...]) -> bool:
    """Не ниже ли объявленного начала сборки."""
    if not platform:
        return False
    return platform >= version_tuple(since)


def until_matches(until: str, platform: tuple[int, ...]) -> bool:
    """Попадает ли платформа в объявленный конец сборки.

    «261.*» — вся ветка 261. «263.5701.*» — только подплатформа 263.5701.
    Без звёздочки — «до этой версии включительно».
    """
    raw = str(until or "").strip()
    if not raw or raw == "*":
        return True
    if raw.endswith(".*"):
        prefix = version_tuple(raw[:-2])
        return platform[: len(prefix)] == prefix
    return platform <= version_tuple(raw)


def build_matches(build: dict, platform: tuple[int, ...]) -> bool:
    """Подходит ли сборка под эту платформу.

    Оба края берутся из дескриптора самой сборки. Ничего не угадываем:
    именно поэтому программа не может выбрать сборку, которая не загрузится.
    """
    return since_matches(str(build.get("since") or ""), platform) and until_matches(
        str(build.get("until") or ""), platform
    )


def pick_build(builds: list[dict], platform: tuple[int, ...]) -> dict | None:
    """Самая свежая сборка из списка, подходящая под платформу.

    None, если подходящей нет. Сравнение по номеру версии, не по дате:
    дата в архиве сборки может отсутствовать.
    """
    fits = [b for b in builds if build_matches(b, platform)]
    if not fits:
        return None
    return max(fits, key=lambda b: version_tuple(str(b.get("version") or "")))


def file_sha256(path: Path) -> str:
    """Хеш файла, читаемого потоком. Файл может быть большим."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()