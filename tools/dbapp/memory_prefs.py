"""Настройки выбора типа памяти в окне создания базы.

Раньше здесь жили два флажка Obsidian. Теперь — строго один тип памяти
(NCP / Obsidian / Hindsight): хранилище у базы одно, и сочетания двух
хранилищ нет (решение человека 25.10.2026). Способ установки
Hindsight (uv / docker) — тоже настройка окна.

Файл настроек — тот же, что у старых флажков, чтобы они и новая
запись не конфликтовали: данные лежат рядом с программой, а не в базе.
Состояние окна — это не данные пользователя.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAM = HERE.parent.parent
PREFS_NAME = "создание-базы.json"
PREFS_PATH = PROGRAM / "данные" / PREFS_NAME

# Типы памяти и значения способа установки — те же, что в core.
MEMORY_DEFAULT = "ncp"
INSTALL_DEFAULT = "uv"  # способ установки Hindsight по умолчанию


def _read() -> dict:
    try:
        data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def load() -> tuple[str, str]:
    """(тип памяти, способ установки) как в прошлый раз. Битые — (ncp, uv)."""
    data = _read()
    memory = str(data.get("memory", "") or "").strip().lower()
    if memory not in ("ncp", "obsidian", "hindsight"):
        memory = MEMORY_DEFAULT
    install = str(data.get("hindsight_install", "") or "").strip().lower()
    if install not in ("uv", "docker"):
        install = INSTALL_DEFAULT
    return memory, install


def save(memory: str, install: str) -> str | None:
    """Пишет тип памяти и способ установки. Существующие базы не меняет."""
    body = json.dumps(
        {
            "memory": memory,
            "hindsight_install": install,
            # прежние флаги пишутся по новой структуре пустыми, чтобы
            # старый код, читающий файл, ничего не сломал
            "obsidian": memory == "obsidian",
            "obsidian_agent": False,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(body, encoding="utf-8")
    except OSError as exc:
        return f"Настройки выбора памяти не сохранились: {exc}"
    return None
