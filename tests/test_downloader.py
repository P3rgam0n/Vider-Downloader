"""Unit tests for the resumable segmented Downloader engine."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vider_downloader.downloader import (
    DownloadCancelled,
    Downloader,
    DownloadError,
    resolve_safe_output_path,
)
from vider_downloader.models import DownloadProgress, VideoInfo


def _make_video_info(file_size: int | None) -> VideoInfo:
    return VideoInfo(
        id="DEMO10",
        title="Sample Video",
        extension="mp4",
        duration=60,
        stream_url="https://stream.vider.info/video/10/v.mp4",
        embed_url="https://vider.pl/embed/video/DEMO10",
        poster_url="",
        file_size=file_size,
    )


def _mock_stream_response(status_code: int, payload: bytes):
    resp = MagicMock(status_code=status_code)
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    chunks = [payload[i : i + 4] for i in range(0, len(payload), 4)] or [b""]
    resp.iter_content.return_value = iter(chunks)
    return resp


class TestDownloader:
    def test_resolve_safe_output_path_prevents_traversal(self, tmp_path):
        safe = resolve_safe_output_path(tmp_path, "../../evil.exe")
        resolved = Path(safe)
        assert resolved.parent == tmp_path.resolve()
        assert resolved.name == "evil.mp4"

    def test_segmented_download_and_progress_callbacks(self, tmp_path):
        payload = b"0123456789ABCDEF"  # 16 bytes
        info = _make_video_info(len(payload))

        session = MagicMock()
        session.headers = {}
        session.get.side_effect = [
            _mock_stream_response(206, payload[:8]),
            _mock_stream_response(206, payload[8:]),
        ]

        dl = Downloader(session=session, max_retries=2, retry_base_delay=0.0)
        dl.SEGMENT_SIZE = 8
        dl.CHUNK_SIZE = 4

        updates: list[DownloadProgress] = []
        target = tmp_path / "video.mp4"
        final_path = dl.download(info, str(target), progress_callback=updates.append)

        assert Path(final_path).read_bytes() == payload
        assert not Path(f"{target}.part").exists()
        assert updates[-1].percent == 100.0
        assert updates[-1].downloaded_bytes == len(payload)

    def test_resume_from_existing_part_file(self, tmp_path):
        payload = b"AAAABBBBCCCC"
        info = _make_video_info(len(payload))
        target = tmp_path / "resumed.mp4"
        Path(f"{target}.part").write_bytes(payload[:4])

        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_stream_response(206, payload[4:])

        dl = Downloader(session=session, max_retries=2, retry_base_delay=0.0)
        dl.SEGMENT_SIZE = 32
        final_path = dl.download(info, str(target), resume=True)

        assert Path(final_path).read_bytes() == payload
        called_headers = session.get.call_args.kwargs["headers"]
        assert called_headers["Range"] == f"bytes=4-{len(payload) - 1}"

    def test_resume_handles_http_200_without_corrupting_file(self, tmp_path):
        payload = b"FULL_PAYLOAD_DATA"
        info = _make_video_info(len(payload))
        target = tmp_path / "no_range.mp4"
        Path(f"{target}.part").write_bytes(b"STALE")

        session = MagicMock()
        session.headers = {}
        # Server ignores Range and sends 200 OK with full payload
        session.get.return_value = _mock_stream_response(200, payload)

        dl = Downloader(session=session, max_retries=2, retry_base_delay=0.0)
        final_path = dl.download(info, str(target), resume=True)

        assert Path(final_path).read_bytes() == payload

    def test_http_error_exhausts_retries_without_infinite_loop(self, tmp_path):
        info = _make_video_info(16)
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_stream_response(403, b"Forbidden")

        dl = Downloader(session=session, max_retries=3, retry_base_delay=0.0)
        with pytest.raises(DownloadError, match="HTTP 403"):
            dl.download(info, str(tmp_path / "fail.mp4"))

        assert session.get.call_count == 3

    def test_cancellation_stops_and_preserves_part_file(self, tmp_path):
        info = _make_video_info(16)
        cancel = threading.Event()

        resp = MagicMock(status_code=206)
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None

        def chunk_gen():
            yield b"ABCD"
            cancel.set()
            yield b"EFGH"

        resp.iter_content.return_value = chunk_gen()

        session = MagicMock()
        session.headers = {}
        session.get.return_value = resp

        target = tmp_path / "cancelled.mp4"
        dl = Downloader(session=session, max_retries=2, retry_base_delay=0.0)

        with pytest.raises(DownloadCancelled):
            dl.download(info, str(target), cancel_event=cancel)

        assert not target.exists()
        assert Path(f"{target}.part").read_bytes() == b"ABCD"
