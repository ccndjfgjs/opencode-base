"""Проверка остановки дерева процессов. Часть A3 плана.

    python tools/dbapp/launchers/test_process_tree.py

Запускает настоящие процессы: заглушка сама порождает потомка, пишет его
номер и имя образа в файл, а тест проверяет по этому номеру, а не по журналу.
Потомок намеренно переживает родителя в одном из случаев: так проверяется,
что `ошибка_остановки` не выдаётся за обычный таймаут.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bridge_common as common  # noqa: E402

PY = sys.executable
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


#: Заглушка: пишет номер потомка, имя образа и время его создания, затем спит.
STUB_CHILD = """
import subprocess, sys, time
from pathlib import Path
info = Path(sys.argv[1])
child_seconds = int(sys.argv[2])
parent_seconds = int(sys.argv[3])
child = subprocess.Popen([sys.executable, "-c",
                         f"import time; time.sleep({child_seconds})"])
info.write_text("|".join([
    str(child.pid), Path(sys.executable).name, str(int(time.time()))]),
    encoding="utf-8")
time.sleep(parent_seconds)
"""

#: Потомок переживает родителя: родитель уходит сразу, и taskkill /T уже не
#: находит его дерево. Именно этот случай обязан давать не обычный таймаут.
STUB_ORPHAN = """
import os, subprocess, sys, time
from pathlib import Path
info = Path(sys.argv[1])
child_seconds = int(sys.argv[2])
child = subprocess.Popen([sys.executable, "-c",
                         f"import time; time.sleep({child_seconds})"])
info.write_text("|".join([
    str(child.pid), Path(sys.executable).name, str(int(time.time()))]),
    encoding="utf-8")
os._exit(0)
"""


def read_info(path: Path) -> tuple[int, str, float]:
    raw = path.read_text(encoding="utf-8").strip().split("|")
    return int(raw[0]), raw[1], float(raw[2])


def wait_gone(pid: int, image: str, seconds: float = 6.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not common._process_alive(pid, image):
            return True
        time.sleep(0.2)
    return False


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # --- 1. Обычный таймаут: потомок убит вместе с деревом ---
        info = root / "child1.txt"
        stub = root / "stub1.py"
        stub.write_text(STUB_CHILD, encoding="utf-8")

        # Живость потомка смотрим из отдельного потока, пока идёт ожидание:
        # после остановки проверять нечего, он уже мёртв.
        seen_alive = []

        def watch():
            deadline = time.time() + 3
            while time.time() < deadline:
                if info.is_file():
                    try:
                        pid, image, _ = read_info(info)
                    except (OSError, ValueError):
                        time.sleep(0.05)
                        continue
                    if common._process_alive(pid, image):
                        seen_alive.append(pid)
                        return
                time.sleep(0.05)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        code, out, err, status = common.run_capture(
            [PY, str(stub), str(info), "60", "60"], timeout=3)
        watcher.join(5)
        check(status == "таймаут", "зависший процесс дал статус «таймаут»")
        check(code is None, "при таймауте кода нет")
        check("остановлен" in err, "в тексте сказано, что процесс остановлен")
        check(info.is_file(), "заглушка успела записать номер потомка")
        check(bool(seen_alive),
              "потомок был жив ВО ВРЕМЯ ожидания, а не после остановки")
        pid, image, _ = read_info(info)
        check(wait_gone(pid, image), "потомок исчез после остановки дерева")

        # --- 2. Потомок переживает родителя: это не обычный таймаут ---
        info2 = root / "child2.txt"
        stub2 = root / "stub2.py"
        stub2.write_text(STUB_ORPHAN, encoding="utf-8")
        code, out, err, status = common.run_capture(
            [PY, str(stub2), str(info2), "30"], timeout=3)
        check(info2.is_file(), "во втором случае номер потомка тоже записан")
        pid2, image2, _ = read_info(info2)
        # Группа заданий должна достать потомка, даже если родитель умер и
        # потомок переподчинился: иначе мост врал бы «остановлено».
        check(wait_gone(pid2, image2),
              "потомок, переживший родителя, тоже остановлен")
        check(status == "таймаут",
              "при полной очистке статус обычный таймаут: %r" % status)
        check("остановить не удалось" not in err,
              "очистка не выдаётся за неудачную, когда она удачная")

        # --- 2б. Когда очистку НЕ удалось подтвердить, статус отдельный ---
        real_desc = common._descendant_pids

        def fake_desc(pid: int) -> list[int]:
            # Сообщаем о процессе, которого мост на самом деле не остановил.
            return [*real_desc(pid), os.getpid()]

        info3 = root / "child3.txt"
        stub3 = root / "stub3.py"
        stub3.write_text(STUB_CHILD, encoding="utf-8")
        common._descendant_pids = fake_desc
        try:
            code, out, err, status = common.run_capture(
                [PY, str(stub3), str(info3), "60", "60"], timeout=2)
        finally:
            common._descendant_pids = real_desc
        check(status == "ошибка_остановки",
              "неподтверждённая очистка — это отдельный статус, а не таймаут: %r"
              % status)
        check("остановить не удалось" in err, "сказано прямо, что не остановили")
        check("остались процессы" in err, "назван номер оставшегося процесса")

        # --- 3. Обычный вызов: статус пустой, код настоящий ---
        code, out, err, status = common.run_capture(
            [PY, "-c", "print('живой ответ')"], timeout=30)
        check(status == "", "нормальный вызов не даёт никакого статуса остановки")
        check(code == 0, "код нормального вызова 0")
        check("живой ответ" in out, "stdout дошёл")

        # --- 4. Ненулевой код — это не таймаут ---
        code, out, err, status = common.run_capture(
            [PY, "-c", "import sys; sys.exit(7)"], timeout=30)
        check(code == 7, "ненулевой код программы не путается с таймаутом")
        check(status == "", "ненулевой код не даёт статуса остановки")

        # --- 5. Несуществующая программа ---
        code, out, err, status = common.run_capture(
            [str(root / "нет_такой.exe"), "--version"], timeout=10)
        check(status == "не_запустился", "отсутствующая программа — это не таймаут")
        check("не запустился" in err, "причина неудачного запуска названа")

        # --- 6. Опознание по номеру и образу ---
        check(common._process_alive(os.getpid()), "свой процесс виден в tasklist")
        check(not common._process_alive(999999), "несуществующий номер не «жив»")
        check(not common._process_alive(os.getpid(), "нет_такого_образа.exe"),
              "чужой образ не считается тем же процессом")

        # --- 7. Тексты статусов различаются ---
        texts = {status: common.stop_status_text(status, "Codex", 600)
                 for status in ("таймаут", "ошибка_остановки",
                                "не_запустился", "")}
        check(len(set(texts.values())) == 4,
              "у всех четырёх статусов свой неповторяющийся текст")
        check("остаться работать" in texts["ошибка_остановки"],
              "при неудачной остановке сказано, что могло остаться работать")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()