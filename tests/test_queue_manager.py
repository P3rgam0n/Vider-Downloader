"""Unit tests for BatchQueueManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from vider_downloader.models import DownloadProgress, DownloadStatus, VideoInfo
from vider_downloader.queue_manager import BatchQueueManager


def _make_fake_info(video_id: str) -> VideoInfo:
    return VideoInfo(
        id=video_id,
        title=f"Sample {video_id}",
        extension="mp4",
        duration=120,
        stream_url=f"https://stream.vider.info/video/{video_id}/v.mp4",
        embed_url=f"https://vider.pl/embed/video/{video_id}",
        poster_url="",
        file_size=1024,
    )


class TestBatchQueueManager:
    def test_add_deduplicate_and_import_file(self, tmp_path):
        extractor = MagicMock()
        extractor.session = MagicMock()
        downloader = MagicMock()
        qm = BatchQueueManager(extractor=extractor, downloader=downloader)

        added, dupes, invalid = qm.add_from_text(
            "https://vider.info/vid/+fITEM01\nhttps://vider.pl/embed/video/ITEM01\nbad_url!"
        )
        assert len(added) == 1
        assert dupes == 1
        assert invalid == ["bad_url!"]

        links_file = tmp_path / "batch.txt"
        links_file.write_text(
            "# comment\nhttps://vider.info/vid/+fITEM01\nhttps://vider.info/vid/+fITEM02\n",
            encoding="utf-8",
        )
        added2, dupes2, invalid2 = qm.add_from_file(links_file)
        assert [i.video_id for i in added2] == ["ITEM02"]
        assert dupes2 == 1
        assert invalid2 == []

    def test_run_sync_partial_failure_and_retry(self, tmp_path):
        extractor = MagicMock()
        extractor.session = MagicMock()

        def fake_extract(raw: str) -> VideoInfo:
            if "FAIL02" in raw:
                raise RuntimeError("Temporary server error")
            vid = raw[-6:]
            return _make_fake_info(vid)

        extractor.extract.side_effect = fake_extract

        downloader = MagicMock()

        def fake_download(video_info, output_path, progress_callback=None, **_kwargs):
            Path(output_path).write_bytes(b"DATA")
            if progress_callback:
                progress_callback(DownloadProgress(downloaded_bytes=4, total_bytes=4, percent=100.0))
            return output_path

        downloader.download.side_effect = fake_download

        qm = BatchQueueManager(extractor=extractor, downloader=downloader)
        qm.add_from_text("+fGOOD01\n+fFAIL02\n+fGOOD03")

        summary = qm.run_sync(output_dir=str(tmp_path))
        assert summary["completed"] == 2
        assert summary["failed"] == 1
        assert summary["total"] == 3

        # Retry failed item after error resolves
        extractor.extract.side_effect = lambda raw: _make_fake_info(raw[-6:])
        retried = qm.retry_failed()
        assert retried == 1

        summary2 = qm.run_sync(output_dir=str(tmp_path))
        assert summary2["completed"] == 3
        assert summary2["failed"] == 0

        cleared = qm.clear_completed()
        assert cleared == 3
        assert qm.get_items() == []

    def test_remove_item_and_clear_all(self):
        extractor = MagicMock()
        extractor.session = MagicMock()
        qm = BatchQueueManager(extractor=extractor, downloader=MagicMock())
        added, _, _ = qm.add_from_text("+fDEMO01\n+fDEMO02")

        assert qm.remove_item(added[0].uid) is True
        assert len(qm.get_items()) == 1
        assert qm.clear_all() is True
        assert qm.get_items() == []
        assert qm.get_summary()["total"] == 0
        assert DownloadStatus.PENDING.value == "pending"


class TestConcurrencyAndCaptcha:
    def test_parallel_downloads_respect_limit(self, tmp_path):
        import threading
        import time

        extractor = MagicMock()
        extractor.session = MagicMock()
        extractor.extract.side_effect = lambda raw: _make_fake_info(raw)
        downloader = MagicMock()
        lock = threading.Lock()
        state = {"now": 0, "peak": 0}

        def fake_download(**kwargs):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.1)
            with lock:
                state["now"] -= 1
            return kwargs["output_path"]

        downloader.download.side_effect = fake_download
        qm = BatchQueueManager(extractor=extractor, downloader=downloader)
        qm.add_from_text("AAAA01 AAAA02 AAAA03 AAAA04 AAAA05 AAAA06")
        summary = qm.run_sync(output_dir=str(tmp_path), max_concurrent=3)
        assert summary["completed"] == 6
        assert state["peak"] == 3

    def test_invalid_captcha_flagged_on_item(self, tmp_path):
        from vider_downloader.core import InvalidCaptchaError

        extractor = MagicMock()
        extractor.session = MagicMock()
        extractor.extract.side_effect = InvalidCaptchaError("zły kod")
        qm = BatchQueueManager(extractor=extractor, downloader=MagicMock())
        qm.add_from_text("BBBB01")
        qm.run_sync(output_dir=str(tmp_path))
        item = qm.get_items()[0]
        assert item.status == DownloadStatus.FAILED
        assert item.captcha_error is True
        assert qm.retry_item(item.uid) and item.captcha_error is False
