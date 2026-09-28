# -*- coding: utf-8 -*-
"""Защищённый DNS-резолвер — запасной способ обхода блокировок.

Когда все прокси/V2Ray-каналы не сработали, фасад может резолвить
домен через защищённый DNS (DoH) и идти к сайту напрямую по
полученному IP. Так обходится блокировка на уровне DNS (РКН не может
подменить ответ, если запрос шифрованный).

Поддерживаются:
  * DoH (DNS-over-HTTPS): dns.google, cloudflare-dns.com, Quad9, AdGuard;
  * обычные DNS-серверы (8.8.8.8, 1.1.1.1) через системный UDP.

Запрос DoH идёт через прокси-фасад (как и весь остальной трафик),
иначе до dns.google можно не достучаться из-под блокировки.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request
from typing import Iterable

#: Защищённые DNS по умолчанию. Строка = DoH-URL либо обычный IP.
#: Пробуются по очереди, берётся ответ от первого рабочего.
DEFAULT_DNS_SERVERS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
    "https://dns.quad9.net:5053/dns-query",
    "https://unfiltered.adguard-dns.com/dns-query",
    "https://dns.yandex/dns-query",
    "https://dns.nextdns.io/dns-query",
    "https://doh.cleanbrowsing.org/doh/security-filter/",
    "https://dns.mullvad.net/dns-query",
    "1.1.1.1",
    "8.8.8.8",
    "8.8.4.4",
)

#: Обходные DNS-сервисы (запасные, добавляются к защищённым).
EXTRA_DNS_SERVERS = (
    "https://dns10.quad9.net/dns-query",
    "94.140.14.14",   # AdGuard DNS
    "76.76.2.0",      # Control D
    "77.88.8.8",      # Yandex DNS
    "9.9.9.9",        # Quad9
    "1.1.1.2",        # Cloudflare без вредоносного
    "8.8.4.4",        # Google без вредоносного
)


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text.strip())
        return True
    except ValueError:
        return False


def _is_dns_server(text: str) -> bool:
    return _is_ip(text)


def _is_doh(text: str) -> bool:
    return text.startswith("https://") and "dns-query" in text


def _query_doh(url: str, host: str, timeout: float, proxy_url: str) -> list[str]:
    """Резолвит host через DoH-URL. Возвращает список IP (тип A)."""
    # у разных сервисов разный формат параметра
    if "dns-query" in url:
        sep = "?" if "?" not in url else "&"
        full = f"{url}{sep}name={host}&type=A"
    else:
        full = f"{url}?name={host}&type=A"
    headers = {
        "accept": "application/dns-json",
        "user-agent": "Mozilla/5.0",
    }
    req = urllib.request.Request(full, headers=headers)
    handlers = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({
            "http": proxy_url, "https": proxy_url,
        }))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    answers = data.get("Answer") or []
    return [
        a.get("data")
        for a in answers
        if a.get("type") == 1 and _is_ip(a.get("data", ""))
    ]


def _query_udp(server: str, host: str, timeout: float) -> list[str]:
    """Резолвит host через обычный DNS-сервер (UDP, порт 53)."""
    # Простой DNS-запрос типа A
    transaction_id = b"\x12\x34"
    flags = b"\x01\x00"
    questions = b"\x00\x01"
    answers = b"\x00\x00\x00\x00\x00\x00"
    header = transaction_id + flags + questions + answers
    # QNAME: host разделённый на длину+метки
    qname = b"".join(
        bytes([len(part)]) + part.encode("ascii")
        for part in host.rstrip(".").split(".")
    ) + b"\x00"
    qtype = b"\x00\x01"  # A
    qclass = b"\x00\x01"  # IN
    query = header + qname + qtype + qclass

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(query, (server, 53))
        data, _ = sock.recvfrom(512)
    finally:
        sock.close()

    # разбираем ответ: пропускаем заголовок (12) + вопрос, читаем answer
    offset = 12
    # пропустить QNAME (метки)
    while data[offset] != 0:
        offset += 1 + data[offset]
    offset += 5  # null + qtype(2) + qclass(2)
    ancount = int.from_bytes(data[6:8], "big")
    ips = []
    for _ in range(ancount):
        # NAME (может быть указателем 0xC0)
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
        else:
            while data[offset] != 0:
                offset += 1 + data[offset]
            offset += 1
        rtype = int.from_bytes(data[offset:offset+2], "big")
        rdlength = int.from_bytes(data[offset+8:offset+10], "big")
        if rtype == 1 and rdlength == 4:
            ip = socket.inet_ntoa(data[offset+10:offset+14])
            if _is_ip(ip):
                ips.append(ip)
        offset += 10 + rdlength
    return ips


class DNSResolutionError(Exception):
    """Не удалось резолвить через ни один защищённый DNS."""


def resolve_host(
    host: str,
    servers: Iterable[str] = DEFAULT_DNS_SERVERS,
    proxy_url: str = "",
    timeout: float = 8.0,
) -> list[str]:
    """Резолвит host через защищённые DNS. Возвращает список IP.

    Пробует серверы по очереди; берёт ответ от первого рабочего.
    Бросает DNSResolutionError, если все не сработали.
    """
    if not host or is_private_host(host):
        raise DNSResolutionError(f"нельзя резолвить {host!r}")
    if not servers:
        servers = DEFAULT_DNS_SERVERS
    last_error: Exception | None = None
    for server in servers:
        server = server.strip()
        if not server:
            continue
        try:
            if _is_doh(server):
                ips = _query_doh(server, host, timeout, proxy_url)
            elif _is_ip(server):
                ips = _query_udp(server, host, timeout)
            else:
                continue
            if ips:
                return ips
        except Exception as exc:  # noqa: BLE001 — пробуем следующий
            last_error = exc
            continue
    if last_error:
        raise DNSResolutionError(f"все DNS не сработали: {last_error}") from last_error
    raise DNSResolutionError("нет рабочих DNS-серверов")


def is_private_host(host: str) -> bool:
    """True, если хост локальный — такой резолвить не нужно."""
    normalized = host.strip().strip("[]").rstrip(".").lower()
    if normalized in {"localhost", "localhost.localdomain"}:
        return True
    if normalized.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        return ipaddress.ip_address(normalized).is_private
    except ValueError:
        return False
