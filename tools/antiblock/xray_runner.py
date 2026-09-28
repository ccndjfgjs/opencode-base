# -*- coding: utf-8 -*-
"""Независимый Xray-менеджер для обхода блокировок.

Поднимает свой экземпляр Xray-core из VLESS-подписок на локальном
SOCKS5-порту, не полагаясь на сторонние программы (INCY, Amnezia и т.д.).

Что умеет:
  * скачивать xray.exe при первом запуске с официального GitHub Xray-core;
  * собирать VLESS-узлы из подписок (subscriptions.txt);
  * проверять живые узлы по задержке и брать быстрейший;
  * генерировать xray-config.json с SOCKS5-входом на 127.0.0.1:10900;
  * запускать xray и следить за ним (перезапуск при падении).

Только стандартная библиотека.
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zlib
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

import check_nodes

# --- константы -----------------------------------------------------------
XRAY_DEFAULT_PORT = 10900
CONFIG_FILE = "xray-config.json"
NODE_FILE = "xray-node.txt"
NODES_CACHE = "nodes.vless.txt"
XRAY_EXE = "xray.exe"

# Официальный GitHub Xray-core: последняя версия берётся через API.
XRAY_RELEASE_URL = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
# Прямые ссылки на последнюю версию (как фолбэк, если API недоступен).
XRAY_DOWNLOAD_TEMPLATE = (
    "https://github.com/XTLS/Xray-core/releases/download/{tag}/"
    "Xray-windows-64.zip"
)

# VLESS-подписки (встроенные в комплект).
DEFAULT_SUBSCRIPTIONS = (
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/master/Sub4.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/master/Sub4.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/master/Sub5.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/master/Sub5.txt",
)

TEST_URL = "https://www.google.com/"
FETCH_TIMEOUT = 25
CHECK_TIMEOUT = 10


# --- парсинг VLESS -------------------------------------------------------
def _b64decode_pad(text: str) -> bytes:
    """Декодирует base64url c выравниванием и отбрасыванием мусора."""
    text = text.strip()
    while len(text) % 4 != 0:
        text += "="
    # base64url -> base64
    text = text.replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(text)
    except Exception:
        return b""


def parse_subscription(raw: str) -> list[str]:
    """Разбирает содержимое подписки на список VLESS-ссылок.

    Подписка может быть простым текстом (строки-ссылки) либо base64
    (стандарт для V2Ray-подписок).
    """
    raw = raw.strip()
    urls: list[str] = []
    # 1) пробуем как обычный текст построчно
    candidates = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    has_vless = any(ln.startswith("vless://") for ln in candidates)
    if has_vless:
        urls = [ln for ln in candidates if ln.startswith("vless://")]
    else:
        # 2) пробуем base64 (целиком)
        try:
            decoded = _b64decode_pad(raw)
            text = decoded.decode("utf-8", errors="ignore")
            urls = [
                ln.strip() for ln in text.splitlines()
                if ln.strip().startswith("vless://")
            ]
        except Exception:
            urls = []
    # убрать дубликаты, сохранив порядок
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def parse_vless(url: str) -> dict:
    """Превращает VLESS-ссылку в outbound-конфиг Xray.

    Возвращает dict с полями: tag, protocol, settings, streamSettings.
    Бросает ValueError, если ссылка не VLESS или битая.
    """
    if not url.startswith("vless://"):
        raise ValueError("не VLESS-ссылка")
    rest = url[len("vless://"):]
    # отрезаем фрагмент (имя узла) — он в конце после #
    if "#" in rest:
        rest = rest.split("#", 1)[0]
    # отделяем query
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    # в rest остаётся id@host:port
    if "@" not in rest:
        raise ValueError("нет id@host в ссылке")
    userinfo, hostport = rest.rsplit("@", 1)
    if ":" in hostport:
        host, port_text = hostport.rsplit(":", 1)
        port = int(port_text)
    else:
        host, port = hostport, 443
    if not host:
        raise ValueError("пустой host")

    params = parse_qs(query, keep_blank_values=True)
    def g(name: str, default: str = "") -> str:
        val = params.get(name)
        return val[0] if val else default

    security = g("security", "none")
    flow = g("flow", "")
    network = g("type", "tcp")
    sni = g("sni", "")
    fp = g("fp", "chrome")
    alpn = g("alpn", "")
    host_h = g("host", "")
    path = g("path", "")
    pbk = g("pbk", "")
    sid = g("sid", "")
    service_name = g("serviceName", "")
    header_type = g("headerType", "none")

    user = {"id": userinfo, "encryption": "none"}
    if flow:
        user["flow"] = flow

    vnext = [{"address": host, "port": port, "users": [user]}]
    outbound: dict = {
        "tag": "proxy",
        "protocol": "vless",
        "settings": {"vnext": vnext},
    }

    stream: dict = {"network": network}
    if security == "reality":
        stream["security"] = "reality"
        rs: dict = {"fingerprint": fp or "chrome"}
        if pbk:
            rs["publicKey"] = pbk
        if sid:
            rs["shortId"] = sid
        if sni:
            rs["serverName"] = sni
        stream["realitySettings"] = rs
    elif security == "tls":
        stream["security"] = "tls"
        tls: dict = {"fingerprint": fp or "chrome"}
        if sni:
            tls["serverName"] = sni
        if alpn:
            tls["alpn"] = [a for a in alpn.split(",") if a]
        stream["tlsSettings"] = tls
    else:
        stream["security"] = "none"

    # тип сети
    if network == "tcp":
        if header_type not in ("", "none"):
            stream["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "path": ["/"],
                        "headers": {"Host": [host_h or host]},
                    },
                }
            }
    elif network == "ws":
        ws: dict = {}
        if path:
            ws["path"] = path
        if host_h:
            ws["headers"] = {"Host": host_h}
        stream["wsSettings"] = ws
    elif network == "grpc":
        grpc: dict = {}
        if service_name:
            grpc["serviceName"] = service_name
        stream["grpcSettings"] = grpc
    elif network == "xhttp":
        xh: dict = {}
        if path:
            xh["path"] = path
        if host_h:
            xh["host"] = host_h
        stream["xhttpSettings"] = xh
    elif network == "httpupgrade":
        hu: dict = {}
        if path:
            hu["path"] = path
        if host_h:
            hu["host"] = host_h
        stream["httpupgradeSettings"] = hu
    elif network == "kcp":
        pass
    elif network in ("http", "raw"):
        stream["network"] = "tcp"

    outbound["streamSettings"] = stream
    return outbound


# --- сбор узлов из подписок ---------------------------------------------
def fetch_text(url: str, timeout: float = FETCH_TIMEOUT) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def load_subscriptions_file(path: Path) -> list[str]:
    """Читает список URL подписок из файла (строки, # — комментарий)."""
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http"):
            result.append(line)
    return result


def collect_nodes(
    subscriptions: list[str],
    timeout: float = FETCH_TIMEOUT,
) -> list[str]:
    """Скачивает все подписки и собирает уникальные VLESS-ссылки."""
    urls: list[str] = []
    seen = set()
    for sub in subscriptions:
        try:
            raw = fetch_text(sub, timeout=timeout)
            parsed = parse_subscription(raw)
        except Exception:
            continue
        for u in parsed:
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def _node_endpoint(url: str) -> tuple[str, int] | None:
    """Возвращает (host, port) сервера узла или None, если битая ссылка."""
    try:
        out = parse_vless(url)
        vnext = out["settings"]["vnext"][0]
        return vnext["address"], vnext["port"]
    except Exception:
        return None


def _tcp_alive(url: str, timeout: float = 3.0) -> bool:
    ep = _node_endpoint(url)
    if not ep:
        return False
    import socket
    try:
        s = socket.create_connection(ep, timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def tcp_filter(urls: list[str], workers: int = 30,
               timeout: float = 3.0) -> list[tuple[str, float]]:
    """Параллельная TCP-фильтрация: возвращает [(url, tcp_latency_ms)] живых.

    Отсекает синтаксически битые и серверно-мёртвые узлы быстро, без
    запуска Xray.
    """
    from concurrent.futures import ThreadPoolExecutor

    def _probe(url: str):
        import socket, time
        ep = _node_endpoint(url)
        if not ep:
            return None
        start = time.monotonic()
        try:
            s = socket.create_connection(ep, timeout=timeout)
            s.close()
            return (url, round((time.monotonic() - start) * 1000, 1))
        except Exception:
            return None

    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(urls))) as pool:
        results = list(pool.map(_probe, urls))
    return [r for r in results if r is not None]


