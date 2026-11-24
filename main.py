#!/usr/bin/env python3
"""
Vider Downloader — główny punkt wejścia (GUI oraz CLI).

Użycie:
  python main.py                         # uruchamia interfejs graficzny (GUI)
  python main.py --cli                   # uruchamia interaktywny tryb terminalowy
  python main.py URL1 [URL2 ...]         # pobiera jeden lub wiele linków (CLI)
  python main.py --batch links.txt       # pobiera listę z pliku tekstowego
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles (when stdout/stderr are attached)
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

# Allow running directly from repository root without installing the package
_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.is_dir():
    _src_str = str(_SRC_DIR)
    if _src_str not in sys.path:
        sys.path.insert(0, _src_str)

from vider_downloader.cli import main  # noqa: E402

if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
