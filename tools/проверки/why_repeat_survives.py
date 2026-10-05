"""Почему `ln not in carried` не теряет законный повтор.

Одна фраза: `carried` содержит ТОЛЬКО строки, в которых встретилось имя
исчезнувшей папки, а повтор живой строки под это имя не подпадает, поэтому
фильтр его не трогает.

Показано на двух файлах: смысловой части указателя и архива.
"""
import shutil
import sys
import tempfile
from pathlib import Path

PROG = Path(r'C:\Users\Dedy_Sher\Downloads\opencode-base-main')
sys.path.insert(0, str(PROG / 'tools' / 'dbapp'))
import core  # noqa: E402

KEEP_1 = "## Когда заходить"
KEEP_2 = "- про устройства — смотри `Техника/`, там всё про железо."
KEEP_3 = ("- отправку ждёт скрипт с `ALLOW_PUSH`, "
          "настройки в `opencode.jsonc`.")
GONE_1 = "- про машины — смотри `Транспорт/`, там всё про колёса."
GONE_2 = "- про участок — смотри `Земля/`, там всё про грядки."
R1 = "---"
R2 = "- про железо — снова `Техника/`."

base = Path(tempfile.mkdtemp(prefix="пояснение-"))
try:
    ia = base / "Имущество"
    (ia / "Техника").mkdir(parents=True)
    (ia / "Техника" / "железо.md").write_text("x", encoding="utf-8")
    old = ("# Указатель: Имущество\n\n" + core.INDEX_BEGIN
           + "\nСобрано: 2026-10-01.\n\n## Пути\n"
           "- `Техника/` — 3 файла\n- `Транспорт/` — 2 файла\n"
           "- `Земля/` — 1 файл\n" + core.INDEX_END + "\n\n"
           + KEEP_1 + "\n" + KEEP_2 + "\n" + R1 + "\n" + R2 + "\n" + R1 + "\n"
           + GONE_1 + "\n" + GONE_2 + "\n" + GONE_1 + "\n" + KEEP_3 + "\n")
    (ia / "_подсказки-имущество.md").write_text(old, encoding="utf-8")

    _, _, after = core._split_index(old)
    new_paths = {r for r, _n in core._index_paths(ia, "children")}
    moved, carried = core._orphaned_lines(old, new_paths)
    core.append_archive(ia, moved, "2026-10-05")
    arch = (ia / core.ARCHIVE_NAME).read_text(encoding="utf-8")

    print("=== ФАЙЛ 1: смысловая часть указателя (была) ===")
    for ln in after.strip().split("\n"):
        mark = "  <- уходит в архив" if ln in carried else ""
        print(f"  {ln}{mark}")
    print()
    print("=== ФАЙЛ 2: архив ===")
    for ln in arch.strip().split("\n"):
        if ln.strip():
            print(f"  {ln}")
    print()
    print("=== отсюда и причина ===")
    print(f"  carried содержит {len(carried)} строк(и), и все они — с именем")
    print("  исчезнувшей папки:")
    for c in sorted(carried):
        print(f"    {c}")
    print()
    print(f"  повтор '{R1}' в carried? {R1 in carried}")
    print(f"  повтор '{R2}' в carried? {R2 in carried}")
    print("  -> фильтр `ln not in carried` сравнивает текст строки. Живой")
    print("     повтор под имена исчезнувших папок не подпадает, значит")
    print("     он остаётся. Совпадение результатов с «поломанной» версией")
    print("     было не случайностью: обе версии ведут себя одинаково.")
finally:
    shutil.rmtree(base, ignore_errors=True)