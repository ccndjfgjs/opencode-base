"""Проверки модуля редакторов и движков.

    python tools/dbapp/test_editor_plugins.py

Проверяется то, что можно проверить без установки программ: честность
отказов, работа с проектом-подделкой, откат и включение расширения Гидры.

Отказы проверяются на подставных папках, а не на том, что случайно стоит
на машине: 18.10.2026 на этой машине появились настоящие Unity и Roblox
Studio, и проверки, ожидавшие их отсутствия, стали врать — падали там, где
отказа быть не должно. Состояние машины теперь не влияет на результат.
"""

from __future__ import annotations

import json
import os
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
    import versions

    # Проверка не должна зависеть от прошлого прогона: временная папка
    # очищается целиком, иначе «плагина нет» окажется ложью на втором запуске.
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)

    # === 1. Честность отказа в обе стороны ===
    editors = ep.unity_editors()
    check(bool(editors.attempts),
          f"перечислено, где искали Unity: {len(editors.attempts)} мест")
    if editors.ok:
        check(editors.path.name == "Unity.exe"
              and editors.path.parent.name == "Editor"
              and bool(versions.version_tuple(editors.version)),
              f"найденная Unity названа верно: {editors.version}")
    else:
        why = editors.why("Unity")
        check("не найдена" in why, f"причина словами: {why}")

    engines = ep.unreal_engines()
    if engines.ok:
        check(engines.path.is_file(),
              f"движок Unreal найден верно: {engines.version}")
    else:
        check("не найдена" in engines.why("Unreal Engine"),
              f"движка Unreal нет — и сказано честно")

    # Редактор Unity, поставленный winget без хаба, лежит отдельной папкой
    # рядом с Program Files: «Unity <версия>\Editor\Unity.exe». Программа о
    # такой раскладке не знала и объявляла установленный редактор
    # ненайденным — а на этой машине он стоит именно так.
    fake_root = TMP / "program files"
    fake_exe = fake_root / "Unity 6000.6.6f1" / "Editor" / "Unity.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_text("", encoding="utf-8")
    (fake_root / "Unity Hub").mkdir(parents=True, exist_ok=True)
    (fake_root / "Unity 2023.2.1f1").mkdir(parents=True, exist_ok=True)
    standalone = ep.unity_standalone_editors([fake_root, fake_root / "нет-такой"])
    check(len(standalone) == 1 and standalone[0][0] == "6000.6.6f1",
          "редактор без хаба найден по своей раскладке: "
          f"{[item[0] for item in standalone]}")
    check(bool(standalone) and standalone[0][1] == fake_exe,
          "и путь у него верный — до самого Unity.exe")
    check(not ep.unity_standalone_editors([]),
          "а на пустой папке редактор не выдумывается")

    # Отказы проверяются на подставных папках: так «не найдено» остаётся
    # правдой независимо от того, что у человека стоит.
    saved_env = {key: os.environ.get(key) for key in
                 ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA",
                  "USERPROFILE")}
    empty_root = TMP / "пустая-машина"
    empty_root.mkdir(parents=True, exist_ok=True)
    os.environ["ProgramFiles"] = str(empty_root)
    os.environ["ProgramFiles(x86)"] = str(empty_root)
    os.environ["LOCALAPPDATA"] = str(empty_root)
    os.environ["USERPROFILE"] = str(empty_root)
    try:
        godot = ep.godot_editor()
        check(not godot.ok, "Godot не найден — и сказано честно")
        check("не найдена" in godot.why("Godot"),
              "и причина словами")
        roblox = ep.roblox_studio()
        check(not roblox.ok, "Roblox Studio не найден — и сказано честно")
        roblox_why = roblox.why("Roblox Studio")
        check("Roblox.RobloxStudio" in roblox_why,
              f"и назван идентификатор winget: {roblox_why}")
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # === 2. Поиск проектов Unity: программа сама находит и предлагает ===
    # Кнопка «Настроить автоматически» не должна требовать набирать путь
    # руками: человек выбирает проект из списка. Поиск ограничен известными
    # папками пользователя — весь диск не обходится никогда.
    scan_root = TMP / "сканирование"
    (scan_root / "проект-старый" / "Assets").mkdir(parents=True, exist_ok=True)
    (scan_root / "проект-старый" / "ProjectSettings").mkdir(parents=True, exist_ok=True)
    (scan_root / "проект-старый" / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.10f1\n", encoding="utf-8")
    (scan_root / "вложенный" / "игра" / "Assets").mkdir(parents=True, exist_ok=True)
    (scan_root / "вложенный" / "игра" / "ProjectSettings").mkdir(parents=True, exist_ok=True)
    (scan_root / "вложенный" / "игра" / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.6.6f1\n", encoding="utf-8")
    (scan_root / "не-проект" / "Assets").mkdir(parents=True, exist_ok=True)
    (scan_root / "мусор" / "Library").mkdir(parents=True, exist_ok=True)
    (scan_root / "мусор" / "Library" / "глубоко" / "Assets").mkdir(parents=True, exist_ok=True)

    scanned = ep.scan_unity_projects([scan_root])
    names = sorted(item[0].name for item in scanned.items)
    check(names == ["игра", "проект-старый"],
          f"найдены оба проекта, в том числе вложенный: {names}")
    found_versions = dict((item[0].name, item[1]) for item in scanned.items)
    check(found_versions.get("проект-старый") == "2022.3.10f1",
          f"версия старого проекта прочитана: {found_versions.get('проект-старый')}")
    check(found_versions.get("игра") == "6000.6.6f1",
          f"версия вложенного проекта прочитана: {found_versions.get('игра')}")
    check(not any(item[0].name == "не-проект" for item in scanned.items),
          "папка с одной только Assets проектом не считается")
    check(not any("глубоко" in str(item[0]) for item in scanned.items),
          "в мусорную папку Library поиск не лезет")
    check(not scanned.truncated, "маленький обход бюджет не исчерпал")
    # Бюджет папок: без него поиск по «Загрузкам» идёт полторы минуты, и
    # окно выглядит зависшим. Обрезанный поиск обязан об этом сказать.
    tiny = ep.scan_unity_projects([scan_root], budget=2)
    check(tiny.truncated, "обход ограничен бюджетом папок")
    check(tiny.visited <= 3,
          f"и бюджет не превышен: просмотрено папок {tiny.visited}")
    check(not ep.scan_unity_projects([scan_root / "нет-такой"]).items,
          "на несуществующей папке ничего не выдумывается")
    check(bool(ep.unity_project_roots()),
          f"указаны папки пользователя для поиска: {len(ep.unity_project_roots())}")

    # Поиск на настоящих папках пользователя обязан быть быстрым: он идёт
    # в окне, и 75 секунд — это окно, которое выглядит зависшим.
    import time as _time
    _start_real = _time.time()
    _real = ep.scan_unity_projects()
    _elapsed = _time.time() - _start_real
    check(_elapsed < 10.0,
          f"поиск по папкам пользователя уложился в { _elapsed:.1f} с "
          f"(просмотрено папок: {_real.visited}, найдено: {len(_real.items)})")

    # === 3. Версия из файла на настоящем файле машины ===
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

    # === 4б. Сервер и плагин — из одного релиза ===
    # В линии 0.6 сервер живёт внутри плагина, поэтому отдельной версии
    # сервера нет и сверять нечего: рассинхрон невозможен по построению.
    same_pair, note_pair = ep.enginewire_pair("5.7")
    check(same_pair, f"для движка 5.7 плагин годен: {note_pair}")
    no_pair, note_no = ep.enginewire_pair("4.27")
    check(not no_pair and "не попадает" in note_no,
          f"а для неподходящей версии — отказ с причиной: {note_no}")

    # === 4в. Живая проверка адреса: четыре причины — четыре ответа ===
    # Поддельный сервер поднимается на настоящем порту: иначе ветка «порт
    # отвечает» проверялась бы на слове, а не на поведении.
    import http.server
    import socket
    import threading

    def dead_port() -> tuple[socket.socket, int]:
        """Порт, на котором гарантированно никто не отвечает.

        Сокет остаётся занятым и НЕ слушает: подключиться к нему нельзя, и
        ответ «никто не слушает» получается всегда. Раньше порт брался
        свободным и сразу отпускался — за эти микросекунды его успевала
        занять чужая программа (на живой машине это случилось один раз из
        четырёх запусков), и проверка «порт молчит» становилась случайной.
        Мигающая проверка хуже её отсутствия: она раз за разом съедает
        время на выяснение, что именно сломалось.
        """
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        return sock, int(sock.getsockname()[1])

    def fake_server(handler_body: str, code: int):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — так в стандартной библиотеке
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(handler_body.encode("utf-8"))

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, int(server.server_address[1])

    holder, closed_port = dead_port()
    try:
        ok_closed, note_closed = ep.unreal_http_state(closed_port,
                                                      editor_running=False)
        check(not ok_closed and "не открыт" in note_closed,
              f"редактор закрыт — сказано про редактор, а не про порт: {note_closed}")
        ok_mute, note_mute = ep.unreal_http_state(closed_port,
                                                  editor_running=True)
        check(not ok_mute and "никто не слушает" in note_mute,
              f"редактор открыт, а порт молчит — сказано про плагин: {note_mute}")
    finally:
        holder.close()

    plain, plain_port = fake_server('{"hello":"world"}', 200)
    try:
        ok_plain, note_plain = ep.unreal_http_state(plain_port, editor_running=True)
        check(not ok_plain and "другой программой" in note_plain,
              f"порт отвечает, но не MCP — названа чужая программа: {note_plain}")
    finally:
        plain.shutdown()
        plain.server_close()

    mcp, mcp_port = fake_server(
        '{"jsonrpc":"2.0","error":{"code":-32000,"message":"session"}}', 400)
    try:
        ok_mcp, note_mcp = ep.unreal_http_state(mcp_port, editor_running=True)
        check(ok_mcp and "отвечает" in note_mcp,
              f"настоящий MCP-сервер опознан по jsonrpc в ответе: {note_mcp}")
    finally:
        mcp.shutdown()
        mcp.server_close()

    for bad in ("не число", 0, 70000):
        ok_bad, note_bad = ep.unreal_http_state(bad, editor_running=True)
        check(not ok_bad and "порт" in note_bad,
              f"битый порт {bad!r} отвергнут, а не превращён в адрес: {note_bad}")

    # === 4в. Программа знает версии каждого моста ===
    # Указатель — единственное место, где записано, что мосту нужно. Мосты
    # без указателя по существу (OBS, Blender, Roblox) молчат честно: сверять
    # нечего, и называть это проблемой было бы враньём.
    ok_u_v, note_u_v = ep.bridge_versions("unity")
    check(ok_u_v and "10.3.0" in note_u_v,
          f"для Unity названы обе версии: {note_u_v}")
    ok_un_v, note_un_v = ep.bridge_versions("unreal")
    check(ok_un_v and "0.6.0-beta-f" in note_un_v,
          f"и для Unreal — из одного релиза: {note_un_v}")
    ok_g_v, note_g_v = ep.bridge_versions("godot")
    check(ok_g_v and "4.3.0" in note_g_v, f"для Godot: {note_g_v}")
    ok_gh_v, note_gh_v = ep.bridge_versions("ghidra-mcp")
    check(ok_gh_v and "7.0.0-rc.3" in note_gh_v, f"для Ghidra: {note_gh_v}")
    ok_obs_v, note_obs_v = ep.bridge_versions("obs")
    check(ok_obs_v and ep.without_pointer("obs"),
          f"а у OBS указателя нет по существу: {note_obs_v[:60]}")
    unknown_ok, unknown_note = ep.bridge_versions("такого-моста")
    check("указателя плагинов нет" in unknown_note,
          f"незнакомый мост не выдумывает версий: {unknown_note[:60]}")
    check(ep.bridge_versions("unreal", "4.27")[0] is False,
          "а для неподходящей версии движка — отказ, а не «годится любой»")

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

    # === 7. Roblox: три состояния, каждое своим текстом ===
    # Проверяются все три и на подставных папках: 18.10.2026 на этой машине
    # студия стоит и сервер в ней включён, поэтому проверка, ждавшая «студии
    # нет», падала. Состояние машины не должно решать за проверку.
    fake_local = TMP / "роблокс"
    fake_roblox = fake_local / "Roblox"
    (fake_roblox / "Versions" / "version-тест").mkdir(parents=True, exist_ok=True)
    (fake_roblox / "Versions" / "version-тест" / "RobloxStudioBeta.exe").write_text(
        "", encoding="utf-8")
    # Версия читается из свойств файла, а у подставки их нет. Подменяем
    # только её — поиск и логика остаются настоящими.
    saved_ver = ep.file_version
    ep.file_version = lambda path: "0.743.383.25553"
    saved_local = os.environ.get("LOCALAPPDATA")
    saved_pf86 = os.environ.get("ProgramFiles(x86)")
    try:
        os.environ["LOCALAPPDATA"] = str(TMP / "роблокс-нет-студии")
        os.environ["ProgramFiles(x86)"] = str(TMP / "роблокс-нет-студии")
        ok12, note12 = ep.roblox_mcp_state()
        check(not ok12, "студии нет — встроенный сервер выключен")
        # Студии нет — честный ответ обязан называть, чем она ставится.
        check("Roblox.RobloxStudio" in note12 or "Manage MCP Servers" in note12,
              f"и сказано, что делать: {note12}")
        check("не установлена" in note12,
              "и сказано прямо, что студия не установлена")
        check("поставлю" not in note12.lower() and "установлю" not in note12.lower(),
              "обещания поставить галочку в чужом окне нет")

        # Студия стоит, сервер в ней ещё не включён: ответ обязан называть
        # два клика в студии.
        os.environ["LOCALAPPDATA"] = str(fake_local)
        os.environ["ProgramFiles(x86)"] = str(TMP / "роблокс-нет-студии")
        ok13, note13 = ep.roblox_mcp_state()
        check(not ok13, "студия есть, но файл запуска ещё не создан")
        check("mcp.bat" in note13 and "Manage MCP Servers" in note13,
              f"и сказано, что делать дальше: {note13}")
        check("поставлю" not in note13.lower() and "установлю" not in note13.lower(),
              "и здесь обещаний поставить чужую галочку нет")

        # Студия стоит и сервер включён — единственное состояние «готово».
        (fake_roblox / "mcp.bat").write_text("@echo off\n", encoding="utf-8")
        ok14, note14 = ep.roblox_mcp_state()
        check(ok14 and "включён" in note14,
              f"файл запуска на месте — состояние «готово»: {note14}")
        check("поставлю" not in note14.lower() and "установлю" not in note14.lower(),
              "и даже тут обещаний поставить чужую галочку нет")
    finally:
        ep.file_version = saved_ver
        for key, value in (("LOCALAPPDATA", saved_local),
                           ("ProgramFiles(x86)", saved_pf86)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())