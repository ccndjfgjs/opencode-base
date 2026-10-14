"""Четыре комбинации Obsidian и агента. Окно и сеть не нужны.

    python tools/dbapp/test_obsidian_base.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import obsidian_base as obs  # noqa: E402


def check(ok: bool, text: str) -> None:
    print(("  ok  " if ok else "  FAIL  ") + text)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="obsidian-base-"))
    parent = root / "место"
    parent.mkdir()

    plan = core.build_plan(parent, "Как-раньше", None)
    core.create_base(plan)
    check(not (plan.target / "Главная.md").exists(), "без переключателей Главная.md не появляется")
    check(not (plan.target / "tools" / "agents" / "obsidian.md").exists(),
          "без переключателя агент в базу не кладётся")
    kept = (plan.target / "facts.md").read_text(encoding="utf-8")

    notes, errors = obs.apply(plan.target, obsidian=False, agent=False)
    check(not errors and "как раньше" in notes[0], "оба выключены ничего не пишут")
    check((plan.target / "facts.md").read_text(encoding="utf-8") == kept,
          "выключенные переключатели не трогают факты")

    only_plan = core.build_plan(parent, "Только-хранилище", None)
    only_vault = only_plan.target
    core.create_base(only_plan)
    user_note = only_vault / "Своя.md"
    user_note.write_text("не трогать\n", encoding="utf-8")
    notes, errors = obs.apply(only_vault, obsidian=True, agent=False)
    check(not errors, "хранилище без ошибок")
    check((only_vault / "Главная.md").is_file(), "Главная.md создана")
    check("[[КАРТА-БАЗЫ]]" in (only_vault / "Главная.md").read_text(encoding="utf-8"),
          "в главной есть ссылка Obsidian")
    check(user_note.read_text(encoding="utf-8") == "не трогать\n", "своя заметка не перезаписана")
    before = (only_vault / "Главная.md").read_text(encoding="utf-8")
    notes, errors = obs.apply(only_vault, obsidian=True, agent=False)
    check("не перезаписываю" in " ".join(notes), "повтор не затирает Главную")
    check((only_vault / "Главная.md").read_text(encoding="utf-8") == before,
          "текст Главной остался прежним")
    check(not (only_vault / "tools" / "agents" / "obsidian.md").exists(),
          "только хранилище агента не подключает")

    agent_plan = core.build_plan(parent, "Только-агент", None)
    only_agent = agent_plan.target
    core.create_base(agent_plan)
    notes, errors = obs.apply(only_agent, obsidian=False, agent=True)
    check(not errors, "агент без ошибок")
    agent_file = only_agent / ".opencode" / "agents" / "obsidian.md"
    check(agent_file.is_file(), "агент лежит в .opencode/agents этой базы")
    check("edit: ask" in agent_file.read_text(encoding="utf-8"),
          "правка только со спросом")
    check("bash: deny" in agent_file.read_text(encoding="utf-8"),
          "команды агенту запрещены")
    check(not (only_agent / "Главная.md").exists(), "только агент Главную не создаёт")
    check(obs.AGENT_MARK in (only_agent / "AGENTS.md").read_text(encoding="utf-8"),
          "в конец правил добавлена пометка")
    old_rules = (only_agent / "AGENTS.md").read_text(encoding="utf-8")
    notes, errors = obs.apply(only_agent, obsidian=False, agent=True)
    check((only_agent / "AGENTS.md").read_text(encoding="utf-8") == old_rules,
          "повторное подключение правила не дублирует")

    both_plan = core.build_plan(parent, "Оба", None)
    both = both_plan.target
    core.create_base(both_plan)
    notes, errors = obs.apply(both, obsidian=True, agent=True)
    check(not errors, "обе опции без ошибок")
    check((both / "Главная.md").is_file()
          and (both / ".opencode" / "agents" / "obsidian.md").is_file(),
          "вместе есть и заметка, и агент")

    name = "Моя база"
    uri = obs.open_uri(name)
    check(uri.startswith("obsidian://open?vault="), "адрес официальной схемы")
    check(" " not in uri and "Моя" not in uri, "пробелы и буквы в адресе закодированы")
    check(";" not in uri and "&file" not in uri, "в адрес не подмешана команда")

    config = root / "obsidian.json"
    config.write_text(json.dumps({"vaults": {"old": {"path": "C:/чужое", "ts": 1}}}), encoding="utf-8")
    ok, note = obs.register_vault(both, config)
    check(ok and "old" in json.loads(config.read_text(encoding="utf-8"))["vaults"],
          "чужое хранилище осталось")
    check((config.parent / "obsidian.json.bak-opencode").is_file(), "перед записью есть копия")
    ok, note = obs.register_vault(both, config)
    vaults = json.loads(config.read_text(encoding="utf-8"))["vaults"]
    check(ok and len(vaults) == 2, "повтор не плодит записи")
    broken = root / "битый.json"
    broken.write_text("{", encoding="utf-8")
    ok, note = obs.register_vault(both, broken)
    check(not ok and broken.read_text(encoding="utf-8") == "{", "битый файл Obsidian не переписан")

    opened: list[str] = []
    ok, note = obs.open_vault(both, config, opener=opened.append)
    check(ok and opened and opened[0].startswith("obsidian://open?vault="),
          "открытие уходит адресом, не командой оболочки")
    check("не проверялся" in note, "живой ответ Obsidian не объявлен")

    empty = root / "нет-obsidian"
    ok, note = obs.open_vault(empty)
    check(not ok and "не найден" in note.lower() or "Папки нет" in note,
          "без папки или без программы открытие отказывает")

    prefs = root / "программа"
    obs.save_prefs(True, False, prefs)
    check(obs.load_prefs(prefs) == (True, False), "переключатели читаются обратно")
    (prefs / "данные" / obs.PREFS_NAME).write_text("{", encoding="utf-8")
    check(obs.load_prefs(prefs) == (False, False), "битые настройки не включают опции")

    custom = root / "свой-агент.md"
    custom.write_text("свой\n", encoding="utf-8")
    dest = root / "opencode"
    (dest / "agents").mkdir(parents=True)
    (dest / "agents" / "obsidian.md").write_text("свой\n", encoding="utf-8")
    ok, note = obs.place_agent_in_opencode(dest, obs.agent_source())
    check(not ok and (dest / "agents" / "obsidian.md").read_text(encoding="utf-8") == "свой\n",
          "чужой файл агента в OpenCode не затирается")

    print("obsidian: проверки прошли")


if __name__ == "__main__":
    main()
