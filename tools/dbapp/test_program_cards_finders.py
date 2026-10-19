"""Проверки состояния карточек, которые знает собственный поисковик.

Запуск: python tools/dbapp/test_program_cards_finders.py

О чём речь. Состояние программы на карточке считалось по требованиям
реестра, и только по двум их видам — `program` и `command`. Программы,
которые ставятся папкой и не имеют записи в реестре Windows и команды
в PATH, туда не попадали: Гидра, Unity, Godot, Roblox Studio. Поисковики
для них написаны и работают, но карточка их не спрашивала — и говорила
«нечем проверять» вместо правды.

Три правила, которые проверка защищает:

1. **«Найдена» и «работает» — разные вещи.** Поисковик отвечает только
   на вопрос, лежит ли программа на диске. Требование плагина остаётся
   отдельным и не зеленеет вместе с карточкой.
2. **Нет поисковика — остаётся честное «нечем проверять».** Придумывать
   проверку там, где её нет, хуже, чем сказать, что её нет.
3. **Поисковик не всегда отвечает «найдено».** На это отдельная
   проверка: сказав «найдено», поисковик обязан показать путь, который
   действительно есть на диске.

Проверка идёт и на настоящем реестре: карточка с поисковиком обязана
давать определённый ответ (установлена или не установлена), а не
«нечем проверять». Это верно и на машине без Гидры.
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


class _Answer:
    """Ответ поисковика: нашлось или нет, и почему."""

    def __init__(self, path, version="", note=""):
        self.path = path
        self.version = version
        self.note = note

    @property
    def ok(self) -> bool:
        return bool(self.path)

    def why(self, what: str) -> str:
        if self.ok:
            return f"{what}: {self.version}" if self.version else f"{what} найдена"
        return self.note or f"{what} не найдена"


def draft(name: str) -> pc._Draft:
    """Карточка программы, у которой в реестре нет проверки."""
    return pc._Draft(name=name, servers=[],
                     install=programs.InstallView(action="manual"))


def main() -> int:
    # --- правило 3 и 1: найденная программа -------------------------------
    found = {"Гидра тестовая": lambda: _Answer(
        r"C:\путь\Ghidra12", "12.1.4")}
    state = pc._state(draft("Гидра тестовая"), {}, finders=found)
    check(state.state == pc.STATE_OK and state.status == "установлена",
          f"программа, которую нашли, показана установленной: "
          f"{state.state} / {state.status}")
    check("12.1.4" in state.text,
          f"и версия названа: {state.text}")

    # --- правило 3: не найденная программа --------------------------------
    missing = {"Гидра тестовая": lambda: _Answer(
        None, note="Гидра не найдена. Искала: Загрузки, Рабочий стол.")}
    state = pc._state(draft("Гидра тестовая"), {}, finders=missing)
    check(state.state == pc.STATE_MISSING and state.status == "не установлена",
          f"программа, которой нет, показана не установленной: "
          f"{state.state} / {state.status}")
    check("Искала" in state.text,
          f"и сказано, где искали: {state.text}")

    # --- правило 2: поисковика нет ----------------------------------------
    state = pc._state(draft("TikTok"), {}, finders=found)
    check(state.status == "нечем проверять",
          f"без поисковика остаётся честное «нечем проверять»: "
          f"{state.status}")
    check(pc.finder_answer("TikTok") is None,
          "и поисковик не выдумывается для программы, которой нет")

    # --- правило 1: карточка не зеленеет мост -----------------------------
    # Требование плагина у сервера — ручное и не выполнено. Оно обязано
    # остаться в pending, когда программа найдена: зелёная карточка при
    # красном плагине это ровно то враньё, о котором речь.
    class _Req:
        kind = "manual"
        ok = False
        what = "плагин GhidraMCP включён"
        blocks = False

    class _Server:
        requirements = (_Req(),)

    class _ServerDraft(pc._Draft):
        pass

    # install задан явно: у пустой карточки он ACTION_NONE, и проверка
    # ушла бы в ветку «не нужна», а не в состояние программы.
    with_plugin = pc._Draft(name="Гидра тестовая", servers=["ghidra-mcp"],
                            install=programs.InstallView(action="manual"))
    state = pc._state(with_plugin, {"ghidra-mcp": _Server()},
                      finders=found)
    check(state.state == pc.STATE_OK,
          f"программа найдена — карточка зелёная: {state.state}")
    check("плагин GhidraMCP" in " ".join(state.pending),
          f"а требование плагина осталось отдельным и не выполненным: "
          f"{state.pending}")

    # --- настоящий реестр: ответ определённый ----------------------------
    cards = {card.name: card for card in
             pc.cards(PROGRAM_ROOT)}
    for name in ("Ghidra", "Godot", "Roblox Studio"):
        card = cards.get(name)
        if card is None:
            check(False, f"карточка «{name}» есть во вкладке")
            continue
        check(card.state != pc.STATE_UNKNOWN,
              f"карточка «{name}» больше не «нечем проверять»: "
              f"{card.state} / {card.status}")

    # --- настоящие поисковики не всегда отвечают «найдено» ---------------
    lie = [name for name, run in pc.PROGRAM_FINDERS.items()
           if run().ok and not Path(str(run().path)).exists()]
    check(not lie,
          f"поисковик не отвечает «найдено» без файла на диске: "
          f"{lie or 'правда'}")

    # На этой машине Гидра стоит, и это должно быть видно версией, а не
    # словом «нечем проверять». Проверка честная на любой машине: если
    # Гидры нет, состояние будет «не установлена», и это тоже верно.
    ghidra = cards.get("Ghidra")
    if ghidra is not None:
        check(ghidra.state in (pc.STATE_OK, pc.STATE_MISSING),
              f"состояние Гидры определённое, а не неизвестное: "
              f"{ghidra.state}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())