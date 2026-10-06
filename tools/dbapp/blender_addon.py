# -*- coding: utf-8 -*-
"""Аддон MCP for Blender: найти, поставить, честно сказать о результате.

Модуль отвечает на три вопроса, и порядок именно такой:

1. **есть ли аддон** — по папке, которую Blender называет своей;
2. **можно ли его поставить** — пробой записи в эту папку;
3. **что будет после установки** — и тут ответ не «готово».

**Почему ответ не «готово».** Файл аддона кладётся автоматически, а
включается вручную: Правки -> Настройки -> Аддоны -> `Interface: MCP for
Blender`. Ни одна команда этого не делает, потому что список включённых
аддонов Blender хранит у себя и перезаписывает при выходе. Поэтому
программа обещает ровно половину и говорит, какую: «файл положен,
осталось включить руками».

**Откуда взялась папка аддонов.** Не вычислена, а измерена: Blender сам
назвал её, когда его спросили без окна.

    blender.exe -b --python-expr \\
      "import bpy; print(bpy.utils.user_resource('SCRIPTS', path='addons'))"

    -> C:\\Users\\...\\AppData\\Roaming\\Blender Foundation\\Blender\\5.2\\scripts\\addons

Измерено 06.10.2026 на Blender 5.2.2 LTS. Имя папки содержит номер
версии, поэтому оно вычисляется из папки установки: `Blender 5.2` ->
`5.2`. Проверка 8ф в селфтесте сверяет вычисленный путь с тем, что
назвал сам Blender, — иначе расхождение всплыло бы только при первой
установке, то есть у человека, а не у нас.

**Две дороги установки, и обе честно названы.**

* `uvx mcp-for-blender install-addon` — команда самого проекта. Она
  копирует `blender_mcp.py` и печатает, куда записала.
* прямой файл `addon.py` из репозитория проекта — README называет это
  поддерживаемым запасным способом.

Дорога выбирается не по вкусу, а по тому, что реально работает: на этой
машине команда проекта падает ещё на выборе интерпретатора, и если бы мы
молча перешли на запасную, человек увидел бы «поставлено» и не узнал бы,
что официальная команда не работает. Поэтому выбор записан в реестре
полем `fallback`, а не зашит в код.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

#: Куда Blender себя кладёт. Тот же шаблон живёт в реестре, в строке
#: `check` требования Blender; проверка сверяет, чтобы они не разошлись.
BLENDER_PATTERN = (r"C:\Program Files\Blender Foundation"
                   r"\Blender *\blender.exe")

#: Имя файла аддона. Именно это имя ждёт Blender в папке аддонов.
ADDON_FILE = "blender_mcp.py"

#: Откуда берём запасной файл. Ветка проекта — `main`, как в README.
ADDON_URL = ("https://raw.githubusercontent.com/ahujasid/"
             "mcp-for-blender/main/addon.py")

#: Команда проекта. `--python 3.11` и only-managed — из README: uv не
#: должен хватать чужой Python из conda или pyenv, с которыми он
#: несовместим.
PACKAGE = "mcp-for-blender"
INSTALL_ARGS = ("--python", "3.11", PACKAGE, "install-addon")
INSTALL_TIMEOUT = 900
MAX_ADDON_BYTES = 8 * 1024 * 1024

#: Куда Blender пишет папку пользовательских настроек.
USER_ROOT = Path.home() / "AppData" / "Roaming" / "Blender Foundation"


def blender_exe() -> Path | None:
    """Путь к blender.exe или None. Ищет по шаблону: папка версионирована."""
    import mcp_registry  # noqa: PLC0415 - тяжёлый модуль, нужен в одном месте

    found = mcp_registry.find_program(BLENDER_PATTERN)
    return Path(found) if found else None


def blender_version_line(exe: Path) -> str:
    """Строка версии из имени папки установки: `Blender 5.2` -> `5.2`.

    Не запускаем Blender ради этого: он стартует секунд десять, а карточка
    перерисовывается целиком при каждом щелчке. Настоящая проверка версии
    живьём — отдельная задача этапа 11, и она не должна висеть на пути к
    отрисовке карточек.
    """
    tail = exe.parent.name.replace("Blender", "").strip()
    return tail or "0"


def addon_dir(exe: Path) -> Path:
    """Папка аддонов Blender: та, что назвал сам Blender.

    Путь воспроизводится из измеренного, а не ищется заново: на машине без
    запущенного Blender папки ещё нет, и «искать» значило бы не найти
    ничего и сказать «ставить некуда» — в то время как место есть и
    принадлежит пользователю.
    """
    return (USER_ROOT / "Blender" / blender_version_line(exe) / "scripts"
            / "addons")


def addon_file(exe: Path) -> Path:
    return addon_dir(exe) / ADDON_FILE


def can_write_addons(folder: Path) -> tuple[bool, str]:
    """Проба записи в папку аддонов. Настоящая попытка, а не права.

    Папка принадлежит пользователю, и права администратора тут не нужны.
    Но «должна быть» — не проверка: папки может не быть вовсе, а может
    оказаться, что каталог закрыт политикой. Проба стоит миллисекунды и
    отвечает заранее, до скачивания.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"папку аддонов создать нельзя: {exc}"
    probe = folder / ".проба-записи"
    try:
        probe.write_bytes(b"")
    except OSError as exc:
        return False, f"в папку аддонов не записать: {exc}"
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
    return True, ""


