"""Data models for video metadata, download progress, and batch queue items."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

ALLOWED_VIDEO_EXTENSIONS = frozenset(
    {"mp4", "mkv", "webm", "avi", "mov", "flv", "rmvb", "ts", "m4v", "wmv"}
)

WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """Sanitizes filename safely across Windows, Linux, and macOS filesystems."""
    if not name:
        return "video"

    cleaned = html.unescape(name)
    # Strip ASCII control characters
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    # Replace illegal filesystem characters and path separators
    cleaned = re.sub(r'[\\/*?:"<>|]', " ", cleaned)
    # Neutralize parent directory traversal segments
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    # Collapse whitespace and strip trailing dots/spaces (invalid on Windows)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")

    if not cleaned:
        return "video"

    # Guard against Windows reserved device names
    stem = cleaned.split(".")[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")

    return cleaned or "video"


def sanitize_extension(ext: Optional[str]) -> str:
    """Validates and normalizes video file extension against an allowlist."""
    if not ext:
        return "mp4"
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", ext.lstrip(".")).lower()
    if cleaned in ALLOWED_VIDEO_EXTENSIONS:
        return cleaned
    return "mp4"


def format_bytes(num_bytes: Optional[int]) -> str:
    """Formats a byte count into human-readable units."""
    if num_bytes is None or num_bytes < 0:
        return "Nieznany"
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    if mb >= 1:
        return f"{mb:.2f} MB"
    kb = num_bytes / 1024
    return f"{kb:.1f} KB"


def format_duration(seconds: int) -> str:
    """Formats seconds into HH:MM:SS or MM:SS."""
    if not seconds or seconds < 0:
        return "00:00"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass
class VideoInfo:
    """Extracted video metadata and stream URL."""

    id: str
    title: str
    extension: str
    duration: int
    stream_url: str
    embed_url: str
    poster_url: str
    file_size: Optional[int] = None
    page_url: Optional[str] = None

    @property
    def formatted_duration(self) -> str:
        """Returns human-readable duration (HH:MM:SS or MM:SS)."""
        return format_duration(self.duration)

    @property
    def formatted_size(self) -> str:
        """Returns human-readable file size."""
        return format_bytes(self.file_size)

    @property
    def default_filename(self) -> str:
        """Returns filesystem-safe default filename."""
        safe_title = sanitize_filename(self.title)
        safe_ext = sanitize_extension(self.extension)
        return f"{safe_title}.{safe_ext}"


class DownloadStatus(str, Enum):
    """Lifecycle states of a queued download item."""

    PENDING = "pending"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadProgress:
    """Snapshot of an ongoing or completed file transfer."""

    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed_bps: float = 0.0
    eta_seconds: Optional[float] = None
    percent: float = 0.0
    resumed: bool = False

    @property
    def formatted_speed(self) -> str:
        if self.speed_bps <= 0:
            return "—"
        mb_s = self.speed_bps / (1024 * 1024)
        if mb_s >= 1:
            return f"{mb_s:.2f} MB/s"
        return f"{self.speed_bps / 1024:.0f} KB/s"

    @property
    def formatted_eta(self) -> str:
        if self.eta_seconds is None or self.eta_seconds < 0:
            return "—"
        return format_duration(int(self.eta_seconds))


@dataclass
class QueueItem:
    """Represents a single video download task in the batch queue."""

    uid: str
    raw_input: str
    video_id: str
    status: DownloadStatus = DownloadStatus.PENDING
    title: str = ""
    video_info: Optional[VideoInfo] = None
    output_path: Optional[str] = None
    custom_filename: Optional[str] = None
    progress: DownloadProgress = field(default_factory=DownloadProgress)
    error: Optional[str] = None
    captcha_error: bool = False

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.video_info and self.video_info.title:
            return self.video_info.title
        return f"Wideo #{self.video_id}"
