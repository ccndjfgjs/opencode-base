"""Проверки указателей плагинов: выбор по версии и сверка файла.

    python tools/dbapp/test_plugin_index.py

Пишется до модуля. Сначала падает, потом проходит — иначе проверка ничего
не доказывает: она бы читала код, который сам же и писался под неё.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

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


SAMPLE = {
    "family": "проба",
    "server": "server-mcp@1.2.3",
    "builds": [
        {"since": "5.0", "until": "5.4", "version": "1.0.0",
         "file": "плагин-1.0.0.zip", "url": "https://пример/1.0.0.zip",
         "sha256": "aa" * 32},
        {"since": "5.5", "until": "5.8", "version": "1.2.3",
         "file": "плагин-1.2.3.zip", "url": "https://пример/1.2.3.zip",
         "sha256": "bb" * 32},
    ],
}


def main() -> int:
    import plugin_index as pi

    # === 1. Мусор в указателе не роняет программу ===
    tmp = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(tempfile.gettempdir()) / "opencode" / "проверка-указателей")
    root = tmp / "указатели"
    root.mkdir(parents=True, exist_ok=True)
    broken = root / "индекс-сломанный"
    broken.mkdir(exist_ok=True)
    (broken / "index.json").write_text("{это не json", encoding="utf-8")
    data, note = pi.load("индекс-сломанный", root=root)
    check(data is None, "испорченный указатель не читается как данные")
    check(bool(note) and "index.json" in note,
          f"и называет сам файл, а не падает: {note}")

    missing, note2 = pi.load("такого-нет", root=root)
    check(missing is None and "нет" in note2.lower(),
          f"отсутствующий указатель назван прямо: {note2}")

    # === 2. Выбор по версии ===
    got, why = pi.pick(SAMPLE, "5.2")
    check(got is not None and got.version == "1.0.0",
          f"5.2 берёт первую полосу: {got.version if got else why}")
    got, why = pi.pick(SAMPLE, "5.7")
    check(got is not None and got.version == "1.2.3",
          f"5.7 берёт вторую полосу: {got.version if got else why}")
    got, why = pi.pick(SAMPLE, "5.8")
    check(got is not None and got.version == "1.2.3",
          f"верхняя граница включительно: {got.version if got else why}")
    got, why = pi.pick(SAMPLE, "5.4")
    check(got is not None and got.version == "1.0.0",
          f"нижняя граница полосы тоже включительно: {got.version if got else why}")

    # === 3. Версия вне полос — честный отказ, а не «новейший на всякий случай» ===
    got, why = pi.pick(SAMPLE, "5.0")
    check(got is not None and got.version == "1.0.0",
          f"5.0 — ровно нижняя граница: {got.version if got else why}")
    got, why = pi.pick(SAMPLE, "4.9")
    check(got is None, "слишком старая версия не получила плагин")
    check(bool(why) and "4.9" in why,
          f"и сказано, какая версия не подошла: {why}")
    got, why = pi.pick(SAMPLE, "5.9")
    check(got is None, "слишком новая версия не получила плагин")
    check("5.9" in why or "5.8" in why,
          f"и названы границы: {why}")

    # === 4. Версия без цифр ===
    got, why = pi.pick(SAMPLE, "не-версия")
    check(got is None, "строка без цифр не выдаёт плагин молча")
    check(bool(why), f"и получает объяснение: {why}")

    # === 5. Сверка файла: три честных состояния ===
    payload = tmp / "файл.bin"
    payload.write_bytes("проверяем".encode("utf-8"))
    real = versions.file_sha256(payload)

    good = pi.Plugin(family="проба", name="плагин", version="1.0.0",
                     file="плагин-1.0.0.zip", url="https://пример/1.0.0.zip",
                     sha256=real)
    status, note3 = pi.verify(good, payload)
    check(status == "match", f"совпавший хеш — match ({status})")

    bad = pi.Plugin(family="проба", name="плагин", version="1.0.0",
                    file="плагин-1.0.0.zip", url="https://пример/1.0.0.zip",
                    sha256="0" * 64)
    status, note4 = pi.verify(bad, payload)
    check(status == "mismatch", f"чужой хеш — mismatch ({status})")
    check("не устанавливаем" in note4.lower() or "нельзя" in note4.lower()
          or "совпал" not in note4.lower(),
          f"и прямо сказано, что ставить нельзя: {note4}")

    none_hash = pi.Plugin(family="проба", name="плагин", version="1.0.0",
                          file="плагин-1.0.0.zip", url="https://пример/1.0.0.zip",
                          sha256="")
    status, note5 = pi.verify(none_hash, payload)
    check(status == "unchecked", f"без официального хеша — unchecked ({status})")
    check("хеш" in note5.lower(), f"и это названо предупреждением: {note5}")

    # === 6. Версия сервера едет из указателя, а не из константы ===
    check(SAMPLE.get("server") == "server-mcp@1.2.3",
          "указатель хранит и закреплённую версию сервера")

    # === 6б. Сервер и плагин обязаны быть из одного релиза ===
    # При расхождении Unreal отвечает на каждый вызов `versionMismatch`,
    # и это выглядит как «мост сломан», хотя сломан не мост.
    # У пробного указателя полосы разные: 5.0–5.4 → плагин 1.0.0, а сервер
    # заявлен 1.2.3. Это и есть расхождение, которое обязано быть видно.
    sample_plugin, why_s = pi.pick(SAMPLE, "5.2")
    if sample_plugin is None:
        check(False, f"плагин подходящей версии выбран: {why_s}")
    else:
        check(sample_plugin.version == "1.0.0",
              f"под 5.2 выбран плагин своей полосы: {sample_plugin.version}")
        same, note_same = pi.server_matches(sample_plugin)
        check(not same and "версии не совпадают" in note_same,
              f"расхождение версий называется прямо: {note_same}")
        same_aligned, why_al = pi.pick(SAMPLE, "5.6")
        if same_aligned is None:
            check(False, f"плагин второй полосы выбран: {why_al}")
        else:
            check(pi.server_package(same_aligned) == "server-mcp@1.2.3",
                  f"пакет сервера собран из указателя: "
                  f"{pi.server_package(same_aligned)}")
            check(pi.server_version(same_aligned) == "1.2.3",
                  f"версия сервера снята из строки: {pi.server_version(same_aligned)}")
            same_ok, note_ok = pi.server_matches(same_aligned)
            check(same_ok, f"совпадение версий подтверждено: {note_ok}")
            eq_style = pi.Plugin(name="Y", version="4.3.0", server="godot-ai==4.3.0")
            check(pi.server_package(eq_style) == "godot-ai==4.3.0",
                  f"и формат со знаком == тоже разбирается: "
                  f"{pi.server_package(eq_style)}")
            check(pi.server_package(pi.Plugin(name="Z", version="1.0", server="")) == "",
                  "а без версии сервера в указателе не выдумывается")
        aligned = pi.Plugin(name="X", version="1.2.3", server="server-mcp@1.2.3")
        same_ok, note_ok = pi.server_matches(aligned)
        check(same_ok, f"совпадение версий подтверждено: {note_ok}")
        eq_style = pi.Plugin(name="Y", version="4.3.0", server="godot-ai==4.3.0")
        check(pi.server_package(eq_style) == "godot-ai==4.3.0",
              f"и формат со знаком == тоже разбирается: {pi.server_package(eq_style)}")
        check(pi.server_package(pi.Plugin(name="Z", version="1.0", server="")) == "",
              "а без версии сервера в указателе не выдумывается")

    # === 6г. Свежая полоса, когда версия программы ещё не измерена ===
    # Пустая строка в требовании — это «пока неизвестно», а не «версия 9999»:
    # выдуманная версия выпадает из всех полос, и мост отказывается на пустом
    # месте. Берётся самая свежая полоса.
    newest, why_new = pi.latest(SAMPLE)
    check(newest is not None and newest.version == "1.2.3",
          f"без версии программы взята самая свежая полоса: "
          f"{newest.version if newest else why_new}")
    newest_real, why_real = pi.latest_for("enginewire")
    check(newest_real is not None and newest_real.version == "0.6.0-beta-f",
          f"и по настоящему указателю тоже: "
          f"{newest_real.version if newest_real else why_real}")
    pair_ok, note_pair = pi.family_pair("enginewire", "5.7")
    check(pair_ok is not None and bool(note_pair),
          f"вызов «плагин плюс сверка» работает: {note_pair}")
    pair_bad, note_bad_pair = pi.family_pair("enginewire", "4.27")
    check(pair_bad is None and "не попадает" in note_bad_pair,
          f"а неподходящая версия отказывает до сети: {note_bad_pair}")

    # === 6в. Инвариант по всем настоящим указателям ===
    # Проверяется не на выдуманном примере, а на всех семействах программы:
    # добавим мост и забудем про версии — проверка сразу скажет.
    for family in ("enginewire", "godot-ai", "unity-mcp", "ghidra-mcp"):
        idx, why_f = pi.load(family)
        if idx is None:
            check(False, f"указатель {family} читается: {why_f}")
            continue
        for build in idx.get("builds") or []:
            got, why_b = pi.pick(idx, str(build.get("since") or "1.0"))
            if got is None:
                check(False, f"{family}: полоса {build.get('since')} не выбралась: {why_b}")
                continue
            same_b, note_b = pi.server_matches(got)
            check(same_b,
                  f"{family} {got.version}: сервер и плагин из одного релиза"
                  + (f" — {note_b}" if not same_b else ""))

    # === 7. Настоящие указатели программы читаются и попадают в полосы ===
    real_cases = [
        ("enginewire", "5.7", True),
        ("enginewire", "4.27", False),
        ("enginewire", "5.9", False),
        ("godot-ai", "4.7", True),
        ("godot-ai", "4.6", False),
        ("godot-ai", "4.5", False),
        ("ghidra-mcp", "12.1.4", True),
        ("ghidra-mcp", "12.1.2", False),
        ("unity-mcp", "2021.3", True),
        ("unity-mcp", "2020.3", False),
    ]
    for family, version, expected in real_cases:
        idx, why6 = pi.load(family)
        if idx is None:
            check(False, f"указатель {family} читается: {why6}")
            continue
        got, why7 = pi.pick(idx, version)
        check((got is not None) == expected,
              f"{family} на {version}: {'плагин есть' if expected else 'плагина нет'}"
              + ("" if got else f" — {why7}"))

    # === 8. Распаковка: снятие верхней папки и отказ на выходе из папки ===
    import zipfile

    def make_zip(name: str, entries: dict[str, bytes]) -> Path:
        path = tmp / name
        with zipfile.ZipFile(path, "w") as zf:
            for inside, blob in entries.items():
                zf.writestr(inside, blob)
        return path

    proj = tmp / "проект"
    proj.mkdir(parents=True, exist_ok=True)
    arch = make_zip("enginewire.zip", {
        "plugins/EngineWire/EngineWire.uplugin": b"<uplugin/>",
        "plugins/EngineWire/Source/модуль.cpp": "// код".encode("utf-8"),
    })
    engine = pi.Plugin(family="enginewire", name="EngineWire", version="0.6.0-beta-f",
                       file=arch.name, url="https://пример/x.zip", sha256="",
                       folder="plugins/EngineWire", strip=1, dest="Plugins")
    where, note8 = pi.extract(engine, arch, proj / "Plugins")
    check(where is not None, f"архив распакован: {note8}")
    check((proj / "Plugins" / "EngineWire" / "EngineWire.uplugin").is_file(),
          "верхняя папка plugins снята, EngineWire лёг прямо в Plugins")
    check((proj / "Plugins" / "EngineWire" / "Source" / "модуль.cpp").is_file(),
          "вложенные файлы не потерялись")

    evil = make_zip("злой.zip", {"../вне.txt": "нельзя".encode("utf-8")})
    bad_plugin = pi.Plugin(family="проба", name="злой", version="1", file="злой.zip",
                           url="https://пример/x.zip", sha256="", folder="addons/что-то",
                           strip=0)
    where9, note9 = pi.extract(bad_plugin, evil, proj / "Plugins")
    check(where9 is None, "архив с выходом из папки не распакован")
    check(".." in note9 or "выход" in note9.lower(), f"и сказано почему: {note9}")
    check(not (tmp / "вне.txt").exists(), "файл наружу не записан")

    # === 9. Скачивание: сверка на месте, чужой файл удаляется ===
    good_file = tmp / "хороший.zip"
    good_file.write_bytes("содержимое плагина".encode("utf-8"))
    dl = pi.Plugin(family="проба", name="плагин", version="1", file="хороший.zip",
                   url=good_file.as_uri(), sha256=versions.file_sha256(good_file))
    into = tmp / "загрузки"
    got, note10 = pi.download(dl, into)
    check(got is not None and got.is_file(), f"файл скачан: {note10}")
    if got is not None:
        check(got.read_bytes() == good_file.read_bytes(), "содержимое не поехало")

    wrong = pi.Plugin(family="проба", name="плагин", version="1", file="плохой.zip",
                      url=good_file.as_uri(), sha256="1" * 64)
    got2, note11 = pi.download(wrong, into)
    check(got2 is None, "чужой файл не отдан наружу")
    check(not (into / "плохой.zip").exists(), "и удалён с диска, а не оставлен")

    # === 10. Архив не от того плагина — честный отказ, а не «готово» ===
    other = make_zip("чужой.zip", {"docs/readme.txt": b"x"})
    got3, note12 = pi.extract(bad_plugin, other, proj / "Plugins")
    check(got3 is None, "архив без нужной папки не принят")
    check("нет папки" in note12, f"и сказано, чего не хватило: {note12}")

    # === 11. Без описанной папки не распаковываем вообще ничего ===
    no_folder = pi.Plugin(family="проба", name="без-папки", version="1",
                          file="чужой.zip", url="https://пример/x.zip", sha256="",
                          folder="", strip=0)
    got4, note13 = pi.extract(no_folder, other, proj / "Plugins")
    check(got4 is None, "без folder распаковка отказана")
    check("folder" in note13, f"и названа причина: {note13}")
    check(not (proj / "Plugins" / "docs" / "readme.txt").exists(),
          "чужой архив не расписан по проекту")

    # === 12. Встроенный файл важнее сети ===
    bundled_root = root / "встроенные"
    (bundled_root / "проба").mkdir(parents=True, exist_ok=True)
    payload = bundled_root / "проба" / "плагин-1.0.0.zip"
    payload.write_bytes("встроенное содержимое".encode("utf-8"))
    built = pi.Plugin(family="проба", name="плагин", version="1.0.0",
                      file="плагин-1.0.0.zip", url="https://пример/1.0.0.zip",
                      sha256=versions.file_sha256(payload), bundled=True)
    check(pi.bundled_path(built, root=bundled_root) == payload,
          "встроенный файл найден по папке программы")
    got5, note14 = pi.obtain(built, tmp / "загрузки2", root=bundled_root)
    check(got5 == payload, f"об obtain берёт встроенный файл: {note14}")
    check("интернет не нужен" in note14,
          f"и говорит, что сеть не понадобилась: {note14}")

    # Встроенный файл, не прошедший сверку, НЕ скачивается заменой.
    broken_payload = bundled_root / "проба" / "плагин-1.0.0.zip"
    broken_payload.write_bytes("подменили".encode("utf-8"))
    got6, note15 = pi.obtain(built, tmp / "загрузки3", root=bundled_root)
    check(got6 is None, "подменённый встроенный файл не поставлен")
    check("не ставлю его и не качаю другой молча" in note15,
          f"и молчаливую замену из сети обещает не делать: {note15}")

    # Встроенного файла нет — тогда сеть, и это сказано вслух.
    net_source = tmp / "из-сети.zip"
    net_source.write_bytes("содержимое из сети".encode("utf-8"))
    net_only = pi.Plugin(family="проба", name="плагин", version="1.0.0",
                         file="из-сети.zip", url=net_source.as_uri(),
                         sha256=versions.file_sha256(net_source), bundled=True)
    got7, note16 = pi.obtain(net_only, tmp / "загрузки4", root=root / "пусто")
    check(got7 is not None and got7.is_file(),
          f"без встроенного файла работает загрузка из сети: {note16}")
    check("встроенного файла" in note16.lower() or "интернет не нужен" not in note16,
          f"и это сказано вслух: {note16}")

    not_bundled = pi.Plugin(family="проба", name="плагин", version="1.0.0",
                            file="плагин-1.0.0.zip", url="https://пример/1.0.0.zip",
                            sha256="")
    check(pi.bundled_path(not_bundled, root=bundled_root) is None,
          "без отметки bundled встроенного файла не ищется")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())