r"""Скачивание обновления: сеть, контрольная сумма, распаковка.

**Почему проверки именно такие.** Скачанный архив будет распакован поверх
рабочей программы, а распакованный код — запущен. Поэтому проверяется всё,
что влияет на то, откуда и что придёт:

  * **только HTTPS и только `github.com`** — сделано в `update_source`, и
    здесь адреса берутся только оттуда. Повторять проверку вредно: две
    копии правила разъедутся, и одна из них перестанет проверяться.
  * **контрольная сумма SHA-256** — лежит в том же релизе. Защищает от
    битой или обрезанной загрузки. **Не защищает от подмены релиза**,
    если у кого-то есть доступ к аккаунту: сумма лежит рядом с архивом и
    меняется вместе с ним. Об этом сказано в тексте, а не спрятано.
  * **защита от выхода за пределы папки** (zip-slip) — запись вида
    `../../Windows/System32/x.dll` в архиве при распаковке уходит за
    пределы папки назначения. Проверяется каждый путь ДО записи, а не
    после: после распаковки файлы уже на диске.
  * **лимит размера** — 400 МБ, как у OBS. Ответ больше обрывается, а не
    съедает место.
  * **откат по контрольной сумме** — сначала сумма, потом архив. Иначе
    пришлось бы качать сотни мегабайт, чтобы узнать, что файл битый.

**Что здесь нет.** Ни распаковки поверх программы, ни замены файлов: это
`selfupdate.apply_update`, и вызывающий решает сам. Функция отдаёт
проверенный архив и текст.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from update_source import (
    SourceError,
    asset_url,
    check_url,
    release_url,
    releases_url,
)

#: Только ASCII в заголовке: HTTP кодирует его в latin-1, и кириллица
#: обрывает попытку до отправки. Так уже было в `bridges.py`.
UA = "opencode-base/1.0 (update download)"

#: Потолок на размер. Официальный архив — десятки мегабайт; 400 МБ запас.
MAX_BYTES = 400 * 1024 * 1024

#: Сколько байт читать за раз.
CHUNK = 256 * 1024


def _describe_http(status: int, headers: dict, what: str) -> str:
    """Человеческий текст для кода ответа.

    Коды 403 и 404 требуют разных слов, а 404 у GitHub без токена означает
    сразу две разные вещи — и это не догадка, а особенность GitHub: он не
    отличает «репозитория нет/нет доступа» от «объекта нет».
    """
    if status == 404:
        return (f"{what} не найдено: 404. Либо {what} не опубликовано, либо "
                f"репозиторий закрыт — GitHub отвечает на оба случая "
                f"одинаково, и по одному коду их не различить.")
    if status == 403:
        left = headers.get("X-RateLimit-Remaining")
        tail = (f" Осталось запросов: {left}."
                if left is not None else "")
        retry = headers.get("Retry-After")
        if retry:
            tail += f" Повторить через {retry} с."
        return (f"GitHub отклонил запрос: 403 — исчерпан лимит запросов "
                f"без токена, либо нужен токен для приватного "
                f"репозитория.{tail}")
    if status == 401:
        return "GitHub требует авторизации: 401. Нужен токен."
    return f"{what}: неожиданный ответ {status}."


def _get_json(url: str, timeout: int = 120) -> tuple[dict, str]:
    """Забрать JSON. Отказ — строкой, а не исключением наружу.

    Наружу бросается только `DownloadError` с текстом: вызывающий
    показывает его человеку, и трассировка в окне бесполезна.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = dict(resp.headers)
            body = resp.read()
    except urllib.error.HTTPError as exc:
        headers = dict(exc.headers) if exc.headers else {}
        raise DownloadError(_describe_http(exc.code, headers,
                                           "описание релиза")) from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"сеть не ответила: {exc.reason}") from exc
    except OSError as exc:
        raise DownloadError(f"не получилось: {exc}") from exc
    try:
        return json.loads(body.decode("utf-8", "replace")), ""
    except json.JSONDecodeError as exc:
        raise DownloadError(f"ответ не разобран: {exc}") from exc


def release(source: dict, tag: str, timeout: int = 120) -> dict:
    """Описание релиза по метке."""
    url = release_url(source, tag)
    try:
        return _get_json(url, timeout)[0]
    except DownloadError as exc:
        raise DownloadError(
            f"релиз {tag} недоступен. {exc}") from exc


def published(source: dict, timeout: int = 180) -> list[dict]:
    """Опубликованные релизы, новые сверху. Черновики пропущены.

    Именно этот список — источник того, что вообще можно скачать. Список
    меток для этого не годится: измерено на `obsproject/obs-websocket`
    07.10.2026, метки дошли до `5.7.5`, а последний опубликованный релиз
    — `4.9.1-compat`, и описание по `5.7.5` отдало 404.
    """
    url = releases_url(source)
    try:
        items = _get_json(url, timeout)[0]
    except DownloadError as exc:
        raise DownloadError(f"список релизов недоступен. {exc}") from exc
    if not isinstance(items, list):
        raise DownloadError("список релизов пришёл не списком.")
    out = []
    for item in items:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        if not item.get("tag_name"):
            continue
        out.append(item)
    return out


