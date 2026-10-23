# -*- coding: utf-8 -*-
"""Тест bridge_updates без сети: пины, разбор спеков, отказы закреплённым."""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "launchers"))

import bridge_updates as bu  # noqa: E402
import bridge_versions as bv  # noqa: E402

# --- _pinned_version: питон и npm форматы
assert bu._pinned_version("mcpforunityserver==10.3.0") == "10.3.0"
assert bu._pinned_version("mcp-for-blender") == ""
assert bu._pinned_version("pkg==1.2.3.post4") == "1.2.3."
assert bu._pinned_version("адрес от хоста") == ""
assert bu._pinned_version("@getmcpads/tiktok-ads-mcp-server@2.0.1") == "2.0.1"
print("1. _pinned_version — оба формата, верно")

# --- venv_python_for: kinocut по конфигу настроек, чужой мост — пусто
tmp = Path(tempfile.mkdtemp())
(tmp / "mcp-kinocut.json").write_text(
    json.dumps({"kino": r"C:\kino\.venv\Scripts\kino.exe"}), encoding="utf-8")
py = bu.venv_python_for("kinocut", tmp)
assert str(py).endswith("python.exe") and py.parent.name == "Scripts", py
assert bu.venv_python_for("dbhub", tmp) == Path()  # нет постоянного окружения
assert bu.venv_python_for("kinocut", tmp / "нет") == Path()
assert bu.venv_version(tmp / "нет" / "python.exe", "kinocut") == ""
print("2. venv_python_for и venv_version — из конфига, отказы без падений")

# --- installed_version по настоящей таблице
table, note = bv.load(None)
assert table is not None, note
bridges = table["bridges"]
assert bu.installed_version("unity", bridges["unity"]) == "10.3.0"
assert bu.installed_version("tiktok", bridges["tiktok"]) == "2.0.1"
assert bu.installed_version("dbhub", bridges["dbhub"]) == ""
assert bu.installed_version("kinocut", bridges["kinocut"], tmp) == ""
print("3. installed_version — пины, venv, честная пустота")


# --- вердикты словами
def verdict(entry, installed, latest, family, why=""):
    return bu._verdict(
        "проба", entry,
        {"installed": installed, "latest": latest, "family": family,
         "latest_why": ""})


assert verdict(bridges["kinocut"], "1.16.1", "1.16.1", "pypi") == "свежая"
silent = verdict({"mcp_server": {}}, "1.0.0", "", "pypi", "HTTP 429")
assert silent.startswith("не проверено"), silent
v_npm = verdict({"mcp_server": {"pinned": False}}, "", "2.5", "npm")
assert "npx" in v_npm and "2.5" in v_npm, v_npm
v_pin = verdict(bridges["unity"], "10.3.0", "10.4.0", "pypi")
assert "закреплён" in v_pin and "правкой кода" in v_pin, v_pin
print("5. вердикты — свежая / не проверено / npm / пин — словами")

# --- install отказывается там, где трогать нельзя
messages, errors = bu.install("unity", "10.4.0", None)
assert messages == [] and "закреплён" in errors[0], errors
messages, errors = bu.install("dbhub", "1.0", None)
assert "npm" in errors[0], errors
print("6. install: закреплённый и npm-мост отказываются словами")

# --- check_all: структура строк
rows, errors = bu.check_all(None)
assert errors == []
assert all({"bridge", "installed", "latest", "verdict"} <= set(r)
           for r in rows)
# 23.10.2026: мостов с блоком update стало 35 — в реестр добавили 28,
# и у 27 из них есть способ обновления. У Cloudflare его нет: сервер
# удалённый, версию ведёт вендор, обновлять на машине нечего.
EXPECTED_UPDATE_ROWS = 35
assert len(rows) == EXPECTED_UPDATE_ROWS, len(rows)
print("6. check_all вернул", len(rows), "строк, все с полями")
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
