"""Command-line interface and interactive terminal mode for Vider Downloader."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from vider_downloader import __version__
from vider_downloader.core import ViderExtractor, parse_urls_from_text
from vider_downloader.downloader import Downloader, resolve_safe_output_path
from vider_downloader.models import DownloadProgress, VideoInfo

console = Console(legacy_windows=False)


def print_banner() -> None:
    """Displays CLI header banner."""
    banner = (
        "[bold cyan]======================================================\n"
        "           VIDER.INFO / VIDER.PL DOWNLOADER\n"
        "======================================================[/bold cyan]\n"
        f"[dim]Wersja {__version__} | Pobieranie wideo i list wsadowych (Batch)[/dim]"
    )
    console.print(Panel(banner, border_style="cyan", expand=False))


def display_video_info(info: VideoInfo) -> None:
    """Displays formatted metadata table."""
    table = Table(title="[bold green]Szczegóły Materiału Wideo[/bold green]", border_style="cyan")
    table.add_column("Parametr", style="bold white", width=20)
    table.add_column("Wartość", style="cyan")

    table.add_row("ID Wideo", info.id)
    table.add_row("Tytuł", info.title)
    table.add_row("Format", info.extension.upper())
    table.add_row("Czas trwania", info.formatted_duration)
    table.add_row("Szacowany rozmiar", info.formatted_size)
    table.add_row("Strona źródłowa", info.page_url or "N/A")
    table.add_row("Bezpośredni strumień", f"{info.stream_url[:65]}...")

    console.print(table)


def cli_captcha_handler(image_bytes: bytes) -> Optional[str]:
    """Safely writes Captcha image to a private temporary file, opens it, and reads user input."""
    console.print("\n[bold yellow][!] WYKRYTO ZABEZPIECZENIE ANTY-BOT (CAPTCHA)[/bold yellow]")
    console.print("    Vider wymaga jednorazowego przepisania kodu z obrazka.")

    temp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="vider_captcha_", suffix=".png", delete=False
        ) as tmp:
            tmp.write(image_bytes)
            temp_path = tmp.name

        try:
            if sys.platform == "win32":
                os.startfile(temp_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", temp_path])
            else:
                subprocess.Popen(["xdg-open", temp_path])
            console.print(f"[dim]Otwarto podgląd obrazka captcha: {temp_path}[/dim]")
        except Exception:
            console.print(f"[dim]Zapisano obrazek captcha pod ścieżką: {temp_path}[/dim]")

        code = console.input(
            "[bold yellow]>> Wpisz kod z obrazka (lub Enter, aby anulować): [/bold yellow]"
        ).strip()
        return code if code else None
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def download_with_rich_progress(
    downloader: Downloader,
    info: VideoInfo,
    target_path: str,
    overwrite: bool = False,
) -> str:
    """Runs Downloader.download() attached to a Rich terminal progress bar."""
    display_name = Path(target_path).name
    if len(display_name) > 35:
        display_name = display_name[:32] + "..."

    progress = Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(bar_width=40, style="grey37", complete_style="bold green"),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "-",
        DownloadColumn(),
        "-",
        TransferSpeedColumn(),
        "-",
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )

    with progress:
        task_id = progress.add_task(
            "download",
            filename=display_name,
            total=info.file_size,
            completed=0,
        )

        def on_progress(state: DownloadProgress) -> None:
            progress.update(
                task_id,
                total=state.total_bytes,
                completed=state.downloaded_bytes,
            )

        final_path = downloader.download(
            video_info=info,
            output_path=target_path,
            resume=True,
            overwrite=overwrite,
            progress_callback=on_progress,
        )

    console.print(f"[bold green]OK: Pobrano pomyślnie:[/bold green] [cyan]{final_path}[/cyan]")
    return final_path


def process_url(
    url: str,
    extractor: ViderExtractor,
    downloader: Downloader,
    output_dir: str,
    filename: Optional[str] = None,
    info_only: bool = False,
    overwrite: bool = False,
) -> bool:
    """Extracts metadata and downloads a single video URL."""
    try:
        info = extractor.extract(url)
        display_video_info(info)

        if info_only:
            return True

        target_name = filename if filename else info.default_filename
        target_path = resolve_safe_output_path(output_dir, target_name)

        console.print(
            f"\n[bold green]Rozpoczynanie pobierania do:[/bold green] [cyan]{target_path}[/cyan]\n"
        )
        download_with_rich_progress(downloader, info, target_path, overwrite=overwrite)
        return True
    except Exception as exc:
        console.print(f"[bold red][Błąd przetwarzania {url}]:[/bold red] {exc}")
        return False


def run_interactive(extractor: ViderExtractor, downloader: Downloader) -> None:
    """Runs interactive CLI loop supporting single or multi-link batch input."""
    print_banner()
    while True:
        try:
            console.print(
                "\n[bold yellow]> Wklej jeden lub kilka linków Vider (oddzielone spacją) "
                "lub wpisz 'q' aby wyjść:[/bold yellow]"
            )
            raw_input = console.input("> ").strip()
            if not raw_input or raw_input.lower() in ("q", "exit", "quit"):
                console.print("[dim]Koniec programu.[/dim]")
                break

            valid_entries, dupes, invalid = parse_urls_from_text(raw_input)
            if invalid:
                console.print(f"[yellow]Pominięto nierozpoznane wpisy: {', '.join(invalid)}[/yellow]")
            if dupes:
                console.print(f"[dim]Pominięto duplikaty: {dupes}[/dim]")
            if not valid_entries:
                console.print("[bold red]Nie rozpoznano żadnego poprawnego linku Vider.[/bold red]")
                continue

            default_dir = os.path.join(os.getcwd(), "downloads")
            out_dir_input = console.input(
                f"[bold yellow]> Katalog docelowy [[dim]{default_dir}[/dim]]: [/bold yellow]"
            ).strip()
            out_dir = out_dir_input or default_dir

            if len(valid_entries) == 1:
                single_url = valid_entries[0][0]
                console.print("\n[dim]Pobieranie informacji o filmie...[/dim]")
                try:
                    info = extractor.extract(single_url)
                except Exception as exc:
                    console.print(f"[bold red][Błąd][/bold red] {exc}")
                    continue

                display_video_info(info)
                default_name = info.default_filename
                out_name_input = console.input(
                    f"[bold yellow]> Nazwa pliku [[dim]{default_name}[/dim]]: [/bold yellow]"
                ).strip()
                target_path = resolve_safe_output_path(out_dir, out_name_input or default_name)
                console.print(
                    f"\n[bold green]Rozpoczynanie pobierania do:[/bold green] [cyan]{target_path}[/cyan]\n"
                )
                download_with_rich_progress(downloader, info, target_path)
            else:
                console.print(
                    f"\n[bold cyan]Rozpoczynanie pobierania wsadowego ({len(valid_entries)} linków)...[/bold cyan]"
                )
                ok = 0
                for idx, (url_token, _vid) in enumerate(valid_entries, 1):
                    console.print(
                        f"\n[bold yellow]--- [{idx}/{len(valid_entries)}] {url_token} ---[/bold yellow]"
                    )
                    if process_url(url_token, extractor, downloader, out_dir):
                        ok += 1
                console.print(
                    f"\n[bold green]Zakończono pobieranie wsadowe. Sukces: {ok}/{len(valid_entries)}[/bold green]"
                )

        except KeyboardInterrupt:
            console.print("\n[dim]Anulowano.[/dim]")
            break
        except Exception as exc:
            console.print(f"\n[bold red][Błąd][/bold red] {exc}")


def build_parser() -> argparse.ArgumentParser:
    """Creates CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="vider-dl",
        description="Vider Downloader - Pobieranie filmów i list wsadowych z vider.info / vider.pl",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="Jeden lub więcej linków do filmów (np. https://vider.info/vid/+fEXAMPLE) lub ID",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="./downloads",
        help="Katalog docelowy zapisu plików (domyślnie: ./downloads)",
    )
    parser.add_argument(
        "-n",
        "--filename",
        help="Własna nazwa pliku wyjściowego (tylko dla pojedynczego linku)",
    )
    parser.add_argument(
        "-i",
        "--info",
        action="store_true",
        help="Wyświetl wyłącznie metadane wideo bez pobierania",
    )
    parser.add_argument(
        "-b",
        "--batch",
        help="Ścieżka do pliku tekstowego z listą linków (jeden link na wiersz)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Nadpisz istniejący plik, jeśli już istnieje",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Uruchom okienkowy interfejs graficzny (GUI)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Wymuś interaktywny tryb terminalowy (CLI)",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _try_launch_gui() -> Optional[int]:
    """Attempts to launch desktop GUI; returns None if display/GUI is unavailable."""
    try:
        from vider_downloader.gui.app import launch_gui

        return launch_gui()
    except Exception:
        return None


def main(args: Optional[List[str]] = None) -> int:
    """Main application entrypoint supporting GUI and CLI modes."""
    parser = build_parser()
    parsed = parser.parse_args(args)

    # Explicit GUI flag
    if parsed.gui:
        from vider_downloader.gui.app import launch_gui

        return launch_gui()

    # No CLI targets given -> launch GUI by default unless --cli is forced
    if not parsed.urls and not parsed.batch:
        if not parsed.cli:
            gui_result = _try_launch_gui()
            if gui_result is not None:
                return gui_result
            console.print(
                "[dim]Środowisko graficzne niedostępne — uruchamianie trybu terminalowego (CLI)...[/dim]"
            )
        extractor = ViderExtractor(captcha_handler=cli_captcha_handler)
        downloader = Downloader(session=extractor.session)
        run_interactive(extractor, downloader)
        return 0

    print_banner()
    extractor = ViderExtractor(captcha_handler=cli_captcha_handler)
    downloader = Downloader(session=extractor.session)

    # Collect URLs from both positional args and --batch file
    raw_lines: List[str] = list(parsed.urls)
    if parsed.batch:
        batch_path = Path(parsed.batch)
        if not batch_path.exists():
            console.print(f"[bold red]Plik z listą nie istnieje:[/bold red] {parsed.batch}")
            return 1
        raw_lines.append(batch_path.read_text(encoding="utf-8"))

    valid_entries, dupes, invalid = parse_urls_from_text("\n".join(raw_lines))
    if invalid:
        console.print(f"[yellow]Pominięto nierozpoznane wpisy: {', '.join(invalid)}[/yellow]")
    if dupes:
        console.print(f"[dim]Pominięto duplikaty: {dupes}[/dim]")
    if not valid_entries:
        console.print("[bold red]Brak poprawnych linków do przetworzenia.[/bold red]")
        return 1

    if len(valid_entries) == 1:
        ok = process_url(
            valid_entries[0][0],
            extractor,
            downloader,
            parsed.output_dir,
            filename=parsed.filename,
            info_only=parsed.info,
            overwrite=parsed.overwrite,
        )
        return 0 if ok else 1

    console.print(f"[bold cyan]Załadowano {len(valid_entries)} linków do pobrania.[/bold cyan]\n")
    success_count = 0
    for idx, (url_token, _vid) in enumerate(valid_entries, 1):
        console.print(
            f"\n[bold yellow]--- [{idx}/{len(valid_entries)}] Przetwarzanie: {url_token} ---[/bold yellow]"
        )
        if process_url(
            url_token,
            extractor,
            downloader,
            parsed.output_dir,
            info_only=parsed.info,
            overwrite=parsed.overwrite,
        ):
            success_count += 1

    console.print(
        f"\n[bold green]Zakończono pobieranie wsadowe. Sukces: {success_count}/{len(valid_entries)}[/bold green]"
    )
    return 0 if success_count == len(valid_entries) else 1
