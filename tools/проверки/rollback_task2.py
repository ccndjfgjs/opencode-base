# -*- coding: utf-8 -*-
"""Откат для раздела 8ц-2 селфтеста (машинная часть указателя).

Одиннадцать новых проверок. Каждая должна ломаться, когда ломается её
условие, иначе она не проверка, а украшение.

Работает на копии `core.py` во временной папке и проверяет те же
утверждения, что стоят в селфтесте. Полный селфтест не гоняется: он
занимает минуты, а суть проверок проверяется теми же утверждениями.

Настоящий файл не трогает.
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent.parent / "tools" / "dbapp" / "core.py"
OUT = HERE / "отчёт-откат-задача-2.txt"

#: Что ломаем в копии core.py. Номер — та проверка, которая обязана
#: погаснуть. Поломки подобраны так, чтобы касалась кода, а не комментария
#: и не соседней функции: подмена, которая меняет только текст, ничего
#: не ломает и выглядит как «проверка мимо».
BREAKS = [
    ("не обходить вложенные папки при scope=tree",
     '        folders = [p for p in folder.rglob("*") if p.is_dir()]',
     '        folders = [p for p in folder.iterdir() if p.is_dir()]',
     4, "scope=tree перечисляет поддерево"),
    ("не перечислять прямые подпапки",
     '        folders = [p for p in folder.iterdir() if p.is_dir()]',
     '        folders = []',
     1, "корневой указатель перечисляет области"),
    ("убрать маркеры машинной части",
     'INDEX_BEGIN = "<!-- == авточасть: дальше не редактировать руками -->"',
     'INDEX_BEGIN = "<!-- == что-то другое -->"',
     3, "маркеры именно те, о которых договорились"),
    ("забыть про служебные файлы в счёте",
     'def _is_service_markdown(path: Path) -> bool:\n    return path.name == "_О-ПАПКЕ.md" or path.name.startswith("_подсказки")',
     'def _is_service_markdown(path: Path) -> bool:\n    return False',
     8, "служебные файлы не попали в счёт"),
    ("перевернуть порядок",
     '    folders.sort(key=lambda p: p.relative_to(folder).as_posix())',
     '    folders.sort(key=lambda p: p.relative_to(folder).as_posix(), reverse=True)',
     12, "пути идут по алфавиту"),
    # Поломка «убрать сортировку совсем» удалена: на дереве из двух папок
    # порядок обхода уже совпадает с алфавитным, и поломка ничего не
    # меняет. Она выглядела бы как непойманная по причине, которой нет.
    ("убрать число папок",
     'f"Собрано: {stamp}. Папок: {len(paths)}, файлов: {total_files}.",',
     'f"Собрано: {stamp}.",',
     10, "число папок в авточасти верно"),
    ("заменить формулировку правила разрешения",
     '"Полный путь = папка указателя + строка из раздела «Пути».",',
     '"Полный путь = она + строка.",',
     2, "правило разрешения путей написано"),
    ("забыть сказать про перекрытие строк",
     '        "Складывать строки нельзя: вложенная папка посчитана дважды.",',
     '        "Складывать строки можно.",',
     13, "в авточасти сказано, что строки перекрываются"),
]


def load(tmpdir: Path, text: str, name: str):
    """Кладёт текст как core.py и импортирует.

    Регистрация в sys.modules обязательна: иначе падает `@dataclass`.
    """
    path = tmpdir / f"{name}.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def fixture(root: Path) -> None:
    """Дерево из примера селфтеста: одна вложенная папка и два служебных файла."""
    (root / "знания" / "Деньги").mkdir(parents=True)
    (root / "знания" / "Деньги" / "вклад.md").write_text("x", encoding="utf-8")
    tech = root / "знания" / "Имущество" / "Техника"
    tech.mkdir(parents=True)
    (tech / "a.md").write_text("x", encoding="utf-8")
    (tech / "Глубже").mkdir(parents=True)
    (tech / "Глубже" / "b.md").write_text("x", encoding="utf-8")
    (tech / "_О-ПАПКЕ.md").write_text("пояснение", encoding="utf-8")
    (tech / "_подсказки-техника.md").write_text("указатель", encoding="utf-8")


def assertions(core, root: Path) -> list[tuple[int, str, bool]]:
    """Те же одиннадцать утверждений, что стоят в селфтесте, раздел 8ц-2."""
    kr = root / "знания"
    areas = core.build_knowledge_index(kr, "areas", "2026-10-05")
    child = core.build_knowledge_index(kr / "Имущество", "children", "2026-10-05")
    tree = core.build_knowledge_index(kr / "Имущество", "tree", "2026-10-05")
    again = core.build_knowledge_index(kr, "areas", "2026-10-05")
    import re as _re

    listed = _re.findall(r"^- `([^`]+)/`", tree, _re.M)
    return [
        (1, "корневой указатель перечисляет области",
         "`Деньги/`" in areas and "`Имущество/`" in areas),
        (2, "правило разрешения путей написано",
         "Полный путь = папка указателя + строка" in areas),
        (3, "маркеры именно те, о которых договорились",
         "<!-- == авточасть: дальше не редактировать руками -->" in areas
         and "<!-- == конец авточасти -->" in areas),
        (4, "scope=tree перечисляет поддерево", "`Техника/Глубже/`" in tree),
        (5, "scope=children не заходит глубже",
         "`Техника/`" in child and "`Техника/Глубже/`" not in child),
        (6, "путь не удваивается", "`Техника/Техника/`" not in child),
        (7, "children и tree различаются", child != tree),
        (8, "служебные файлы не попали в счёт", "- `Техника/` — 2 файла" in tree),
        (9, "сборка детерминирована", again == areas),
        (10, "число папок в авточасти верно", "Папок: 2" in areas),
        (11, "общее число файлов верно", "файлов: 3" in areas),
        (12, "пути идут по алфавиту", listed == sorted(listed)),
        (13, "в авточасти сказано, что строки перекрываются",
         "Складывать строки нельзя" in tree),
    ]


def main() -> int:
    original = CORE.read_text(encoding="utf-8")
    lines = ["=== откат раздела 8ц-2: машинная часть указателя ===", ""]
    ok = True

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        root = tmp / "дерево"
        fixture(root)

        base = assertions(load(tmp, original, "core_rb2_base"), root)
        lines.append("1. без поломок — все должны быть верны")
        for num, what, passed in base:
            lines.append(f"   проверка {num}: {'верно' if passed else 'ЛОЖЬ'}")
            if not passed:
                ok = False

        lines.append("")
        lines.append("2. каждая поломка обязана ломать свою проверку")
        for i, (what, good, bad, num, label) in enumerate(BREAKS):
            if good not in original:
                lines.append(f"   НЕЛЬЗЯ ДОКАЗАТЬ: нет строки «{what}» — "
                             "код изменился, скрипт устарел")
                ok = False
                continue
            root2 = tmp / f"дерево-{i}"
            fixture(root2)
            try:
                got = assertions(
                    load(tmp, original.replace(good, bad, 1), f"core_rb2_b{i}"),
                    root2)
            except Exception as exc:              # noqa: BLE001
                lines.append(f"   {what}: код не выполнился ({exc})")
                ok = False
                continue
            fired = {n for n, _w, p in got if not p}
            hit = num in fired
            if not hit:
                ok = False
            lines.append(f"   {what}: проверка {num} «{label}» — "
                         f"{'поймана' if hit else 'ПРОПУЩЕНА'}")
            lines.append(f"      сработавшие: {sorted(fired)}")

    lines.append("")
    lines.append(f"ИТОГ: {'откат доказан' if ok else 'ОТКАТ НЕ ДОКАЗАН'}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())