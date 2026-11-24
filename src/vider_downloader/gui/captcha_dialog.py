"""In-app modal dialog for solving Vider anti-bot Captcha images safely in memory."""

from __future__ import annotations

import io
import threading
from typing import Optional

import customtkinter as ctk
from PIL import Image

from vider_downloader.gui import theme


class CaptchaDialog(ctk.CTkToplevel):
    """Modal window displaying Captcha PNG bytes directly without writing temp files."""

    def __init__(self, master: ctk.CTk, image_bytes: bytes):
        super().__init__(master)
        self.title("Weryfikacja Anty-Bot (Captcha)")
        self.geometry("400x290")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_APP)

        self.result: Optional[str] = None
        self._done_event = threading.Event()

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        container = ctk.CTkFrame(
            self,
            fg_color=theme.BG_CARD,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=12,
        )
        container.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            container,
            text="Serwis Vider wymaga przepisania kodu",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(14, 4))

        ctk.CTkLabel(
            container,
            text="Sesja zostanie zapamiętana lokalnie po poprawnej weryfikacji.",
            font=ctk.CTkFont(size=12),
            text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 10))

        # Decode PNG directly from bytes in memory
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        scale = min(280 / max(width, 1), 90 / max(height, 1), 2.0)
        display_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        self._ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=display_size)

        img_frame = ctk.CTkFrame(container, fg_color="#ffffff", corner_radius=8)
        img_frame.pack(pady=(0, 12), padx=20)
        ctk.CTkLabel(img_frame, text="", image=self._ctk_image).pack(padx=10, pady=8)

        self._entry = ctk.CTkEntry(
            container,
            placeholder_text="Wpisz kod z obrazka...",
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            height=36,
            width=240,
            justify="center",
        )
        self._entry.pack(pady=(0, 12))
        self._entry.bind("<Return>", lambda _e: self._on_submit())
        self._entry.focus_set()

        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(pady=(0, 12))

        ctk.CTkButton(
            btn_row,
            text="Anuluj",
            width=105,
            height=34,
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_SECONDARY,
            command=self._on_cancel,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_row,
            text="Zatwierdź",
            width=125,
            height=34,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color=theme.TEXT_ON_ACCENT,
            font=ctk.CTkFont(weight="bold"),
            command=self._on_submit,
        ).pack(side="left", padx=6)

    def _on_submit(self) -> None:
        text = self._entry.get().strip()
        self.result = text if text else None
        self._finish()

    def _on_cancel(self) -> None:
        self.result = None
        self._finish()

    def _finish(self) -> None:
        if not self._done_event.is_set():
            self._done_event.set()
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass

    def wait_for_result(self) -> Optional[str]:
        self._done_event.wait()
        return self.result
