"""Порт из настроек → адрес в настройках opencode → живая проверка.

Зачем эта проверка отдельная. Прежние проверки спрашивали
`unreal_http_state` тем портом, который сами же и подняли. Это верно, но
до проверяемого слоя не достаёт: между «порт назван» и «порт в адресе»
есть ещё `build_block` с подстановкой, и именно там ошибка была бы
незаметна — адрес уехал бы с одним портом, а диагностика говорила бы о
другом. Здесь проверка идёт по всей цепочке и берёт порт **из готового
блока**, то есть ровно тот, что увидит opencode.

Ничего не подменяется: тот же поддельный сервер, та же функция, тот же
реестр — меняется только точка, из которой берётся порт.
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import editor_plugins  # noqa: E402
import engine_setup  # noqa: E402
import mcp_registry  # noqa: E402

PROGRAM_ROOT = HERE.parent.parent

passed = 0
failed = 0


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


def fake_server(body: str, code: int):
    """Поддельный сервер на свободном порту. Возвращает сервер и порт."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — так в стандартной библиотеке
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, int(server.server_address[1])


def port_from_block(block: str) -> int:
    """Порт из готового блока подключения. Тот же разбор, что у человека."""
    for line in block.splitlines():
        if '"url"' in line and ":" in line:
            tail = line.split(":", 1)[1].strip().rstrip(",").strip('"')
            if "//127.0.0.1:" in tail:
                return int(tail.split("//127.0.0.1:")[1].split("/")[0])
    return 0


def main() -> int:
    import tempfile

    dest = Path(tempfile.mkdtemp(prefix="unreal-chain-"))
    (dest / "opencode.jsonc").write_text(
        '{"$schema": "https://opencode.ai/config.json", "mcp": {}}\n',
        encoding="utf-8")
    servers = {s.id: s for s in mcp_registry.load_servers(PROGRAM_ROOT)}
    unreal = servers.get("unreal")

    check(unreal is not None, "мост Unreal есть в реестре")
    if unreal is None:
        print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
        return 1

    # 1. Порт, названный человеком, попадает в адрес.
    plain, plain_port = fake_server('{"ok":true}', 200)
    try:
        ok_save, note_save = engine_setup.save_unreal_port(dest, str(plain_port))
        block = mcp_registry.build_block(unreal, dest=dest)
        got = port_from_block(block)
        check(ok_save and got == plain_port,
              f"порт назван — и он же в адресе блока: {got} вместо {plain_port} "
              f"({note_save})")
        check(str(plain_port) in block and "3000" not in block,
              f"а значение по умолчанию не подставилось: {block.strip()[:80]}")

        # 2. Живая проверка говорит ровно о сервере по этому адресу.
        ok_live, note_live = editor_plugins.unreal_http_state(got, editor_running=True)
        check(not ok_live and "другой программой" in note_live,
              f"по порту из блока отвечает подставной сервер: {note_live[:90]}")
        other, other_note = editor_plugins.unreal_http_state(
            engine_setup.read_unreal_port(dest) + 1, editor_running=True)
        check(not other and "не отвечает" not in other_note,
              f"а соседний порт отличается — блок не подставляется где попало: "
              f"{other_note[:70]}")
    finally:
        plain.shutdown()
        plain.server_close()

    # 3. Тот же адрес, но отвечает настоящий MCP — проверка это узнаёт.
    mcp, mcp_port = fake_server(
        '{"jsonrpc":"2.0","error":{"code":-32000,"message":"нет сессии"}}', 400)
    try:
        engine_setup.save_unreal_port(dest, str(mcp_port))
        block2 = mcp_registry.build_block(unreal, dest=dest)
        got2 = port_from_block(block2)
        ok_mcp, note_mcp = editor_plugins.unreal_http_state(got2, editor_running=True)
        check(got2 == mcp_port and ok_mcp,
              f"по порту из блока виден настоящий MCP-сервер: {note_mcp[:90]}")
    finally:
        mcp.shutdown()
        mcp.server_close()

    # 4. Без записи порта — адрес с честной пометкой, а не выдуманный.
    (dest / engine_setup.UNREAL_PORT_NAME).unlink(missing_ok=True)
    block3 = mcp_registry.build_block(unreal, dest=dest)
    got3 = port_from_block(block3)
    check(got3 == engine_setup.UNREAL_PORT_DEFAULT,
          f"без записи подставляется значение по умолчанию: {got3}")
    check(str(engine_setup.UNREAL_PORT_DEFAULT) in block3,
          "и оно честно числом, а не заглушкой «ПОРТ-НЕ-ЗАДАН»")

    # 5. Блок собирается как валидный JSON — адрес не разъехался.
    try:
        # Блок — кусок JSONC для секции mcp: "имя": {...}, поэтому читать его
        # надо как фрагмент объекта, а не как самостоятельный JSON.
        parsed = json.loads("{" + block3.strip().rstrip(",") + "}")["unreal"]
        check(parsed.get("type") == "remote"
              and parsed.get("url", "").endswith("/mcp"),
              f"блок читается и указывает на адрес: {parsed.get('url')}")
    except (json.JSONDecodeError, KeyError) as exc:
        check(False, f"блок читается: {exc}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
