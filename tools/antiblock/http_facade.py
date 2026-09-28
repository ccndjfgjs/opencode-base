import argparse
import ipaddress
import json
import logging
import select
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 17890
DEFAULT_BASE_PORT = 10900
DEFAULT_COOLDOWN = 30.0
DEFAULT_CONNECT_TIMEOUT = 8.0
DEFAULT_HEADER_TIMEOUT = 15.0
MAX_HEADER_BYTES = 65536
COPY_BUFFER_SIZE = 65536


class ProxyUnavailable(ConnectionError):
    pass


def _parse_upstream_url(url: str):
    parsed = urlsplit(url)
    if parsed.scheme not in {"socks5", "socks5h"}:
        raise ValueError("upstream must use socks5:// or socks5h://")
    if not parsed.hostname or parsed.port is None:
        raise ValueError("upstream must include host and port")
    if parsed.username or parsed.password:
        raise ValueError("upstream credentials are not supported")
    return parsed


def _parse_authority(authority: str, default_port: int = 80) -> tuple[str, int]:
    value = authority.strip()
    if not value:
        raise ValueError("empty authority")
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            raise ValueError("invalid IPv6 authority")
        host = value[1:end]
        remainder = value[end + 1:]
        if remainder.startswith(":"):
            port = int(remainder[1:])
        elif remainder:
            raise ValueError("invalid authority")
        else:
            port = default_port
    elif value.count(":") == 1:
        host, port_text = value.rsplit(":", 1)
        port = int(port_text)
    elif ":" in value:
        raise ValueError("IPv6 authority must be bracketed")
    else:
        host = value
        port = default_port
    if not host or not 1 <= port <= 65535:
        raise ValueError("invalid authority")
    return host, port


def is_private_host(host: str) -> bool:
    normalized = host.strip().strip("[]").rstrip(".").lower()
    if not normalized:
        return True
    if normalized in {"localhost", "localhost.localdomain"}:
        return True
    if normalized.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise ConnectionError("upstream closed the connection")
        data += part
    return data


def _read_socks_response(sock: socket.socket) -> None:
    header = _recv_exact(sock, 4)
    if header[0] != 5:
        raise ProxyUnavailable("invalid SOCKS response")
    if header[1] != 0:
        raise ProxyUnavailable(f"SOCKS CONNECT rejected with code {header[1]}")
    address_type = header[3]
    if address_type == 1:
        _recv_exact(sock, 4)
    elif address_type == 4:
        _recv_exact(sock, 16)
    elif address_type == 3:
        length = _recv_exact(sock, 1)[0]
        _recv_exact(sock, length)
    else:
        raise ProxyUnavailable("invalid SOCKS address type")
    _recv_exact(sock, 2)


def open_socks_tunnel(
    proxy_url: str,
    target_host: str,
    target_port: int,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
) -> socket.socket:
    if not 1 <= target_port <= 65535:
        raise ValueError("invalid target port")
    if is_private_host(target_host):
        raise ValueError("private target is not allowed")
    parsed = _parse_upstream_url(proxy_url)
    sock = socket.create_connection(
        (parsed.hostname, parsed.port), timeout=timeout
    )
    try:
        sock.settimeout(timeout)
        sock.sendall(b"\x05\x01\x00")
        if _recv_exact(sock, 2) != b"\x05\x00":
            raise ProxyUnavailable("SOCKS5 authentication is required")
        host_bytes = target_host.rstrip(".").encode("idna")
        if len(host_bytes) > 255:
            raise ValueError("target host is too long")
        sock.sendall(
            b"\x05\x01\x00\x03"
            + bytes([len(host_bytes)])
            + host_bytes
            + target_port.to_bytes(2, "big")
        )
        _read_socks_response(sock)
        sock.settimeout(None)
        return sock
    except Exception:
        sock.close()
        raise


