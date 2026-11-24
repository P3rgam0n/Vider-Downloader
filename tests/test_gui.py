"""Headless smoke tests for the CustomTkinter desktop GUI."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

from vider_downloader.queue_manager import BatchQueueManager


def _display_available() -> bool:
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@pytest.mark.skipif(not _display_available(), reason="No graphical display available")
def test_gui_smoke_add_and_remove_batch_links():
    from vider_downloader.gui.app import ViderApp

    extractor = MagicMock()
    extractor.session = MagicMock()
    qm = BatchQueueManager(extractor=extractor, downloader=MagicMock())

    app = ViderApp(queue_manager=qm)
    try:
        app.update()
        app._clear_placeholder()
        app._url_textbox.insert(
            "1.0",
            "https://vider.info/vid/+fDEMO01\nhttps://vider.pl/embed/video/DEMO02\n",
        )
        app._on_add_links()
        app.update()

        assert len(app._rows) == 2
        assert qm.get_summary()["total"] == 2

        first_uid = next(iter(app._rows.keys()))
        app._on_remove_item(first_uid)
        app.update()

        assert len(app._rows) == 1
        assert qm.get_summary()["total"] == 1
    finally:
        app.destroy()
