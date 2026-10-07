r"""Источник обновления: откуда и с какого хоста качать.

**Зачем отдельный слой.** Обновление приходит из сети и запускает код, поэтому
проверять надо всё: протокол, хост, имя файла, содержимое. Проверки
разбросаны по трём местам — их легко забыть при добавлении нового пути, и
забытая проверка выглядит как работающая. Здесь все они в одном месте, и
каждый отказ возвращает текст, который можно показать человеку.

**Что проверяется и почему.**

  * **только HTTPS.** По `http://` ответ подделать тривиально: в сети
    нужен не HTTPS, а правильный сертификат, а сам протокол по дороге
    подменяется без усилий. Адрес с `http://` отвергается целиком.
  * **только `github.com`.** Файл из сети будет распакован и запущен.
    Адрес вида `evil.example/github.com` проходит любую проверку на
    подстроку, поэтому сравнивается именно хост, а не весь адрес.
  * **хост проверяется при каждом чтении, а не только при скачивании.**
    `обновление.json` приезжает **внутри** обновляемого архива: после
    обновления адрес читается из нового файла. Значит проверка на границе
    доверия недостаточна — файл из сети нельзя принимать как источник
    доверия.
  * **тег отделён от номера версии.** Метка на GitHub называется
    `v1.0.0`, а версия в файле `ВЕРСИЯ` — `1.0.0`. Подстановка номера в
    адрес даёт `releases/download/1.0.0/…`, что отдаёт 404 на каждом
    релизе. Поэтому возвращаются оба значения.

**Что здесь нет.** Ни скачивания, ни распаковки, ни запуска кода — только
разбор источника и проверки. Скачивание в `download_release`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

#: Файл с адресом источника. Лежит в данных рядом с реестром, а не в коде.
SOURCE_FILE = ("данные", "обновление.json")

#: Хосты GitHub, с которых допустимо брать. Сравнивается точно, а не
#: «есть ли в строке подстрока»: адрес `evil.example/github.com/...`
#: содержит `github.com`, и такая проверка его бы пропустила.
#:
#: Хостов два, и это не опечатка. `api.github.com` отдаёт метаданные —
#: метки и список релизов, через него идёт опрос. `github.com` отдаёт
#: сами вложения, потому что файл релиза лежит по адресу
#: `github.com/…/releases/download/…`, и `api.github.com` для этого не
#: используется. Первая версия проверки знала только `github.com` и
#: падала на собственном же адресе списка меток.
ALLOWED_HOSTS = ("github.com", "api.github.com")

#: Хост, с которого качается сам архив. Отдельно от API: вложение лежит
#: на `github.com`, и подставлять `api.` значит гарантированный 404.
DOWNLOAD_HOST = "github.com"

#: Схема. Только она: по `http://` ответ подменяется без усилий.
ALLOWED_SCHEME = "https://"

#: Куда идти за списком меток. API отдаёт его без токена, измерено
#: 07.10.2026: три метки видны, лимит запросов в заголовке.
API_TAGS = "https://api.github.com/repos/{owner}/{repo}/tags"

#: Список релизов. Нужен отдельно от меток, потому что они не совпадают:
#: измерено на `obsproject/obs-websocket` 07.10.2026 — метки до `5.7.5`,
#: последний релиз `4.9.1-compat`, а запрос описания релиза по `5.7.5`
#: отдал 404. Метка может быть впереди опубликованных релизов, и брать
#: «самую свежую метку» для скачивания нельзя: скачивать нечего.
API_RELEASES = "https://api.github.com/repos/{owner}/{repo}/releases"

#: Куда идти за самим релизом. Здесь `tag`, а не `version`: в адресе
#: релиза живёт имя метки с ведущей `v`, и подстановка номера версии даёт
#: 404 на каждом релизе.
API_RELEASE = "https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"

#: Имя метки, пригодное для разбора версии: начинается с `v`, дальше цифры
#: и точки. Метки вида `before-root-cleanup` под это не подходят, и они
## должны отбрасываться, а не превращаться в версию.
_TAG_RE = re.compile(r"^v(\d+(?:\.\d+)*)$")


class SourceError(Exception):
    """Источник обновления непригоден. Текст — для человека."""


def _normalise_host(host: str) -> str:
    """Хост в нижний регистр без схемы и без пути.

    Отдельная функция, а не `split`: разбирать руками — значит забыть
    про uppercase и про точку с запятой в начале URL.
    """
    text = (host or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = text.split("/", 1)[0]
    return text.split("@")[-1].split(":")[0]


def check_url(url: str, hosts: tuple[str, ...] | None = None) -> str:
    """Проверить адрес и вернуть его же. Иначе SourceError с текстом.

    Проверяется ровно две вещи, и обе — про то, откуда придёт код: схема
    и хост. Всё остальное (путь, имя файла) не влияет на то, с какого
    сервера придёт содержимое.

    `hosts` по умолчанию — оба разрешённых хоста. Для адреса скачивания
    передается один, потому что вложение лежит на `github.com`.
    """
    allowed = hosts or ALLOWED_HOSTS
    text = (url or "").strip()
    if not text:
        raise SourceError("адрес пустой")
    if not text.startswith(ALLOWED_SCHEME):
        raise SourceError(
            f"адрес не {ALLOWED_SCHEME}: {text}. По http ответ подменяется "
            f"без усилий, поэтому такой адрес не берём.")
    host = _normalise_host(text)
    if host not in allowed:
        raise SourceError(
            f"хост {host!r} не из {allowed}: {text}. Из этого адреса "
            f"пришёл бы код, а он будет запущен.")
    return text


def _tags_from_git(repo_root: Path) -> list[str]:
    """Метки из локального git. Запасной путь, а не основной.

    У папки программы `.git` нет, измерено 07.10.2026: `git ls-remote`
    падает с кодом 128. Поэтому этот путь работает только в рабочей копии,
    и вызывающий обязан знать, что путь может не сработать.
    """
    import subprocess

    try:
        done = subprocess.run(
            ["git", "-C", str(repo_root), "ls-remote", "--tags", "origin"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    names: list[str] = []
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[1].endswith("^{}"):
            continue
        names.append(parts[1].rsplit("/", 1)[-1])
    return names


def load_source(base: Path | str | None = None) -> dict:
    """Прочитать источник обновления и проверить его.

    Хост проверяется здесь, при каждом чтении: файл приезжает внутри
    обновляемого архива, и доверять ему без проверки — значит оставить
    человеку возможность перенаправить обновление куда угодно.
    """
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    path = root.joinpath(*SOURCE_FILE)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceError(
            f"файл источника не читается: {path.name} ({exc.strerror}). "
            f"Программа не знает, откуда брать обновление.") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(
            f"файл источника п��вреждён: {exc}. Обновление приостановлено, "
            f"чтобы не качать неизвестно откуда.") from exc

    host = str(data.get("host") or "").strip()
    if _normalise_host(host) != DOWNLOAD_HOST:
        raise SourceError(
            f"в файле источника хост {host!r}, а вложения лежат на "
            f"{DOWNLOAD_HOST!r}. Файл приезжает внутри обновления, поэтому "
            f"его хосту веры нет: проверка при каждом чтении.")

    owner = str(data.get("owner") or "").strip()
    repo = str(data.get("repo") or "").strip()
    if not owner or not repo:
        raise SourceError("в файле источника нет owner или repo")
    for value in (owner, repo):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise SourceError(f"имя репозитория выглядит подозрительно: {value!r}")

    asset = str(data.get("asset_pattern") or "").strip()
    if not asset:
        raise SourceError("в файле источника нет asset_pattern")
    checksum = str(data.get("checksum_pattern") or "").strip()
    if not checksum:
        raise SourceError("в файле источника нет checksum_pattern")
    # Шаблон имени обязан содержать {version}: иначе все релизы получат
    # одно и то же имя файла, и второй релиз не отличить от первого.
    for name, label in ((asset, "asset_pattern"),
                        (checksum, "checksum_pattern")):
        if "{version}" not in name:
            raise SourceError(
                f"в {label} нет подстановки {{version}}: {name!r}")

    return {
        "owner": owner,
        "repo": repo,
        "host": host,
        "asset_pattern": asset,
        "checksum_pattern": checksum,
        "asset_note": str(data.get("asset_note") or ""),
        "path": path,
    }


def tags_url(source: dict) -> str:
    """Адрес списка меток."""
    return check_url(API_TAGS.format(owner=source["owner"],
                                     repo=source["repo"]))


def releases_url(source: dict) -> str:
    """Адрес списка релизов."""
    return check_url(API_RELEASES.format(owner=source["owner"],
                                         repo=source["repo"]))


def release_url(source: dict, tag: str) -> str:
    """Адрес описания релиза по МЕТКЕ, а не по номеру версии.

    Метка называется `v1.0.0`, версия — `1.0.0`. Подстановка номера даёт
    `releases/tags/1.0.0` и 404 на каждом релизе.
    """
    return check_url(API_RELEASE.format(owner=source["owner"],
                                       repo=source["repo"], tag=tag))


def asset_url(source: dict, asset: str) -> str:
    """Адрес вложения релиза.

    Отдельная функция, потому что вложение лежит на `github.com`, а не на
    `api.github.com`: подстановка `api.` в адрес вложения даёт 404, и
    ошибка выглядела бы как «релиз сломан», хотя сломан адрес.
    """
    if "/" in asset or "\\" in asset:
        raise SourceError(f"имя вложения уходит в путь: {asset!r}")
    url = (f"https://{DOWNLOAD_HOST}/{source['owner']}/{source['repo']}"
           f"/releases/download/{asset}")
    return check_url(url, hosts=(DOWNLOAD_HOST,))


def asset_link(release_url_value: str, asset: str) -> str:
    """Прямая ссылка на вложение из ответа API.

    API отдаёт вложения с готовым `browser_download_url` — уже на
    `github.com`. Если собирать адрес из адреса описания релиза, хост
    останется `api.github.com`, а вложения там не лежат: получится 404,
    и ошибка выглядела бы как «релиз сломан». Поэтому хост заменяется
    явно, а не наследуется.
    """
    if "/" in asset or "\\" in asset:
        raise SourceError(f"имя вложения уходит в путь: {asset!r}")
    if "releases/tags/" not in release_url_value:
        raise SourceError(
            f"адрес не похож на адрес описания релиза: "
            f"{release_url_value}")
    prefix = release_url_value.split("/releases/tags/", 1)[0]
    # Хост меняется явно: вложения лежат на github.com, а не на api.
    prefix = prefix.replace(f"https://api.{DOWNLOAD_HOST}",
                            f"https://{DOWNLOAD_HOST}", 1)
    # И путь `/repos/` уходит: адрес вложения его не содержит, и без
    # среза получается `github.com/repos/…/releases/download/…` — 404,
    # который выглядит как «релиз сломан».
    prefix = prefix.split("/repos/", 1)[0]
    url = prefix + "/releases/download/" + asset
    return check_url(url, hosts=(DOWNLOAD_HOST,))


def asset_name(source: dict, version: str) -> tuple[str, str]:
    """Имена файлов релиза: архив и его контрольная сумма."""
    try:
        asset = source["asset_pattern"].format(version=version)
        checksum = source["checksum_pattern"].format(version=version)
    except (KeyError, IndexError) as exc:
        raise SourceError(f"имя файла не подставляется: {exc}") from exc
    # Имя проверяется на `..` ДО подстановки версии и до сравнения: если
    # версия пуста, `format` даст пустое имя, а если версия сама содержит
    # слэш — путь уйдёт куда угодно. Первая проверка стояла после
    # сравнения и пропускала чистое `..`.
    for value in (version,):
        if not value or "/" in str(value) or "\\" in str(value) \
                or str(value) in (".", ".."):
            raise SourceError(f"версия для имени файла не годится: {value!r}")
    for name in (asset, checksum):
        if "/" in name or "\\" in name or name in (".", "..") \
                or ".." in name:
            raise SourceError(f"имя файла уходит в путь: {name!r}")
    return asset, checksum


def split_tag(tag: str) -> tuple[str, str] | None:
    """Разобрать метку на (метка, версия). None — метка не про версию.

    Метки `before-root-cleanup` и `before-root-cleanup-2` версиями не
    являются: они остались от уборки корня и не должны участвовать в
    сравнении версий. Возвращать для них версию «0» нельзя — ноль
    валидная версия, и программа объявила бы обновление.
    """
    match = _TAG_RE.match((tag or "").strip())
    if not match:
        return None
    return tag.strip(), match.group(1)


def latest_tag(source: dict, base: Path | str | None = None,
               fetch=None) -> tuple[str, str]:
    """Самая свежая метка версии: (метка, версия).

    Порядок источников: сначала API — он работает без `.git`, то есть у
    человека. Git — запасной, на случай если API недоступен.

    ВНИМАНИЕ, измерено 07.10.2026 на `obsproject/obs-websocket`: самая
    свежая метка и последний опубликованный релиз — **разные вещи**.
    Там метки дошли до `5.7.5`, а последний релиз — `4.9.1-compat`, и
    запрос описания релиза по метке `5.7.5` отдал 404. То есть метка
    может быть впереди релизов, и «самая свежая метка» не равно «то, что
    можно скачать».

    Отсюда правило: для скачивания годятся только метки, у которых есть
    опубликованный релиз. Проверяет это `latest_release`, а не эта
    функция. Здесь она по-прежнему отвечает на вопрос «какая версия
    вообще объявлена», и это честно другое.
    """
    tags: list[str] = []
    if fetch is not None:
        tags = [str(name) for name in fetch(tags_url(source))]
    if not tags:
        root = Path(base) if base else Path(__file__).resolve().parent.parent
        tags = _tags_from_git(root)

    import versions as _vs

    parsed = []
    for name in tags:
        pair = split_tag(name)
        if pair:
            parsed.append(pair)
    if not parsed:
        raise SourceError(
            "ни одной метки с версией не нашлось. Метки вида "
            "before-root-cleanup версиями не являются и не считаются.")
    return max(parsed, key=lambda pair: _vs.version_tuple(pair[1]))