class ProxyPool:
    def __init__(
        self,
        upstreams: list[str],
        cooldown_seconds: float = DEFAULT_COOLDOWN,
        clock: Callable[[], float] = time.monotonic,
        priority: list[str] | None = None,
    ):
        if not upstreams:
            raise ValueError("at least one upstream is required")
        normalized = []
        for upstream in upstreams:
            _parse_upstream_url(upstream)
            if upstream not in normalized:
                normalized.append(upstream)
        self.upstreams = tuple(normalized)
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._cooldowns = {upstream: 0.0 for upstream in self.upstreams}
        self._latency = {upstream: None for upstream in self.upstreams}
        # приоритетные upstream (например V2Ray-канал) пробуются первыми,
        # чтобы не ждать, когда начнётся обход медленного пула
        self._priority = tuple(
            u for u in (priority or []) if u in self._cooldowns
        )
        self._cursor = 0
        self._lock = threading.Lock()

    def _ordered_available(self) -> list[str]:
        now = self._clock()
        available = [
            u for u in self.upstreams if self._cooldowns[u] <= now
        ]
        if not available:
            available = list(self.upstreams)
        # приоритетные — впереди, остальные — по измеренной задержке
        prio = [u for u in self._priority if u in available]
        rest = [u for u in available if u not in self._priority]
        rest.sort(key=lambda u: (self._latency[u] is None, self._latency[u] or 1e9))
        return prio + rest

    def next_url(self) -> str:
        with self._lock:
            ordered = self._ordered_available()
            if not ordered:
                ordered = list(self.upstreams)
            upstream = ordered[self._cursor % len(ordered)]
            self._cursor += 1
            return upstream

    def candidates(self) -> list[str]:
        with self._lock:
            ordered = self._ordered_available()
            available = [
                upstream for upstream in ordered
                if self._cooldowns[upstream] <= self._clock()
            ]
            if not available:
                available = ordered
            first_index = self.upstreams.index(available[0])
            self._cursor = (first_index + 1) % len(self.upstreams)
            return available

    def mark_failure(self, upstream: str) -> None:
        with self._lock:
            if upstream in self._cooldowns:
                self._cooldowns[upstream] = self._clock() + self.cooldown_seconds

    def mark_success(self, upstream: str) -> None:
        with self._lock:
            if upstream in self._cooldowns:
                self._cooldowns[upstream] = 0.0

    def mark_latency(self, upstream: str, ms: float) -> None:
        with self._lock:
            if upstream in self._latency:
                self._latency[upstream] = ms

    def cooldown_remaining(self, upstream: str) -> float:
        with self._lock:
            return max(0.0, self._cooldowns.get(upstream, 0.0) - self._clock())

    def set_upstreams(self, upstreams: list[str]) -> int:
        """Горячо подменяет пул узлов без перезапуска сервера.

        Возвращает, сколько узлов принято. Сбрасывает паузы (cooldowns)
        и курсор, чтобы новый список сразу был доступен.
        """
        normalized = []
        for upstream in upstreams:
            try:
                _parse_upstream_url(upstream)
            except ValueError:
                continue
            if upstream not in normalized:
                normalized.append(upstream)
        with self._lock:
            if not normalized:
                return 0
            # При горячем обновлении публичного пула приоритетный
            # V2Ray-канал не должен выпадать из списка.
            for prio in self._priority:
                if prio not in normalized:
                    normalized.insert(0, prio)
            # Приоритет мог быть задан до появления upstream в пуле
            # (теперь он точно есть) — чиним _priority на всякий случай.
            self._priority = tuple(
                u for u in self._priority if u in normalized
            )
            self.upstreams = tuple(normalized)
            self._cooldowns = {upstream: 0.0 for upstream in self.upstreams}
            self._latency = {upstream: None for upstream in self.upstreams}
            self._cursor = 0
        return len(normalized)


def _read_headers(
    sock: socket.socket, max_bytes: int = MAX_HEADER_BYTES
) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        if len(data) >= max_bytes:
            raise ValueError("HTTP headers are too large")
        part = sock.recv(min(4096, max_bytes - len(data)))
        if not part:
            raise ConnectionError("client closed before headers")
        data += part
    marker = data.index(b"\r\n\r\n") + 4
    return data[:marker], data[marker:]


def _send_error(sock: socket.socket, status: int, reason: str) -> None:
    body = reason.encode("utf-8")
    response = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        sock.sendall(response)
    except OSError:
        pass


