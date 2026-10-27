"""Категории программ в реестре: куда положить карточку и почему.

Задача модуля одна — разложить мосты по группам так, чтобы человек
находил нужный с первого взгляда, и **объяснить каждое решение**. Вторая
часть важнее первой: группа, выбранная молча, не проверяется.

Правил два вида, и это разные вещи:

1. **По данным реестра** — плагин из указателя движка или издатель в
   списке. Таких мостов 12 из 54, и их разложение выводится само.
2. **Явный список** — 42 моста, у которых в данных сигнала нет: Excel
   ставится не через winget, TikTok и ChatGPT тоже, а «мост к эмулятору»
   из названия издателя не выводится в принципе. Список вырос 23.10.2026
   вместе с реестром: у большинства новых мостов нет устанавливаемой
   программы вовсе — это сервисы (почта, мессенджеры, базы, биржи), и
   сигнала в данных у них не будет никогда. Для них список назван прямо
   и помечен как список, а не подан как «программа сама догадалась».

Всё, что не сработало ни по правилу, ни из списка, попадает в группу
«Прочее». Она для этого и нужна: на настоящем реестре она обязана быть
пустой, и это проверяется отдельно — пустая «Прочее» означает, что ни
один мост не потерялся при размышлении.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Группы в порядке показа. Порядок задан здесь, а не по алфавиту:
#: человек ищет движок первым, а «Прочее» в конце — это то, что осталось.
GROUPS: tuple[tuple[str, str], ...] = (
    ("engines", "Движки и игры"),
    ("editors", "Редакторы и студии"),
    ("office", "Офис и работа"),
    ("media", "Творчество и медиа"),
    ("record", "Запись и стриминг"),
    ("devices", "Машина, эмуляторы и система"),
    ("shared", "Общие программы"),
    ("bridges", "Служебные мосты"),
    ("other", "Прочее"),
)

GROUP_TITLES = dict(GROUPS)

#: Сколько групп у карточки — уже «общая программа». Node.js нужен шести
#: мостам из шести разных групп, uv/uvx — двум. По первому мосту такие
#: карточки выдавали себя за движки: Node.js стоял в «Движках и играх»
#: только потому, что Unreal попался первым. Общая программа — это и есть
#: отдельная группа, и называть её «движками» было бы враньём в интерфейсе.
SHARED_MIN_GROUPS = 2

#: Семейства указателей, за которыми стоят движки и игры. Плагин движка —
#: самый честный сигнал: он стоит внутри проекта чужой программы.
ENGINE_FAMILIES = ("unity-mcp", "enginewire", "godot-ai")
#: Расширения чужих программ: тоже движки по смыслу, но не по названию.
EDITOR_FAMILIES = ("ghidra-mcp",)

#: Издатели в winget — сигнал по данным. Проверяется по началу строки,
#: потому что `Unity.UnityHub` и `Unity.Unity.6000` — один издатель.
PUBLISHERS: dict[str, tuple[str, ...]] = {
    "engines": ("Unity.", "EpicGames.", "GodotEngine.", "Roblox."),
    "editors": ("Google.", "JetBrains.", "BlenderFoundation."),
    "office": ("Microsoft.Office", "Adobe."),
    "media": ("Spotify.", "ByteDance."),
    "record": ("OBSProject.",),
}

#: Мосты, у которых в реестре нет сигнала. Список явный: иначе пришлось
#: бы угадывать по названию моста, а это враньё в коде.
#: Причина у каждого — почему сигнала нет. После роста реестра 23.10.2026
#: записей стало больше, чем правил: сервис (почта, мессенджер, база,
#: биржа) не ставится на машину, и вывести его группу из данных не из чего.
#:
#: Четыре CLI ИИ-агентов (ChatGPT, Codex, Cursor, Claude) лежат в группе
#: «Служебные мосты» вместе с dbhub и browsers: это мосты к чужой программе,
#: которая ставится не через winget. Отдельная восьмая группа для них —
#: вопрос к человеку; если он скажет «да», это одна правка в EXPLICIT плюс
#: одна строка в GROUPS, и ни одно другое место не меняется.
EXPLICIT: dict[str, tuple[str, str]] = {
    "excel": ("office", "программа ставится не через winget: в реестре метода нет"),
    "tiktok": ("media", "своё приложение, winget-идентификатора нет"),
    "chatgpt": ("bridges", "облачный сервис: программа на машине не ставится"),
    "codex": ("bridges", "CLI ИИ-агента, официальная установка, winget-идентификатора нет"),
    "cursor": ("bridges", "CLI ИИ-агента, официальная установка, winget-идентификатора нет"),
    "claude": ("bridges", "CLI ИИ-агента, официальный установщик, winget-идентификатора нет"),
    "windows-admin": ("devices", "winget-идентификатор — это Node.js, а не система"),
    "android-emulator": ("devices", "мост к устройству: издателя нет"),
    "ldplayer": ("devices", "мост к устройству: издателя нет"),
    "dbhub": ("bridges", "мост к базам данных, программа не ставится"),
    "kinocut": ("bridges", "мост к монтажу видео, программа не ставится"),
    "hindsight": ("bridges", "банк памяти: сервер ставит и поднимает сама программа (uv/docker), внешней программы-издателя нет"),
    "browsers": ("bridges", "мост к браузеру, программа не ставится"),
    "omniroute": ("bridges", "шлюз программы, внешней программы нет"),
    "lmarena": ("bridges", "мост к сайту, внешней программы нет"),
    "mcp-doctor": ("bridges", "мост самой программы: он проверяет остальные, а не подключается к программе"),
    # ---- добавлено 23.10.2026 вместе с 28 недостающими мостами.
    # Premiere Pro здесь нет намеренно: у него winget-идентификатор
    # Adobe.CreativeCloud, и правило издателя ставит его в «Офис и работу»
    # раньше явного списка — рядом с карточкой Creative Cloud, откуда он и
    # ставится. Дублировать это решение в списке значило бы соврать о том,
    # какое правило сработало.
    "notion": ("office", "сервис, а не редактор: программа не ставится"),
    "word": ("office", "подписка Microsoft 365, winget-идентификатора нет"),
    "powerpoint": ("office", "подписка Microsoft 365, winget-идентификатора нет"),
    "libreoffice": ("office", "офисный пакет; издатель The Document Foundation не в списке издателей"),
    "gmail": ("office", "почтовый сервис, программа не ставится"),
    "google-workspace": ("office", "облачный офис, программа не ставится"),
    "comfyui": ("media", "переносная программа на Python, winget-идентификатора нет"),
    "davinci-resolve": ("media", "установщик с сайта Blackmagic, winget-идентификатора нет"),
    "twitch": ("media", "сервис стриминга, программа не ставится"),
    "jetbrains": ("editors", "IDE ставится своим установщиком, winget-идентификатора нет"),
    "desktop-commander": ("devices", "мост к файлам и терминалу: программа не ставится"),
    "docker": ("devices", "Docker Desktop есть в winget, но издатель Docker Inc. не в списке издателей"),
    "ssh": ("devices", "мост к чужим машинам: программа не ставится"),
    "slack": ("bridges", "мессенджер: программа на машине не ставится"),
    "discord": ("bridges", "мессенджер: программа на машине не ставится"),
    "telegram": ("bridges", "мессенджер: программа на машине не ставится"),
    "cloudflare": ("bridges", "удалённый сервер вендора: программа не ставится"),
    "mongodb": ("bridges", "мост к базе данных, программа не ставится"),
    "postgres": ("bridges", "мост к базе данных, программа не ставится"),
    "supabase": ("bridges", "мост к базе данных, программа не ставится"),
    "firebase": ("bridges", "мост к базе данных, программа не ставится"),
    "okx": ("bridges", "биржевые данные, программа не ставится"),
    "coincap": ("bridges", "биржевые данные, программа не ставится"),
    "coinmarketcap": ("bridges", "биржевые данные, программа не ставится"),
    "unusual-whales": ("bridges", "биржевые данные, программа не ставится"),
    "shodan": ("bridges", "поиск по базе вендора, программа не ставится"),
    "censys": ("bridges", "поиск по базе вендора, программа не ставится"),
}


@dataclass
class Placement:
    """Куда положен мост и каким правилом."""

    bridge: str = ""
    group: str = "other"
    rule: str = ""

    @property
    def title(self) -> str:
        return GROUP_TITLES.get(self.group, GROUP_TITLES["other"])


#: Карточки программ, у которых в реестре нет мостов вообще. Их строит не
#: реестр, а другая проверка (обход блокировок), и в раскладке по мостам они
#: не видны — без отдельной строки они молча уехали бы в «Прочее».
CARD_ONLY: dict[str, tuple[str, str]] = {
    "xray-core": ("devices", "обход блокировок, к мостам реестра отношения не имеет"),
}


def _family(server) -> str:
    install = getattr(server, "program_install", None)
    plugin = getattr(install, "plugin", None) if install is not None else None
    return str(getattr(plugin, "finder", "") or "")


def _winget(server) -> str:
    install = getattr(server, "program_install", None)
    return str(getattr(install, "winget_id", "") or "") if install is not None else ""


def family_of(server) -> str:
    """Семейство указателя по имени моста (пусто — указателя нет)."""
    try:
        import editor_plugins  # noqa: PLC0415 — тяжёлый модуль, нужен здесь

        return editor_plugins.family_for(_family(server))
    except ImportError:
        return ""


def place(server) -> Placement:
    """Куда положить мост и почему. Порядок правил важен."""
    bridge = str(getattr(server, "id", "") or "")
    family = family_of(server)
    if family in ENGINE_FAMILIES:
        return Placement(bridge, "engines",
                         f"плагин из указателя движка: {family}")
    if family in EDITOR_FAMILIES:
        return Placement(bridge, "editors",
                         f"плагин-расширение чужой программы: {family}")
    winget = _winget(server)
    for group, prefixes in PUBLISHERS.items():
        for prefix in prefixes:
            if winget.startswith(prefix):
                return Placement(bridge, group,
                                 f"издатель в winget: {winget}")
    if bridge in EXPLICIT:
        group, why = EXPLICIT[bridge]
        return Placement(bridge, group, f"явный список: {why}")
    return Placement(bridge, "other",
                     "ни одно правило не сработало — это видно, а не спрятано")


def placements(servers) -> list[Placement]:
    """Все мосты с их группами, в порядке групп."""
    items = [place(server) for server in servers]
    order = {key: index for index, (key, _title) in enumerate(GROUPS)}
    return sorted(items, key=lambda item: (order.get(item.group, len(order)),
                                           item.bridge))


def groups(items) -> list[tuple[str, str, list]]:
    """Группы по порядку: ключ, заголовок, мосты внутри. Пустые группы убираются."""
    order = {key: index for index, (key, _title) in enumerate(GROUPS)}
    buckets: dict[str, list] = {key: [] for key, _title in GROUPS}
    for item in items:
        buckets.setdefault(item.group, []).append(item)
    out: list[tuple[str, str, list]] = []
    for key, title in sorted(GROUPS, key=lambda pair: order[pair[0]]):
        if buckets.get(key):
            out.append((key, title, buckets[key]))
    return out


def by_bridge(servers) -> dict[str, Placement]:
    """Разложение «мост → куда», чтобы не считать одно и то же дважды."""
    return {item.bridge: item for item in placements(servers)}


def place_card(card, placed: dict[str, Placement]) -> Placement:
    """Группа карточки программы и причина.

    Карточка — это программа, а мостов у неё может быть несколько: Node.js
    нужен и OBS, и Blender. Группа берётся по первому мосту в порядке групп,
    а чужие группы перечислены рядом и **с ограничением по числу**: полный
    список у Node.js нечитаем, и человек перестал бы его читать.

    Отдельная строка — для программ, которых в реестре нет вовсе (обход
    блокировок). Их строит не реестр, и без `CARD_ONLY` они уехали бы в
    «Прочее» молча.
    """
    key = str(getattr(card, "key", "") or getattr(card, "name", "") or "")
    items = [placed[str(b)] for b in (getattr(card, "servers", None) or [])
             if str(b) in placed]
    if not items:
        for name, (group, why) in CARD_ONLY.items():
            if key == name or key.startswith(name):
                return Placement("", group, f"карточка без мостов в реестре: {why}")
        return Placement("", "other",
                         "у программы нет мостов в реестре — карточку построила "
                         "другая проверка, и группа не выведена")
    groups = sorted({item.group for item in items},
                    key=lambda key: [k for k, _t in GROUPS].index(key)
                    if key in GROUP_TITLES else len(GROUPS))
    if len(groups) >= SHARED_MIN_GROUPS:
        # Общая программа: нужна мостам из разных групп, и любая одна
        # группа была бы про неё ложью. Группы названы по-человечески, иначе
        # в подписи карточки читалось бы «из 6 групп: bridges, devices…».
        return Placement("", "shared",
                         f"нужна мостам из {len(groups)} групп: "
                         f"{', '.join(GROUP_TITLES.get(key, key) for key in groups)}")
    first = items[0]
    return Placement(first.bridge, first.group,
                     f"по мосту {first.bridge} — {first.rule}")
