# -*- coding: utf-8 -*-
"""Откат для раздела 8ц-1 селфтеста (список указателей знаний).

Восемь новых проверок. Каждая должна ломаться, когда ломается её условие.
Иначе она не проверка, а украшение.

Работает на копии `core.py` во временной папке: настоящий файл не
трогает. Полный селфтест здесь не гоняется — он занимает минуты, а суть
проверок проверяется теми же самыми утверждениями.
"""

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent.parent / "tools" / "dbapp" / "core.py"
OUT = HERE / "отчёт-откат-задача-1.txt"

#: (имя, что подменяем в копии core.py, номер проверки, ожидаемый вердикт)
BREAKS = [
    ("убрать ветку безопасности",
     '        if KNOWLEDGE_SUBSUBDIRS.get(sub):',
     '        if False:',
     2, "указателей одиннадцать"),
    ("убрать область из списка",
     '    "Люди",\n    "Имущество",\n    "Экстренное",\n)',
     '    "Люди",\n    "Имущество",\n)',
     2.5, "областей девять по решению от 05.10"),
    ("сломать тройку",
     'out.append((branch_root, "_подсказки-техника.md", INDEX_LIMIT_AREA))',
     'out.append((branch_root, "_подсказки-техника.md",\n                INDEX_LIMIT_AREA, "лишнее"))',
     3, "тройкой"),
    ("спутать уровни: корень отнести к области",
     '    out: list[tuple[str, str, int]] = [\n        ("знания", "_подсказки-общая.md", INDEX_LIMIT_ROOT),\n    ]',
     '    out: list[tuple[str, str, int]] = [\n        ("знания/Деньги", "_подсказки-общая.md", INDEX_LIMIT_ROOT),\n    ]',
     4, "корневой указатель ровно один"),
    ("переименовать корень по имени папки",
     '        ("знания", "_подсказки-общая.md", INDEX_LIMIT_ROOT),',
     '        ("знания", "_подсказки-знания.md", INDEX_LIMIT_ROOT),',
     5, "корневой указатель называется так"),
    ("сменить лимит ветки безопасности",
     'INDEX_LIMIT_BRANCH = 32 * 1024',
     'INDEX_LIMIT_BRANCH = 5 * 1024',
     6, "у ветки безопасности свой лимит 32 КБ"),
    ("дать указатель не всем областям",
     '    for area in KNOWLEDGE_AREAS:\n        if area == "Техника":\n            continue',
     '    for area in KNOWLEDGE_AREAS:\n        if area in ("Техника", "Учёба"):\n            continue',
     7, "указатель области есть у каждой области"),
    ("вывести имя не из имени папки",
     'out.append((f"знания/{area}", f"_подсказки-{area.lower()}.md",',
     'out.append((f"знания/{area}", f"_подсказки-{area}-указатель.md",',
     8, "имя указателя выведено из имени папки"),
]


def load(tmpdir: Path, text: str, name: str):
    """Кладёт текст как core.py во временную папку и импортирует.

    Регистрировать модуль в sys.modules обязательно: иначе падает
    `@dataclass` — он ищет модуль класса через `sys.modules`.
    """
    path = tmpdir / f"{name}.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def assertions(core) -> list[tuple[int, str, bool]]:
    """Те же восемь утверждений, что стоят в селфтесте, раздел 8ц-1."""
    kidx = core.knowledge_index_targets()
    want = 1 + len(core.KNOWLEDGE_AREAS) + 1
    lvl1 = [t for t in kidx if t[0].count("/") == 0]
    lvl2 = [t for t in kidx if t[0].count("/") == 1]
    sec = [t for t in kidx if "Безопасность" in t[0]]
    bad = []
    # Обращение по индексам, а не распаковка: иначе поломка «не тройка»
    # роняет сам скрипт, и доказательство не получается — падает не
    # проверка, а код до неё.
    for t in kidx:
        rel, fname = t[0], t[1]
        want_name = (f"_подсказки-{Path(rel).name.lower()}.md"
                     if rel != "знания" else "_подсказки-общая.md")
        if fname != want_name:
            bad.append(f"{rel}: {fname} ждали {want_name}")
    return [
        (1, "указателей для всех областей", len(kidx) == want),
        (2, "указателей одиннадцать по решению от 05.10", len(kidx) == 11),
        (2.5, "областей девять по решению от 05.10",
         len(core.KNOWLEDGE_AREAS) == 9),
        (3, "каждый указатель описан тройкой", all(len(t) == 3 for t in kidx)),
        (4, "корневой указатель ровно один", len(lvl1) == 1),
        (5, "корневой указатель называется так",
         bool(lvl1) and lvl1[0][1] == "_подсказки-общая.md"),
        (6, "у ветки безопасности свой лимит 32 КБ",
         len(sec) == 1 and sec[0][2] == 32 * 1024),
        (7, "указатель области есть у каждой из девяти", len(lvl2) == 9),
        (8, "имя указателя выведено из имени папки", not bad),
    ]


def main() -> int:
    original = CORE.read_text(encoding="utf-8")
    lines = ["=== откат раздела 8ц-1: список указателей знаний ===", ""]
    ok = True

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        base = assertions(load(tmp, original, "core_rb_base"))
        lines.append("1. без поломок — все восемь должны быть верны")
        for num, what, passed in base:
            lines.append(f"   проверка {num}: {'верно' if passed else 'ЛОЖЬ'}")
            if not passed:
                ok = False
        lines.append(f"   все верны: {all(p for _n, _w, p in base)}")

        lines.append("")
        lines.append("2. каждая поломка обязана ломать свою проверку")
        for i, (what, good, bad, num, label) in enumerate(BREAKS):
            num = int(num)
            if good not in original:
                lines.append(f"   НЕЛЬЗЯ ДОКАЗАТЬ: нет строки «{what}» — "
                             "код изменился, скрипт устарел")
                ok = False
                continue
            try:
                got = assertions(
                    load(tmp, original.replace(good, bad, 1), f"core_rb_b{i}"))
            except Exception as exc:              # noqa: BLE001
                lines.append(f"   {what}: код не выполнился ({exc}) — "
                             "это тоже падение, но не проверки")
                ok = False
                continue
            fired = [n for n, _w, p in got if not p]
            hit = float(num) in [float(n) for n in fired]
            mark = "поймана" if hit else "ПРОПУЩЕНА"
            if not hit:
                ok = False
            lines.append(f"   {what}: проверка {num} «{label}» — {mark}")
            if fired:
                lines.append(f"      сработавшие: {fired}")

    lines.append("")
    lines.append(f"ИТОГ: {'откат доказан' if ok else 'ОТКАТ НЕ ДОКАЗАН'}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())