def _build_forward_request(
    method: str,
    target: str,
    version: str,
    headers: bytes,
) -> tuple[bytes, str, int]:
    parsed = urlsplit(target)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("only absolute HTTP forward requests are supported")
    if parsed.username or parsed.password:
        raise ValueError("proxy URL credentials are not supported")
    port = parsed.port or 80
    host = parsed.hostname
    host_header = host
    if ":" in host:
        host_header = f"[{host}]"
    if port != 80:
        host_header = f"{host_header}:{port}"
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    lines = headers[:-4].split(b"\r\n")
    filtered = []
    for line in lines[1:]:
        if not line:
            continue
        name = line.split(b":", 1)[0].lower()
        if name in {b"host", b"proxy-connection", b"proxy-authorization"}:
            continue
        filtered.append(line)
    filtered.append(f"Host: {host_header}".encode("idna"))
    request = (
        f"{method} {path} {version}\r\n".encode("ascii")
        + b"\r\n".join(filtered)
        + b"\r\n\r\n"
    )
    return request, host, port


def _relay(first: socket.socket, second: socket.socket) -> None:
    sockets = [first, second]
    while sockets:
        readable, _, _ = select.select(sockets, [], [])
        for source in readable[:]:
            data = source.recv(COPY_BUFFER_SIZE)
            if not data:
                sockets.remove(source)
                destination = second if source is first else first
                try:
                    destination.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                continue
            destination = second if source is first else first
            destination.sendall(data)


class FacadeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(self.server.header_timeout)
        try:
            headers, remainder = _read_headers(self.request)
            request_line = headers.split(b"\r\n", 1)[0].decode("iso-8859-1")
            parts = request_line.split(" ", 2)
            if len(parts) != 3:
                _send_error(self.request, 400, "Bad Request")
                return
            method, target, version = parts
            if method.upper() == "CONNECT":
                self._handle_connect(target, remainder)
                return
            if target.lower().startswith(("http://", "https://")):
                self._handle_forward(method, target, version, headers, remainder)
                return
            _send_error(self.request, 400, "Bad Request")
        except (ConnectionError, OSError, UnicodeError, ValueError):
            return

    def _open_upstream(self, host: str, port: int) -> socket.socket:
        last_error = None
        started = time.monotonic()
        for upstream in self.server.pool.candidates():
            try:
                tunnel = open_socks_tunnel(
                    upstream,
                    host,
                    port,
                    timeout=self.server.connect_timeout,
                )
                self.server.pool.mark_success(upstream)
                latency_ms = round((time.monotonic() - started) * 1000, 1)
                self.server.pool.mark_latency(upstream, latency_ms)
                self.server.logger.info(
                    "connected through upstream %s (%.0f ms)",
                    upstream.rsplit(":", 1)[-1],
                    latency_ms,
                )
                return tunnel
            except (OSError, ProxyUnavailable, ValueError) as error:
                last_error = error
                self.server.pool.mark_failure(upstream)
                self.server.logger.warning(
                    "upstream %s failed: %s",
                    upstream.rsplit(":", 1)[-1],
                    type(error).__name__,
                )
        # Запасной способ: если ни один SOCKS (V2Ray/прокси) не сработал —
        # резолвим хост через защищённый DNS и идём напрямую по IP.
        # Так обходится блокировка на уровне DNS.
        direct = self._open_dns_direct(host, port)
        if direct is not None:
            return direct
        if last_error is None:
            raise ProxyUnavailable("no upstream available")
        raise ProxyUnavailable("all upstreams failed") from last_error

    def _open_dns_direct(self, host: str, port: int):
        """Пробует подключиться напрямую через защищённый DNS.

        Резолвит host через DoH (защищённый DNS), затем открывает
        прямое соединение с полученным IP. Возвращает сокет или None,
        если DNS-резолв или подключение не удались.
        """
        if is_private_host(host):
            return None
        try:
            from dns_resolver import resolve_host, DNSResolutionError
        except ImportError:
            return None
        try:
            ips = resolve_host(
                host,
                proxy_url=self._facade_proxy_url(),
                timeout=10,
            )
        except DNSResolutionError:
            return None
        for ip in ips:
            try:
                sock = socket.create_connection(
                    (ip, port), timeout=self.server.connect_timeout
                )
                sock.settimeout(self.server.header_timeout)
                self.server.logger.info(
                    "dns-direct %s -> %s (защищённый DNS)", host, ip
                )
                return sock
            except OSError:
                continue
        return None

    def _facade_proxy_url(self) -> str:
        """Адрес самого фасада — чтобы DoH-запрос шёл через обход."""
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def _handle_connect(self, target: str, remainder: bytes) -> None:
        try:
            host, port = _parse_authority(target, 443)
            if is_private_host(host):
                _send_error(self.request, 403, "Forbidden")
                return
            upstream = self._open_upstream(host, port)
        except ValueError:
            _send_error(self.request, 400, "Bad Request")
            return
        except ProxyUnavailable:
            _send_error(self.request, 502, "Bad Gateway")
            return
        try:
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if remainder:
                upstream.sendall(remainder)
            _relay(self.request, upstream)
        except OSError:
            pass
        finally:
            upstream.close()

    def _handle_forward(
        self,
        method: str,
        target: str,
        version: str,
        headers: bytes,
        remainder: bytes,
    ) -> None:
        try:
            request, host, port = _build_forward_request(
                method, target, version, headers
            )
            if is_private_host(host):
                _send_error(self.request, 403, "Forbidden")
                return
            upstream = self._open_upstream(host, port)
        except ValueError:
            _send_error(self.request, 400, "Bad Request")
            return
        except ProxyUnavailable:
            _send_error(self.request, 502, "Bad Gateway")
            return
        try:
            upstream.sendall(request)
            if remainder:
                upstream.sendall(remainder)
            _relay(self.request, upstream)
        except OSError:
            pass
        finally:
            upstream.close()


class FacadeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        pool: ProxyPool,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        header_timeout: float = DEFAULT_HEADER_TIMEOUT,
        logger: logging.Logger | None = None,
    ):
        self.pool = pool
        self.connect_timeout = connect_timeout
        self.header_timeout = header_timeout
        self.logger = logger or logging.getLogger("http_facade")
        super().__init__(server_address, FacadeHandler)


def create_server(
    listen_host: str,
    listen_port: int,
    upstreams: list[str],
    cooldown_seconds: float = DEFAULT_COOLDOWN,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    header_timeout: float = DEFAULT_HEADER_TIMEOUT,
    logger: logging.Logger | None = None,
    priority: list[str] | None = None,
) -> FacadeServer:
    if listen_host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("facade must listen on loopback")
    return FacadeServer(
        (listen_host, listen_port),
        ProxyPool(
            upstreams,
            cooldown_seconds=cooldown_seconds,
            priority=priority,
        ),
        connect_timeout=connect_timeout,
        header_timeout=header_timeout,
        logger=logger,
    )


class PoolRefresher(threading.Thread):
    """Фон: раз в `interval_hours` обновляет пул с тех же источников.

    После обновления горячо подменяет список узлов у живого сервера
    (set_upstreams), не останавливая его. Если живых узлов нет —
    старый пул остаётся работать, ничего не перезаписывается.
    """

    def __init__(
        self,
        server,
        pool_file: Path,
        sources: tuple[str, ...],
        interval_hours: float,
        logger: logging.Logger | None = None,
    ):
        super().__init__(name="pool-refresher", daemon=True)
        self.server = server
        self.pool_file = Path(pool_file)
        self.sources = tuple(sources)
        self.interval = max(interval_hours, 0.1) * 3600.0
        self.logger = logger or logging.getLogger("http_facade")
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def refresh_once(self) -> bool:
        from pool_refresh import refresh_pool

        try:
            report = refresh_pool(output=self.pool_file, sources=self.sources)
        except Exception as error:  # noqa: BLE001 — фон не должен ронять сервер
            self.logger.warning("автообновление пула упало: %s", type(error).__name__)
            return False
        if not report.get("ok"):
            self.logger.warning(
                "автообновление: %s", report.get("message", "не удалось")
            )
            return False
        urls = report.get("urls") or []
        accepted = self.server.pool.set_upstreams(urls)
        self.logger.info(
            "автообновление: узлов %s -> живых %s, в пуле %s",
            report.get("candidates"),
            report.get("alive"),
            accepted,
        )
        return True

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            self.refresh_once()


def _normalize_upstream_line(value: str) -> str | None:
    value = value.strip()
    if not value or value.startswith("#"):
        return None
    if "://" not in value:
        value = f"socks5://{value}"
    try:
        parsed = _parse_upstream_url(value)
    except ValueError:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return f"socks5://{host}:{parsed.port}"


