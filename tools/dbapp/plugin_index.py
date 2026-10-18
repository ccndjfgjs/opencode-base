"""Указатели плагинов: какой файл нужен программе такой-то версии.

Задача модуля — одна: по измеренной версии чужой программы сказать, какой
плагин ей положить, откуда его взять и чем сверить. Всё остальное (куда
распаковывать, куда писать пакет) — в модулях конкретных программ.

Форма указателя взят у `tools/thirdparty/android-studio/index.json`, но границы
задаёт не сборка студии, а версия САМОЙ программы, и полос может быть
несколько: Unity 2021.3 и Unity 6 — это разные строки.

```json
{
  "family": "enginewire",
  "name": "EngineWire",
  "kind": "archive",
  "server": "встроенный в плагин, отдельной версии нет",
  "checked": "2026-10-18",
  "builds": [
    {"since": "5.0", "until": "5.8", "version": "0.6.0-beta-f",
     "file": "EngineWire-plugin-0.6.0-beta-f.zip",
     "url": "https://github.com/.../EngineWire-plugin-0.6.0-beta-f.zip",
     "sha256": "5abe558f...", "size": 3933665,
     "folder": "EngineWire", "strip": 1, "dest": "Plugins"}
  ]
}
```

Три правила, которые здесь зашиты и которые нельзя ломать молча:

1. **Версия вне всех полос — отказ, а не «самый новый на всякий случай».**
   Плагин не той версии хуже, чем никакого: Unity отказывается собирать проект.
2. **Пустой `sha256` — честное «сверять нечем», а не «считаем, что совпало».**
   Возвращается третий статус `unchecked`, и вызывающий решает сам.
3. **Версия сервера едет из указателя.** Две строки правды («константа в коде»
   и «указатель») разъедутся на первом же обновлении. У мостов, где сервер
   встроен в плагин (так у Unreal в линии 0.6), `server` не содержит номера
   версии — сверять тогда нечего, и это правда, а не недосказанность.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import versions

HERE = Path(__file__).resolve().parent
INDEX_ROOT = HERE.parent / "thirdparty"

#: Статусы сверки файла. Три, а не два: «сверить нечем» — это не «совпало».
MATCH = "match"
MISMATCH = "mismatch"
UNCHECKED = "unchecked"


@dataclass
class Plugin:
    """Один подходящий плагин: что качать, куда и чем сверить."""

    family: str = ""
    name: str = ""
    version: str = ""
    file: str = ""
    url: str = ""
    sha256: str = ""
    local_sha256: str = ""      # посчитан на этой машине: официального нет
    local_sha256_when: str = ""
    bundled: bool = False       # файл лежит в папке программы
    size: int = 0
    since: str = ""
    until: str = ""
    kind: str = "archive"       # archive | package
    server: str = ""            # закреплённая версия сервера из указателя
    folder: str = ""            # папка плагина внутри архива
    strip: int = 0              # сколько уровней снять при распаковке
    dest: str = ""              # куда относительно проекта
    manifest_entry: str = ""    # для kind=package: строка в manifest.json
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_archive(self) -> bool:
        return self.kind != "package"


def index_path(family: str, root: Path | None = None) -> Path:
    """Путь к указателю. `root` — папка, где искать (для проверок)."""
    base = Path(root) if root is not None else INDEX_ROOT
    return base / str(family) / "index.json"


def load(family: str, root: Path | None = None) -> tuple[dict | None, str]:
    """Прочитать указатель. Битый JSON — причина словами, а не исключение.

    Исключение здесь уехало бы в окно программы: человек увидит traceback
    вместо того, чтобы узнать, что файл указателя испорчен и где он лежит.
    """
    path = index_path(family, root)
    if not path.is_file():
        return None, f"указателя {family} нет: ожидался файл {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return None, f"указатель {family} не читается ({path.name}): {exc}"
    if not isinstance(data, dict):
        return None, f"указатель {family} должен быть объектом, а не списком: {path}"
    builds = data.get("builds")
    if not isinstance(builds, list) or not builds:
        return None, f"в указателе {family} нет ни одной полосы versions: {path}"
    return data, ""


def _fits(build: dict, version: tuple[int, ...]) -> bool:
    """Влезает ли версия в полосу. Нижняя и верхняя границы включительно."""
    since = versions.version_tuple(str(build.get("since") or ""))
    lower_ok = versions.since_matches(
        str(build.get("since") or ""), version[:len(since)] if since else ())
    return lower_ok and versions.until_ok(str(build.get("until") or ""), version)


def _reason_none(data: dict, version: str, parsed: tuple[int, ...]) -> str:
    """Почему плагин не нашёлся. Текст для человека, а не для разработчика."""
    builds = data.get("builds") or []
    spans = []
    for build in builds:
        low = str(build.get("since") or "").strip() or "любая"
        high = str(build.get("until") or "").strip()
        high = "и выше" if high in ("", "*") else high
        spans.append(f"{low} — {high}")
    if not parsed:
        return (f"версия «{version}» не разобрана: нет ни одной цифры. "
                f"Плагин есть для: {'; '.join(spans)}")
    return (f"версия {version} не попадает ни в одну полосу указателя "
            f"({data.get('family', '?')}). Плагин есть для: {'; '.join(spans)}")


def _build_plugin(data: dict, best: dict, family: str = "") -> Plugin:
    """Собрать Plugin из полосы указателя. Один на всех — и pick, и latest."""
    return Plugin(
        family=str(data.get("family") or family),
        name=str(data.get("name") or ""),
        version=str(best.get("version") or ""),
        file=str(best.get("file") or ""),
        url=str(best.get("url") or ""),
        sha256=str(best.get("sha256") or "").strip().lower(),
        local_sha256=str(best.get("local_sha256") or "").strip().lower(),
        local_sha256_when=str(best.get("local_sha256_when") or ""),
        bundled=bool(best.get("bundled")),
        size=int(best.get("size") or 0),
        since=str(best.get("since") or ""),
        until=str(best.get("until") or ""),
        kind=str(best.get("kind") or data.get("kind") or "archive"),
        server=str(data.get("server") or ""),
        folder=str(best.get("folder") or data.get("folder") or ""),
        strip=int(best.get("strip", 0)),
        dest=str(best.get("dest") or data.get("dest") or ""),
        manifest_entry=str(best.get("manifest_entry") or data.get("manifest_entry") or ""),
        note=str(data.get("note") or ""),
        extra=dict(best.get("extra") or {}),
    )


def pick(data: dict | None, version: str | tuple[int, ...],
         family: str = "") -> tuple[Plugin | None, str]:
    """Плагин для версии программы. Второе значение — причина отказа.

    Самая свежая подходящая полоса выигрывает: полосы могут пересекаться по
    границам, и брать надо ту, где версия плагина новее.
    """
    if not data:
        return None, "указатель не загружен"
    text = version if isinstance(version, str) else ".".join(map(str, version))
    parsed = versions.version_tuple(text)
    if not any(parsed):
        return None, _reason_none(data, str(text), parsed)
    fits = [b for b in (data.get("builds") or []) if isinstance(b, dict) and _fits(b, parsed)]
    if not fits:
        return None, _reason_none(data, str(text), parsed)
    best = max(fits, key=lambda b: versions.version_tuple(str(b.get("version") or "")))
    plugin = _build_plugin(data, best, family)
    if plugin.kind != "package" and not plugin.url:
        return None, (f"в полосе для версии {text} нет ссылки на файл плагина — "
                      f"указатель описан не полностью")
    return plugin, ""


def latest(data: dict, family: str = "") -> tuple[Plugin | None, str]:
    """Самая свежая полоса указателя — когда версия программы не измерена.

    Нужна мостам, у которых движок может и стоять, и ещё не стоять: пустая
    строка в требовании — это «пока неизвестно», а не «версия 9999».
    """
    builds = [b for b in (data.get("builds") or []) if isinstance(b, dict)]
    if not builds:
        return None, f"в указателе {data.get('family', family)} нет ни одной полосы"
    best = max(builds, key=lambda b: versions.version_tuple(str(b.get("since") or "")))
    plugin = _build_plugin(data, best, family)
    if plugin.kind != "package" and not plugin.url:
        return None, (f"у свежей полосы указателя ({data.get('family', family)}) "
                      f"нет ссылки на файл плагина — указатель описан не полностью")
    return plugin, ""


def latest_for(family: str, root: Path | None = None) -> tuple[Plugin | None, str]:
    """Прочитать указатель и взять его самую свежую полосу."""
    data, note = load(family, root)
    if data is None:
        return None, note
    return latest(data, family)


def pick_for(family: str, version: str | tuple[int, ...],
             root: Path | None = None) -> tuple[Plugin | None, str]:
    """Прочитать указатель и выбрать плагин — две операции одним вызовом."""
    data, note = load(family, root)
    if data is None:
        return None, note
    return pick(data, version, family)


def family_pair(family: str, version: str | tuple[int, ...],
                root: Path | None = None) -> tuple[Plugin | None, str]:
    """Плагин для версии программы и сверка версий — одним вызовом.

    Порядок именно такой: сначала сверка, потом всё остальное. Мост не
    должен качать и разворачивать архив, если сервер и плагин из разных
    релизов — вызывающий получает отказ до сети.
    """
    plugin, why = pick_for(family, version, root)
    if plugin is None:
        return None, why
    same, note = server_matches(plugin)
    if not same:
        return None, note
    return plugin, note


def server_version(plugin: Plugin) -> str:
    """Версия из строки сервера. Формат у мостов разный: `пакет@1.2.3`
    и `пакет==1.2.3`, поэтому знак ищется, а не зашит."""
    text = str(plugin.server or "").strip()
    if not text:
        return ""
    for mark in ("==", "@", ">="):
        if mark in text:
            return text.rsplit(mark, 1)[1].strip()
    return ""


def server_package(plugin: Plugin) -> str:
    """Строка пакета сервера той же версии, что и выбранный плагин.

    Версия сервера и плагина обязаны быть из одного релиза: при расхождении
    Unreal отвечает на каждый вызов `versionMismatch`, и это выглядит как
    «мост сломан», хотя сломан не мост. Поэтому версия подставляется из
    указателя — той полосы, что выбрана для измеренной версии движка, — а
    не из константы в коде лаунчера, которая разъедется при первом же
    обновлении указателя.
    """
    text = str(plugin.server or "").strip()
    if not text:
        return ""
    version = str(plugin.version or "").strip()
    if not version:
        return text
    for mark in ("==", "@", ">="):
        if mark in text:
            return text.rsplit(mark, 1)[0] + mark + version
    return text


def server_matches(plugin: Plugin) -> tuple[bool, str]:
    """Совпадают ли версии сервера и плагина. Расхождение — отказ, а не «и так сойдёт».

    Пустая версия сервера в указателе — это не расхождение: bridges без
    сервера в указателе (Ghidra) просто не объявляют его.
    """
    name = str(plugin.name or "").strip() or "плагин"
    want = server_version(plugin)
    got = str(plugin.version or "").strip()
    if not want:
        return True, (f"указатель не заявляет версию сервера для {name} — "
                      f"сверять нечего")
    if not got:
        return False, (f"у {name} не записана версия, а сервер заявлен как "
                       f"{want} — сверять не с чем")
    if versions.version_tuple(want) == versions.version_tuple(got):
        return True, f"сервер и плагин одного релиза: {got}"
    return False, (f"версии не совпадают: сервер {want}, плагин {got}. При таком "
                   f"расхождении {name} отвечает на каждый вызов "
                   f"versionMismatch — мост включать нельзя")


#: Потолок файла. Плагины весят единицы мегабайт; 200 МБ — это уже не плагин,
#: и такой файл не должен съесть место и время человека молча.
MAX_BYTES = 200 * 1024 * 1024
CHUNK = 256 * 1024
UA = "opencode-base/1.0 (plugin fetch)"


def download(plugin: Plugin, into: Path, progress=None) -> tuple[Path | None, str]:
    """Скачать файл плагина и сразу сверить. Не совпал — файл удаляется.

    Сверка здесь же, а не после распаковки, потому что распаковка чужого
    архива — это уже запись на диск чужой программы.
    """
    import urllib.error
    import urllib.request

    if not plugin.url:
        return None, f"в указателе для {plugin.name} нет ссылки на файл"
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    target = into / (plugin.file or "плагин")
    request = urllib.request.Request(plugin.url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            if total and total > MAX_BYTES:
                return None, (f"файл {plugin.file} объявлен на "
                              f"{total // 1048576} МБ — это не плагин, качать не буду")
            written = 0
            with target.open("wb") as stream:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_BYTES:
                        stream.close()
                        target.unlink(missing_ok=True)
                        return None, f"файл перевалил за {MAX_BYTES // 1048576} МБ — качать не буду"
                    stream.write(chunk)
                    if progress is not None:
                        progress(f"качаю {plugin.file}: {written // 1024} КБ")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        target.unlink(missing_ok=True)
        return None, f"не скачался {plugin.file}: {exc}"

    status, note = verify(plugin, target)
    if status == MISMATCH:
        target.unlink(missing_ok=True)
        return None, note
    if status == UNCHECKED and progress is not None:
        progress(f"внимание: {note}")
    return target, note


def extract(plugin: Plugin, archive: Path, root: Path) -> tuple[Path | None, str]:
    """Распаковать плагин в проект.

    `folder` — путь внутри архива, который кладём (например
    `plugins/EngineWire` или `addons/godot_ai`). `strip` — сколько папок из
    начала этого пути снять при укладке: у EngineWire в проект кладётся сама
    папка `Plugins/EngineWire`, поэтому снимаем одну (`plugins`), а у Godot
    архив ложится в корень проекта как есть.

    Пути вида `..` и абсолютные отвергаются: программа распаковывает чужой
    архив, доверять его содержимому на запись нельзя. И если не извлеклось
    ничего — это отказ, а не «готово».
    """
    import zipfile

    archive = Path(archive)
    root = Path(root)
    if not archive.is_file():
        return None, f"архива нет: {archive.name}"
    wanted = str(plugin.folder or "").strip("/\\").replace("\\", "/")
    parts = [p for p in wanted.split("/") if p] if wanted else []
    if not parts:
        # Пустая папка — это не «распаковать всё». Так распаковался бы любой
        # архив по любому пути, и чужая сборка расписалась бы по проекту.
        return None, (f"в указателе для {plugin.name} не сказано, какую папку "
                      f"класть (folder) — не распаковываю")
    tail_name = "/".join(parts[plugin.strip:]) if plugin.strip < len(parts) else wanted
    written = 0
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        return None, f"архив не открывается ({archive.name}): {exc}"
    with zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            chunks = [p for p in name.split("/") if p not in ("", ".")]
            if any(p == ".." for p in chunks):
                return None, f"в архиве есть выход из папки ({name}) — не распаковываю"
            if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
                return None, f"в архиве абсолютный путь ({name}) — не распаковываю"
            if parts:
                if not chunks[: len(parts)] == parts:
                    continue
                rest = chunks[len(parts):]
                if rest:
                    rest = ([tail_name] if tail_name else []) + rest
            else:
                rest = chunks
            if not rest:
                continue
            out = root.joinpath(*rest)
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    dst.write(chunk)
            written += 1
    if not written:
        inside = wanted or "(любой путь)"
        return None, (f"в архиве {archive.name} нет папки «{inside}» — "
                      f"это не тот релиз плагина, ничего не разложил")
    return root, f"разложил {plugin.name} ({written} файлов) в {root}"


def bundled_path(plugin: Plugin, root: Path | None = None) -> Path | None:
    """Файл плагина, уже лежащий в папке программы.

    Программа везёт плагины с собой — как девять сборок плагина Android
    Studio. Человек ставит их без интернета, а сеть нужна только если
    файла нет (например программу перенесли, а встроенный архив забыли).
    """
    if not plugin.bundled or not plugin.file:
        return None
    base = Path(root) if root is not None else INDEX_ROOT
    candidate = base / plugin.family / plugin.file
    return candidate if candidate.is_file() else None


def obtain(plugin: Plugin, into: Path, progress=None,
           root: Path | None = None) -> tuple[Path | None, str]:
    """Файл плагина для установки: сначала встроенный, потом из сети.

    Порядок не для экономии, а для честности: встроенный файл проверен
    официальным хешем прямо на этой машине, и его установка не зависит от
    того, доступен ли интернет и не подменил ли кто файл по дороге.
    """
    local = bundled_path(plugin, root)
    if local is not None:
        status, note = verify(plugin, local)
        if status == MISMATCH:
            return None, (f"встроенный файл {local.name} не проходит сверку "
                          f"({note}) — не ставлю его и не качаю другой молча")
        if progress is not None:
            progress(f"беру встроенный {local.name} из папки программы: {note}")
        return local, f"{note} (встроенный, интернет не нужен)"
    if progress is not None:
        progress(f"встроенного файла {plugin.file} в программе нет — качаю из сети")
    return download(plugin, into, progress)


def verify(plugin: Plugin, path: Path) -> tuple[str, str]:
    """Сверить файл. Три честных исхода, а не два.

    `mismatch` — файл не наш, ставить нельзя. `unchecked` — официального хеша
    нет: сверять нечем, и это должно быть видно человеку, а не спрятано под
    «установлено».
    """
    path = Path(path)
    if not path.is_file():
        return MISMATCH, f"файл не на месте: {path.name} отсутствует"
    want = str(plugin.sha256 or "").strip().lower()
    if not want:
        local_want = str(plugin.local_sha256 or "").strip().lower()
        if not local_want:
            return UNCHECKED, (f"у {plugin.name} нет официального хеша файла "
                               f"({path.name}) — сверка не выполнена")
        try:
            got = versions.file_sha256(path)
        except OSError as exc:
            return MISMATCH, f"файл не прочитался для сверки: {exc}"
        when = plugin.local_sha256_when or "дата не указана"
        if got.lower() != local_want:
            return MISMATCH, (f"встроенный файл не совпал с копией, посчитанной "
                              f"на этой машине ({when}): получили {got[:12]}, "
                              f"ждали {local_want[:12]} — не устанавливаю")
        return UNCHECKED, (f"официального хеша нет; сверено с копией, посчитанной "
                           f"на этой машине {when}: {got[:12]}")
    try:
        got = versions.file_sha256(path)
    except OSError as exc:
        return MISMATCH, f"файл не прочитался для сверки: {exc}"
    if got.lower() != want:
        return MISMATCH, (f"хеш не совпал: скачали {got[:12]}, а ждали "
                          f"{want[:12]} — файл не из того релиза, не устанавливаем")
    return MATCH, f"хеш совпал: {got[:12]}"