"""UI-agnostic video download engine with segmented Range streaming, resume, and cancellation."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from vider_downloader.models import DownloadProgress, VideoInfo, sanitize_extension, sanitize_filename

ProgressCallback = Callable[[DownloadProgress], None]


class DownloadError(RuntimeError):
    """Raised when a download fails after exhausting retries."""


class DownloadCancelled(Exception):
    """Raised when a download is interrupted by the user via cancel_event."""


def resolve_safe_output_path(output_dir: str | Path, filename: str) -> str:
    """
    Safely combines output_dir and filename, preventing path traversal outside output_dir.
    """
    base_dir = Path(output_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    raw_name = Path(filename).name
    stem, ext = os.path.splitext(raw_name)
    safe_stem = sanitize_filename(stem)
    safe_ext = sanitize_extension(ext) if ext else "mp4"
    candidate = (base_dir / f"{safe_stem}.{safe_ext}").resolve()

    if base_dir not in candidate.parents:
        raise DownloadError("Nieprawidłowa ścieżka docelowa poza wybranym katalogiem.")
    return str(candidate)


class Downloader:
    """Segmented Range streaming downloader supporting resume, retry backoff, and cancellation."""

    SEGMENT_SIZE = 4 * 1024 * 1024  # 4 MB per Range segment
    CHUNK_SIZE = 64 * 1024          # 64 KB inner stream chunks for smooth progress & fast cancel
    PROGRESS_INTERVAL = 0.1         # Throttle progress callbacks to ~10 Hz

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        user_agent: Optional[str] = None,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ):
        self.session = session or requests.Session()
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self.max_retries = max(1, max_retries)
        self.retry_base_delay = max(0.0, retry_base_delay)
        self.session.headers.setdefault("User-Agent", self.user_agent)

    def download(
        self,
        video_info: VideoInfo,
        output_path: str,
        resume: bool = True,
        overwrite: bool = False,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> str:
        """
        Downloads a video to output_path with Range-based resume support.

        Returns the final path of the downloaded file.
        """
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        target_path = output_path
        part_path = f"{target_path}.part"
        total_size = video_info.file_size

        # Handle already-existing target file
        if os.path.exists(target_path) and not overwrite:
            existing_size = os.path.getsize(target_path)
            if total_size and existing_size == total_size:
                self._emit_progress(
                    progress_callback,
                    DownloadProgress(
                        downloaded_bytes=existing_size,
                        total_bytes=total_size,
                        percent=100.0,
                    ),
                )
                return target_path

            base, ext = os.path.splitext(target_path)
            idx = 1
            while os.path.exists(f"{base} ({idx}){ext}"):
                idx += 1
            target_path = f"{base} ({idx}){ext}"
            part_path = f"{target_path}.part"

        # Determine resume offset from existing .part file
        downloaded_bytes = 0
        resumed = False
        if resume and os.path.exists(part_path):
            downloaded_bytes = os.path.getsize(part_path)
            if total_size and downloaded_bytes >= total_size:
                os.replace(part_path, target_path)
                self._emit_progress(
                    progress_callback,
                    DownloadProgress(
                        downloaded_bytes=total_size,
                        total_bytes=total_size,
                        percent=100.0,
                        resumed=True,
                    ),
                )
                return target_path
            if downloaded_bytes > 0:
                resumed = True

        self._check_cancelled(cancel_event)

        start_time = time.monotonic()
        session_bytes = 0
        last_emit = 0.0

        def report(current: int, total: Optional[int], force: bool = False) -> None:
            nonlocal last_emit
            now = time.monotonic()
            if not force and (now - last_emit) < self.PROGRESS_INTERVAL:
                return
            last_emit = now
            elapsed = max(now - start_time, 1e-3)
            speed = session_bytes / elapsed
            percent = (current / total * 100.0) if (total and total > 0) else 0.0
            eta = ((total - current) / speed) if (total and total > current and speed > 0) else None
            self._emit_progress(
                progress_callback,
                DownloadProgress(
                    downloaded_bytes=current,
                    total_bytes=total,
                    speed_bps=speed,
                    eta_seconds=eta,
                    percent=min(100.0, percent),
                    resumed=resumed,
                ),
            )

        mode = "ab" if downloaded_bytes > 0 else "wb"
        current_byte = downloaded_bytes
        report(current_byte, total_size, force=True)

        def on_segment_chunk(chunk_len: int, base_byte: int, seg_written: int) -> None:
            nonlocal session_bytes
            session_bytes += chunk_len
            report(base_byte + seg_written, total_size)

        with open(part_path, mode) as file_handle:
            if total_size and total_size > 0:
                while current_byte < total_size:
                    self._check_cancelled(cancel_event)
                    end_byte = min(current_byte + self.SEGMENT_SIZE - 1, total_size - 1)
                    seg_headers = {
                        "Referer": video_info.embed_url,
                        "User-Agent": self.user_agent,
                        "Range": f"bytes={current_byte}-{end_byte}",
                    }
                    bytes_written, restarted_full = self._download_segment(
                        stream_url=video_info.stream_url,
                        headers=seg_headers,
                        file_handle=file_handle,
                        current_byte=current_byte,
                        total_size=total_size,
                        cancel_event=cancel_event,
                        on_chunk=on_segment_chunk,
                    )
                    if restarted_full:
                        # Server ignored Range and sent full file from byte 0
                        current_byte = bytes_written
                        break
                    if bytes_written <= 0:
                        raise DownloadError("Serwer zwrócił pusty segment danych.")
                    current_byte += bytes_written
                    report(current_byte, total_size)
            else:
                headers = {
                    "Referer": video_info.embed_url,
                    "User-Agent": self.user_agent,
                }
                if current_byte > 0:
                    headers["Range"] = f"bytes={current_byte}-"

                with self.session.get(
                    video_info.stream_url, headers=headers, stream=True, timeout=30
                ) as resp:
                    if resp.status_code not in (200, 206):
                        raise DownloadError(f"Błąd pobierania (HTTP {resp.status_code}).")
                    if resp.status_code == 200 and current_byte > 0:
                        file_handle.seek(0)
                        file_handle.truncate(0)
                        current_byte = 0
                    for chunk in resp.iter_content(chunk_size=self.CHUNK_SIZE):
                        self._check_cancelled(cancel_event)
                        if chunk:
                            file_handle.write(chunk)
                            current_byte += len(chunk)
                            session_bytes += len(chunk)
                            report(current_byte, total_size)
                    file_handle.flush()

        os.replace(part_path, target_path)
        final_size = os.path.getsize(target_path)
        self._emit_progress(
            progress_callback,
            DownloadProgress(
                downloaded_bytes=final_size,
                total_bytes=total_size or final_size,
                speed_bps=session_bytes / max(time.monotonic() - start_time, 1e-3),
                eta_seconds=0.0,
                percent=100.0,
                resumed=resumed,
            ),
        )
        return target_path

    def _download_segment(
        self,
        stream_url: str,
        headers: dict[str, str],
        file_handle,
        current_byte: int,
        total_size: int,
        cancel_event: Optional[threading.Event],
        on_chunk: Optional[Callable[[int, int, int], None]] = None,
    ) -> tuple[int, bool]:
        """Downloads a single Range segment with retries and backoff."""
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            self._check_cancelled(cancel_event)
            segment_start_pos = file_handle.tell()
            written = 0
            try:
                with self.session.get(stream_url, headers=headers, stream=True, timeout=20) as resp:
                    if resp.status_code not in (200, 206):
                        raise DownloadError(f"Serwer odrzucił żądanie segmentu (HTTP {resp.status_code}).")

                    restarted_full = False
                    effective_base = current_byte
                    if resp.status_code == 200 and current_byte > 0:
                        # Server ignored Range header and is sending the entire file from byte 0
                        file_handle.seek(0)
                        file_handle.truncate(0)
                        segment_start_pos = 0
                        effective_base = 0
                        restarted_full = True

                    for chunk in resp.iter_content(chunk_size=self.CHUNK_SIZE):
                        self._check_cancelled(cancel_event)
                        if chunk:
                            file_handle.write(chunk)
                            written += len(chunk)
                            if on_chunk:
                                on_chunk(len(chunk), effective_base, written)

                    file_handle.flush()
                    if restarted_full:
                        return written, True
                    if written == 0 and current_byte < total_size:
                        raise DownloadError("Otrzymano pustą odpowiedź dla segmentu wideo.")
                    return written, False

            except DownloadCancelled:
                file_handle.flush()
                raise
            except (requests.RequestException, DownloadError) as exc:
                last_error = exc
                # Roll back partial failed attempt so retries never duplicate bytes
                file_handle.seek(segment_start_pos)
                file_handle.truncate(segment_start_pos)
                if attempt < self.max_retries - 1:
                    delay = self.retry_base_delay * (2**attempt)
                    self._sleep_cancellable(delay, cancel_event)

        raise DownloadError(
            f"Nie udało się pobrać segmentu po {self.max_retries} próbach: {last_error}"
        ) from last_error

    @staticmethod
    def _check_cancelled(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("Pobieranie zostało zatrzymane przez użytkownika.")

    @staticmethod
    def _sleep_cancellable(seconds: float, cancel_event: Optional[threading.Event]) -> None:
        if seconds <= 0:
            return
        if cancel_event is None:
            time.sleep(seconds)
            return
        if cancel_event.wait(timeout=seconds):
            raise DownloadCancelled("Pobieranie zostało zatrzymane przez użytkownika.")

    @staticmethod
    def _emit_progress(
        callback: Optional[ProgressCallback], progress: DownloadProgress
    ) -> None:
        if callback is not None:
            callback(progress)
