"""Запуск окна управления базой без чёрного окна консоли.

Двойной щелчок по этому файлу открывает программу.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main.run())
