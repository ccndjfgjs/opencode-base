# -*- coding: utf-8 -*-
r"""Обновление моста OmniRoute с официального GitHub.

**Что это.** Версию моста человек спрашивает у официального
репозитория `diegosouzapw/OmniRoute` — того же, что прописан в реестре
моста. Сравнивается она с той, что стоит на диске, и если новая есть,
программа ставит именно её.

**Почему версия из GitHub, а пакет из npm.** Так вышло по двум
разным причинам, и их важно не смешивать.

*Версию* надо у официального источника, а не у npm. Именно это человек
и просил, и именно тут проверяемо: метки `v3.8.51` в репозитории
есть. Взять ту же цифру из npm-пакета — значит спросить у того же
поставщика дважды и получить от него два разных ответа.

*Пакет* ставится из npm, потому что в релизах GitHub его нет.
Проверено 19.10.2026: у релиза `v3.8.51` восемнадцать вложений, и это
настольные сборки (`.exe`, `.AppImage`, `.dmg`, `.deb`) и исходники
(`.source.zip`, `.source.tar.gz`). Пригодного для моста нет ни одного.
Ставить из исходников — это в разы тяжелее, без подписи сборки
программы и с выдуманным шагом сборки. `npm install omniroute@<версия>`
берет ровно ту версию, которую назвал GitHub.

**Почему версия закрепляется в команде.** `npm install omniroute@latest`
между проверкой и установкой вправе отдать другую версию: человек
увидит в подписи `3.8.52`, а получит `3.9.0`. Поэтому в команде
пишется номер из подписи, а не `latest`.

**Почему адрес проверяется чужим слоем.** Источник обновления самой
программы приезжает внутри обновляемого архива, и доверять ему без
проверки — значит оставить человеку возможность перенаправить
обновление куда угодно. Здесь ровно тот случай, поэтому адрес
проверяется `update_source.check_url`: только HTTPS, только
`github.com` и `api.github.com`. Свой разбор правил означал бы, что
они завтра разойдутся с общими.

**Лимит запросов.** GitHub без ключа отдаёт 60 запросов в час на
адрес. Поэтому один запрос на одну проверку, остаток показывается
человеку, а при отказе по лимиту сказано именно про лимит, а не
«сеть не ответила».
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import omniroute  # noqa: E402
import update_source  # noqa: E402
import versions as _vs  # noqa: E402

#: Официальный репозиторий OmniRoute. Тот же, что в реестре моста:
#: модуль и реестр обязаны называть один адрес, иначе один из них
#: со временем начнёт врать.
OWNER = "diegosouzapw"
REPO = "OmniRoute"

#: Куда идти за списком меток. api.github.com отдаёт его без ключа.
TAGS_URL = "https://api.github.com/repos/{owner}/{repo}/tags"

#: Кто мы для GitHub. Без этого заголовка API отвечает 403.
USER_AGENT = "opencode-base-omniroute-update"

#: Сколько ждать ответа. Список меток маленький, но сеть медленная.
TIMEOUT = 60

#: Где в сообщениях человек видит источник.
SOURCE_LABEL = f"https://github.com/{OWNER}/{REPO}"


class UpdateError(Exception):
    """Обновиться не вышло. Текст — для человека."""


def official_source() -> dict:
    """Источник в том же виде, что ждёт `update_source`."""
    return {"owner": OWNER, "repo": REPO, "host": update_source.DOWNLOAD_HOST}


def tags_url(source: dict | None = None) -> str:
    """Адрес списка меток, проверенный общим слоем.

    Проверка не выдумывается здесь: подставляем то, что дали, и
    спрашиваем `update_source.check_url`. Если host или схема не те —
    отказ с текстом, а не молчаливая загрузка по чужому адресу.
    """
    src = source or official_source()
    url = TAGS_URL.format(owner=src["owner"], repo=src["repo"])
    update_source.check_url(url)
    return url


def pick_version(tags: list) -> tuple[str, str]:
    """Самая свежая метка с номером версии: (метка, версия).

    Метки без номера — `before-something`, `nightly` — версиями не
    являются и в сравнении не участвуют. Превращать их в «0» нельзя:
    ноль — валидная версия, и мост был бы объявлен устаревшим.
    """
    parsed = []
    for item in tags or []:
        name = item.get("name") if isinstance(item, dict) else item
        pair = update_source.split_tag(str(name or ""))
        if pair:
            parsed.append(pair)
    if not parsed:
        raise UpdateError(
            "в репозитории не нашлось ни одной метки с номером версии. "
            "Метки вида `nightly` или `before-…` версиями не являются.")
    return max(parsed, key=lambda pair: _vs.version_tuple(pair[1]))


def latest_version(fetch=None) -> tuple[str, str]:
    """Спросить официальный GitHub: (метка, версия).

    `fetch` подменяется в проверке: реальный запрос без человека
    делать нельзя. Отказ приходит текстом, а не трассировкой —
    текст показывается в окне.
    """
    url = tags_url()
    getter = fetch or _fetch_tags
    try:
        tags, note = getter(url)
    except UpdateError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"GitHub не ответил: {exc}") from exc
    if not isinstance(tags, list):
        raise UpdateError("ответ GitHub не похож на список меток: "
                          f"{str(tags)[:120]}")
    tag, version = pick_version(tags)
    if note:
        pass  # остаток лимита доведёт вызывающий
    return tag, version


def _fetch_tags(url: str) -> tuple[list, str]:
    """Забрать список меток. Возвращает (метки, примечание)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            headers = dict(resp.headers)
            body = resp.read()
    except urllib.error.HTTPError as exc:
        headers = dict(exc.headers) if exc.headers else {}
        if exc.code in (403, 429):
            left = headers.get("X-RateLimit-Remaining")
            if left == "0":
                reset = headers.get("X-RateLimit-Reset") or "позже"
                raise UpdateError(
                    "GitHub не даёт запросы без ключа: лимит 60 в час на "
                    f"адрес исчерпан, восстановление {reset}. Повтори "
                    "позже — программа тут ни при чём.") from exc
        raise UpdateError(
            f"GitHub ответил кодом {exc.code}: "
            f"{exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"сеть не ответила: {exc}") from exc
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise UpdateError(f"ответ GitHub не разобран: {exc}") from exc
    left = headers.get("X-RateLimit-Remaining")
    limit = headers.get("X-RateLimit-Limit")
    note = ""
    if left and limit:
        note = f"Осталось запросов к GitHub: {left} из {limit}."
    return (data if isinstance(data, list) else []), note


def is_newer(here: str, there: str) -> bool:
    """Новее ли `there`, чем `here`. Сравнение числовое, не строковое.

    Строковое сравнение объявило бы `3.8.9` новее `3.8.51` — а это
    откат, и человек получил бы старую версию вместо новой.
    """
    if not here or not there:
        return True
    return _vs.version_tuple(there) > _vs.version_tuple(here)


def install_argv(version: str) -> list[str]:
    """Команда установки ровно названной версии.

    `npm` берётся у моста: тот же поиск, что и при развёртывании, и
    поэтому подставится та же самая программа.
    """
    npm = omniroute.npm_exe()
    if not npm:
        raise UpdateError(
            "npm не найден. Он ставится вместе с Node.js: "
            "https://nodejs.org/ — без него пакет не обновить.")
    text = str(version or "").strip()
    if not text:
        raise UpdateError("версия не названа — обновлять нечем.")
    return omniroute._wrap_cmd([
        npm, "install", f"{omniroute.PACKAGE}@{text}",
        "--no-audit", "--no-fund", "--loglevel=warn",
    ])


def check(dest: Path, remote: str = "", progress=None) -> tuple[list[str], list[str]]:
    """Что стоит и что предлагает официальный GitHub.

    `remote` передаётся снаружи, чтобы проверка не ходила в сеть: сеть
    спрашивает `latest_version`, а сравнивать уже никто не должен
    дважды.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    if not omniroute.deployed():
        return ["Мост не развёрнут: нажми «Развернуть» у строки OmniRoute — "
                "иначе обновлять нечего."], []
    here = omniroute.installed_version() or ""
    if not here:
        return ["Версия моста не названа: в папке пакета нет "
                "package.json. Обновлять нечего — нажми «Развернуть»."], []
    say(f"Стоит: OmniRoute {here}.")
    say(f"Источник версии: {SOURCE_LABEL}")
    if not remote:
        return messages, ["Версия в репозитории не названа: нечем обновлять."]
    say(f"В репозитории: {remote}.")
    if not is_newer(here, remote):
        say(f"Обновлений нет: стоит {here}, а в репозитории {remote} — "
            "не новее.")
    return messages, errors


def install(dest: Path, version: str, progress=None) -> tuple[list[str], list[str]]:
    """Поставить названную версию и проверить результат по-настоящему.

    Итог судится тем, что лежит на диске после установки, а не кодом
    npm: код у npm и у OmniRoute на Windows бывает врёт, а папка пакета
    врать не может.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    argv = install_argv(version)
    say(f"Ставлю OmniRoute {version}: npm install, это сотни мегабайт и "
        "несколько минут…")
    try:
        code, out, err = omniroute.run_argv(
            argv, omniroute.SERVER_DIR, dest, timeout=omniroute.INSTALL_TIMEOUT)
    except OSError as exc:
        return messages, [f"Запуск npm не удался: {exc}"]
    if code != 0:
        tail = omniroute._tail(err or out)
        return messages, [f"npm вернул код {code}: {tail}"]
    got = omniroute.installed_version() or ""
    if not got:
        return messages, [
            "npm отработал, но версия на диске не названа — папка пакета "
            "не появилась или не прочиталась.",
        ]
    say(f"На диске теперь OmniRoute {got}.")
    if got != str(version):
        errors.append(
            f"Поставили не то: просили {version}, а на диске {got}. "
            "Возможно, у npm нет такой версии.")
        return messages, errors
    say("Мост обновлён. Нажми «Перезапустить» у строки OmniRoute — сервер "
        "работает на старой версии до перезапуска.")
    return messages, errors