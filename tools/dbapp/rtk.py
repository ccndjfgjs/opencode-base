"""rtk — короткий вывод команд: сжатие до того, как текст увидит нейросеть.

Что это. rtk — сторонняя программа на Rust (автор rtk-ai, лицензия
Apache-2.0): она переписывает вывод команд (git, npm, тесты, списки файлов
и другое) в короткий вид. Выигрыш даёт чужая программа, а наша работа —
поставить плагин opencode, включать и выключать его галочкой на вкладке
opencode и честно говорить, если rtk на машине нет.

Где что лежит:

    tools/thirdparty/rtk/hooks/opencode/rtk.ts   плагин автора (копия целиком)
    tools/thirdparty/rtk/LICENSE                 лицензия автора
    <папка настроек opencode>/plugins/rtk.ts     плагин, поставленный программой

Порядок установки — из README автора (https://github.com/rtk-ai/rtk):
`winget install rtk-ai.rtk` (Windows), `brew install rtk`, `install.sh`,
`cargo install --git https://github.com/rtk-ai/rtk`, либо готовый архив с
бинарником (положить `rtk.exe` в PATH, не запускать двойным щелчком).
Проверка по README: `rtk --version` и `rtk gain`. На crates.io под именем
`rtk` лежит другая программа (Rust Type Kit) — ставить только по README.

Чего программа не делает сама: не ставит бинарник и не зовёт
`rtk init -g --opencode` — эта команда автора правит ещё и настройки
Claude, то есть залезала бы в чужие файлы. Плагин кладётся в папку
opencode и записывается в наш манифест.

Живая проверка перед включением: бинарник находится в PATH, отвечает
`--version`, и главное — отвечает команда `rtk hook opencode`, которой и
живёт плагин (она появилась в версиях новее v0.51). Если rtk старее, плагин
молча ничего не переписывает, и «включено» без проверки было бы неправдой.
Проверка не прошла — в настройки opencode не пишется ничего.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
# Под pythonw (оконный Python, без консоли) sys.stdout равен None:
# .reconfigure() на нём роняет импорт модуля, а модуль импортирует
# main.py при старте — программа не открывалась совсем. Найдено живьём.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass

#: Откуда взят плагин и по какому коммиту сверялись его байты.
SOURCE = "https://github.com/rtk-ai/rtk"
SOURCE_REF = "develop"
SOURCE_COMMIT = "e0b2e85a0a7114b56a2d9f51c501ccc00c7e48f7"
SOURCE_NOTE = "коммит от 07.10.2026"
SOURCE_BLOB = "1332e6e9626fc9dc3db64330f6199ced2bd38160"
LICENSE = "Apache-2.0"

#: Плагин в репозитории и место, куда его кладёт программа.
PLUGIN_SRC = ("tools", "thirdparty", "rtk", "hooks", "opencode", "rtk.ts")
PLUGIN_REL = ("plugins", "rtk.ts")

#: Имя программы, которое ищем в PATH, и подкоманда, которой живёт плагин:
#: без неё вывод команд через rtk идти не будет.
BINARY = "rtk"
HOOK_ARGS = ("hook", "opencode")

CHECK_TIMEOUT = 20
MEASURE_TIMEOUT = 180

#: Длинная команда для замера. В плане назван именно большой `git log`.
MEASURE_COMMAND = ("git", "log", "-n", "200")


def program_root() -> Path:
    """Корень программы — папка, в которой лежит `tools`."""
    return Path(__file__).resolve().parent.parent.parent


def plugin_source() -> Path:
    """Путь к копии плагина в репозитории."""
    return program_root().joinpath(*PLUGIN_SRC)


def find_settings_dir() -> Path:
    """Папка настроек opencode — та же логика, что у остальной программы.

    Переменные `OPENCODE_CONFIG_DIR` и `XDG_CONFIG_HOME` уважаются: иначе
    проверки писали бы в настоящие настройки человека.
    """
    raw = os.environ.get("OPENCODE_CONFIG_DIR") or os.environ.get("XDG_CONFIG_HOME")
    if raw:
        candidate = Path(raw)
        if candidate.name == ".config":
            candidate = candidate / "opencode"
        if candidate.is_dir():
            return candidate
    return Path.home() / ".config" / "opencode"


#: Выпуски, которые разрешено ставить. Хэш обязателен: скачанный со
#: страницы архив без сверки мы бы не ставили. Версия 1.0.1 — первая, у
#: которой есть команда `rtk hook opencode`; в winget лежит устаревшая
#: 0.50.0, и на живой проверке 15.10.2026 от неё отказ.
RELEASE_BASE = "https://github.com/rtk-ai/rtk/releases/download"
KNOWN_RELEASES = {
    "v1.0.1": {
        "asset": "rtk-x86_64-pc-windows-msvc.zip",
        "sha256": "64b4807c50b61dddf2ac1e86751dbda9117ab94ed02bf266e6584da571c39896",
    },
}

#: Проверкам ставить нельзя: программа ставит софт, а проверка не имеет
#: права менять машину, на которой сама работает.
NO_INSTALL_ENV = "OPENCODE_NO_AUTO_INSTALL"


def binary_dir() -> Path:
    """Куда кладём программу. Эта папка уже есть в PATH."""
    return Path.home() / ".local" / "bin"


def install_binary(progress=None) -> tuple[list[str], list[str]]:
    """Ставит rtk сам. Тихо, без вопросов: галочка нажата — значит надо.

    Повторный вызов ничего не делает: если программа уже есть и отвечает,
    это уже готово. Ничего не ставим, если выставлен запрет проверок.
    """
    import hashlib  # noqa: PLC0415 — нужен только здесь
    import shutil  # noqa: PLC0415 — нужен только здесь
    import urllib.request  # noqa: PLC0415 — нужен только здесь
    import zipfile  # noqa: PLC0415 — нужен только здесь

    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    if os.environ.get(NO_INSTALL_ENV, ""):
        # Отказ говорит так же, как остальные отказы rtk: «не включён» и
        # «ничего не вписано». Одна и та же неудача двумя разными словами
        # неудобна: человек не понимает, что произошло, и ищет причину не там.
        return [], [f"rtk не включён: установка запрещена переменной "
                    f"{NO_INSTALL_ENV} — её выставили проверки. "
                    "В настройки opencode ничего не вписано."]

    found = find_binary()
    if found:
        ok, note = live_check()
        if ok:
            return [f"rtk уже стоит: {found}"], []
        say(f"rtk есть, но не отвечает ({note}) — поставлю подходящую версию.")
    else:
        say("rtk не найден — ставлю сам.")

    if not KNOWN_RELEASES:
        return messages, ["Нет ни одного выпуска с известным хэшем — ставить "
                          "нечем. Поставь rtk сам, как в README автора."]

    version = sorted(KNOWN_RELEASES, reverse=True)[0]
    spec = KNOWN_RELEASES[version]
    url = f"{RELEASE_BASE}/{version}/{spec['asset']}"
    say(f"Качаю {version}: {spec['asset']}")

    target = binary_dir()
    target.mkdir(parents=True, exist_ok=True)
    temp = target / f"rtk-{version}.zip"
    try:
        with urllib.request.urlopen(url, timeout=300) as response, \
                temp.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as exc:
        return messages, [f"скачать rtk не удалось: {exc}"]

    got = hashlib.sha256(temp.read_bytes()).hexdigest()
    if got != spec["sha256"]:
        temp.unlink(missing_ok=True)
        return messages, [
            f"хэш не совпал: получили {got[:16]}…, а ждали "
            f"{spec['sha256'][:16]}… Архив удалён, ничего не ставлю.",
        ]
    say(f"Хэш сверен: {got[:16]}…")

    try:
        with zipfile.ZipFile(temp) as archive:
            for name in archive.namelist():
                low = name.lower()
                if low.endswith("rtk.exe") and low.count("/") == 0:
                    (target / (BINARY + ".exe")).write_bytes(archive.read(name))
                    break
            else:
                return messages, ["В архиве нет rtk.exe — ставить нечего."]
    except (OSError, zipfile.BadZipFile) as exc:
        return messages, [f"архив не распаковался: {exc}"]
    finally:
        temp.unlink(missing_ok=True)

    exe = target / (BINARY + ".exe")
    if not exe.is_file():
        return messages, [f"файл положен, но называется не {BINARY}.exe: {exe}"]
    say(f"Готово: {exe} ({exe.stat().st_size} байт)")
    ok, note = live_check()
    if not ok:
        return messages, [f"поставил, но не работает: {note}"]
    say("Проверка после установки прошла: " + note)
    return messages, errors


#: winget ставит пакет в свою папку и НЕ ВСЕГДА создаёт псевдоним в Links.
#: Живая проверка 15.10.2026: rtk 0.50.0 лежал в
#: WinGet\Packages\rtk-ai.rtk_...\rtk.exe, а Links содержал только чужой
#: файл — то есть программа стояла и была не видна. Ровно то же было с
#: Claude Code, и там это уже закрыто отдельным источником поиска.
WINGET_PACKAGES = ("%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages",)


def find_binary() -> str | None:
    """Путь к rtk. None — программы нет.

    Сначала PATH, как всегда. Если там нет, смотрим пакетные папки winget:
    там программа бывает уже поставлена, но без псевдонима.
    """
    found = shutil.which(BINARY)
    if found:
        return found
    import glob  # noqa: PLC0415 — нужен только здесь

    for root in WINGET_PACKAGES:
        # Широкий шаблон ловит и служебные файлы пакета (живая проверка:
        # подобран .db вместо программы), поэтому отбираем по имени и
        # расширению: сначала настоящий .exe, потом пакетный .cmd.
        for pattern in ("*\\" + BINARY + ".exe", "*\\" + BINARY + ".cmd"):
            for hit in sorted(glob.glob(os.path.expandvars(
                    root + "\\" + BINARY + "*" + pattern))):
                if os.path.isfile(hit) and Path(hit).stem.lower() == BINARY.lower():
                    return hit
    return None


def _run(args: list[str], timeout: int) -> tuple[int, str, str]:
    """Запускает программу и возвращает код, вывод и ошибки (текстом)."""
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return done.returncode, done.stdout or "", done.stderr or ""


def binary_version(exe: str | None = None) -> str:
    """Версия rtk строкой. Пустая строка — не удалось спросить."""
    exe = exe or find_binary()
    if not exe:
        return ""
    code, out, err = _run([exe, "--version"], CHECK_TIMEOUT)
    text = (out or err).strip().splitlines()
    if code != 0 or not text:
        return ""
    return text[0].strip()


def live_check() -> tuple[bool, str]:
    """Живая проверка rtk: отвечает ли он и умеет ли то, что нужно плагину.

    Возвращает (получилось, объяснение словами). Второй шаг — не
    формальность: на версии v0.51.0 команды `rtk hook opencode` ещё нет,
    и плагин с ней просто ничего не переписывает.
    """
    exe = find_binary()
    if not exe:
        return False, (
            f"{BINARY} не найден в PATH. Поставь его по README автора "
            "(winget install rtk-ai.rtk, brew install rtk или готовый "
            "архив) и включи снова"
        )
    version = binary_version(exe)
    if not version:
        return False, f"{BINARY} есть, но не отвечает на --version — проверь установку"
    code, out, err = _run([exe, *HOOK_ARGS, "git", "status"], CHECK_TIMEOUT)
    text = (out or "").strip()
    if code != 0 or not text:
        return False, (
            f"{version}: команды «rtk hook opencode» в нём нет — нужна версия "
            "новее v0.51, плагин без неё ничего не переписывает"
        )
    try:
        answer = json.loads(text.splitlines()[0])
    except (ValueError, IndexError):
        return False, (
            f"{version}: «rtk hook opencode» отвечает не разбираемым ответом — "
            "нужна версия новее v0.51"
        )
    if not isinstance(answer, dict):
        return False, (
            f"{version}: «rtk hook opencode» отвечает не тем, что ждёт плагин"
        )
    return True, f"{version} — команда «rtk hook opencode» отвечает"


def status(dest: Path) -> dict[str, object]:
    """Что сейчас: стоит ли плагин, есть ли бинарник, какой версии."""
    exe = find_binary()
    plugin = Path(dest) / Path(*PLUGIN_REL)
    return {
        "installed": plugin.is_file(),
        "binary": exe or "",
        "version": binary_version(exe) if exe else "",
        "plugin": str(plugin),
    }


def status_text(dest: Path) -> str:
    """Строка состояния словами — для окна и для командной строки."""
    data = status(dest)
    parts = [
        "Плагин rtk: " + ("поставлен" if data["installed"] else "не поставлен"),
    ]
    if data["binary"]:
        parts.append(f"программа: {data['binary']}" + (
            f" ({data['version']})" if data["version"] else ""))
    else:
        parts.append("программа: не найдена в PATH")
    return ". ".join(parts) + "."


def install(dest: Path, progress=None) -> tuple[list[str], list[str]]:
    """Ставит плагин в настройки opencode. Перед записью — живая проверка.

    Проверка не прошла — возвращаются только ошибки, и в папке настроек
    ничего не меняется.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    # Программы может не быть. Тогда ставим её сами: человек нажал галочку,
    # значит он её хочет. Проверка состояния сюда не заходит — она только
    # читает и ничего не ставит, иначе прогон самопроверки ставил бы софт.
    if not find_binary():
        auto_messages, auto_errors = install_binary(progress=progress)
        messages += auto_messages
        if auto_errors:
            errors += auto_errors
            return messages, errors

    ok, note = live_check()
    if not ok:
        errors.append(f"rtk не включён: {note}. В настройки opencode ничего не вписано.")
        return messages, errors
    say("Проверка rtk прошла: " + note)

    source = plugin_source()
    if not source.is_file():
        errors.append(f"В репозитории нет плагина rtk ({source}) — ставить нечего.")
        return messages, errors

    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = opencode_caps.read_manifest(dest)
    manifest.setdefault("files", {})
    target = dest / Path(*PLUGIN_REL)
    body = source.read_text(encoding="utf-8")
    if target.is_file():
        try:
            if target.read_text(encoding="utf-8") == body:
                # Повторное «Включить» файл не переписывает: содержимое уже
                # то же. Проверка нужна затем, чтобы это было видно словами.
                if str(target) not in manifest.get("files", {}):
                    manifest.setdefault("files", {})[str(target)] = opencode_caps.file_hash(target)
                    opencode_caps.write_manifest(dest, manifest)
                messages.append("Плагин rtk уже стоит — файл не менялся.")
                return messages, errors
        except (OSError, UnicodeDecodeError):
            pass
    if opencode_caps.place_file(target, body, manifest, say, errors, "Плагин rtk"):
        messages.append("Плагин rtk стоит: plugins/rtk.ts")
        messages.append("Перезапустите opencode: плагины читаются при старте.")
    opencode_caps.write_manifest(dest, manifest)
    return messages, errors


