"""Dark theme color palette and UI constants for Vider Downloader."""

from __future__ import annotations

from vider_downloader.models import DownloadStatus

# Modern dark theme palette
BG_APP = "#0b0f19"
BG_CARD = "#111827"
BG_INPUT = "#1f2937"
BG_ROW = "#161f30"
BG_BUTTON_MUTED = "#1f2937"
BG_BUTTON_MUTED_HOVER = "#374151"
BORDER = "#273449"

TEXT_PRIMARY = "#f9fafb"
TEXT_SECONDARY = "#cbd5e1"
TEXT_MUTED = "#94a3b8"
TEXT_ON_ACCENT = "#0b0f19"

ACCENT = "#38bdf8"
ACCENT_HOVER = "#0ea5e9"
SUCCESS = "#34d399"
SUCCESS_HOVER = "#10b981"
WARNING = "#fbbf24"
DANGER = "#f87171"
DANGER_HOVER = "#ef4444"

STATUS_STYLES: dict[DownloadStatus, tuple[str, str, str]] = {
    # status -> (Polish label, pill bg, text color)
    DownloadStatus.PENDING: ("Oczekuje", "#1e293b", "#cbd5e1"),
    DownloadStatus.RESOLVING: ("Analiza...", "#172554", "#60a5fa"),
    DownloadStatus.DOWNLOADING: ("Pobieranie", "#083344", "#38bdf8"),
    DownloadStatus.COMPLETED: ("Ukończono", "#064e3b", "#34d399"),
    DownloadStatus.FAILED: ("Błąd", "#450a0a", "#f87171"),
    DownloadStatus.CANCELLED: ("Zatrzymano", "#422006", "#fbbf24"),
}
