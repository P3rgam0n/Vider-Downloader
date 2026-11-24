"""Unit tests for CLI argument parsing and multi-URL batch handling."""

from __future__ import annotations

from unittest.mock import patch

from vider_downloader.cli import build_parser, main


class TestCLI:
    def test_parser_accepts_multiple_urls_and_flags(self):
        parser = build_parser()
        parsed = parser.parse_args(
            [
                "https://vider.info/vid/+fDEMO01",
                "https://vider.info/vid/+fDEMO02",
                "-o",
                "./out",
                "--overwrite",
                "--info",
            ]
        )
        assert parsed.urls == [
            "https://vider.info/vid/+fDEMO01",
            "https://vider.info/vid/+fDEMO02",
        ]
        assert parsed.output_dir == "./out"
        assert parsed.overwrite is True
        assert parsed.info is True

    def test_main_batch_file_missing_returns_error(self, tmp_path):
        missing = tmp_path / "does_not_exist.txt"
        code = main(["--batch", str(missing)])
        assert code == 1

    def test_main_multi_url_invokes_process_url_for_each_unique_video(self, tmp_path):
        with patch("vider_downloader.cli.process_url", return_value=True) as mock_proc:
            code = main(
                [
                    "https://vider.info/vid/+fDEMO01",
                    "https://vider.pl/embed/video/DEMO01",
                    "https://vider.info/vid/+fDEMO02",
                    "-o",
                    str(tmp_path),
                    "--info",
                ]
            )
        assert code == 0
        assert mock_proc.call_count == 2
