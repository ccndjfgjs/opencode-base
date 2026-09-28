# -*- coding: utf-8 -*-
"""Общая логика обновления публичного пула SOCKS5 для фасада обхода.

Используется двумя местами:
  * refresh_public_nodes.py — команда «Обновить» вручную;
  * http_facade.py — фоновое автообновление раз в сутки.

Всё обновление живёт здесь, чтобы не было двух расходящихся копий.
"""

from __future__ import annotations

import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

try:
    from check_nodes import check_socks
except ImportError:  # pragma: no cover — при импорте из незнакомого места
    from .check_nodes import check_socks  # type: ignore


DEFAULT_SOURCES = (
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
    "https://raw.githubusercontent.com/zloi-dev/proxy-list/main/socks5.txt",
)
DEFAULT_TEST_URL = "https://example.com/"
DEFAULT_LIMIT = 60


def normalize_proxy_line(value: str) -> str | None:
    value = value.strip()
    if not value or value.startswith("#"):
        return None
    if "://" not in value:
        value = f"socks5://{value}"
    parsed = urlsplit(value)
    if parsed.scheme not in {"socks5", "socks5h"}:
        return None
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname or port is None or not 1 <= port <= 65535:
        return None
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return f"socks5://{host}:{port}"


def fetch_candidates(
    sources: tuple[str, ...] = DEFAULT_SOURCES,
    timeout: float = 20.0,
) -> tuple[list[str], list[str]]:
    candidates = []
    seen = set()
    errors = []
    for source in sources:
        try:
            request = Request(source, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", "ignore")
        except Exception as error:
            errors.append(f"{source}: {type(error).__name__}")
            continue
        for line in text.splitlines():
            value = normalize_proxy_line(line)
            if value is not None and value not in seen:
                seen.add(value)
                candidates.append(value)
    return candidates, errors


def check_candidates(
    candidates: list[str],
    test_url: str = DEFAULT_TEST_URL,
    timeout: float = 4.0,
    workers: int = 40,
) -> list[dict]:
    if not candidates:
        return []
    worker_count = min(max(workers, 1), len(candidates))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(
            pool.map(
                lambda url: check_socks(url, test_url=test_url, timeout=timeout),
                candidates,
            )
        )
    return sorted(
        (result for result in results if result["alive"]),
        key=lambda result: (
            result["latency_ms"] if result["latency_ms"] is not None else float("inf")
        ),
    )


def refresh_pool(
    output: Path,
    sources: tuple[str, ...] = DEFAULT_SOURCES,
    test_url: str = DEFAULT_TEST_URL,
    timeout: float = 4.0,
    fetch_timeout: float = 20.0,
    workers: int = 40,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Полное обновление пула. Возвращает отчёт для лога.

    Никогда не трогает существующий файл, если живых узлов нет:
    тогда возвращает ошибку, а старый пул остаётся работать.
    """
    output = Path(output)
    candidates, errors = fetch_candidates(sources, timeout=fetch_timeout)
    alive = check_candidates(
        candidates,
        test_url=test_url,
        timeout=timeout,
        workers=workers,
    )
    if not alive:
        return {
            "ok": False,
            "candidates": len(candidates),
            "alive": 0,
            "errors": errors,
            "message": "нет живых узлов — старый пул не тронут",
        }
    normalized = []
    for value in alive:
        candidate = normalize_proxy_line(value["proxy_url"])
        if candidate is not None and candidate not in normalized:
            normalized.append(candidate)
    selected = normalized[:limit]
    backup = None
    if output.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = output.with_name(f"{output.stem}.bak-{timestamp}{output.suffix}")
        try:
            shutil.copy2(output, backup)
        except OSError:
            backup = None
    try:
        output.write_text("\n".join(selected) + "\n", encoding="utf-8")
    except OSError as error:
        return {
            "ok": False,
            "candidates": len(candidates),
            "alive": len(alive),
            "errors": errors,
            "message": f"файл не записался: {type(error).__name__}",
        }
    return {
        "ok": True,
        "candidates": len(candidates),
        "alive": len(alive),
        "written": len(selected),
        "urls": selected,
        "backup": str(backup) if backup else None,
        "errors": errors,
    }
