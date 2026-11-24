"""Lightweight CustomTkinter desktop UI for Vider Downloader."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, Optional

import customtkinter as ctk

from vider_downloader import __app_name__, __version__
from vider_downloader.config import AppSettings, load_settings, save_settings
from vider_downloader.core import ViderExtractor
from vider_downloader.gui import theme
from vider_downloader.gui.captcha_dialog import CaptchaDialog
from vider_downloader.models import DownloadStatus, QueueItem, format_bytes
from vider_downloader.queue_manager import BatchQueueManager

PLACEHOLDER_TEXT = (
    "Wklej jeden lub kilka linków z Vider (każdy w nowej linii), np.:\n"
    "https://vider.info/vid/+fEXAMPLE1\n"
    "https://vider.pl/embed/video/EXAMPLE2"
)

DISCLAIMER_TEXT = (
    "Jak korzystać (3 proste kroki):\n"
    "1. Skopiuj jeden lub kilka linków do filmów i wklej je w górnym polu.\n"
    "2. Kliknij «Dodaj do kolejki» i sprawdź folder zapisu.\n"
    "3. Kliknij «Pobierz wszystko» — program pobierze listę po kolei "
    "i automatycznie wznowi przerwane pobierania.\n\n"
    "Prywatność:\n"
    "• Aplikacja nie wysyła żadnej telemetrii ani danych analitycznych.\n"
    "• Ustawienia i sesja zapisywane są wyłącznie lokalnie na Twoim komputerze.\n\n"
    "Zastrzeżenie prawne (Disclaimer):\n"
    "Narzędzie ma charakter edukacyjny i służy do archiwizacji materiałów, do których "
    "użytkownik posiada odpowiednie prawa. Autorzy nie hostują żadnych plików wideo "
    "i nie odpowiadają za sposób wykorzystania programu przez użytkowników końcowych."
)


class QueueRowWidget(ctk.CTkFrame):
    """Single card representing one video item in the batch download queue."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        item: QueueItem,
        on_remove,
        on_retry,
    ):
        super().__init__(
            master,
            fg_color=theme.BG_ROW,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=10,
        )
        self.uid = item.uid
        self._on_remove = on_remove
        self._on_retry = on_retry
        self._retry_visible = False

        # Top row: status badge + title + actions
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))

        self._status_badge = ctk.CTkLabel(
            top,
            text="",
            corner_radius=6,
            padx=8,
            pady=2,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self._status_badge.pack(side="left", padx=(0, 8))

        self._title_label = ctk.CTkLabel(
            top,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        )
        self._title_label.pack(side="left", fill="x", expand=True)

        self._retry_btn = ctk.CTkButton(
            top,
            text="Ponów",
            width=64,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.ACCENT,
            command=lambda: self._on_retry(self.uid),
        )

        self._remove_btn = ctk.CTkButton(
            top,
            text="✕",
            width=26,
            height=24,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent",
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_MUTED,
            command=lambda: self._on_remove(self.uid),
        )
        self._remove_btn.pack(side="right")

        # Progress bar
        self._progress_bar = ctk.CTkProgressBar(
            self,
            height=7,
            corner_radius=4,
            fg_color=theme.BG_INPUT,
            progress_color=theme.ACCENT,
        )
        self._progress_bar.pack(fill="x", padx=12, pady=(2, 4))
        self._progress_bar.set(0.0)

        # Bottom detail row
        self._meta_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=theme.TEXT_MUTED,
            anchor="w",
        )
        self._meta_label.pack(fill="x", padx=12, pady=(0, 8))

        self.update_from_item(item)

    def update_from_item(self, item: QueueItem) -> None:
        label_text, badge_bg, badge_fg = theme.STATUS_STYLES[item.status]
        self._status_badge.configure(text=label_text, fg_color=badge_bg, text_color=badge_fg)

        title = item.display_title
        if len(title) > 68:
            title = title[:65] + "..."
        self._title_label.configure(text=title)

        progress_val = max(0.0, min(1.0, item.progress.percent / 100.0))
        if item.status == DownloadStatus.COMPLETED:
            progress_val = 1.0
            self._progress_bar.configure(progress_color=theme.SUCCESS)
        elif item.status == DownloadStatus.FAILED:
            self._progress_bar.configure(progress_color=theme.DANGER)
        elif item.status == DownloadStatus.CANCELLED:
            self._progress_bar.configure(progress_color=theme.WARNING)
        else:
            self._progress_bar.configure(progress_color=theme.ACCENT)
        self._progress_bar.set(progress_val)

        # Action button visibility
        is_active = item.status in (DownloadStatus.RESOLVING, DownloadStatus.DOWNLOADING)
        self._remove_btn.configure(state="disabled" if is_active else "normal")
        if item.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            if not self._retry_visible:
                self._retry_btn.pack(side="right", padx=(0, 6))
                self._retry_visible = True
        else:
            if self._retry_visible:
                self._retry_btn.pack_forget()
                self._retry_visible = False

        # Meta info line
        if item.status == DownloadStatus.FAILED and item.error:
            self._meta_label.configure(text=f"Błąd: {item.error}", text_color=theme.DANGER)
        elif item.status == DownloadStatus.CANCELLED:
            self._meta_label.configure(
                text="Zatrzymano — możesz wznowić od miejsca przerwania (.part).",
                text_color=theme.WARNING,
            )
        elif item.status == DownloadStatus.RESOLVING:
            self._meta_label.configure(
                text=f"Pobieranie informacji o filmie ({item.video_id})...",
                text_color=theme.TEXT_SECONDARY,
            )
        elif item.status == DownloadStatus.DOWNLOADING:
            prog = item.progress
            total_str = format_bytes(prog.total_bytes) if prog.total_bytes else "?"
            done_str = format_bytes(prog.downloaded_bytes)
            detail = (
                f"{prog.percent:5.1f}%  •  {done_str} / {total_str}"
                f"  •  {prog.formatted_speed}  •  ETA: {prog.formatted_eta}"
            )
            self._meta_label.configure(text=detail, text_color=theme.TEXT_SECONDARY)
        elif item.status == DownloadStatus.COMPLETED:
            size_str = format_bytes(item.progress.downloaded_bytes)
            saved_name = Path(item.output_path).name if item.output_path else ""
            self._meta_label.configure(
                text=f"Zapisano: {saved_name} ({size_str})",
                text_color=theme.SUCCESS,
            )
        else:
            self._meta_label.configure(
                text=f"ID: {item.video_id}  •  Gotowe do pobrania",
                text_color=theme.TEXT_MUTED,
            )


