r"""Сборка релиза: архив из отслеживаемого и содержимого подмодуля.

**Зачем скрипт, а не `git archive`.** Измерено на этой машине: подмодуль
`tools/thirdparty/obs-mcp` в индексе — одна запись вида `160000 commit`,
то есть ссылка, а не файлы. `git archive HEAD` кладёт на её месте **пустую
папку**: в архиве 1655 записей, из них про `obs-mcp` четыре, и ни одной с
содержимым. На диске подмодуля 60 файлов. Значит релиз, собранный только
через git, уехал бы сломанным: мост OBS не работал бы, и человек увидел
бы «переустановите», хотя переустанавливать нечего.

**Почему только отслеживаемые.** В архив попадает то, что отдаётся людям.
Папки `config/.secrets/`, `config/cache/`, `config/device_id`,
`config/hwid` и всё, что не прошло через `git add`, в архив не идут —
это ровно то, ради чего сборка идёт через список файлов под контролем
версий, а не копированием папки. Если человек забыл `git add`, файл в
релиз не попадёт: это лучше, чем утечка ключа в публичный архив.

**Проверки, без которых скрипт не работает.**

  * подмодуль не пуст — иначе архив уедет сломанным;
  * версия из файла `ВЕРСИЯ` совпадает с меткой `v<версия>`, если метка
    есть: вложение называется `opencode-base-<версия>.zip`, а человек
    может прикладывать его к другой метке;
  * в архиве не осталось записи-ссылки подмодуля: она заменена
    содержимым, и пустая папка означала бы недособранный релиз;
  * пересобранный архив проходит ту же проверку выхода за пределы папки,
    что и при применении.

**Что печатает.** Точный список того, что нужно приложить к релизу на
GitHub: имя архива, имя файла суммы и команды для проверки. Без этого
человек прикладывает один файл, программа требует два и отказывается
качать.

**Запуск:**

    python tools/сборка/собери-релиз.py
    python tools/сборка/собери-релиз.py --tag v1.0.0
    python tools/сборка/собери-релиз.py --out C:\...\куда
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Корень репозитория — на два уровня выше: tools/сборка/сам.py.
ROOT = HERE.parent.parent

#: Подмодули, содержимое которых обязано попасть в архив. Перечислены
#: явно: «найти все подмодули» значило бы надеяться на то, что скрипт
#: ничего не пропустит, а пропуск здесь означает сломанный релиз.
SUBMODULES = ("tools/thirdparty/obs-mcp",)

#: Имя файла версии. Такое же, как читает программа.
VERSION_FILE = "ВЕРСИЯ"

#: Куда по умолчанию класть готовый архив.
DEFAULT_OUT = ROOT / "отчёты" / "релизы"


def say(text: str = "") -> None:
    try:
        print(text, flush=True)
    except Exception:
        pass


def git(*args: str, repo: Path = ROOT) -> str:
    """Вывод команды git. Ошибка — текстом, а не исключением."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.quotepath=false", *args],
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"git не отвечает: {exc}")
    if done.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} вернул {done.returncode}:\n"
            f"{(done.stderr or '').strip()[:400]}")
    return done.stdout


def tracked_files() -> list[str]:
    """Файлы под контролем версий, относительные пути через прямой слэш."""
    raw = git("ls-files", "-z", "--")
    out: list[str] = []
    for chunk in raw.split("\0"):
        if chunk.strip():
            out.append(chunk.replace("\\", "/"))
    return out


def local_version() -> str:
    path = ROOT / VERSION_FILE
    if not path.is_file():
        raise SystemExit(
            f"нет файла {VERSION_FILE} в корне. Версию не из чего взять, "
            f"а имя архива строится из неё.")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"файл {VERSION_FILE} пуст.")
    if not re.fullmatch(r"\d+(?:\.\d+)*", text):
        raise SystemExit(
            f"в {VERSION_FILE} написано {text!r}, а ожидается номер версии "
            f"цифрами через точку.")
    return text


def check_tag(tag: str | None, version: str) -> None:
    """Метка, если она дана, обязана быть `v<версия>`."""
    if not tag:
        return
    if tag != f"v{version}":
        raise SystemExit(
            f"метка {tag!r} не совпадает с файлом {VERSION_FILE} "
            f"({version!r}). Ожидается v{version}.\n"
            f"Либо поправь файл версии, либо возьми другую метку: имя "
            f"архива строится из версии, и человек приложит файл не к тому "
            f"релизу.")


