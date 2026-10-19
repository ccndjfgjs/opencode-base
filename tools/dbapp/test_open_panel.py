"""Кнопка «Открыть» у моста OmniRoute: и в окне, и в трее.

Запуск: python tools/dbapp/test_open_panel.py

Что тут проверяется. 19.10.2026 OmniRoute поднимает локальный веб-сайт —
панель на `http://127.0.0.1:20128` — но открыть его из программы было
нечем: ни в строке реестра, ни в панели трея. Человек шёл искать адрес
вручную, хотя программа знает его лучше него: адрес напечатан в
подробностях строки.

Три требования, и все три из-за разных причин.

1. **Открывать надо только живой панель.** Кнопка «Открыть» при
   выключенном сервере откроет страницу с ошибкой подключения — и
   человек решит, что программа сломалась. Поэтому сначала живой
   запрос `GET /api/health`, и только потом открытие.
2. **Адрес — один на всё.** И кнопка в окне, и кнопка в трее берут
   его из одной функции. Два адреса в двух местах разъедутся при
   первом же изменении порта.
3. **Открывает вид, а не модуль моста.** `webbrowser.open` на Windows
   запускает внешнюю программу, а программа работает на pythonw — и
   на экране снова появилось бы чёрное окно. Поэтому открывает
   `QDesktopServices`, он системный и без окна.

Проверка работает с настоящими модулями. Браузер она не открывает:
проверяется решение функции, а не запуск браузера на машине человека.
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import omniroute  # noqa: E402
import ui  # noqa: E402

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


def _source(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def need(obj, name: str):
    """Взять функцию или честно записать провал и вернуть None.

    Без этого проверка падала бы с AttributeError на первой же
    недостающей функции, и остальные проверки не дошли бы — а именно
    они показывают, чего не хватает СРАЗУ, а не по одному.
    """
    value = getattr(obj, name, None)
    check(value is not None, f"у {getattr(obj, '__name__', obj)} есть {name}")
    return value


def main() -> int:
    # --- 1. адрес один и собран из порта, а не написан строкой
    panel_url = need(omniroute, "panel_url")
    if panel_url is not None:
        url = panel_url()
        check(url == f"http://{omniroute.DEFAULT_HOST}:{omniroute.DEFAULT_PORT}",
              f"адрес панели собирается из порта по умолчанию: {url}")

    # --- 2. открывать можно только живое: при мёртвом сервере — отказ
    # Подменяем именно ту функцию, на которой стоит решение. Временная
    # папка тут не годится: `health()` ходит по живому порту и временный
    # каталог на это не влияет — первая версия проверки так и делала,
    # и «выключенный сервер» отвечал «панель готова».
    panel_ready = need(omniroute, "panel_ready")
    if panel_ready is not None:
        was_health = omniroute.health
        was_deployed = omniroute.deployed
        try:
            omniroute.health = lambda *a, **k: (
                False, {}, "API OmniRoute не ответил: подставная проверка")
            omniroute.deployed = lambda: True
            ok, note = panel_ready(Path("нет-такой-папки"))
        finally:
            omniroute.health = was_health
            omniroute.deployed = was_deployed
        check(not ok, f"при выключенном сервере панель не открывается: {note[:80]}")
        check(bool(note),
              "и сказано почему — без причины отказ читается как поломка")
        check("Запустить" in note or "Запустить" in note,
              f"и сказано, что делать, а не только что сломано: {note[:110]}")

        try:
            omniroute.deployed = lambda: False
            ok2, note2 = panel_ready(Path("нет-такой-папки"))
        finally:
            omniroute.deployed = was_deployed
        check(not ok2 and "Развернуть" in note2,
              f"при неразвёрнутом мосте сказано про «Развернуть»: {note2[:90]}")

    # --- 3. живой сервер — панель готова
    dest = omniroute.find_settings_dir()
    if panel_ready is not None and omniroute.deployed():
        ok, note = panel_ready(dest)
        check(ok, f"при живом сервере панель готова: {note[:90]}")

    # --- 4. открывает вид, а не webbrowser (иначе будет чёрное окно)
    check(hasattr(ui, "open_link"),
          "в ui есть общая функция открытия ссылки open_link")
    ui_src = _source(Path(ui.__file__))
    check("QDesktopServices" in ui_src,
          "она открывает через QDesktopServices")
    tree = ast.parse(ui_src)
    # Ищем ЗОВОН, а не слово: «webbrowser» есть в самом пояснении, почему
    # его не берут. Первая версия проверки искала подстроку и объявила
    # враньём собственный комментарий.
    webbrowser_calls = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "webbrowser"]
    webbrowser_import = "import webbrowser" in ui_src
    check(not webbrowser_import and not webbrowser_calls,
          "и не через webbrowser: тот запускает внешнюю программу, "
          "а на pythonw это чёрное окно")
    url_arg = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "open_link":
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                url_arg = arg.arg
    check(url_arg is not None,
          "функция принимает адрес, а не ходит куда-то сама")
    # Адрес проверяется ДО передачи: QDesktopServices откроет что угодно,
    # включая file:// и javascript:.
    check("http://" in ui_src and "https://" in ui_src
          and "startswith" in ui_src,
          "и проверяет схему адреса до открытия")

    # --- 5. кнопка в окне: создана, подписана и подключена
    main_src = _source(HERE / "main.py")
    for needle in ("btn_or_open", 'QPushButton("Открыть панель")'):
        check(needle in main_src, f"в main.py есть {needle}")
    tree = ast.parse(main_src)
    connected = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and isinstance(node.func.value, ast.Attribute)):
            continue
        owner = node.func.value.value
        if (isinstance(owner, ast.Attribute)
                and owner.attr == "btn_or_open"):
            connected = True
    check(connected, "кнопка подключена к своему обработчику")
    handler = "def _or_open_panel" in main_src
    check(handler, "и обработчик у неё свой — _or_open_panel")
    check("ui.open_link" in main_src,
          "и открывает видом (ui.open_link), а не webbrowser")
    gated = "self.btn_or_open.setEnabled(is_or)" in main_src
    check(gated, "и гасится у чужих строк — как остальные кнопки моста")

    # --- 6. кнопка в трее: действие есть у строки OmniRoute
    tray_src = _source(HERE / "tray_panel.py")
    check("def _open_server_panel" in tray_src,
          "в панели трея есть общий обработчик открытия панели моста")
    check("import omniroute" in tray_src,
          "и он берёт адрес у того же модуля моста, а не пишет свой")
    check("_open_server_panel" in tray_src
          and '"Открыть"' in tray_src,
          "у строки моста появляется кнопка «Открыть»")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())