def downloadable(source: dict, timeout: int = 180) -> tuple[str, str]:
    """Самый новый релиз, у которого есть нужное вложение.

    Возвращает (метка, версия). Версия берётся из имени вложения, а не
    из метки: вложение названо по версии, и метка может быть с буквой,
    без неё или с собственным форматом. Если вложения нет ни у одного
    релиза — это не «сеть отвалилась», а «ещё нечего качать», и текст
    должен говорить именно это.
    """
    releases = published(source, timeout)
    if not releases:
        raise DownloadError(
            "релизов у репозитория нет. Обновление ещё не опубликовано.")

    pattern = source["asset_pattern"]
    if "{version}" not in pattern:
        raise DownloadError(
            f"в шаблоне имени вложения нет подстановки версии: {pattern!r}")

    def версия_из_имени(asset_name: str) -> str:
        before = pattern.split("{version}", 1)[0]
        after = pattern.split("{version}", 1)[1]
        if not asset_name.startswith(before) or not asset_name.endswith(after):
            return ""
        return asset_name[len(before):len(asset_name) - len(after)] if after \
            else asset_name[len(before):]

    for item in releases:
        names = [a.get("name") or "" for a in (item.get("assets") or [])]
        for candidate in names:
            version = версия_из_имени(candidate)
            if version:
                return item["tag_name"], version

    # Ни одного вложения с версией. Показываем, что есть, — иначе
    # человек гадает, что он приложил не то.
    shown = sorted({(a.get("name") or "") for item in releases[:5]
                    for a in (item.get("assets") or [])})[:8]
    tail = (" Последние вложения: " + ", ".join(shown)) if shown else ""
    raise DownloadError(
        "ни у одного релиза нет вложения вида "
        f"{pattern}.{tail}")


class Cancelled(Exception):
    """Человек закрыл окно. Не ошибка сети и не сбой программы."""


def _download(url: str, dest: Path, what: str,
              timeout: int = 300, cancel=None) -> int:
    """Скачать файл с пределом размера. Возвращает число байт.

    `cancel` — функция без аргументов, возвращающая истину, когда надо
    прекратить. Проверяется перед каждой записью и после каждой: иначе
    закрытие окна во время загрузки оставило бы недокачанный файл во
    временной папке, а следующий запуск принял бы его за годный архив.

    Отмена не бросает исключение наружу сама: файл удаляется, а дальше
    поднимается `Cancelled`, чтобы вызывающий отличил «человек закрыл
    окно» от «сеть отвалилась».
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = dict(resp.headers)
            length = headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise DownloadError(
                    f"{what}: файл {int(length):,} байт больше предела "
                    f"{MAX_BYTES:,}. Загрузка остановлена, чтобы не съесть "
                    f"место.")
            if cancel is not None and cancel():
                raise Cancelled
            got = 0
            with dest.open("wb") as handle:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_BYTES:
                        raise DownloadError(
                            f"{what}: ответ больше предела {MAX_BYTES:,} "
                            f"байт. Загрузка остановлена.")
                    handle.write(chunk)
                    if cancel is not None and cancel():
                        # Файл недокачан: он удаляется, чтобы не остаться
                        # во временной папке и не быть принят загодный.
                        handle.close()
                        dest.unlink(missing_ok=True)
                        raise Cancelled
    except Cancelled:
        raise
    except urllib.error.HTTPError as exc:
        raise DownloadError(_describe_http(exc.code,
                                           dict(exc.headers or {}),
                                           what)) from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"{what}: сеть не ответила: {exc.reason}") from exc
    except OSError as exc:
        raise DownloadError(f"{what}: не получилось: {exc}") from exc
    return got


def fetch_checksum(url: str, timeout: int = 120) -> str:
    """Прочитать ожидаемую сумму из файла `.sha256`.

    Формат принят тот, что даёт `sha256sum`: `сумма  имя`, где имя может
    стоять, а может нет. Берётся первое поле — это единственное, что
    является суммой.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise DownloadError(_describe_http(
            exc.code, dict(exc.headers or {}),
            "файл контрольной суммы")) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DownloadError(f"файл контрольной суммы: {exc}") from exc
    for line in text.splitlines():
        token = line.strip().split(None, 1)[0] if line.strip() else ""
        if len(token) == 64 and all(
                ch in "0123456789abcdefABCDEF" for ch in token):
            return token.lower()
    raise DownloadError(
        "в файле контрольной суммы не нашлось 64 знаков хекса. Файл "
        "приложен неверно.")


