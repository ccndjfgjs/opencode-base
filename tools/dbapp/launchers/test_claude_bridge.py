"""Проверки моста Claude. Сеть, CLI и ключи не нужны.

    python tools/dbapp/launchers/test_claude_bridge.py

Настоящей Claude Code на машине нет, поэтому проверяется МЕХАНИКА: сборка
команды, разбор ответов, фильтр секретов и классификация состояний.
Совместимость с настоящей версией эти проверки не доказывают и доказать
не могут — см. раздел 10 спецификации.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bridge_common as common  # noqa: E402
import claude_bridge_launcher as claude  # noqa: E402

EXE = r"C:\путь\к\claude.exe"
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
    # === 1. Сборка команды: пять отдельных элементов, не перечисление ===
    argv = claude.claude_argv(EXE, "привет")
    check(argv[0] == EXE, "первым идёт абсолютный путь, а не имя программы")
    check(argv[1] == "-p" and argv[2] == "привет", "запрос идёт одним аргументом")
    check("--permission-mode" in argv and
          argv[argv.index("--permission-mode") + 1] == "plan",
          "режим plan передан отдельным флагом и значением")
    check("--permission-prompts" in argv and
          argv[argv.index("--permission-prompts") + 1] == "none",
          "--permission-prompts none передан")
    check("--disallowedTools" in argv, "флаг --disallowedTools есть")
    idx = argv.index("--disallowedTools")
    tools = argv[idx + 1:idx + 5]
    check(tools == ["Edit", "Write", "NotebookEdit", "MultiEdit"],
          "четыре имени запрета идут отдельными элементами argv")
    check(len(argv) - (idx + 1) == 4,
          "после флага ровно четыре имени и ничего лишнего")
    argv_res = claude.claude_argv(EXE, "ещё", resume="abc-123")
    idx_res = argv_res.index("--disallowedTools")
    check(argv_res[idx_res + 5] == "--resume",
          "у продолжения --resume идёт сразу после четырёх имён")
    joined = " ".join(argv)
    check("Edit,Write" not in joined, "запреты не склеены через запятую")
    check("bypassPermissions" not in joined, "нет bypassPermissions")
    check("--dangerously-skip-permissions" not in joined, "нет опасного флага пропуска прав")
    check("--allowedTools" not in joined, "нет разрешающего списка инструментов")
    check("--bare" not in joined, "--bare не передаём: он убил бы вход по подписке")

    # === 2. Продолжение собирает ограничения заново ===
    argv2 = claude.claude_argv(EXE, "ещё", resume="abc-123")
    idx2 = argv2.index("--disallowedTools")
    check(argv2[idx2 + 1:idx2 + 5] == ["Edit", "Write", "NotebookEdit", "MultiEdit"],
          "claude_send заново собирает все четыре запрета")
    check("--permission-mode" in argv2 and "--permission-prompts" in argv2,
          "claude_send заново собирает plan и permission-prompts")
    check("--resume" in argv2 and argv2[argv2.index("--resume") + 1] == "abc-123",
          "продолжение передаёт id")

    # === 3. Версия и совместимость ===
    check(claude.compatible((2, 1, 259)), "минимальная версия совместима")
    check(claude.compatible((2, 2, 0)), "версия выше минимума совместима")
    check(not claude.compatible((2, 1, 258)), "версия ниже минимума несовместима")
    check(not claude.compatible((1, 9, 9)), "сильно старая версия несовместима")
    check(not claude.compatible(None), "непрочитанная версия НЕ считается совместимой")

    # === 4. Контракт разбора: семь ситуаций ===
    ok = claude.build_result(0, '{"result":"привет","session_id":"s1"}', "", "")
    check(ok.status == "ок" and ok.text == "привет" and ok.session_id == "s1",
          "код 0, JSON верный, result непустой")

    empty = claude.build_result(0, '{"result":"","session_id":"s2"}', "", "")
    check(empty.status == "ошибка_разбора", "пустой result — это не успех")
    check("не вернул текст" in empty.text, "про пустой result сказано прямо")

    bad_json = claude.build_result(0, "не json вовсе", "", "")
    check(bad_json.status == "ошибка_разбора", "нечитаемый JSON не выдан за ответ")
    check("не json вовсе" not in bad_json.text,
          "текст из stdout не выдаётся за ответ модели")

    nonzero_json = claude.build_result(3, '{"result":"текст","session_id":"s3"}', "", "")
    check(nonzero_json.status == "ошибка_процесса",
          "ненулевой код с корректным JSON — не успех")
    check(nonzero_json.session_id == "s3", "id при ошибке сохраняется для диагностики")

    nonzero_text = claude.build_result(4, "", "ошибка запуска", "")
    check(nonzero_text.status == "ошибка_процесса"
          and "кодом 4" in nonzero_text.text,
          "ненулевой код назван прямо")
    check("ошибка запуска" in nonzero_text.detail, "диагностика из stderr на месте")
    check("ошибка запуска" not in nonzero_text.text,
          "stderr не выдаётся за ответ модели")

    not_started = claude.build_result(None, "", "не запустился", "не_запустился")
    check(not_started.status == "не_запустился", "незапуск отделён от ошибок Claude")

    timeout = claude.build_result(None, "", "", "таймаут")
    check(timeout.status == "таймаут" and "остановлен" in timeout.text,
          "таймаут говорит, что процесс остановлен")
    stuck = claude.build_result(None, "", "", "ошибка_остановки")
    check(stuck.status == "ошибка_остановки", "неподтверждённая очистка — свой статус")
    check("могли остаться" in stuck.text or "остановить его не удалось" in stuck.text,
          "при неудачной остановке сказано, что могло остаться работать")

    # === 5. session_id не поднимает статус до успеха ===
    check(not empty.session_id or empty.status != "ок",
          "id при ошибке не делает вызов успешным")

    # === 6. Фильтр секретов: все обещанные представления ===
    secret = "sk-ant-секрет&значение=1"
    raw = (f"вот ключ {secret}\n"
           f"в url: https://x.test/?k={secret}\n"
           f"плюсами: {secret.replace(' ', '+')}\n"
           f"html: {secret.replace('&', '&amp;')}")
    import urllib.parse
    clean = claude.filter_secrets(raw, [secret])
    check(secret not in clean, "исходное значение не осталось в тексте")
    check(urllib.parse.quote(secret, safe="") not in clean,
          "процентно закодированная форма не осталась")
    check(claude.SECRET_MARK in clean, "на месте стоит маркер скрытого")
    check(claude.filter_secrets("обычный текст", []) == "обычный текст",
          "без секретов текст не трогаем")

    # === 7. Сбой фильтра: диагностика не выдаётся целиком ===
    check(claude.filter_secrets(12345, ["x"]) == "",
          "на нестроковых данных фильтр не падает, а возвращает пусто")
    check(claude.filter_secrets(None, ["x"]) == "", "None тоже даёт пусто")

    # === 8. Длинная диагностика обрезается ===
    long = claude.build_result(9, "", "x" * 9000, "")
    check(len(long.detail) <= claude.DETAIL_LIMIT,
          "диагностика обрезана до 2000 символов")

    # === 9. Предупреждение о безопасности — постоянное свойство ===
    for tool in claude.TOOLS:
        check("абсолютной защиты" in tool["description"],
              f"в описании {tool['name']} есть честное предупреждение")
    check(claude.SAFETY_NOTE in claude.TOOLS[0]["description"],
          "предупреждение не зависит от текста запроса")
    check("защищ" not in claude.TOOLS[0]["description"].replace(
        "абсолютной защиты", ""), "мост не обещает защиту папки")

    # === 10. Таймаут вызова тот же, что у остальных мостов ===
    check(claude.TIMEOUT == 600, "таймаут вызова 600 секунд")
    check(claude.MIN_VERSION == (2, 1, 259), "минимум версии зафиксирован")

    # === 11. Проверка входа: ровно три элемента argv ===
    import inspect
    source = inspect.getsource(claude.auth_state)
    check('"auth", "status"' in source,
          "argv проверки входа — абсолютный путь плюс ровно auth и status")
    check('"login"' not in source,
          "в команде проверки нет подкоманды входа")
    check("claude auth login" in source,
          "в тексте совета человеку команда входа упомянута — это не запуск")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()