class ViderApp(ctk.CTk):
    """Main desktop application window for Vider Downloader."""

    def __init__(self, queue_manager: Optional[BatchQueueManager] = None):
        super().__init__()
        ctk.set_appearance_mode("dark")

        self.title(f"{__app_name__} v{__version__}")
        self.geometry("880x700")
        self.minsize(720, 560)
        self.configure(fg_color=theme.BG_APP)

        self._settings: AppSettings = load_settings()
        extractor = ViderExtractor(captcha_handler=self._solve_captcha_from_worker)
        self.queue_manager = queue_manager or BatchQueueManager(extractor=extractor)

        self._rows: Dict[str, QueueRowWidget] = {}
        self._has_placeholder = True
        self._empty_visible = True

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=20, pady=16)

        # 1. Header
        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.pack(side="left", fill="x", expand=True)

        title_line = ctk.CTkFrame(title_block, fg_color="transparent")
        title_line.pack(anchor="w")

        ctk.CTkLabel(
            title_line,
            text=__app_name__,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")

        ctk.CTkLabel(
            title_line,
            text=f"v{__version__}",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=theme.BG_INPUT,
            text_color=theme.ACCENT,
            corner_radius=6,
            padx=8,
            pady=2,
        ).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            title_block,
            text="Lekkie pobieranie pojedynczych filmów i całych list (Batch) z vider.info / vider.pl",
            font=ctk.CTkFont(size=12),
            text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkButton(
            header,
            text="?  Pomoc i Info",
            width=120,
            height=32,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            border_width=1,
            border_color=theme.BORDER,
            text_color=theme.TEXT_SECONDARY,
            command=self._show_about_dialog,
        ).pack(side="right", anchor="n")

        # 2. Batch Link Input Card
        input_card = ctk.CTkFrame(
            root,
            fg_color=theme.BG_CARD,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=12,
        )
        input_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            input_card,
            text="Dodaj linki do pobrania",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=14, pady=(12, 6))

        self._url_textbox = ctk.CTkTextbox(
            input_card,
            height=78,
            fg_color=theme.BG_INPUT,
            border_width=1,
            border_color=theme.BORDER,
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            corner_radius=8,
        )
        self._url_textbox.pack(fill="x", padx=14, pady=(0, 8))
        self._url_textbox.insert("1.0", PLACEHOLDER_TEXT)
        self._url_textbox.bind("<FocusIn>", self._clear_placeholder)
        self._url_textbox.bind("<FocusOut>", self._restore_placeholder)

        input_actions = ctk.CTkFrame(input_card, fg_color="transparent")
        input_actions.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkButton(
            input_actions,
            text="+  Dodaj do kolejki",
            width=155,
            height=34,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color=theme.TEXT_ON_ACCENT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_add_links,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            input_actions,
            text="Wklej ze schowka",
            width=130,
            height=34,
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_SECONDARY,
            command=self._on_paste_clipboard,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            input_actions,
            text="Wczytaj plik .txt",
            width=125,
            height=34,
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_SECONDARY,
            command=self._on_import_txt,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            input_actions,
            text="Wyczyść pole",
            width=100,
            height=34,
            fg_color="transparent",
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_MUTED,
            command=self._clear_input_box,
        ).pack(side="right")

        self._feedback_label = ctk.CTkLabel(
            input_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=theme.TEXT_MUTED,
            anchor="w",
        )
        self._feedback_label.pack(fill="x", padx=14, pady=(0, 8))

        # 3. Output Directory Bar
        out_card = ctk.CTkFrame(
            root,
            fg_color=theme.BG_CARD,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=12,
        )
        out_card.pack(fill="x", pady=(0, 12))

        out_row = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(
            out_row,
            text="Folder zapisu:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 8))

        self._output_var = ctk.StringVar(value=self._settings.output_dir)
        self._output_entry = ctk.CTkEntry(
            out_row,
            textvariable=self._output_var,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            height=32,
        )
        self._output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            out_row,
            text="Zmień...",
            width=82,
            height=32,
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_SECONDARY,
            command=self._on_choose_folder,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            out_row,
            text="Otwórz",
            width=74,
            height=32,
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_SECONDARY,
            command=self._on_open_folder,
        ).pack(side="left", padx=(0, 12))

        self._overwrite_var = ctk.BooleanVar(value=self._settings.overwrite)
        ctk.CTkCheckBox(
            out_row,
            text="Nadpisuj istniejące",
            variable=self._overwrite_var,
            font=ctk.CTkFont(size=12),
            text_color=theme.TEXT_SECONDARY,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
            checkbox_width=18,
            checkbox_height=18,
            command=self._persist_settings,
        ).pack(side="left")

        # 4. Queue Card
        queue_card = ctk.CTkFrame(
            root,
            fg_color=theme.BG_CARD,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=12,
        )
        queue_card.pack(fill="both", expand=True, pady=(0, 12))

        q_header = ctk.CTkFrame(queue_card, fg_color="transparent")
        q_header.pack(fill="x", padx=14, pady=(10, 6))

        self._queue_title = ctk.CTkLabel(
            q_header,
            text="Kolejka pobierania (0)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self._queue_title.pack(side="left")

        ctk.CTkButton(
            q_header,
            text="Wyczyść gotowe",
            width=115,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.TEXT_SECONDARY,
            command=self._on_clear_completed,
        ).pack(side="right")

        ctk.CTkButton(
            q_header,
            text="Ponów nieudane",
            width=115,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color=theme.BG_BUTTON_MUTED,
            hover_color=theme.BG_BUTTON_MUTED_HOVER,
            text_color=theme.ACCENT,
            command=self._on_retry_failed,
        ).pack(side="right", padx=(0, 8))

        self._queue_scroll = ctk.CTkScrollableFrame(
            queue_card,
            fg_color="transparent",
            scrollbar_button_color=theme.BG_INPUT,
            scrollbar_button_hover_color=theme.BORDER,
        )
        self._queue_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._empty_label = ctk.CTkLabel(
            self._queue_scroll,
            text="Kolejka jest pusta.\nWklej linki powyżej i kliknij «Dodaj do kolejki».",
            font=ctk.CTkFont(size=13),
            text_color=theme.TEXT_MUTED,
            justify="center",
        )
        self._empty_label.pack(pady=48)

        # 5. Footer Controls
        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x")

        self._summary_label = ctk.CTkLabel(
            footer,
            text="Gotowy do pracy",
            font=ctk.CTkFont(size=12),
            text_color=theme.TEXT_SECONDARY,
        )
        self._summary_label.pack(side="left")

        self._start_btn = ctk.CTkButton(
            footer,
            text="▶   Pobierz wszystko",
            width=190,
            height=40,
            fg_color=theme.SUCCESS,
            hover_color=theme.SUCCESS_HOVER,
            text_color=theme.TEXT_ON_ACCENT,
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
            command=self._on_toggle_download,
        )
        self._start_btn.pack(side="right")

    # ------------------------------------------------------------------
    # Placeholder & Input Actions
    # ------------------------------------------------------------------
    def _clear_placeholder(self, _event=None) -> None:
        if self._has_placeholder:
            self._url_textbox.delete("1.0", "end")
            self._url_textbox.configure(text_color=theme.TEXT_PRIMARY)
            self._has_placeholder = False

    def _restore_placeholder(self, _event=None) -> None:
        content = self._url_textbox.get("1.0", "end").strip()
        if not content:
            self._url_textbox.delete("1.0", "end")
            self._url_textbox.insert("1.0", PLACEHOLDER_TEXT)
            self._url_textbox.configure(text_color=theme.TEXT_MUTED)
            self._has_placeholder = True

    def _clear_input_box(self) -> None:
        self._url_textbox.delete("1.0", "end")
        self._has_placeholder = False
        self._restore_placeholder()

    def _get_input_text(self) -> str:
        if self._has_placeholder:
            return ""
        return self._url_textbox.get("1.0", "end").strip()

    def _on_paste_clipboard(self) -> None:
        try:
            clip = self.clipboard_get().strip()
        except Exception:
            self._set_feedback("Schowek jest pusty lub nie zawiera tekstu.", theme.WARNING)
            return
        if not clip:
            self._set_feedback("Schowek jest pusty.", theme.WARNING)
            return
        self._clear_placeholder()
        existing = self._url_textbox.get("1.0", "end").strip()
        if existing:
            self._url_textbox.insert("end", "\n" + clip)
        else:
            self._url_textbox.insert("1.0", clip)
        self._set_feedback("Wklejono zawartość schowka. Kliknij «Dodaj do kolejki».", theme.ACCENT)

    def _on_import_txt(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Wybierz plik tekstowy z linkami",
            filetypes=[("Pliki tekstowe", "*.txt"), ("Wszystkie pliki", "*.*")],
        )
        if not file_path:
            return
        try:
            added, dupes, invalid = self.queue_manager.add_from_file(file_path)
            self._append_rows(added)
            self._report_add_result(len(added), dupes, len(invalid))
        except Exception as exc:
            self._set_feedback(f"Nie udało się wczytać pliku: {exc}", theme.DANGER)

    def _on_add_links(self) -> None:
        raw_text = self._get_input_text()
        if not raw_text:
            self._set_feedback("Wklej najpierw co najmniej jeden link z Vider.", theme.WARNING)
            return

        added, dupes, invalid = self.queue_manager.add_from_text(raw_text)
        self._append_rows(added)
        self._report_add_result(len(added), dupes, len(invalid))
        if added:
            self._clear_input_box()

    def _report_add_result(self, added_count: int, dupes: int, invalid_count: int) -> None:
        parts = []
        if added_count:
            parts.append(f"Dodano do kolejki: {added_count}")
        if dupes:
            parts.append(f"pominięto duplikaty: {dupes}")
        if invalid_count:
            parts.append(f"nierozpoznane wpisy: {invalid_count}")

        if not parts:
            self._set_feedback("Nie znaleziono poprawnych linków Vider.", theme.WARNING)
            return

        color = theme.SUCCESS if added_count else theme.WARNING
        self._set_feedback(" • ".join(parts), color)

    def _set_feedback(self, message: str, color: str = theme.TEXT_MUTED) -> None:
        self._feedback_label.configure(text=message, text_color=color)

    # ------------------------------------------------------------------
    # Folder & Settings Actions
    # ------------------------------------------------------------------
    def _on_choose_folder(self) -> None:
        initial = self._output_var.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(title="Wybierz folder zapisu filmów", initialdir=initial)
        if selected:
            self._output_var.set(selected)
            self._persist_settings()

    def _on_open_folder(self) -> None:
        target = Path(self._output_var.get().strip() or self._settings.output_dir)
        target.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(target))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            self._set_feedback(f"Nie udało się otworzyć folderu: {exc}", theme.WARNING)

    def _persist_settings(self) -> None:
        self._settings = AppSettings(
            output_dir=self._output_var.get().strip() or self._settings.output_dir,
            overwrite=bool(self._overwrite_var.get()),
        )
        save_settings(self._settings)

    # ------------------------------------------------------------------
    # Queue Management & Rendering
    # ------------------------------------------------------------------
    def _append_rows(self, items: list[QueueItem]) -> None:
        if not items:
            return
        if self._empty_visible:
            self._empty_label.pack_forget()
            self._empty_visible = False
        for item in items:
            row = QueueRowWidget(
                self._queue_scroll,
                item=item,
                on_remove=self._on_remove_item,
                on_retry=self._on_retry_item,
            )
            row.pack(fill="x", padx=4, pady=4)
            self._rows[item.uid] = row
        self._refresh_summary()

    def _on_remove_item(self, uid: str) -> None:
        if self.queue_manager.remove_item(uid):
            row = self._rows.pop(uid, None)
            if row is not None:
                row.destroy()
            if not self._rows and not self._empty_visible:
                self._empty_label.pack(pady=48)
                self._empty_visible = True
            self._refresh_summary()

    def _on_retry_item(self, uid: str) -> None:
        if self.queue_manager.retry_item(uid):
            item = self.queue_manager.get_item(uid)
            if item and uid in self._rows:
                self._rows[uid].update_from_item(item)
            self._refresh_summary()

    def _on_retry_failed(self) -> None:
        count = self.queue_manager.retry_failed()
        if count:
            for item in self.queue_manager.get_items():
                if item.uid in self._rows:
                    self._rows[item.uid].update_from_item(item)
            self._set_feedback(f"Przywrócono do kolejki: {count}", theme.ACCENT)
            self._refresh_summary()

    def _on_clear_completed(self) -> None:
        removed = self.queue_manager.clear_completed()
        if removed:
            valid_uids = {item.uid for item in self.queue_manager.get_items()}
            for uid in list(self._rows.keys()):
                if uid not in valid_uids:
                    self._rows.pop(uid).destroy()
            if not self._rows and not self._empty_visible:
                self._empty_label.pack(pady=48)
                self._empty_visible = True
            self._refresh_summary()

    def _refresh_summary(self) -> None:
        summary = self.queue_manager.get_summary()
        self._queue_title.configure(text=f"Kolejka pobierania ({summary['total']})")
        self._summary_label.configure(
            text=(
                f"Razem: {summary['total']}  •  "
                f"Ukończono: {summary['completed']}  •  "
                f"Oczekuje: {summary['pending']}  •  "
                f"Błędy: {summary['failed']}"
            )
        )

    # ------------------------------------------------------------------
    # Download Lifecycle
    # ------------------------------------------------------------------
    def _on_toggle_download(self) -> None:
        if self.queue_manager.is_running:
            self.queue_manager.cancel()
            self._start_btn.configure(text="Zatrzymywanie...", state="disabled")
            return

        # Automatically pull any links left un-added in the textbox for better UX
        if self._get_input_text():
            self._on_add_links()

        summary = self.queue_manager.get_summary()
        if summary["pending"] == 0:
            self._set_feedback("Brak oczekujących linków w kolejce.", theme.WARNING)
            return

        self._persist_settings()
        output_dir = self._output_var.get().strip() or self._settings.output_dir

        self._start_btn.configure(
            text="■   Zatrzymaj",
            fg_color=theme.DANGER,
            hover_color=theme.DANGER_HOVER,
            text_color=theme.TEXT_PRIMARY,
        )
        self._set_feedback("Rozpoczęto pobieranie kolejki...", theme.ACCENT)

        self.queue_manager.start(
            output_dir=output_dir,
            overwrite=bool(self._overwrite_var.get()),
            on_item_update=self._schedule_item_update,
            on_queue_finished=self._schedule_queue_finished,
        )

    def _schedule_item_update(self, item: QueueItem) -> None:
        self.after(0, lambda i=item: self._apply_item_update(i))

    def _apply_item_update(self, item: QueueItem) -> None:
        row = self._rows.get(item.uid)
        if row is not None:
            row.update_from_item(item)
        self._refresh_summary()

    def _schedule_queue_finished(self, summary: Dict[str, int]) -> None:
        self.after(0, lambda s=summary: self._apply_queue_finished(s))

    def _apply_queue_finished(self, summary: Dict[str, int]) -> None:
        self._start_btn.configure(
            text="▶   Pobierz wszystko",
            state="normal",
            fg_color=theme.SUCCESS,
            hover_color=theme.SUCCESS_HOVER,
            text_color=theme.TEXT_ON_ACCENT,
        )
        self._refresh_summary()
        if summary["failed"] > 0:
            self._set_feedback(
                f"Zakończono z błędami (Ukończono: {summary['completed']}, Błędy: {summary['failed']}).",
                theme.WARNING,
            )
        elif summary["cancelled"] > 0:
            self._set_feedback("Pobieranie zatrzymane. Postęp zapisany w plikach .part.", theme.WARNING)
        else:
            self._set_feedback(
                f"Wszystkie zadania zakończone pomyślnie ({summary['completed']}/{summary['total']}).",
                theme.SUCCESS,
            )

    # ------------------------------------------------------------------
    # Captcha Bridge (Worker Thread -> Tk Main Thread)
    # ------------------------------------------------------------------
    def _solve_captcha_from_worker(self, image_bytes: bytes) -> Optional[str]:
        result_holder: dict[str, Optional[str]] = {"code": None}
        done = threading.Event()

        def open_modal() -> None:
            try:
                dialog = CaptchaDialog(self, image_bytes)
                self.wait_window(dialog)
                result_holder["code"] = dialog.result
            finally:
                done.set()

        self.after(0, open_modal)
        done.wait()
        return result_holder["code"]

    # ------------------------------------------------------------------
    # Info Modal & Close Guard
    # ------------------------------------------------------------------
    def _show_about_dialog(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title(f"Pomoc i informacje — {__app_name__}")
        win.geometry("500x390")
        win.resizable(False, False)
        win.configure(fg_color=theme.BG_APP)
        win.transient(self)
        win.grab_set()

        card = ctk.CTkFrame(
            win,
            fg_color=theme.BG_CARD,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=12,
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            card,
            text=f"{__app_name__} v{__version__}  •  Autor: Michał Jura",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=16, pady=(14, 6))

        body = ctk.CTkTextbox(
            card,
            fg_color=theme.BG_INPUT,
            text_color=theme.TEXT_SECONDARY,
            font=ctk.CTkFont(size=12),
            wrap="word",
            corner_radius=8,
        )
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        body.insert("1.0", DISCLAIMER_TEXT)
        body.configure(state="disabled")

        ctk.CTkButton(
            card,
            text="Zamknij",
            width=110,
            height=32,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color=theme.TEXT_ON_ACCENT,
            font=ctk.CTkFont(weight="bold"),
            command=win.destroy,
        ).pack(pady=(0, 12))

    def _on_close(self) -> None:
        if self.queue_manager.is_running:
            confirm = messagebox.askyesno(
                "Trwa pobieranie",
                "Kolejka jest w trakcie pobierania. Czy na pewno zatrzymać i zamknąć program?\n"
                "(Częściowo pobrane pliki .part zostaną zachowane do wznowienia.)",
            )
            if not confirm:
                return
            self.queue_manager.cancel()
        self._persist_settings()
        self.destroy()


def launch_gui() -> int:
    """Starts the CustomTkinter desktop GUI."""
    app = ViderApp()
    app.mainloop()
    return 0
