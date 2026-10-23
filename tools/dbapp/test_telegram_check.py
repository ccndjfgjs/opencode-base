# -*- coding: utf-8 -*-
"""Проверки telegram_check: имена полей, три уровня, никаких утечек.

Запускается как скрипт: python test_telegram_check.py
"""
from __future__ import annotations

import base64
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import telegram_check as tc  # noqa: E402

PASSED = 0
FAILED = 0


def check(ok: bool, text: str) -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  ok    {text}")
    else:
        FAILED += 1
        print(f"  СБОЙ  {text}")


def make_session(ip_len: int = 4, key: bytes | None = None) -> str:
    ip = bytes([149, 154, 167, 51]) if ip_len == 4 else bytes(range(16))
    raw = struct.pack(f">B{ip_len}sH256s", 2, ip, 443,
                      key if key is not None else os.urandom(256))
    return "1" + base64.urlsafe_b64encode(raw).decode()


def write(tmp: Path, name: str, text: str) -> Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tg-check-"))
    ok_session = make_session(4)
    ok_v6 = make_session(16)

    # --- имена совпадают с реестром
    print("--- 1. Имена файла и переменных")
    reg = json.loads((Path(__file__).resolve().parents[2]
                      / "данные" / "mcp-registry.json").read_text(encoding="utf-8"))
    tg = next(e for e in reg["servers"] if e["id"] == "telegram")
    env = (tg.get("connection") or {}).get("environment") or {}
    check(env.get("MCP_BRIDGE_SECRETS") == tc.FILE_NAME,
          f"имя файла совпадает с реестром: {tc.FILE_NAME}")
    check(tg["connection"]["command"][-1].endswith("token_bridge_launcher.py"),
          "мост идёт через общий лаунчер")
    check("TELEGRAM_SESSION_STRING" in tg["connection"]["note"],
          "в описании моста названо то же имя переменной")

    # --- уровни
    print("--- 2. Нет файла и пустой файл")
    missing = tc.check(tmp / "нет-такого.txt")
    check(missing.level == tc.MISSING, "нет файла → MISSING")
    empty = tc.check(write(tmp, "empty.txt", ""))
    check(empty.level == tc.MISSING, "пустой файл → MISSING")
    check(any("TELEGRAM_API_ID" in p for p in empty.problems),
          "пустой файл: назван TELEGRAM_API_ID")

    print("--- 3. Неверные типы")
    bad_id = tc.check(write(tmp, "bad-id.txt",
                            "TELEGRAM_API_ID=abc\n"
                            "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                            f"TELEGRAM_SESSION_STRING={ok_session}\n"))
    check(bad_id.level == tc.BAD_FORMAT, "api_id не число → BAD_FORMAT")
    check(any("TELEGRAM_API_ID" in p for p in bad_id.problems),
          "и проблема названа по имени поля")

    bad_hash = tc.check(write(tmp, "bad-hash.txt",
                              "TELEGRAM_API_ID=123456\n"
                              "TELEGRAM_API_HASH=zzz\n"
                              f"TELEGRAM_SESSION_STRING={ok_session}\n"))
    check(bad_hash.level == tc.BAD_FORMAT, "короткий hash → BAD_FORMAT")

    print("--- 4. Сессия: форматы")
    good = tc.check(write(tmp, "good.txt",
                          "TELEGRAM_API_ID=123456\n"
                          "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                          f"TELEGRAM_SESSION_STRING={ok_session}\n"
                          "TELEGRAM_EXPOSED_TOOLS=read-only\n"))
    check(good.level == tc.FORMAT_OK, "IPv4-сессия (353) → FORMAT_OK")
    check(not good.problems, "и проблем нет")
    check(any("не проверялась" in n for n in good.notes),
          "в примечании сказано, что сессия не проверялась")

    good_v6 = tc.check(write(tmp, "good-v6.txt",
                             "TELEGRAM_API_ID=123456\n"
                             "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                             f"TELEGRAM_SESSION_STRING={ok_v6}\n"))
    check(good_v6.level == tc.FORMAT_OK, "IPv6-сессия (369) → FORMAT_OK")

    broken = tc.check(write(tmp, "broken.txt",
                            "TELEGRAM_API_ID=123456\n"
                            "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                            "TELEGRAM_SESSION_STRING=1abc\n"))
    check(broken.level == tc.BAD_FORMAT, "битая сессия → BAD_FORMAT")

    empty_key = tc.check(write(tmp, "empty-key.txt",
                               "TELEGRAM_API_ID=123456\n"
                               "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                               f"TELEGRAM_SESSION_STRING={make_session(4, bytes(256))}\n"))
    check(empty_key.level == tc.BAD_FORMAT, "пустой ключ в сессии → BAD_FORMAT")

    print("--- 5. Другие способы сессии, которые читает сервер")
    pool = tc.check(write(tmp, "pool.txt",
                          "TELEGRAM_API_ID=123456\n"
                          "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                          f"TELEGRAM_SESSION_STRINGS={ok_session} {ok_v6}\n"))
    check(pool.level == tc.FORMAT_OK, "пул TELEGRAM_SESSION_STRINGS → FORMAT_OK")
    check(any("строже сервера" in n for n in pool.notes),
          "и сказано, что проверка строже сервера (он берёт первую свободную)")

    pool_bad = tc.check(write(tmp, "pool-bad.txt",
                              "TELEGRAM_API_ID=123456\n"
                              "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                              f"TELEGRAM_SESSION_STRINGS={ok_session} 1abc\n"))
    check(pool_bad.level == tc.BAD_FORMAT, "пул с битой строкой → BAD_FORMAT")
    check(any("строка 2" in p for p in pool_bad.problems),
          "и назван номер строки пула")

    named = tmp / "sessions"
    named.mkdir(exist_ok=True)
    (named / "main.session").write_bytes(b"x")
    by_name = tc.check(write(tmp, "by-name.txt",
                             "TELEGRAM_API_ID=123456\n"
                             "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                             f"TELEGRAM_SESSION_NAME={named / 'main'}\n"))
    check(by_name.level == tc.PARTIAL,
          "TELEGRAM_SESSION_NAME с файлом → PARTIAL, а не «формат верный»")
    check("не проверена" in by_name.short(),
          "и короткий статус говорит, что сессия не проверена")
    check(any("содержимое" in n for n in by_name.notes),
          "в примечании сказано, что содержимое не читалось")

    memory = tc.check(write(tmp, "memory.txt",
                            "TELEGRAM_API_ID=123456\n"
                            "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                            "TELEGRAM_SESSION_NAME=:memory:\n"))
    check(memory.level == tc.PARTIAL,
          ":memory: принимается, но тоже PARTIAL (входа не было)")

    no_file = tc.check(write(tmp, "no-file.txt",
                             "TELEGRAM_API_ID=123456\n"
                             "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                             f"TELEGRAM_SESSION_NAME={tmp / 'нет-сессии'}\n"))
    check(no_file.level == tc.MISSING, "TELEGRAM_SESSION_NAME без файла → MISSING")

    # Имя файла рядом с рабочей строкой не должно давать ложную тревогу:
    # сервер возьмёт строку и до файла не дойдёт.
    mixed = tc.check(write(tmp, "mixed.txt",
                           "TELEGRAM_API_ID=123456\n"
                           "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                           f"TELEGRAM_SESSION_STRING={ok_session}\n"
                           f"TELEGRAM_SESSION_NAME={tmp / 'нет-сессии'}\n"))
    check(mixed.level == tc.FORMAT_OK,
          "строка + несуществующий файл → FORMAT_OK (файл не используется)")

    labelled = tc.check(write(tmp, "labelled.txt",
                              "TELEGRAM_API_ID=123456\n"
                              "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                              f"TELEGRAM_SESSION_STRING_WORK={ok_session}\n"))
    check(labelled.level == tc.FORMAT_OK,
          "суффикс TELEGRAM_SESSION_STRING_WORK → FORMAT_OK")

    # Суффиксное имя файла (TELEGRAM_SESSION_NAME_<МЕТКА>) должно давать
    # PARTIAL, как и обычное TELEGRAM_SESSION_NAME: существование файла не
    # доказывает рабочую сессию, а содержимое не проверяется.
    (named / "work.session").write_bytes(b"x")
    suffix_name = tc.check(write(tmp, "suffix-name.txt",
                                "TELEGRAM_API_ID=123456\n"
                                "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                                f"TELEGRAM_SESSION_NAME_WORK={named / 'work'}\n"))
    check(suffix_name.level == tc.PARTIAL,
          "TELEGRAM_SESSION_NAME_WORK с файлом → PARTIAL, а не FORMAT_OK")
    check("не проверена" in suffix_name.short(),
          "и короткий статус говорит, что сессия не проверена")

    # Строковая сессия рядом с суффиксным именем файла тоже PARTIAL:
    # обещать FORMAT_OK нельзя, раз одна из сессий не проверена.
    mix_suffix = tc.check(write(tmp, "mix-suffix.txt",
                                "TELEGRAM_API_ID=123456\n"
                                "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                                f"TELEGRAM_SESSION_STRING={ok_session}\n"
                                f"TELEGRAM_SESSION_NAME_WORK={named / 'work'}\n"))
    check(mix_suffix.level == tc.PARTIAL,
          "строка + суффиксное имя файла → PARTIAL (файл не проверен)")

    # Несколько суффиксных *строковых* сессий без файловых — FORMAT_OK:
    # строки проверяются по формату, поддержка нескольких аккаунтов
    # сохраняется.
    multi_string = tc.check(write(tmp, "multi-string.txt",
                                 "TELEGRAM_API_ID=123456\n"
                                 "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                                 f"TELEGRAM_SESSION_STRING_WORK={ok_session}\n"
                                 f"TELEGRAM_SESSION_STRING_OTHER={ok_v6}\n"))
    check(multi_string.level == tc.FORMAT_OK,
          "несколько суффиксных строковых сессий → FORMAT_OK")

    # Имя с точкой: Telethon добавляет .session к целому имени, поэтому
    # «accounts.db» ищется как «accounts.db.session», а не «accounts.session».
    (named / "accounts.db.session").write_bytes(b"x")
    dotted = tc.check(write(tmp, "dotted.txt",
                           "TELEGRAM_API_ID=123456\n"
                           "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                           f"TELEGRAM_SESSION_NAME={named / 'accounts.db'}\n"))
    check(dotted.level == tc.PARTIAL,
          "имя с точкой (accounts.db) → PARTIAL, файл находится как accounts.db.session")

    print("--- 6. Значения не утекают")
    secret = "SUPER-SECRET-MARKER-123"
    leak = tc.check(write(tmp, "leak.txt",
                          "TELEGRAM_API_ID=123456\n"
                          "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
                          f"TELEGRAM_SESSION_STRING={secret}\n"))
    blob = json.dumps(
        {"level": leak.level, "problems": leak.problems, "notes": leak.notes,
         "short": leak.short()}, ensure_ascii=False)
    check(secret not in blob, "значения нет ни в проблемах, ни в примечаниях")
    check("1abc" not in json.dumps(broken.problems),
          "и повреждённая строка тоже не печатается")

    print("--- 7. Отображение четырёх уровней")
    texts = {
        tc.MISSING: missing.short(),
        tc.BAD_FORMAT: bad_hash.short(),
        tc.PARTIAL: by_name.short(),
        tc.FORMAT_OK: good.short(),
    }
    check(texts[tc.MISSING].startswith("нужно:"),
          f"MISSING в колонке: {texts[tc.MISSING]}")
    check(texts[tc.BAD_FORMAT].startswith("формат:"),
          f"BAD_FORMAT в колонке: {texts[tc.BAD_FORMAT]}")
    check(texts[tc.PARTIAL] == "имя допустимо, сессия не проверена",
          f"PARTIAL в колонке: {texts[tc.PARTIAL]}")
    check(texts[tc.FORMAT_OK].startswith("можно включить"),
          f"FORMAT_OK в колонке: {texts[tc.FORMAT_OK]}")
    check(len(set(texts.values())) == 4,
          "все четыре статуса отличаются друг от друга")

    main_src = (Path(__file__).resolve().parent / "main.py").read_text(
        encoding="utf-8")
    for level in (tc.MISSING, tc.BAD_FORMAT, tc.PARTIAL, tc.FORMAT_OK):
        check(f"telegram_check.{level.upper()}" in main_src,
              f"в словаре статусов main.py есть {level.upper()}")
    check(main_src.count('server.id == "telegram"') == 2,
          "ветки Telegram ровно две: состояние и подсказка")

    print(f"\nИТОГ: {PASSED + FAILED} проверок, {FAILED} провалов")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