def file_sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    """Хекс-сумма файла по кускам: целиком в память архив не влезает."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def download(source: dict, tag: str, version: str, into: Path,
             progress=None, cancel=None) -> tuple[bool, str]:
    """Скачать и проверить архив. Возвращает (вышло, текст).

    Порядок именно такой: сначала сумма, потом архив. Обратный порядок
    означал бы сотни мегабайт трафика ради проверки, которая дешёвая и
    делается первой.

    `cancel` — функция без аргументов, возвращающая истину, когда человек
    закрыл окно. Проверяется и до загрузки, и после каждого куска.
    """

    def say(text: str) -> None:
        if progress:
            progress(text)

    def stop_now() -> bool:
        return bool(cancel and cancel())

    def give_up(text: str) -> tuple[bool, str]:
        """Отмена. Убирает всё, что успела накачать, и возвращает текст.

        Отдельная функция, потому что отмен три, а убирать надо в каждой:
        сумма маленькая и безвредная сама по себе, но оставленная во
        временной папке, она делает состояние папки неоднозначным — то ли
        попытка идёт, то ли это осталось от прошлой. Первая версия убирала
        файлы только в ветке отмены загрузки, и отмена сразу после суммы
        оставляла её на диске: обещание «в папке ничего не остаётся» не
        выполнялось.
        """
        try:
            for item in into.iterdir():
                if item.is_file():
                    item.unlink()
        except OSError:
            pass  # не смогли убрать — не повод врать об отмене
        return False, text

    try:
        asset, checksum_name = _asset_names(source, version)
        sum_url = asset_url(source, checksum_name)
    except SourceError as exc:
        return False, str(exc)

    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)

    if stop_now():
        return give_up("остановлено: окно закрыто")

    say("проверяю контрольную сумму…")
    try:
        expected = fetch_checksum(sum_url)
    except DownloadError as exc:
        return False, (
            f"Без суммы архив качать нельзя: он будет распакован поверх "
            f"рабочей программы. {exc}")
    say(f"  ожидается: {expected[:16]}…")

    if stop_now():
        return give_up("остановлено: окно закрыто")

    say(f"качаю {asset}…")
    archive = into / asset
    try:
        got = _download(asset_url(source, asset), archive, "архив",
                        cancel=cancel)
    except Cancelled:
        # Недокачанный архив уже удалён в `_download`. Убираем всё
        # остальное, чтобы во временной папке не осталось следов
        # прерванной попытки.
        return give_up("остановлено: окно закрыто")
    except DownloadError as exc:
        return False, str(exc)
    say(f"  скачано {got:,} байт")

    say("сверяю сумму…")
    actual = file_sha256(archive)
    if actual != expected:
        archive.unlink(missing_ok=True)
        return False, (
            f"сумма не совпала: ожидалось {expected[:16]}…, "
            f"получилось {actual[:16]}…. Архив удалён и не будет применён.")
    say(f"  совпало: {actual[:16]}…")

    ok, note = check_archive(archive)
    if not ok:
        return False, note
    return True, f"архив скачан и проверен: {archive.name}, {got:,} байт"


def _asset_names(source: dict, version: str) -> tuple[str, str]:
    import update_source

    return update_source.asset_name(source, version)


def safe_members(archive: Path, into: Path) -> list[str]:
    """Имена записей архива, безопасные для распаковки.

    Отсеивается всё, что после распаковки окажется вне `into`: абсолютные
    пути, буквы диска, `..` в любом сегменте, симлинки. Проверка идёт ДО
    записи: после распаковки файлы уже на диске, и «ничего не распаковано,
    потому что нашлось плохое имя» уже неправда.
    """
    base = Path(into).resolve()
    good: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            parts = [p for p in name.split("/") if p not in ("", ".")]
            # Одной проверки достаточно: сегмент ровно `..` — это и есть
            # выход вверх. Раньше стояло две (`any(part == "..")` и
            # `".." in name.split("/")`), и вторая перехватывала всё
            # раньше первой: поломка первой ничего не меняла, и
            # доказательство откатом её не видело. Мёртвая проверка в
            # коде — это код, который никто не проверяет.
            if any(part == ".." for part in parts):
                continue
            if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
                continue
            # Признак симлинки в zip: атрибут 0xA000 записан в старших
            # битах внешних атрибутов.
            if (info.external_attr >> 16) & 0xA000 == 0xA000:
                continue
            target = (base / Path(*parts)).resolve()
            try:
                target.relative_to(base)
            except ValueError:
                continue
            good.append(name)
    return good


def check_archive(archive: Path) -> tuple[bool, str]:
    """Проверить архив перед применением: читается и не выходит наружу."""
    archive = Path(archive)
    if not archive.is_file():
        return False, f"архива нет: {archive}"
    try:
        members = safe_members(archive, archive.parent)
    except zipfile.BadZipFile as exc:
        return False, f"скачалось не то, это не zip: {exc}"
    except OSError as exc:
        return False, f"архив не читается: {exc}"
    if not members:
        return False, ("в архиве нет ни одной безопасной записи — "
                       "возможно, он собран из ссылок или путей вверх.")
    return True, f"архив читается, безопасных записей: {len(members)}"


class DownloadError(Exception):
    """Обновление не скачалось. Текст — для человека."""