def load_upstream_urls(
    nodes_file: Path, base_port: int = DEFAULT_BASE_PORT
) -> list[str]:
    if nodes_file.suffix.lower() in {".txt", ".list"}:
        urls = []
        for line in nodes_file.read_text(encoding="utf-8").splitlines():
            upstream = _normalize_upstream_line(line)
            if upstream is not None and upstream not in urls:
                urls.append(upstream)
        return urls
    data = json.loads(nodes_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("nodes file must contain a list")
    return [
        f"socks5://127.0.0.1:{base_port + index}"
        for index, _ in enumerate(data)
    ]


def _split_upstreams(values: list[str]) -> list[str]:
    result = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result


def _configure_logging(args) -> None:
    """Настраивает лог: в файл (--log-file) и/или в консоль (--console-echo).

    По умолчанию лог идёт только в stderr. При --console-echo те же строки
    дублируются в stdout — они попадают в окно, откуда запущен фасад, и видно,
    через какой канал идёт обход и что отваливается. Формат одинаковый, чтобы
    файл и окно читались одинаково.
    """
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logger = logging.getLogger("http_facade")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    formatter = logging.Formatter(fmt)
    if args.log_file is not None:
        try:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(args.log_file, encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except OSError:
            pass
    if args.console_echo:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        logger.addHandler(sh)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local HTTP to SOCKS5 facade")
    parser.add_argument("--listen-host", default=DEFAULT_LISTEN_HOST)
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT)
    parser.add_argument("--upstream", action="append", default=[])
    parser.add_argument(
        "--nodes-file",
        type=Path,
        default=Path(__file__).with_name("nodes.local.json"),
    )
    parser.add_argument("--base-port", type=int, default=DEFAULT_BASE_PORT)
    parser.add_argument("--cooldown", type=float, default=DEFAULT_COOLDOWN)
    parser.add_argument(
        "--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT
    )
    parser.add_argument("--header-timeout", type=float, default=DEFAULT_HEADER_TIMEOUT)
    parser.add_argument(
        "--refresh-hours",
        type=float,
        default=0.0,
        help="Автообновление пула с источников, раз в N часов (0 = выключено)",
    )
    parser.add_argument(
        "--refresh-source", action="append", dest="refresh_sources", default=[]
    )
    parser.add_argument(
        "--v2ray-socks",
        default="",
        help="Приоритетный локальный SOCKS5 V2Ray-канал (например socks5://127.0.0.1:10900)",
    )
    parser.add_argument(
        "--console-echo",
        action="store_true",
        help="Дублировать лог (смену канала, отказы, DNS) в stdout — видно в окне запуска",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Писать лог и в файл (полезно при --console-echo для диагностики)",
    )
    args = parser.parse_args()

    upstreams = _split_upstreams(args.upstream)
    if not upstreams:
        upstreams = load_upstream_urls(args.nodes_file, args.base_port)
    if not upstreams:
        parser.error("no upstream proxies configured")

    priority = []
    if args.v2ray_socks:
        try:
            _parse_upstream_url(args.v2ray_socks)
            priority = [args.v2ray_socks]
            # Приоритетный канал обязан быть в пуле, иначе ProxyPool
            # молча его отбросит (фильтр по _cooldowns). Ставим первым.
            if args.v2ray_socks not in upstreams:
                upstreams = [args.v2ray_socks] + upstreams
        except ValueError:
            pass
    _configure_logging(args)
    server = create_server(
        args.listen_host,
        args.listen_port,
        upstreams,
        cooldown_seconds=args.cooldown,
        connect_timeout=args.connect_timeout,
        header_timeout=args.header_timeout,
        priority=priority,
    )
    print(
        f"HTTP facade listening on {args.listen_host}:{server.server_address[1]}",
        flush=True,
    )
    refresher = None
    if args.refresh_hours > 0:
        try:
            from pool_refresh import DEFAULT_SOURCES as _REFRESH_SOURCES
        except ImportError:  # pragma: no cover
            _REFRESH_SOURCES = ()
        sources = tuple(args.refresh_sources) or _REFRESH_SOURCES
        refresher = PoolRefresher(
            server,
            args.nodes_file,
            sources=sources,
            interval_hours=args.refresh_hours,
        )
        refresher.start()
        print(
            f"Автообновление пула: раз в {args.refresh_hours} ч, "
            f"файл {args.nodes_file}",
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if refresher is not None:
            refresher.stop()
        return 0
    finally:
        if refresher is not None:
            refresher.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
