"""Application paths, persistent settings, and secure local storage."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


def get_app_data_dir() -> Path:
    """Returns per-user application data directory suitable for both source and frozen (.exe) runs."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        app_dir = base / "ViderDownloader"
    elif sys.platform == "darwin":
        app_dir = Path.home() / "Library" / "Application Support" / "ViderDownloader"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        app_dir = base / "vider-downloader"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_session_file_path() -> Path:
    """Returns path to the local cookie/session cache file."""
    return get_app_data_dir() / "session.json"


def get_settings_file_path() -> Path:
    """Returns path to the user GUI settings file."""
    return get_app_data_dir() / "settings.json"


def get_default_download_dir() -> Path:
    """Returns user-friendly default download directory for GUI mode."""
    downloads = Path.home() / "Downloads"
    if downloads.exists() and os.access(downloads, os.W_OK):
        return downloads / "Vider"
    return Path.cwd() / "downloads"


def set_private_permissions(path: Path) -> None:
    """Restricts file permissions to owner read/write on POSIX systems."""
    if os.name == "posix" and path.exists():
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


@dataclass
class AppSettings:
    """Persisted lightweight UI preferences."""

    output_dir: str
    overwrite: bool = False
    max_concurrent: int = 1

    @classmethod
    def default(cls) -> "AppSettings":
        return cls(output_dir=str(get_default_download_dir()), overwrite=False, max_concurrent=1)


def load_settings(settings_path: Optional[Path] = None) -> AppSettings:
    """Loads saved GUI settings or returns defaults on missing/invalid file."""
    path = settings_path or get_settings_file_path()
    defaults = AppSettings.default()
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        output_dir = str(data.get("output_dir") or defaults.output_dir)
        overwrite = bool(data.get("overwrite", defaults.overwrite))
        try:
            max_concurrent = int(data.get("max_concurrent", defaults.max_concurrent))
        except (TypeError, ValueError):
            max_concurrent = defaults.max_concurrent
        max_concurrent = max(1, min(10, max_concurrent))
        return AppSettings(output_dir=output_dir, overwrite=overwrite, max_concurrent=max_concurrent)
    except Exception:
        return defaults


def save_settings(settings: AppSettings, settings_path: Optional[Path] = None) -> None:
    """Persists GUI settings safely to disk."""
    path = settings_path or get_settings_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
        set_private_permissions(path)
    except OSError:
        pass
