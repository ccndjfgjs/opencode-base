"""§22.2: самообновление программы — модуль целиком, версия 2.

**Что исправлено относительно версии 1.**

1. `make_backup` копировал через `shutil.copytree` с
   `ignore=shutil.ignore_patterns(...)`. На этой машине первый вызов падал
   с `WinError 3` («путь не найден»), причём падал не всегда: внутри
   `apply_update` тот же вызов отрабатывал. Копирование заменено на
   явный обход с `mkdir` перед каждой записью — так понятно, **какой** путь
   не создался, и нет зависимости от поведения `copytree` на длинных
   путях и путях с кириллицей. Побочно ушёл синтаксис-баг версии 1
   (`*\"__pycache__\"` — это не Python).
2. Незавершённый бэкап теперь удаляется при сбое, иначе он занимал бы
   место и блокировал бы следующую попытку навсегда.
3. `remote_version` делал `name.lstrip(\"v\")`. `lstrip` снимает **все**
   ведущие символы из набора, а не один: метка `version-1.0.0` стала бы
   `ersion-1.0.0`. Теперь снимается ровно одна `v` и только если дальше
   цифра.
4. `apply_update` вызывал `make_backup`, а тот **отказывался**, если бэкап
   уже есть. Значит после одной неудачной попытки (битый архив) или после
   одного обновления следующее было невозможно — до ручного
   `drop_backup`. Теперь `apply_update` сначала убирает старый бэкап в
   сторону с датой и только потом делает свежий. Данные не теряются, но и
   обновление больше не блокируется.

**Публикация релизов и создание меток** — внешние действия, здесь они не
выполняются. Модуль только проверяет, сравнивает и применяет готовый
архив.

**Безопасность.** Перед заменой текущая версия копируется целиком в
`служебное/бэкап-перед-обновлением/`. Откат — одной функцией. Бэкап
никогда не удаляется сам.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

#: Имя файла версии в корне программы.
VERSION_FILE = "ВЕРСИЯ"

#: Куда кладётся бэкап перед обновлением.
BACKUP_DIR = ("служебное", "бэкап-перед-обновлением")

#: Что не копировать: служебное лежит внутри и копируется в себя же,
#: `.git` у распакованной копии всё равно нет.
SKIP_DIRS = frozenset({"__pycache__", ".git", "служебное"})


def _root(base: Path | str | None) -> Path:
    """Корень программы: заданный или тот, где лежит модуль (../..)."""
    if base is not None:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def local_version(base: Path | str | None = None) -> str:
    """Версия, которая стоит сейчас. Пустая строка — файла нет."""
    try:
        return (_root(base) / VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _strip_v(name: str) -> str:
    """Снять ведущую `v` у метки — ровно одну и только перед цифрой."""
    if name.startswith("v") and name[1:2].isdigit():
        return name[1:]
    return name


def remote_version(repo: Path | str | None = None) -> str:
    """Версия из меток репозитория. Пустая строка — меток нет или не нашли.

    Идёт через `git ls-remote --tags`, а не через GitHub API: не нужен
    ни токен, ни знание адреса репозитория, ни разбор JSON.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(_root(repo)), "ls-remote", "--tags", "origin"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    tags: list[str] = []
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.endswith("^{}"):
            continue  # метка на аннотированном объекте — дубликат
        name = _strip_v(ref.rsplit("/", 1)[-1])
        if name and name[0].isdigit():
            tags.append(name)
    if not tags:
        return ""
    import versions as _vs  # noqa: PLC0415 — лежит рядом

    return max(tags, key=_vs.version_tuple)


def check_update(base: Path | str | None = None,
                 repo: Path | str | None = None) -> tuple[bool, str, str]:
    """Есть ли обновление. Возвращает (есть, локальная, удалённая).

    Сравнение числовое, а не строковое: иначе 1.9 окажется новее 1.10.
    """
    here = local_version(base)
    there = remote_version(repo)
    if not here:
        return False, here, there or "локальная версия не названа"
    if not there:
        return False, here, "меток нет"
    import versions as _vs  # noqa: PLC0415 — лежит рядом

    if _vs.version_tuple(there) > _vs.version_tuple(here):
        return True, here, there
    return False, here, there


def _backup_path(root: Path) -> Path:
    return root.joinpath(*BACKUP_DIR)


def _copy_tree(src: Path, dst: Path, skipped: list[str]) -> int:
    """Скопировать всё содержимое `src` в `dst` с явным `mkdir`.

    `mkdir` вызывается **до** каждой записи, а не один раз сверху. Иначе
    на длинном пути запись падает в конце, когда папка уже создана, и
    ошибка указывает не на ту причину.
    """
    copied = 0
    for item in sorted(src.iterdir()):
        if item.name in SKIP_DIRS:
            skipped.append(item.name)
            continue
        target = dst / item.name
        if item.is_dir():
            try:
                target.mkdir(exist_ok=True)
            except OSError:
                target.mkdir(parents=True, exist_ok=True)
            copied += _copy_tree(item, target, skipped)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(target))
            copied += 1
    return copied


