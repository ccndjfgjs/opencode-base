"""Проверки модуля редакторов и движков.

    python tools/dbapp/test_editor_plugins.py

Проверяется то, что можно проверить без установки программ: честность
отказов, работа с проектом-подделкой, откат и включение расширения Гидры.
Живые программы (Unity, Unreal, Godot, Roblox) на этой машине не стоят, и
проверка обязана это сказать, а не сделать вид, что всё на месте.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import editor_plugins as ep  # noqa: E402

passed = 0
failed = 0
TMP = Path(tempfile.gettempdir()) / "opencode" / "проверка-редакторов"


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


def fake_unity_project() -> Path:
    project = TMP / "проект-unity"
    (project / "Assets").mkdir(parents=True, exist_ok=True)
    (project / "ProjectSettings").mkdir(parents=True, exist_ok=True)
    (project / "Packages").mkdir(parents=True, exist_ok=True)
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.0.35f1\nm_EditorVersionWithRevision: 6000.0.35f1 (abcdef)\n",
        encoding="utf-8")
    (project / "Packages" / "manifest.json").write_text(
        json.dumps({"dependencies": {"com.unity.ide.rider": "3.0.0"},
                    "testables": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return project


def fake_unreal_project() -> Path:
    project = TMP / "проект-unreal"
    (project / "Content").mkdir(parents=True, exist_ok=True)
    (project / "MyGame.uproject").write_text("{}", encoding="utf-8")
    return project


def fake_ghidra() -> Path:
    install = TMP / "гидра-12.1.4"
    (install / "Ghidra").mkdir(parents=True, exist_ok=True)
    (install / "Ghidra" / "application.properties").write_text(
        "application.name=Ghidra\napplication.version=12.1.4\n", encoding="utf-8")
    (install / "Extensions" / "Ghidra").mkdir(parents=True, exist_ok=True)
    profile = TMP / "профиль" / "ghidra_12.1.4_PUBLIC"
    profile.mkdir(parents=True, exist_ok=True)
    return install


def main() -> int:
    import plugin_index
    import shutil

    # Проверка не должна зависеть от прошлого прогона: временная папка
    # очищается целиком, иначе «плагина нет» окажется ложью на втором запуске.
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)

    # === 1. Честные отказы там, где программы нет ===
    editors = ep.unity_editors()
    check(not editors.ok, "Unity на машине нет — и сказано честно")
    check(bool(editors.attempts), f"и перечислено, где искали: {len(editors.attempts)} мест")
    why = editors.why("Unity")
    check("не найдена" in why, f"причина словами: {why}")

    engines = ep.unreal_engines()
    check(not engines.ok, "движка Unreal на машине нет")

    godot = ep.godot_editor()
    check(not godot.ok, "Godot на машине нет")

    roblox = ep.roblox_studio()
    check(not roblox.ok, "Roblox Studio на машине нет (есть только Player)")
    roblox_why = roblox.why("Roblox Studio")
    check("Roblox.RobloxStudio" in roblox_why,
          f"и назван идентификатор winget: {roblox_why}")

    # === 2. Версия из файла на настоящем файле машины ===
    installer = (Path.home() / "AppData" / "Local" / "Roblox" / "Versions"
                 / "RobloxStudioInstaller.exe")
    if installer.is_file():
        got = ep.file_version(installer)
        check(got.startswith("1.6.3"),
              f"версия Roblox-установщика снята со свойств файла: {got}")
    else:
        check(True, "установщика Roblox на диске нет — версию снимать не с чего")

    # === 3. Проект Unity: пакет ставится один раз и с копией файла ===
    project = fake_unity_project()
    ok, note = ep.unity_package_state(project)
    check(not ok and "com.coplaydev.unity-mcp" in note,
          f"без пакета состояние честное: {note}")
    plugin, why2 = plugin_index.pick_for("unity-mcp",
                                         ep.unity_project_version(project))
    check(plugin is not None, f"под 6000.0.35f1 плагин выбран: {why2}")
    check(plugin is not None and plugin.manifest_entry == "com.coplaydev.unity-mcp",
          "пакет назван правильно")
    check(plugin is not None and "#v10.3.0" in plugin.url,
          f"метка релиза закреплена: {plugin.url if plugin else ''}")
    if plugin is not None:
        ok2, note2 = ep.install_unity_package(project, plugin)
        if ok2:
            check(True, f"пакет прописан: {note2}")
        else:
            # Редактор открыт — это честный отказ, а не ошибка.
            check("открыт" in note2.lower() or "не читается" in note2.lower()
                  or "уже прописан" in note2.lower(),
                  f"отказ назван прямо: {note2}")
        data = json.loads((project / "Packages" / "manifest.json")
                          .read_text(encoding="utf-8"))
        present = "com.coplaydev.unity-mcp" in data.get("dependencies", {})
        check(present == bool(ok2),
              f"manifest.json соответствует сказанному (прописан={present}, ок={ok2})")
        check((project / "Packages" / "manifest.json.opencode-base.bak").is_file()
              if ok2 else True,
              "копия manifest.json сделана до правки")

    not_project = TMP / "не-проект"
    not_project.mkdir(parents=True, exist_ok=True)
    ok3, note3 = ep.unity_package_state(not_project)
    check(not ok3 and "Assets" in note3, f"чужая папка названа не проектом: {note3}")

    # === 4. Проект Unreal: плагина нет, а «5.4» в указатель не попадает ===
    up = fake_unreal_project()
    ok4, note4 = ep.enginewire_state(up)
    check(not ok4 and "EngineWire" in note4, f"без плагина честно: {note4}")
    old, why5 = plugin_index.pick_for("enginewire", "4.27")
    check(old is None, "движок ниже 5.0 не получает плагин молча")
    check("4.27" in why5, f"и сказано, какая версия не подошла: {why5}")

    # === 5. Godot: версия ниже нижней границы отказывает до сети ===
    gp = TMP / "проект-godot"
    gp.mkdir(parents=True, exist_ok=True)
    (gp / "project.godot").write_text("[application]\n", encoding="utf-8")
    ok5, note5 = ep.godot_addon_state(gp)
    check(not ok5 and "addons/godot_ai" in note5, f"аддона нет — честно: {note5}")
    (gp / "addons" / "godot_ai").mkdir(parents=True, exist_ok=True)
    (gp / "addons" / "godot_ai" / "plugin.cfg").write_text(
        "[plugin]\nname=\"Godot AI\"\nversion=\"4.3.0\"\n", encoding="utf-8")
    ok6, note6 = ep.godot_addon_state(gp)
    check(ok6, f"аддон найден: {note6}")
    ok7, note7 = ep.install_godot_addon(gp, "4.5")
    check(not ok7 and "не попадает" in note7,
          f"Godot 4.5 отказан до скачивания: {note7}")

    # === 6. Ghidra: версия снимается, включение патчит файл с копией ===
    install = fake_ghidra()
    version = ep.ghidra_version(install)
    check(version == "12.1.4", f"версия Гидры снята из её файла: {version}")
    ok8, note8 = ep.ghidra_extension_state(install)
    check(not ok8 and "расширени" in note8.lower(), f"расширения нет — честно: {note8}")
    profile = ep.ghidra_profile(install)
    check(profile.name == "ghidra_12.1.4_PUBLIC", f"профиль найден: {profile.name}")
    front = profile / "FrontEndTool.xml"
    front.write_text("<TOOL>\n  <PACKAGE NAME=\"Base\"/>\n</TOOL>\n", encoding="utf-8")
    ok9, note9 = ep.enable_ghidra_extension(install)
    check(ok9, f"расширение включено: {note9}")
    check(ep.GHIDRA_EXTENSION_CLASS in front.read_text(encoding="utf-8"),
          "класс плагина попал в FrontEndTool.xml")
    check(front.with_suffix(".xml.opencode-base.bak").is_file(),
          "копия файла настроек сделана")
    backup_text = front.with_suffix(".xml.opencode-base.bak").read_text(encoding="utf-8")
    check(ep.GHIDRA_EXTENSION_CLASS not in backup_text,
          "в копии плагина нет — копия снята ДО правки")
    ok10, note10 = ep.enable_ghidra_extension(install)
    check(ok10 and "уже включено" in note10, f"повтор не ломает: {note10}")

    (profile / "Extensions" / "GhidraMCP").mkdir(parents=True, exist_ok=True)
    front.write_text("<TOOL>\n</TOOL>\n", encoding="utf-8")
    ok11, note11 = ep.ghidra_extension_state(install)
    check(not ok11 and "не включено" in note11, f"лежащий без включения — честно: {note11}")

    # === 7. Roblox: потолок назван словами, обещания установки нет ===
    ok12, note12 = ep.roblox_mcp_state()
    check(not ok12, "встроенный сервер Roblox выключен")
    # Студии нет — честный ответ обязан называть, чем она ставится.
    # Если студия есть, ответ обязан называть два клика в студии.
    check("Roblox.RobloxStudio" in note12 or "Manage MCP Servers" in note12,
          f"и сказано, что делать: {note12}")
    check("окне студии" in note12,
          "и сказано, что включение живёт в окне студии")
    check("поставлю" not in note12.lower() and "установлю" not in note12.lower(),
          "обещания поставить галочку в чужом окне нет")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())