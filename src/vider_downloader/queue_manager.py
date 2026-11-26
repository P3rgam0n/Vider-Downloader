"""Thread-safe batch download queue manager shared by GUI and CLI."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from vider_downloader.core import InvalidCaptchaError, ViderExtractor, parse_urls_from_text
from vider_downloader.downloader import (
    DownloadCancelled,
    Downloader,
    resolve_safe_output_path,
)
from vider_downloader.models import DownloadProgress, DownloadStatus, QueueItem

ItemCallback = Callable[[QueueItem], None]
QueueFinishedCallback = Callable[[Dict[str, int]], None]


class BatchQueueManager:
    """Manages multiple Vider download tasks sequentially with live progress and cancellation."""

    def __init__(
        self,
        extractor: Optional[ViderExtractor] = None,
        downloader: Optional[Downloader] = None,
    ):
        self.extractor = extractor or ViderExtractor()
        # Share HTTP session & cookies (e.g., solved Captcha) between extractor and downloader
        self.downloader = downloader or Downloader(session=self.extractor.session)
        self._lock = threading.RLock()
        self._items: List[QueueItem] = []
        self._cancel_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._worker_thread is not None and self._worker_thread.is_alive()

    def get_items(self) -> List[QueueItem]:
        with self._lock:
            return list(self._items)

    def get_item(self, uid: str) -> Optional[QueueItem]:
        with self._lock:
            for item in self._items:
                if item.uid == uid:
                    return item
            return None

    def add_from_text(self, text: str) -> Tuple[List[QueueItem], int, List[str]]:
        """
        Parses links from text and appends unique items to the queue.

        Returns:
            (added_items, duplicate_count, invalid_tokens)
        """
        parsed, text_dupes, invalid = parse_urls_from_text(text)
        added: List[QueueItem] = []
        duplicates = text_dupes

        with self._lock:
            existing_ids = {item.video_id for item in self._items}
            for raw_input, video_id in parsed:
                if video_id in existing_ids:
                    duplicates += 1
                    continue
                item = QueueItem(
                    uid=uuid.uuid4().hex[:10],
                    raw_input=raw_input,
                    video_id=video_id,
                )
                self._items.append(item)
                existing_ids.add(video_id)
                added.append(item)

        return added, duplicates, invalid

    def add_from_file(self, file_path: str | Path) -> Tuple[List[QueueItem], int, List[str]]:
        """Reads links from a UTF-8 text file and adds them to the queue."""
        content = Path(file_path).read_text(encoding="utf-8")
        return self.add_from_text(content)

    def remove_item(self, uid: str) -> bool:
        """Removes a non-active item from the queue."""
        with self._lock:
            for idx, item in enumerate(self._items):
                if item.uid == uid:
                    if item.status in (DownloadStatus.RESOLVING, DownloadStatus.DOWNLOADING):
                        return False
                    self._items.pop(idx)
                    return True
            return False

    def clear_completed(self) -> int:
        """Removes completed items from the queue and returns how many were removed."""
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i.status != DownloadStatus.COMPLETED]
            return before - len(self._items)

    def clear_all(self) -> bool:
        """Clears the entire queue when idle."""
        with self._lock:
            if self.is_running:
                return False
            self._items.clear()
            return True

    def retry_item(self, uid: str) -> bool:
        """Resets a failed or cancelled item back to PENDING."""
        with self._lock:
            item = self.get_item(uid)
            if not item:
                return False
            if item.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                item.status = DownloadStatus.PENDING
                item.error = None
                item.captcha_error = False
                item.progress = DownloadProgress()
                return True
            return False

    def retry_failed(self) -> int:
        """Resets all failed and cancelled items back to PENDING."""
        count = 0
        with self._lock:
            for item in self._items:
                if item.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                    item.status = DownloadStatus.PENDING
                    item.error = None
                    item.captcha_error = False
                    item.progress = DownloadProgress()
                    count += 1
        return count

    def cancel(self) -> None:
        """Requests cancellation of the currently running batch."""
        self._cancel_event.set()

    def get_summary(self) -> Dict[str, int]:
        """Returns aggregate counts by status."""
        with self._lock:
            summary = {
                "total": len(self._items),
                "pending": 0,
                "active": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
            }
            for item in self._items:
                if item.status == DownloadStatus.PENDING:
                    summary["pending"] += 1
                elif item.status in (DownloadStatus.RESOLVING, DownloadStatus.DOWNLOADING):
                    summary["active"] += 1
                elif item.status == DownloadStatus.COMPLETED:
                    summary["completed"] += 1
                elif item.status == DownloadStatus.FAILED:
                    summary["failed"] += 1
                elif item.status == DownloadStatus.CANCELLED:
                    summary["cancelled"] += 1
            return summary

    def start(
        self,
        output_dir: str,
        overwrite: bool = False,
        info_only: bool = False,
        on_item_update: Optional[ItemCallback] = None,
        on_queue_finished: Optional[QueueFinishedCallback] = None,
        max_concurrent: int = 1,
    ) -> threading.Thread:
        """Starts processing pending items in a background daemon thread."""
        with self._lock:
            if self.is_running:
                assert self._worker_thread is not None
                return self._worker_thread

            self._cancel_event.clear()
            thread = threading.Thread(
                target=self.run_sync,
                kwargs={
                    "output_dir": output_dir,
                    "overwrite": overwrite,
                    "info_only": info_only,
                    "on_item_update": on_item_update,
                    "on_queue_finished": on_queue_finished,
                    "max_concurrent": max_concurrent,
                },
                daemon=True,
                name="vider-batch-worker",
            )
            self._worker_thread = thread
            thread.start()
            return thread

    def run_sync(
        self,
        output_dir: str,
        overwrite: bool = False,
        info_only: bool = False,
        on_item_update: Optional[ItemCallback] = None,
        on_queue_finished: Optional[QueueFinishedCallback] = None,
        max_concurrent: int = 1,
    ) -> Dict[str, int]:
        """Synchronously processes pending items using up to `max_concurrent` parallel workers."""
        self._cancel_event.clear()
        workers_count = max(1, int(max_concurrent))

        def worker() -> None:
            while True:
                item = self._claim_next_pending_item()
                if item is None:
                    return
                if self._cancel_event.is_set():
                    item.status = DownloadStatus.CANCELLED
                    item.error = "Zatrzymano kolejkę."
                    self._notify(on_item_update, item)
                    return
                self._process_single_item(
                    item=item,
                    output_dir=output_dir,
                    overwrite=overwrite,
                    info_only=info_only,
                    on_item_update=on_item_update,
                )

        threads = [
            threading.Thread(target=worker, daemon=True, name=f"vider-dl-{i}")
            for i in range(workers_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = self.get_summary()
        if on_queue_finished is not None:
            on_queue_finished(summary)
        return summary

    def _claim_next_pending_item(self) -> Optional[QueueItem]:
        """Atomically picks the next PENDING item and marks it RESOLVING."""
        with self._lock:
            for item in self._items:
                if item.status == DownloadStatus.PENDING:
                    item.status = DownloadStatus.RESOLVING
                    return item
            return None

    def _process_single_item(
        self,
        item: QueueItem,
        output_dir: str,
        overwrite: bool,
        info_only: bool,
        on_item_update: Optional[ItemCallback],
    ) -> None:
        item.status = DownloadStatus.RESOLVING
        item.error = None
        self._notify(on_item_update, item)

        try:
            # Resolve metadata just-in-time so temporary stream tokens do not expire mid-batch
            info = self.extractor.extract(item.raw_input)
            item.video_info = info
            item.title = info.title

            if self._cancel_event.is_set():
                raise DownloadCancelled("Pobieranie zatrzymane przez użytkownika.")

            if info_only:
                item.status = DownloadStatus.COMPLETED
                self._notify(on_item_update, item)
                return

            filename = item.custom_filename or info.default_filename
            target_path = resolve_safe_output_path(output_dir, filename)
            item.output_path = target_path
            item.status = DownloadStatus.DOWNLOADING
            self._notify(on_item_update, item)

            def on_progress(prog: DownloadProgress) -> None:
                item.progress = prog
                self._notify(on_item_update, item)

            final_path = self.downloader.download(
                video_info=info,
                output_path=target_path,
                resume=True,
                overwrite=overwrite,
                progress_callback=on_progress,
                cancel_event=self._cancel_event,
            )
            item.output_path = final_path
            item.status = DownloadStatus.COMPLETED
            self._notify(on_item_update, item)

        except DownloadCancelled as exc:
            item.status = DownloadStatus.CANCELLED
            item.error = str(exc)
            self._notify(on_item_update, item)
        except Exception as exc:
            item.status = DownloadStatus.FAILED
            item.error = str(exc)
            item.captcha_error = isinstance(exc, InvalidCaptchaError)
            self._notify(on_item_update, item)

    @staticmethod
    def _notify(callback: Optional[ItemCallback], item: QueueItem) -> None:
        if callback is not None:
            callback(item)