def remove(dest: Path) -> tuple[list[str], list[str]]:
    """Убирает наш плагин. Чужой файл с тем же именем не трогает."""
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)

    import opencode_caps  # noqa: PLC0415 — рядом лежит, круга нет

    dest = Path(dest)
    manifest = opencode_caps.read_manifest(dest)
    target = dest / Path(*PLUGIN_REL)
    record = manifest.get("files", {}).get(str(target))
    if not target.is_file():
        manifest.get("files", {}).pop(str(target), None)
        opencode_caps.write_manifest(dest, manifest)
        say("Плагин rtk не стоял — убирать нечего.")
        return messages, errors
    if record is None:
        errors.append("Плагин rtk в этой папке не наш — оставил как есть.")
        return messages, errors
    if opencode_caps.file_hash(target) != record:
        errors.append("Плагин rtk меняли вручную — оставил как есть.")
        return messages, errors
    try:
        target.unlink()
    except OSError as exc:
        errors.append(f"Плагин rtk не убрался: {exc}")
        return messages, errors
    manifest.get("files", {}).pop(str(target), None)
    opencode_caps.write_manifest(dest, manifest)
    say("Плагин rtk убран. Перезапустите opencode: настройки читаются при старте.")
    return messages, errors


def measure(
    command: tuple[str, ...] | list[str] | None = None,
    cwd: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Замер на длинной команде: сколько байт видит нейросеть без rtk и с ним.

    Один и тот же вызов запускается дважды — напрямую и через rtk. Это
    ровно то, что делает плагин: подменяет команду на её же версию через
    rtk. Числа честные: считаются байты вывода как есть.
    """
    messages: list[str] = []
    errors: list[str] = []
    exe = find_binary()
    if not exe:
        errors.append(
            "Замер не сделан: rtk не найден в PATH. Это не проверено — "
            "поставь rtk по README и повтори."
        )
        return messages, errors
    args = list(command or MEASURE_COMMAND)
    work = Path(cwd) if cwd is not None else program_root()

    code, raw, err = _run(args, MEASURE_TIMEOUT)
    if code != 0:
        errors.append(
            f"Замер не сделан: команда «{' '.join(args)}» в папке {work} "
            f"завершилась кодом {code}"
            + (f": {err.strip().splitlines()[0]}" if err.strip() else "")
            + "."
        )
        return messages, errors
    code2, short, err2 = _run([exe, *args], MEASURE_TIMEOUT)
    if code2 != 0:
        errors.append(
            f"Замер не сделан: через rtk команда завершилась кодом {code2}"
            + (f": {err2.strip().splitlines()[0]}" if err2.strip() else "")
            + "."
        )
        return messages, errors

    before, after = len(raw.encode("utf-8")), len(short.encode("utf-8"))
    messages.append(f"Команда: {' '.join(args)} (папка {work})")
    messages.append(f"Без rtk: {before} байт")
    messages.append(f"Через rtk: {after} байт")
    if before:
        saved = round(100 * (1 - after / before))
        if after < before:
            messages.append(f"Короче на {saved}%.")
        elif after == before:
            messages.append("Не короче: вывод тот же — у этой команды фильтра нет.")
        else:
            messages.append(f"Длиннее на {-saved}%: rtk добавил своё, пользы нет.")
    else:
        messages.append("Команда ничего не вывела — сравнивать нечего, это не проверено.")
    return messages, errors


def _say(text: str) -> None:
    print(text, flush=True)


def _main(argv: list[str]) -> int:
    """Командная строка rtk: то же, что делали галочка и кнопки окна.

    Нужна затем, что проверки и скиллы не могут нажать галочку в окне.
    """
    action = (argv[0] if argv else "status").lower()
    dest = find_settings_dir()
    if action in ("-h", "--help", "help"):
        _say("rtk.py status | check | install | remove | measure")
        _say("Переключатель — на вкладке opencode; здесь то же самое словами.")
        return 0
    if action == "status":
        _say(status_text(dest))
        return 0
    if action == "check":
        ok, note = live_check()
        _say(("Живая проверка: " if ok else "Живая проверка не прошла: ") + note)
        return 0 if ok else 1
    if action == "install":
        messages, errors = install(dest, progress=_say)
    elif action == "remove":
        messages, errors = remove(dest)
    elif action == "measure":
        messages, errors = measure(command=argv[1:] or None)
    else:
        _say(f"Не знаю такой команды: {action}")
        _say("rtk.py status | check | install | remove | measure")
        return 2
    for line in messages:
        _say(line)
    for line in errors:
        _say("Ошибка: " + line)
    return 1 if errors else 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main(_sys.argv[1:]))