def make_backup(base: Path | str | None = None) -> tuple[bool, str]:
    """Скопировать текущую версию в бэкап. Возвращает (вышло, текст)."""
    root = _root(base)
    dest = _backup_path(root)
    if dest.exists():
        return False, (f"бэкап уже есть: {dest}. Сначала реши, "
                       "нужен ли он ещё.")
    skipped: list[str] = []
    copied = 0
    try:
        dest.mkdir(parents=True, exist_ok=True)
        copied = _copy_tree(root, dest, skipped)
    except OSError as exc:
        # Недоудалённый бэкап хуже отсутствующего: он занимает место и
        # блокирует следующую попытку. Убираем только его.
        shutil.rmtree(dest, ignore_errors=True)
        return False, f"бэкап не удался: {type(exc).__name__}: {exc}"
    tail = f", пропущено: {', '.join(sorted(set(skipped)))}" if skipped else ""
    return True, f"бэкап сделан: {dest}, объектов {copied}{tail}"


def _set_aside(backup: Path) -> Path | None:
    """Убрать старый бэкап в сторону с датой. Не удалять — только переименовать.

    Нужно, чтобы прошлый бэкап не блокировал следующее обновление. Данные
    при этом остаются на диске: если новое обновление окажется хуже, человек
    вернётся к тому состоянию, которое было до него.
    """
    if not backup.is_dir():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    aside = backup.with_name(f"{backup.name}-прошлый-{stamp}")
    n = 1
    while aside.exists():
        n += 1
        aside = backup.with_name(f"{backup.name}-прошлый-{stamp}-{n}")
    try:
        backup.rename(aside)
    except OSError:
        return None
    return aside


def apply_update(archive: Path | str,
                 base: Path | str | None = None,
                 progress=None) -> tuple[bool, str]:
    """Применить обновление из архива. Сначала бэкап, потом замена.

    Архив распаковывается во временную папку, и только потом содержимое
    переносится в программу. Если распаковка не удалась — программа
    осталась как была и бэкап не тронут.
    """
    root = _root(base)
    archive = Path(archive)
    if not archive.is_file():
        return False, f"архива нет: {archive}"

    def say(text: str) -> None:
        if progress:
            progress(text)

    aside = _set_aside(_backup_path(root))
    if aside is not None:
        say(f"прошлый бэкап убран в сторону: {aside.name}")
    say("делаю бэкап текущей версии…")
    ok, text = make_backup(root)
    say(text)
    if not ok:
        return False, text

    say("распаковываю архив во временную папку…")
    temp = Path(tempfile.mkdtemp(prefix="обновление-"))
    try:
        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(temp)
        except (zipfile.BadZipFile, OSError) as exc:
            return False, (f"архив не распакован: {exc}. Программа не тронута, "
                           "бэкап свежий.")

        # Внутри архива может быть одна папка-обёртка. Если так — работаем
        # с ней, а не с временной папкой целиком.
        entries = [p for p in temp.iterdir() if p.name != "__MACOSX"]
        source = entries[0] if len(entries) == 1 and entries[0].is_dir() \
            else temp

        say("заменяю файлы программы…")
        replaced = 0
        for item in sorted(source.iterdir()):
            if item.name in SKIP_DIRS:
                continue
            target = root / item.name
            if target.is_dir():
                shutil.rmtree(str(target))
            elif target.exists():
                target.unlink()
            if item.is_dir():
                shutil.copytree(str(item), str(target))
            else:
                shutil.copy2(str(item), str(target))
            replaced += 1
        say(f"заменено объектов: {replaced}")
    except OSError as exc:
        return False, (f"замена не удалась на объекте: "
                       f"{type(exc).__name__}: {exc}. Бэкап на месте, "
                       "откат возможен.")
    finally:
        shutil.rmtree(temp, ignore_errors=True)

    tail = (f" Прошлый бэкап оставлен: {aside.name}."
            if aside is not None else "")
    return True, (f"обновление применено из {archive.name}. "
                  f"Теперь стоит версия {local_version(root) or 'не названа'}"
                  f"{tail}")


def rollback(base: Path | str | None = None) -> tuple[bool, str]:
    """Вернуть программу из бэкапа. Сам бэкап после этого остаётся."""
    root = _root(base)
    backup = _backup_path(root)
    if not backup.is_dir():
        return False, f"бэкапа нет: {backup}"
    try:
        for item in sorted(root.iterdir()):
            if item.name in SKIP_DIRS:
                continue
            if item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()
        restored = 0
        for item in sorted(backup.iterdir()):
            if item.is_dir():
                shutil.copytree(str(item), str(root / item.name))
            else:
                shutil.copy2(str(item), str(root / item.name))
            restored += 1
    except OSError as exc:
        return False, f"откат не удался: {type(exc).__name__}: {exc}"
    return True, (f"возвращено объектов: {restored}. "
                  f"Бэкап не удалён: {backup}. Версия "
                  f"{local_version(root) or 'не названа'}")


def drop_backup(base: Path | str | None = None) -> tuple[bool, str]:
    """Удалить бэкап. Только по прямому вызову, автоматически — никогда."""
    backup = _backup_path(_root(base))
    if not backup.is_dir():
        return True, "бэкапа и не было"
    try:
        shutil.rmtree(str(backup))
    except OSError as exc:
        return False, f"бэкап не удалён: {exc}"
    return True, f"бэкап удалён: {backup}"


if __name__ == "__main__":
    here, there = local_version(), remote_version()
    has, _, _ = check_update()
    print(f"локально: {here or 'не названа'}")
    print(f"в метках: {there or 'меток нет'}")
    print(f"обновление есть: {has}")
    print(f"бэкап: {_backup_path(_root(None))}")
    sys.exit(0)