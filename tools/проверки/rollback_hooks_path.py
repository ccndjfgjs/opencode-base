"""Доказывает, что хук работает при core.hooksPath, а не только в .git/hooks.

Прошлая проверка делалась в .git/hooks, и это ничего не доказывало про
hooksPath: файл лежал в правильном месте случайно. В свежем клоне
.git/hooks пуст, и хук из репозитория не появился бы.

Здесь: пробный репозиторий, hooksPath указывает на tools/hooks, а
проверяются оба состояния — без разрешения (блокирует) и с разрешением
(пропускает). Настоящий репозиторий не трогается.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
REPO = HERE.parent.parent.parent
REL = "документы/2026-10-05-план-указатели-знаний.md"


def git(d: Path, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def make(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "документы").mkdir(exist_ok=True)
    shutil.copytree(PROG / "tools", dest / "tools",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(PROG / REL, dest / REL)
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"],
                ["config", "core.hooksPath", "tools/hooks"],
                ["add", "-A"], ["commit", "-q", "-m", "пробная база"]):
        p = git(dest, *cmd)
        if p.returncode != 0:
            raise SystemExit(f"git {cmd[0]}: {p.stderr[:200]}")
    return dest


def try_commit(d: Path, msg: str) -> tuple[int, str]:
    (d / "файл.txt").write_text("правка для пробы\n", encoding="utf-8")
    git(d, "add", "-A")
    p = subprocess.run(["git", "-C", str(d), "commit", "-F", "-"],
                       input=msg, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="хуки-проба-"))
    try:
        # 1. План испорчен, разрешения нет — хук обязан заблокировать.
        # Строка берётся из плана, а не выдумывается: первая версия
        # искала «- **Файлы:**», а в плане «**Файлы:**», ничего не портила
        # и рапортовала «хук пропустил» — то есть измеряла не хук.
        LOST = "**Файлы:**\n"
        t = make(base / "без-разрешения")
        plan = t / REL
        txt = plan.read_text(encoding="utf-8")
        if LOST not in txt:
            raise SystemExit(f"проба сломана: {LOST!r} нет в плане")
        plan.write_text(txt.replace(LOST, "", 1), encoding="utf-8")
        code, out = try_commit(t, "проба: должен быть заблокирован")
        blocked = "СВЕРКА НЕ ПРОШЛА" in out or code != 0
        print(f"1. без разрешения: код {code} — "
              f"{'ЗАБЛОКИРОВАН' if blocked else 'ПРОПУЩЕН'}")
        for ln in out.split("\n"):
            if "СВЕРКА" in ln or "разрешени" in ln:
                print(f"     {ln.strip()[:88]}")

        # 2. Та же поломка, но разрешение создано — хук обязан пропустить.
        t2 = make(base / "с-разрешением")
        plan2 = t2 / REL
        txt2 = plan2.read_text(encoding="utf-8")
        plan2.write_text(txt2.replace(LOST, "", 1), encoding="utf-8")
        (t2 / ".git" / "разрешение-потерь-плана").write_text(
            "**Файлы:**", encoding="utf-8")
        code2, out2 = try_commit(t2, "проба: должен пройти")
        passed = code2 == 0
        print(f"2. с разрешением:  код {code2} — "
              f"{'ПРОПУЩЕН' if passed else 'ЗАБЛОКИРОВАН'}")

        print()
        print(f"hooksPath в пробном репозитории: "
              f"{git(t, 'config', 'core.hooksPath').stdout.strip()}")
        print(f"хук брался из tools/hooks, не из .git/hooks: "
              f"{(t / '.git' / 'hooks' / 'pre-commit').exists() is False}")
        print()
        if blocked and passed:
            print("ИТОГ: при hooksPath хук и блокирует, и пропускает — "
                  "значит в свежем клоне он будет работать.")
            return 0
        print("ИТОГ: НЕ ДОКАЗАНО.")
        return 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())