def submodule_files(path: str) -> list[str]:
    """Файлы подмодуля, которые git считает нужными.

    Список берётся из самого подмодуля, а не обходом папки: в папке может
    лежать `node_modules`, `.git` и всё, что не должно уехать.
    """
    sub = ROOT / path
    if not sub.is_dir():
        return []
    try:
        raw = subprocess.run(
            ["git", "-C", str(sub), "-c", "core.quotepath=false",
             "ls-files", "-z", "--"],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    if raw.returncode != 0:
        return []
    out: list[str] = []
    for chunk in raw.stdout.split("\0"):
        if chunk.strip():
            out.append(chunk.replace("\\", "/"))
    return out


def check_submodules(files: list[str]) -> dict[str, int]:
    """Подмодуль обязан быть непустым. Иначе релиз уедет сломанным."""
    counts: dict[str, int] = {}
    empty: list[str] = []
    for path in SUBMODULES:
        sub_files = submodule_files(path)
        counts[path] = len(sub_files)
        if not sub_files:
            empty.append(path)
    if empty:
        raise SystemExit(
            "подмодуль пуст, релиз собирать нельзя:\n  "
            + "\n  ".join(empty)
            + "\n\nПроверено на этой машине: git архивирует подмодуль как "
              "пустую папку, и в архиве вместо кода окажется папка без "
              "файлов.\nСобери его командой:\n"
              f"  git submodule update --init --recursive")
    return counts


def build(out_dir: Path, tag: str | None, root_prefix: str
          ) -> tuple[Path, Path, str, int]:
    """Собрать архив и файл суммы. Возвращает пути и версию."""
    version = local_version()
    check_tag(tag, version)
    counts = check_submodules([])
    say("подмодули:")
    for path, count in counts.items():
        say(f"  {path}: {count} файлов")

    files = tracked_files()
    say(f"отслеживаемых файлов: {len(files)}")

    # Запись подмодуля в списке — это ссылка, а не файлы. Она заменяется
    # содержимым; иначе в архиве окажется папка без файлов.
    link_entries = {f"{p}" for p in SUBMODULES}
    plain = [f for f in files if f not in link_entries]
    say(f"из них обычных: {len(plain)}, записей-ссылок подмодуля заменено: "
        f"{len(files) - len(plain)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"opencode-base-{version}.zip"
    archive = out_dir / name

    written = 0
    sub_written = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in plain:
            src = ROOT / rel
            if not src.is_file():
                say(f"  ПРОПУЩЕН, нет на диске: {rel}")
                continue
            zf.write(src, f"{root_prefix}/{rel}")
            written += 1
        for path in SUBMODULES:
            for rel in submodule_files(path):
                src = ROOT / path / rel
                if not src.is_file():
                    continue
                zf.write(src, f"{root_prefix}/{path}/{rel}")
                sub_written += 1

    say(f"записано в архив: {written} обычных и {sub_written} из подмодулей")

    # Проверка после сборки: ссылка подмодуля не должна остаться папкой.
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    leftovers = [f"{root_prefix}/{p}" for p in SUBMODULES
                 if f"{root_prefix}/{p}" in names]
    if leftovers:
        raise SystemExit(
            "в архиве осталась ссылка на подмодуль без содержимого: "
            f"{leftovers}. Такой архив нельзя публиковать.")

    total = archive.stat().st_size
    digest = file_sha256(archive)
    sum_file = out_dir / f"{name}.sha256"
    sum_file.write_text(f"{digest}  {name}\n", encoding="utf-8", newline="\n")
    say(f"архив: {archive}")
    say(f"размер: {total:,} байт")
    say(f"сумма: {digest}")
    say(f"файл суммы: {sum_file}")
    return archive, sum_file, version, total


def file_sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def print_instructions(archive: Path, sum_file: Path, version: str,
                       tag: str | None) -> None:
    """Что именно приложить к релизу. Без этого человек приложит один
    файл, а программа требует два и откажется качать."""
    say("")
    say("=" * 68)
    say(" ЧТО ПРИЛОЖИТЬ К РЕЛИЗУ НА GITHUB")
    say("=" * 68)
    say(f"  метка релиза:     {tag or f'v{version} — создай её, если её нет'}")
    say("")
    say("  ДВА файла, оба обязательны:")
    say(f"    1. {archive.name}")
    say(f"    2. {sum_file.name}")
    say("")
    say("  Программа качает сумму ПЕРВОЙ и отказывается качать архив без")
    say("  неё: файл будет распакован поверх рабочей папки.")
    say("")
    say("  Проверь перед публикацией, что сумма сходится:")
    say(f"    Get-FileHash {archive.name} -Algorithm SHA256")
    say(f"    Get-Content  {sum_file.name}")
    say("")
    say("  Публикация — отдельное действие и делается человеком:")
    say("    gh release create v%s --title \"v%s\" %s %s"
        % (version, version, archive.name, sum_file.name))
    say("")
    say("  После публикации проверь, что GitHub отдаёт оба файла:")
    say(f"    https://github.com/ccndjfgjs/opencode-base/releases/tag/v{version}")
    say("")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Собирает архив релиза из отслеживаемых файлов.")
    parser.add_argument("--tag", default=None,
                        help="метка релиза, если уже создана: v1.0.0")
    parser.add_argument("--out", default=None,
                        help=f"куда класть (по умолчанию {DEFAULT_OUT})")
    parser.add_argument("--prefix", default="opencode-base",
                        help="папка внутри архива (по умолчанию opencode-base)")
    args = parser.parse_args()

    say("Сборка релиза OpenCode_Base")
    say("=" * 68)
    if not (ROOT / ".git").exists():
        raise SystemExit(
            f"в {ROOT} нет .git. Собирать нечего: скрипт берёт только "
            f"отслеживаемые файлы, и без git он не знает, что это.")
    out_dir = Path(args.out) if args.out else DEFAULT_OUT
    try:
        archive, sum_file, version, _size = build(
            Path(out_dir), args.tag, args.prefix)
    except SystemExit as exc:
        say("")
        say(f"ОТКАЗ: {exc}")
        return 1
    print_instructions(archive, sum_file, version, args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())