def _run_installer(progress=None) -> tuple[int, str]:
    """Запускает команду проекта. Возвращает (код, весь вывод)."""
    exe = shutil.which("uvx") or shutil.which("uvx.exe")
    if not exe:
        return 127, "uvx не найден в PATH"

    def say(text: str) -> None:
        if progress:
            progress(text)

    say(f"запускаю {PACKAGE} install-addon")
    # Пакетный файл через cmd.exe. На этой машине uvx — .EXE, и прямой
    # запуск работает; на другой он лежит как .CMD, и прямой запуск
    # полагается на то, что система сама позовёт оболочку. Ровно это
    # случилось сегодня с npm: голое имя падало с FileNotFoundError.
    argv = [exe, *INSTALL_ARGS]
    if exe.lower().endswith((".cmd", ".bat")):
        argv = [os.environ.get("COMSPEC") or "cmd.exe", "/c", exe,
                *INSTALL_ARGS]
    # `dict(**os.environ)` здесь упал бы: в переменных окружения есть
    # имена вроде `ProgramFiles(x86)`, а такое имя не является
    # идентификатором. Распаковка словаря на нём даёт TypeError — и падало
    # бы на любой машине Windows.
    env = dict(os.environ)
    env["UV_PYTHON_PREFERENCE"] = "only-managed"
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=INSTALL_TIMEOUT, encoding="utf-8", errors="replace",
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, f"команда не закончилась за {INSTALL_TIMEOUT} секунд"
    except OSError as exc:
        return 126, f"запустить не удалось: {exc}"
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def _download_addon(progress=None) -> tuple[bool, str]:
    """Запасная дорога: забрать addon.py из репозитория проекта."""
    request = urllib.request.Request(
        ADDON_URL, headers={"User-Agent": "opencode-base/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            data = resp.read(MAX_ADDON_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return False, f"сервер ответил {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, f"сеть не ответила: {exc.reason}"
    except OSError as exc:
        return False, f"не получилось: {exc}"
    if len(data) > MAX_ADDON_BYTES:
        return False, "файл больше ожидаемого — загрузка остановлена"
    if not data.lstrip().startswith(b"#"):
        return False, ("пришло не то: файл аддона начинается не с "
                       "комментария — это не аддон")
    return True, data.decode("utf-8", "replace")


def addon_state(use_fallback: bool = False) -> tuple[bool, bool, str]:
    """Что с аддоном: стоит ли, можно ли поставить, что сказать.

    Три ответа, а не один, потому что человек должен получить их все до
    нажатия. Особенно третий: «можно поставить» и «после установки
    заработает» — разные вещи, и сваливать их в одно слово «готово»
    нельзя.
    """
    exe = blender_exe()
    if exe is None:
        return False, False, ("Blender не установлена — аддон ставить "
                              "некуда")
    target = addon_file(exe)
    if target.is_file():
        return True, False, f"аддон на месте: {target}"

    can_write, why = can_write_addons(addon_dir(exe))
    if not can_write:
        return False, False, ("аддон не установлен, и поставить нельзя: "
                              + why)

    has_uvx = bool(shutil.which("uvx") or shutil.which("uvx.exe"))
    if not has_uvx:
        if use_fallback:
            return False, True, ("uvx не найден, а запасная дорога "
                                 "разрешена: файл аддона будет забран из "
                                 "репозитория проекта")
        return False, False, ("uvx не найден в PATH — командой проекта "
                              "аддон не поставить. Нужен uv, а запасная "
                              "дорога в реестре не разрешена")

    return False, True, (
        f"аддон не установлен. Поставить можно: команда проекта "
        f"«{PACKAGE} install-addon» кладёт {ADDON_FILE} в папку "
        f"{addon_dir(exe)}. После установции его надо включить руками "
        f"в Blender: Правки -> Настройки -> Аддоны -> Interface: MCP for "
        f"Blender")


def install_addon(use_fallback: bool = False,
                  progress=None) -> tuple[bool, str]:
    """Ставит аддон. Возвращает (вышло ли, что сказать).

    Порядок: сначала проба записи, потом запуск. Первая версия делала
    наоборот — то есть человек ждал скачивания, чтобы услышать «писать
    некуда».
    """
    exe = blender_exe()
    if exe is None:
        return False, "Blender не установлена — аддон ставить некуда"
    target = addon_file(exe)
    if target.is_file():
        # Тот же итоговый текст, что и после установки, и с тем же
        # напоминанием. Раньше здесь стояло короткое «аддон уже стоит» —
        # и человек, у которого файл лежит, но аддон не включён, увидел бы
        # радостное сообщение без единого слова про ручное включение.
        # Файл на месте и работающий аддон — разные вещи, и молчать об
        # этом ровно здесь нельзя.
        return True, _done_message(target, "файл уже был на месте", 0, "")

    can_write, why = can_write_addons(addon_dir(exe))
    if not can_write:
        return False, why

    code, output = _run_installer(progress=progress)
    if target.is_file():
        return True, _done_message(target, "командой проекта", code, output)
    if not use_fallback:
        return False, _failed_message(code, output)

    if progress:
        progress("команда проекта не сработала, беру файл из репозитория")
    ok, data = _download_addon(progress=progress)
    if not ok:
        return False, ("команда проекта не сработала, и запасная дорога "
                       "тоже: " + data)
    try:
        target.write_text(data, encoding="utf-8", newline="\n")
    except OSError as exc:
        return False, f"файл записан не смог: {exc}"
    if not target.is_file():
        return False, ("файл записан не смог, и на диске его нет — "
                       "значит, запись прошла мимо")
    return True, _done_message(
        target, "файлом из репозитория проекта", code, output)


def _done_message(target: Path, how: str, code: int, output: str) -> str:
    """Итог установки. Про включение — обязательная часть, а не приписка."""
    written = ""
    for line in output.splitlines():
        if str(target.parent).lower() in line.lower():
            written = line.strip()
            break
    tail = (f" Куда записала команда: {written}" if written else "")
    # Путь называется всегда, а не только когда команда что-то напечатала:
    # человек должен видеть, какой файл программа имеет в виду, иначе
    # при ручной проверке он откроет не то.
    return (f"аддон {ADDON_FILE} положен ({how}), файл: {target}.{tail} "
            f"Осталось включить "
            f"его руками в Blender: Правки -> Настройки -> Аддоны -> "
            f"Interface: MCP for Blender. Без этого мост не ответит, и "
            f"программа не будет говорить, что он готов.")


def _failed_message(code: int, output: str) -> str:
    """Отказ с причиной. Молчание здесь недопустимо.

    Человек ждал, что мост заработает, и получил «готово» — а потом
    тишину от Blender. Поэтому причина идёт вместе с отказом, вместе с
    кодом возврата и первыми строками вывода: по ним видно, чья это
    поломка и куда копать.
    """
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    head = " | ".join(lines[:3])[:300]
    return (f"команда проекта не сработала, код {code}: {head or 'вывода нет'}. "
            f"Файл аддона на месте не появился. Запасная дорога (взять файл "
            f"из репозитория) в реестре не разрешена, и молча её "
            f"использовать нельзя: человек увидит «поставлено» и не узнает, "
            f"что официальный способ отпал.")


if __name__ == "__main__":  # pragma: no cover - только для разведки
    print(addon_state())
    sys.exit(0)
