"""Allow running Vider Downloader via `python -m vider_downloader` or PyInstaller."""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if _stream is not None:
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

from vider_downloader.cli import main  # noqa: E402

if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