def _kill_tree(proc: subprocess.Popen | None) -> None:
    """Гасит процесс вместе со всем деревом (Windows).

    xray.exe форкается: python-обёртка Popen может считать процесс
    завершённым (poll()!=None), хотя реальный xray.exe жив как
    потомок с другим pid. Поэтому полагаться на poll() нельзя —
    всегда бьём taskkill /T /F по сохранённому pid; на мёртвый
    pid taskkill безопасно отвечает «не найден».
    """
    if proc is None or proc.pid is None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        # taskkill не сработал — фолбэк на terminate/kill по обёртке.
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _probe_node_latency(
    workdir: Path,
    url: str,
    port: int,
    test_url: str,
    timeout: float,
) -> dict | None:
    """Запускает Xray с узлом на временном порту, меряет реальную задержку.

    Возвращает dict {url, latency_ms} или None при неудаче.
    """
    import subprocess
    import tempfile

    mgr = XrayManager(workdir=workdir, port=port, test_url=test_url)
    try:
        outbound = parse_vless(url)
        config = build_config(outbound, port=port)
        cfg_path = workdir / f"probe-{port}.json"
        _write_json_no_bom(cfg_path, config)
        exe = mgr.ensure_xray_binary()
        proc = subprocess.Popen(
            [str(exe), "-c", str(cfg_path)],
            cwd=str(workdir), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            if not check_nodes.wait_for_port(f"socks5://127.0.0.1:{port}",
                                             timeout_total=20, timeout_each=4):
                return None
            res = check_nodes.check_socks(
                f"socks5://127.0.0.1:{port}", test_url=test_url, timeout=timeout
            )
            if res.get("alive"):
                return {"url": url, "latency_ms": res["latency_ms"]}
            return None
        finally:
            _kill_tree(proc)
            cfg_path.unlink(missing_ok=True)
    except Exception:
        return None


def select_fastest_node(
    urls: list[str],
    workdir: Path | None = None,
    port: int = XRAY_DEFAULT_PORT,
    limit: int = 120,
    probe_count: int = 12,
    workers: int = 40,
    test_url: str = TEST_URL,
    timeout: float = CHECK_TIMEOUT,
) -> dict | None:
    """Выбирает быстрейший VLESS-узел по реальной задержке через Xray.

    Этап 1: TCP-фильтрация (быстро) по первым `limit` узлам.
    Этап 2: из живых берём `probe_count` быстрейших по TCP и реально
    запускаем Xray, мерим latency через SOCKS, возвращаем быстрейший
    из реально работающих. Несколько узлов могут быть TCP-живыми, но
    VLESS-туннель у них не поднимается — такие отсекаются.
    """
    if not urls:
        return None
    workdir = Path(workdir) if workdir else Path(__file__).parent
    alive = tcp_filter(urls[:limit], workers=workers)
    if not alive:
        return None
    alive.sort(key=lambda item: item[1])
    candidates = [url for url, _ in alive[:probe_count]]
    best = None
    tried = 0
    for url in candidates:
        probe_port = port + 1000 + tried
        r = _probe_node_latency(workdir, url, probe_port, test_url, timeout)
        tried += 1
        if r:
            if best is None or r["latency_ms"] < best["latency_ms"]:
                best = r
    return best


# --- скачивание xray.exe -------------------------------------------------
def latest_xray_tag() -> str:
    """Возвращает тег последней версии Xray-core (например v26.7.28)."""
    req = Request(XRAY_RELEASE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("tag_name", "")


def download_xray(dest_dir: Path, force: bool = False) -> Path:
    """Скачивает и распаковывает xray.exe в dest_dir. Возвращает путь."""
    dest_dir = Path(dest_dir)
    exe_path = dest_dir / XRAY_EXE
    if exe_path.exists() and not force:
        return exe_path

    # пробуем API, затем фолбэк на шаблон
    tag = ""
    try:
        tag = latest_xray_tag()
    except Exception:
        tag = ""
    if not tag:
        # фолбэк — фиксированный известный тег (обновится при следующем запуске)
        tag = "v26.7.28"
    url = XRAY_DOWNLOAD_TEMPLATE.format(tag=tag)

    zip_path = dest_dir / "xray-windows-64.zip"
    dest_dir.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    print(f"Скачиваю Xray {tag}: {url}", flush=True)
    with urlopen(req, timeout=120) as resp, open(zip_path, "wb") as out:
        shutil.copyfileobj(resp, out)

    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract("xray.exe", dest_dir)
    zip_path.unlink(missing_ok=True)
    return exe_path


# --- управление процессом Xray ------------------------------------------
def build_config(outbound: dict, port: int = XRAY_DEFAULT_PORT) -> dict:
    """Собирает полный конфиг Xray: SOCKS-вход + один outbound."""
    return {
        "log": {"loglevel": "warning", "error": "xray-error.log"},
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
        ],
        "outbounds": [
            outbound,
            {"tag": "direct", "protocol": "freedom"},
        ],
        "routing": {
            "rules": [
                {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "proxy"}
            ]
        },
    }


def _write_json_no_bom(path: Path, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


class XrayManager:
    """Запускает и держит живым свой Xray на локальном SOCKS5-порту."""

    def __init__(
        self,
        workdir: Path,
        port: int = XRAY_DEFAULT_PORT,
        subscriptions: list[str] | None = None,
        test_url: str = TEST_URL,
        xray_exe: Path | None = None,
    ):
        self.workdir = Path(workdir)
        self.port = port
        self.subscriptions = subscriptions or list(DEFAULT_SUBSCRIPTIONS)
        self.test_url = test_url
        self.xray_exe = xray_exe or (self.workdir / XRAY_EXE)
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.proxy_url = f"socks5://127.0.0.1:{port}"
        self.node_url: str | None = None

    def ensure_xray_binary(self) -> Path:
        if not self.xray_exe.exists():
            self.xray_exe = download_xray(self.workdir)
        return self.xray_exe

    def pick_node(self) -> str | None:
        """Собирает узлы из подписок и выбирает быстрейший (по задержке)."""
        urls = collect_nodes(self.subscriptions)
        if not urls:
            return None
        chosen = select_fastest_node(
            urls,
            workdir=self.workdir,
            port=self.port,
            test_url=self.test_url,
        )
        if not chosen:
            return None
        return chosen["url"]

    def start(self, node_url: str | None = None) -> bool:
        """Запускает Xray. Без узла — сначала пробует сохранённый
        с прошлого раза (секунды), и только если он мёртв —
        подбирает новый полным перебором (минуты). Возвращает успех."""
        self.ensure_xray_binary()
        if node_url is None:
            cached = self._read_cached_node()
            if cached:
                print("пробую сохранённый узел...", flush=True)
                if self._launch(cached, wait_total=20):
                    # Порт открылся — узел реально поднялся. Проверка
                    # живости по HTTP может не успеть за короткий срок
                    # (медленный узел), поэтому даём тот же бюджет, что
                    # и на поднятие порта, и не объявляем узел мёртвым
                    # наспех: если порт жив — используем его.
                    alive = check_nodes.check_socks(
                        self.proxy_url, test_url=self.test_url, timeout=15
                    ).get("alive", False)
                    if not alive:
                        # Порт жив, но HTTP не прошёл — это не «мёртвый
                        # узел», а медленный/глючный. Даём ему ещё одну
                        # короткую попытку, прежде чем перебирать новый.
                        time.sleep(2)
                        alive = check_nodes.check_socks(
                            self.proxy_url,
                            test_url=self.test_url,
                            timeout=15,
                        ).get("alive", False)
                    if alive:
                        self.node_url = cached
                        print(
                            f"Xray на сохранённом узле: {self.proxy_url}",
                            flush=True,
                        )
                        return True
                    print(
                        "сохранённый узел не отвечает, подбираю новый...",
                        flush=True,
                    )
                else:
                    print(
                        "сохранённый узел не поднялся, подбираю новый...",
                        flush=True,
                    )
            node_url = self.pick_node()
        if not node_url:
            return False
        self.node_url = node_url
        ok = self._launch(node_url, wait_total=30)
        if ok:
            self._write_cached_node(node_url)
        return ok

    def _launch(self, node_url: str, wait_total: float) -> bool:
        """Запускает xray.exe с готовым узлом и ждёт SOCKS-вход.
        Подбора нет — только запуск и ожидание."""
        try:
            outbound = parse_vless(node_url)
        except ValueError:
            return False
        config = build_config(outbound, port=self.port)
        _write_json_no_bom(self.workdir / CONFIG_FILE, config)

        self._stop_proc()
        cmd = [str(self.xray_exe), "-c", str(self.workdir / CONFIG_FILE)]
        self.proc = subprocess.Popen(
            cmd,
            cwd=str(self.workdir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # ждём готовности SOCKS-входа
        return check_nodes.wait_for_port(
            self.proxy_url, timeout_total=wait_total, timeout_each=4
        )

    def _read_cached_node(self) -> str | None:
        """Узел с прошлого удачного запуска или None."""
        try:
            url = (self.workdir / NODE_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not url.startswith("vless://"):
            return None
        try:
            parse_vless(url)
        except ValueError:
            return None
        return url

    def _write_cached_node(self, url: str) -> None:
        """Запоминает удачный узел для быстрого старта в следующий раз."""
        try:
            (self.workdir / NODE_FILE).write_text(
                url.strip() + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def _stop_proc(self) -> None:
        """Гасит свой Xray вместе со всем деревом процессов.

        xray.exe порождает вложенные процессы, поэтому простого
        terminate() по обёртке мало — остаётся сирота. _kill_tree
        бьёт taskkill /T по всему дереву.
        """
        proc = self.proc
        self.proc = None
        _kill_tree(proc)

    def is_alive(self) -> bool:
        if self.proc is None or self.proc.poll() is not None:
            return False
        return check_nodes.check_socks(
            self.proxy_url, test_url=self.test_url, timeout=8
        ).get("alive", False)

    def stop(self) -> None:
        self._stop.set()
        self._stop_proc()

    def run_forever(self) -> int:
        """Держит Xray живым: перезапускает и ротирует узлы, пока не остановят.

        Подписки качаются один раз; при падении узла выбирается следующий
        быстрейший из отфильтрованного списка.
        """
        self.ensure_xray_binary()
        urls = collect_nodes(self.subscriptions)
        if not urls:
            print("Нет узлов в подписках", flush=True)
            return 1
        alive = tcp_filter(urls[:80], workers=30)
        if not alive:
            print("Нет живых узлов", flush=True)
            return 1
        alive.sort(key=lambda item: item[1])
        ordered = [url for url, _ in alive]

        while not self._stop.is_set():
            ok = self.start(self.node_url)
            if not ok:
                print("Xray не поднялся, пробую следующий узел...", flush=True)
                if self.node_url in ordered:
                    idx = ordered.index(self.node_url)
                    self.node_url = ordered[(idx + 1) % len(ordered)]
                else:
                    self.node_url = ordered[0] if ordered else None
                time.sleep(3)
                continue
            print(f"Xray поднят: {self.proxy_url} (узел {self.node_url})", flush=True)
            if self.node_url:
                self._write_cached_node(self.node_url)
            while not self._stop.is_set():
                if self.proc is not None and self.proc.poll() is not None:
                    print("Xray упал, ротирую узел...", flush=True)
                    break
                if not check_nodes.check_socks(
                    self.proxy_url, test_url=self.test_url, timeout=8
                ).get("alive", False):
                    print("Xray не отвечает, ротирую узел...", flush=True)
                    break
                time.sleep(5)
            if self.node_url in ordered:
                idx = ordered.index(self.node_url)
                self.node_url = ordered[(idx + 1) % len(ordered)]
            time.sleep(2)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Независимый Xray-менеджер")
    parser.add_argument("--port", type=int, default=XRAY_DEFAULT_PORT)
    parser.add_argument("--subscriptions", type=Path,
                        default=Path(__file__).with_name("subscriptions.txt"))
    parser.add_argument("--workdir", type=Path,
                        default=Path(__file__).parent)
    parser.add_argument("--once", action="store_true",
                        help="запустить Xray один раз и выйти по Ctrl+C")
    parser.add_argument("--list-nodes", action="store_true",
                        help="показать сколько узлов в подписках и выйти")
    args = parser.parse_args()

    subs = load_subscriptions_file(args.subscriptions) or list(DEFAULT_SUBSCRIPTIONS)

    if args.list_nodes:
        urls = collect_nodes(subs)
        print(f"узлов в подписках: {len(urls)}")
        return 0

    mgr = XrayManager(
        workdir=args.workdir,
        port=args.port,
        subscriptions=subs,
    )
    if args.once:
        if not mgr.start():
            print("не удалось поднять Xray", flush=True)
            return 1
        print(f"Xray на {mgr.proxy_url}", flush=True)
        try:
            while True:
                time.sleep(5)
                if not mgr.is_alive():
                    print("Xray перестал отвечать", flush=True)
                    break
        except KeyboardInterrupt:
            pass
        mgr.stop()
        return 0
    return mgr.run_forever()


if __name__ == "__main__":
    sys.exit(main())
