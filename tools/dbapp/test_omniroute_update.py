"""Обновление моста OmniRoute с официального GitHub.

Запуск: python tools/dbapp/test_omniroute_update.py

Что тут проверяется. 19.10.2026 человек попросил обновлять OmniRoute
из программы, с официального GitHub. Официальный репозиторий —
`diegosouzapw/OmniRoute`, он же прописан в реестре моста.

Три решения, и все три из-за одной неочевидной вещи.

1. **Версию спрашиваем у GitHub, а пакет ставим из npm.** Наличие
   версии проверяется по меткам `v3.8.51` в официальном репозитории —
   это ровно то, что человек и просил. А сам пакет ставится через
   `npm install omniroute@<версия>`, потому что в релизах GitHub нет
   вложения с пакетом: там лежат только настольные сборки и исходники
   (проверено 19.10.2026 — 18 вложений, из них пригодных для моста
   нет ни одного). Ставить из исходников было бы в разы тяжелее и
   придумывалось бы в обход проверки хвоста подписи.

2. **Адрес проверяется тем же слоем, что и у программы.** Источник
   обновления приезжает в архиве обновления, поэтому доверять ему без
   проверки — значит оставить человеку возможность перенаправить
   обновление куда угодно. Зовём `update_source.check_url`: только
   HTTPS, только `github.com` / `api.github.com`.

3. **Версия закрепляется в команде установки.** `npm install
   omniroute@latest` между проверкой и установкой может отдать другую
   версию, и человек получит не ту, которую только что увидел в
   подписи. Поэтому ставится ровно та, которую назвал GitHub.

Проверка сетевую часть подменяет: реальный запрос к GitHub без
человека делать нельзя — это и лимит запросов, и чужая машина.
Всё остальное — настоящие модули программы.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import omniroute  # noqa: E402
import omniroute_update  # noqa: E402
import update_source  # noqa: E402
import versions  # noqa: E402

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


def need(obj, name: str):
    value = getattr(obj, name, None)
    check(value is not None,
          f"у {getattr(obj, '__name__', obj)} есть {name}")
    return value


#: Ответ GitHub на список меток — как он приходит на самом деле.
TAGS = [
    {"name": "v3.8.51"},
    {"name": "v3.8.50"},
    {"name": "before-something"},
]


def main() -> int:
    # --- 1. официальный репозиторий назван и совпадает с реестром
    official_source = need(omniroute_update, "official_source")
    if official_source is not None:
        source = official_source()
        check(source["owner"] == "diegosouzapw"
              and source["repo"] == "OmniRoute",
              f"официальный репозиторий: {source['owner']}/{source['repo']}")
        registry = (HERE.parent.parent / "данные" / "mcp-registry.json")
        data = json.loads(registry.read_text(encoding="utf-8"))
        servers = data["servers"] if isinstance(data, dict) else data
        entry = next(s for s in servers if s.get("id") == "omniroute")
        check(entry["source"] == "https://github.com/diegosouzapw/OmniRoute",
              "и он тот же, что прописан в реестре моста")

    # --- 2. адрес проверяется тем же слоем, что и у программы
    tags_url = need(omniroute_update, "tags_url")
    if tags_url is not None:
        url = tags_url(source)
        check(url.startswith("https://api.github.com/"),
              f"список меток берётся с api.github.com: {url}")
        try:
            update_source.check_url(url)
            check(True, "и проходит проверку хоста и схемы")
        except update_source.SourceError as exc:
            check(False, f"и проходит проверку хоста и схемы: {exc}")
        bad = tags_url({"owner": "evil", "repo": "../../etc"})
        check("evil" in bad,
              f"а чужое имя репозитория подставляется как есть и проверяется: {bad[:70]}")

    # --- 3. метки разбираются номерами версий, мусор отбрасывается
    pick = need(omniroute_update, "pick_version")
    if pick is not None:
        tag, ver = pick(TAGS)
        check((tag, ver) == ("v3.8.51", "3.8.51"),
              f"самая свежая метка: {tag} → версия {ver}")
        only_junk = [{"name": "before-x"}, {"name": "nightly"}]
        try:
            junk = pick(only_junk)
            check(False, f"метки без версии отбрасываются, а не превращаются: {junk}")
        except omniroute_update.UpdateError as exc:
            check(True, f"метки без версии отбрасываются: {str(exc)[:80]}")

    # --- 4. сравнение версий — общим модулем, а не своим разбором
    compare = need(omniroute_update, "is_newer")
    if compare is not None:
        check(compare("3.8.50", "3.8.51"), "3.8.51 новее 3.8.50")
        check(not compare("3.8.51", "3.8.51"), "одинаковые — не новее")
        check(not compare("3.8.51", "3.8.50"), "3.8.50 не новее 3.8.51")
        check(compare("3.8.9", "3.8.51"), "3.8.9 → 3.8.51 числовым сравнением, не строкой")

    # --- 5. версия закрепляется в команде установки
    build = need(omniroute_update, "install_argv")
    if build is not None:
        argv = build("3.8.51")
        joined = " ".join(argv)
        check("3.8.51" in joined,
              f"в команде установки закреплена конкретная версия: {joined[-40:]}")
        check("@latest" not in joined,
              "и НЕ latest: между проверкой и установкой latest мог бы отдать "
              "другую версию")

    # --- 6. обновление честно отказывается, когда версии нет
    #
    # Подменяется и `deployed`. Проверка обязана мерить логику, а не
    # состояние машины: в рабочей копии программы OmniRoute не
    # развёрнут, и без подмены она падала на «не развёрнут», не дойдя
    # до сравнения версий.
    was_installed = omniroute.installed_version
    was_run = omniroute._run
    was_deployed = omniroute.deployed
    try:
        omniroute.deployed = lambda: True
        omniroute.installed_version = lambda: "3.8.51"
        messages, errors = omniroute_update.check(
            Path("нет-такой-папки"), remote="3.8.51")
        check(not errors, f"при равных версиях обновления нет, а не отказ: {errors[:1]}")
        check(any("не новее" in m or "Обновлений нет" in m for m in messages),
              f"и сказано словами: {messages[-1][:110]}")

        messages, errors = omniroute_update.check(
            Path("нет-такой-папки"), remote="3.8.52")
        check(not errors, "при новой версии это не ошибка, а находка")
        check(any("3.8.52" in m for m in messages),
              f"и названа версия, которую надо поставить: {messages[-1][:110]}")

        omniroute.installed_version = lambda: ""
        messages, errors = omniroute_update.check(
            Path("нет-такой-папки"), remote="3.8.52")
        check(any("Развернуть" in m for m in messages + errors),
              f"при неназванной версии сказано про «Развернуть»: {messages[:1]}")

        omniroute.deployed = lambda: False
        messages, errors = omniroute_update.check(
            Path("нет-такой-папки"), remote="3.8.52")
        check(any("Развернуть" in m for m in messages + errors),
              f"при неразвёрнутом мосте сказано про «Развернуть»: {messages[:1]}")
    finally:
        omniroute.installed_version = was_installed
        omniroute._run = was_run
        omniroute.deployed = was_deployed

    # --- 7. ошибка сети говорит словами, а не traceback
    try:
        def broken_fetch(url):
            raise OSError("сеть молчит")

        omniroute_update.latest_version(fetch=broken_fetch)
        check(False, "сеть не ответила — должен быть понятный отказ")
    except omniroute_update.UpdateError as exc:
        check(bool(str(exc)),
              f"сеть не ответила — понятный отказ: {str(exc)[:80]}")

    # --- 8. живой запрос к официальному GitHub
    # Сеть трогаем последней и ровно один раз: без ключа GitHub
    # отдаёт 60 запросов в час на адрес.
    try:
        tag, ver = omniroute_update.latest_version()
        check(ver.replace(".", "").isdigit(),
              f"живой ответ официального GitHub: {tag} → {ver}")
    except omniroute_update.UpdateError as exc:
        check(True, f"живой запрос не прошёл — это внешнее условие: {str(exc)[:90]}")

    # --- 9. ход установки
    #
    # Настоящий `npm install` качает сотни мегабайт, поэтому команда
    # подменяется. Проверяется не успех установки, а честность её
    # итогов: npm на Windows часто отдаёт код с ошибкой даже когда дело
    # сделал, и на Windows он же падает при выходе.
    was_run_argv = omniroute.run_argv
    was_version = omniroute.installed_version
    try:
        calls = []

        def run_ok(argv, cwd=None, dest=None, timeout=0):
            calls.append(list(argv))
            return 0, "added 1 package", ""

        omniroute.run_argv = run_ok
        omniroute.installed_version = lambda: "3.8.52"
        messages, errors = omniroute_update.install(
            Path("нет-такой-папки"), "3.8.52")
        check(not errors, f"успешная установка — не отказ: {errors[:1]}")
        check(len(calls) == 1 and "3.8.52" in " ".join(calls[0]),
              f"и команда ушла ровно одна, с той версией: {calls[:1]}")
        check(any("Перезапустить" in m for m in messages),
              f"и сказано, что сервер надо перезапустить: {messages[-1][:110]}")

        # npm отработал, но на диске не та версия — это враньё, и оно
        # должно быть названо, а не спрятано за кодом 0.
        omniroute.installed_version = lambda: "3.8.51"
        messages, errors = omniroute_update.install(
            Path("нет-такой-папки"), "3.8.52")
        check(bool(errors), "поставили не то — это отказ, а не успех")
        check(any("Поставили не то" in e for e in errors),
              f"и сказано словами: {errors[:1]}")

        # npm вернул ошибку — причина показывается, а не код молча.
        omniroute.run_argv = lambda *a, **k: (1, "", "npm ERR! network timeout")
        messages, errors = omniroute_update.install(
            Path("нет-такой-папки"), "3.8.52")
        check(bool(errors) and "network timeout" in " ".join(errors),
              f"ошибка npm доходит до человека: {errors[:1]}")
    finally:
        omniroute.run_argv = was_run_argv
        omniroute.installed_version = was_version

    # --- 10. без npm честный отказ, а не выдуманный адрес
    was_npm = omniroute.npm_exe
    try:
        omniroute.npm_exe = lambda: None
        try:
            omniroute_update.install_argv("3.8.52")
            check(False, "без npm обновлять нечем — должен быть отказ")
        except omniroute_update.UpdateError as exc:
            check("Node.js" in str(exc),
                  f"без npm сказано про Node.js: {str(exc)[:90]}")
    finally:
        omniroute.npm_exe = was_npm

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())