"""Категории мостов (серверов MCP) для подменю в сайдбаре.

Зачем отдельный модуль. В реестре `данные/mcp-registry.json` категории
нет: там только id, имя, команда подключения и требования. Подменю
строится по явному списку ниже — так же, как `program_groups.EXPLICIT`,
и по той же причине: категория, выведенная из названия наугад, — это
враньё в интерфейсе. Здесь каждое отнесение названо прямо.

Порядок групп задан вручную: сначала то, ради чего окно открывают
(агенты, движки), служебное — в конце. Всё, чего нет в списке, попадает
в «Прочее»; на текущем реестре «Прочее» обязано быть пустым, и это
видно сразу — пустая группа не показывается.

При росте реестра (75, 150 мостов) правится только BY_ID и, если нужно,
GROUPS: интерфейс, поиск и фильтр менять не придётся.
"""

from __future__ import annotations

#: (id группы, подпись в сайдбаре) — в порядке показа.
GROUPS: tuple[tuple[str, str], ...] = (
    ("agents", "ИИ-агенты"),
    ("engines", "Движки и 3D"),
    ("media", "Медиа и видео"),
    ("office", "Офис"),
    ("comms", "Мессенджеры"),
    ("dev", "Разработка и система"),
    ("data", "Базы данных"),
    ("finance", "Финансы"),
    ("security", "Безопасность"),
    ("reverse", "Реверс-инжиниринг"),
    ("web", "Браузеры и сеть"),
    ("service", "Служебные"),
    ("other", "Прочее"),
)

GROUP_TITLES = dict(GROUPS)

#: Короткие подписи для колонки таблицы: полные («Разработка и система»)
#: не влезают в узкую колонку и переносятся на две строки.
SHORT_TITLES: dict[str, str] = {
    "agents": "ИИ",
    "engines": "Движки",
    "media": "Медиа",
    "office": "Офис",
    "comms": "Чаты",
    "dev": "Система",
    "data": "Базы",
    "finance": "Финансы",
    "security": "Защита",
    "reverse": "Реверс",
    "web": "Сеть",
    "service": "Служебные",
    "other": "Прочее",
}

#: id сервера → id группы. Список явный; причина у каждой строки — в
#: названии самого моста или в его описании в реестре.
BY_ID: dict[str, str] = {
    # ИИ-агенты: CLI и облачные ассистенты
    "chatgpt": "agents",
    "codex": "agents",
    "cursor": "agents",
    "claude": "agents",
    # Движки, 3D и игровые студии
    "unity": "engines",
    "unreal": "engines",
    "roblox-studio": "engines",
    "godot": "engines",
    "blender": "engines",
    # Медиа: запись, монтаж, музыка, соцсети
    "obs": "media",
    "tiktok": "media",
    "capcut": "media",
    "kinocut": "media",
    "spotify": "media",
    "comfyui": "media",
    "davinci-resolve": "media",
    "premiere-pro": "media",
    "twitch": "media",
    # Офис
    "excel": "office",
    "adobe-creativity": "office",
    "notion": "office",
    "word": "office",
    "powerpoint": "office",
    "libreoffice": "office",
    "gmail": "office",
    "google-workspace": "office",
    # Мессенджеры
    "slack": "comms",
    "discord": "comms",
    "telegram": "comms",
    # Разработка и система
    "android-studio": "dev",
    "android-emulator": "dev",
    "ldplayer": "dev",
    "windows-admin": "dev",
    "desktop-commander": "dev",
    "docker": "dev",
    "ssh": "dev",
    "jetbrains": "dev",
    # Данные
    "dbhub": "data",
    "mongodb": "data",
    "postgres": "data",
    "supabase": "data",
    "firebase": "data",
    # Финансы: биржи и рыночные данные
    "okx": "finance",
    "coincap": "finance",
    "coinmarketcap": "finance",
    "unusual-whales": "finance",
    # Безопасность: поиск по базам, без сканирования
    "shodan": "security",
    "censys": "security",
    # Реверс-инжиниринг
    "ghidra-mcp": "reverse",
    # Браузеры и сеть
    "browsers": "web",
    "cloudflare": "web",
    # Служебное самой программы
    "omniroute": "service",
    "lmarena": "service",
    "mcp-doctor": "service",
    # Память базы: сервер поднимает сама программа при выборе типа
    # памяти Hindsight в окне создания базы.
    "hindsight": "service",
}


def group_of(server_id: str) -> str:
    """Группа сервера. Неизвестный id — «Прочее», и это видно в списке."""
    return BY_ID.get(str(server_id or ""), "other")


def title(group: str) -> str:
    """Подпись группы для сайдбара и колонки в таблице."""
    return GROUP_TITLES.get(group, GROUP_TITLES["other"])


def short_title(group: str) -> str:
    """Короткая подпись для колонки «Категория» в таблице."""
    return SHORT_TITLES.get(group, SHORT_TITLES["other"])
