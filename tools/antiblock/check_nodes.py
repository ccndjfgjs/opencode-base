"""Проверка живости SOCKS5-прокси: handshake + CONNECT + HTTP-запрос.

Только стандартная библиотека (сокеты), без новых зависимостей.
Имя целевого хоста всегда едет на прокси (ATYP=domain) — локальный
DNS не используется, утечек нет.
"""
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

DEFAULT_TEST_URL = "http://example.com/"


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("прокси закрыл соединение")
        buf += chunk
    return buf


def check_socks(proxy_url: str, test_url: str = DEFAULT_TEST_URL,
                timeout: float = 8) -> dict:
    """Проверить один SOCKS5-прокси.

    Возвращает dict: proxy_url, alive, latency_ms, http_status, error.
    alive=True при любом HTTP-статусе (даже 403 — прокси жив, режет сайт).
    """
    started = time.monotonic()
    result = {"proxy_url": proxy_url, "alive": False, "latency_ms": None,
              "http_status": None, "error": None}
    try:
        pu = urlparse(proxy_url)
        if pu.scheme not in ("socks5", "socks5h") or not pu.hostname or not pu.port:
            raise ValueError("ждём адрес вида socks5://host:port")
        tu = urlparse(test_url)
        if tu.scheme not in ("http", "https") or not tu.hostname:
            raise ValueError("тестовый URL — вида http(s)://…")
        target_port = tu.port or (443 if tu.scheme == "https" else 80)

        sock = socket.create_connection((pu.hostname, pu.port), timeout=timeout)
        sock.settimeout(timeout)
        with sock:
            # Приветствие: SOCKS5, один метод — без авторизации
            sock.sendall(b"\x05\x01\x00")
            if _recv_exact(sock, 2) != b"\x05\x00":
                raise ConnectionError("прокси требует авторизацию")
            # CONNECT к целевому хосту (доменом — резолвит сам прокси)
            host_b = tu.hostname.encode("idna")
            sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b
                         + target_port.to_bytes(2, "big"))
            head = _recv_exact(sock, 4)
            if head[0] != 0x05 or head[1] != 0x00:
                raise ConnectionError(f"CONNECT отклонён (код {head[1]})")
            atyp = head[3]
            if atyp == 0x01:
                _recv_exact(sock, 6)
            elif atyp == 0x04:
                _recv_exact(sock, 18)
            elif atyp == 0x03:
                _recv_exact(sock, _recv_exact(sock, 1)[0] + 2)
            else:
                raise ConnectionError(f"неизвестный ATYP {atyp}")
            stream = sock
            if tu.scheme == "https":
                stream = ssl.create_default_context().wrap_socket(
                    sock, server_hostname=tu.hostname)
            try:
                path = tu.path or "/"
                stream.sendall(
                    f"GET {path} HTTP/1.0\r\nHost: {tu.hostname}\r\n"
                    f"Connection: close\r\n\r\n".encode("latin-1"))
                status_line = b""
                while not status_line.endswith(b"\r\n"):
                    chunk = stream.recv(1)
                    if not chunk:
                        raise ConnectionError("цель не ответила")
                    status_line += chunk
                    if len(status_line) > 512:
                        raise ConnectionError("битая статус-строка")
                parts = status_line.decode("latin-1").split()
                status = int(parts[1]) if len(parts) > 1 else 0
            finally:
                if stream is not sock:
                    stream.close()
        result.update(alive=True, http_status=status,
                      latency_ms=round((time.monotonic() - started) * 1000, 1))
    except Exception as e:  # любой обрыв = мёртвый узел, не падение скрипта
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def wait_for_port(proxy_url: str, timeout_total: float = 40,
                  timeout_each: float = 4) -> bool:
    """Ждать, пока SOCKS-вход начнёт отвечать на handshake (рестарт Xray).

    Проверяет только приветствие, без CONNECT — дёшево и быстро.
    """
    import time as _time

    deadline = _time.monotonic() + timeout_total
    while _time.monotonic() < deadline:
        try:
            pu = urlparse(proxy_url)
            sock = socket.create_connection(
                (pu.hostname, pu.port), timeout=timeout_each)
            sock.settimeout(timeout_each)
            with sock:
                sock.sendall(b"\x05\x01\x00")
                if _recv_exact(sock, 2) == b"\x05\x00":
                    return True
        except Exception:
            pass
        _time.sleep(2)
    return False


def check_many(proxy_urls: list, test_url: str = DEFAULT_TEST_URL,
               timeout: float = 8, workers: int = 10) -> list:
    """Проверить список параллельно. Порядок результатов — как на входе."""
    if not proxy_urls:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(proxy_urls))) as pool:
        return list(pool.map(
            lambda u: check_socks(u, test_url, timeout), proxy_urls))
