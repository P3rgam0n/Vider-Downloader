"""Unit tests for core extraction, URL decoding, input parsing, and filename sanitization."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from vider_downloader.core import (
    CaptchaRequiredError,
    ViderError,
    ViderExtractor,
    decode_video_url,
    extract_video_id,
    parse_urls_from_text,
)
from vider_downloader.models import VideoInfo, sanitize_extension, sanitize_filename


def _encode_vider_url(url: str) -> str:
    """Helper mirroring Vider's obfuscation (5-char padding + XOR 7 + base64 + reverse)."""
    padded = f"abcde{url}fghij".encode("utf-8")
    xored = bytes(b ^ 7 for b in padded)
    return base64.b64encode(xored).decode("ascii")[::-1]


class TestDecodingAndParsing:
    def test_decode_video_url_roundtrip(self):
        expected = "https://stream.vider.info/video/123456/sample.mp4?uid=0"
        encoded = _encode_vider_url(expected)
        assert decode_video_url(encoded) == expected

    def test_decode_video_url_rejects_empty_and_invalid_scheme(self):
        with pytest.raises(ValueError):
            decode_video_url("")

        bad_scheme = _encode_vider_url("file:///etc/passwd")
        with pytest.raises(ValueError):
            decode_video_url(bad_scheme)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://vider.info/vid/+fEXAMP1", "EXAMP1"),
            ("https://vider.pl/embed/video/EXAMP2", "EXAMP2"),
            ("https://vider.info/embed/video/EXAMP3", "EXAMP3"),
            ("https://vider.info/demo-user/sample-clip+fEXAMP4", "EXAMP4"),
            ("+fEXAMP5", "EXAMP5"),
            ("EXAMP6", "EXAMP6"),
        ],
    )
    def test_extract_video_id_formats(self, raw, expected):
        assert extract_video_id(raw) == expected
        assert ViderExtractor.extract_id(raw) == expected

    def test_extract_video_id_rejects_invalid(self):
        with pytest.raises(ValueError):
            extract_video_id("https://example.com/not-a-video")
        with pytest.raises(ValueError):
            extract_video_id("   ")

    def test_parse_urls_from_text_deduplicates_and_ignores_comments(self):
        text = """
        # Comment line should be ignored
        https://vider.info/vid/+fDEMO01
        https://vider.pl/embed/video/DEMO01
        https://vider.info/vid/+fDEMO02   +fDEMO03

        not-a-valid-link!!!
        """
        valid, dupes, invalid = parse_urls_from_text(text)
        assert [vid for _, vid in valid] == ["DEMO01", "DEMO02", "DEMO03"]
        assert dupes == 1
        assert invalid == ["not-a-valid-link!!!"]


class TestSanitizationAndModels:
    def test_sanitize_filename_cross_platform(self):
        assert sanitize_filename("Sample: Video / Episode 1 ?") == "Sample Video Episode 1"
        assert sanitize_filename('A<B>C"D|E*F') == "A B C D E F"
        assert sanitize_filename("   Sample Title 1080p...  ") == "Sample Title 1080p"
        assert sanitize_filename("../../etc/passwd") == "etc passwd"
        assert sanitize_filename("CON") == "_CON"
        assert sanitize_filename("nul.txt") == "_nul.txt"
        assert sanitize_filename("") == "video"

    def test_sanitize_filename_truncates_long_names(self):
        long_name = "A" * 300
        assert len(sanitize_filename(long_name, max_length=180)) == 180

    def test_sanitize_extension_allowlist(self):
        assert sanitize_extension("mp4") == "mp4"
        assert sanitize_extension(".MKV") == "mkv"
        assert sanitize_extension("exe") == "mp4"
        assert sanitize_extension("../../bat") == "mp4"
        assert sanitize_extension("") == "mp4"

    def test_video_info_properties(self):
        info = VideoInfo(
            id="DEMO01",
            title="Sample Video Clip",
            extension="mp4",
            duration=3408,
            stream_url="https://stream.vider.info/video/123456/sample.mp4?uid=0",
            embed_url="https://vider.pl/embed/video/DEMO01",
            poster_url="",
            file_size=215_420_598,
        )
        assert info.formatted_duration == "56:48"
        assert info.formatted_size == "205.44 MB"
        assert info.default_filename == "Sample Video Clip.mp4"


class TestViderExtractorMocked:
    def test_extract_success_and_size_probe(self, tmp_path):
        stream_url = "https://stream.vider.info/video/999/clip.mp4"
        encoded = _encode_vider_url(stream_url)
        html_doc = (
            f'<html><body><div id="video_player" '
            f'data-video-url="{encoded}" '
            f'data-file-name="Demo Clip: Part 1" '
            f'data-file-extension="exe" '
            f'data-duration="125" '
            f'data-photo-url="https://img.example/poster.jpg"></div></body></html>'
        )

        embed_resp = MagicMock(status_code=200, text=html_doc)
        probe_resp = MagicMock(status_code=206, headers={"Content-Range": "bytes 0-0/1048576"})
        probe_resp.__enter__.return_value = probe_resp
        probe_resp.__exit__.return_value = None

        mock_session = MagicMock()
        mock_session.headers = {}
        mock_session.cookies.get_dict.return_value = {}
        mock_session.get.side_effect = [embed_resp, probe_resp]

        extractor = ViderExtractor(
            session_file=tmp_path / "session.json",
            session=mock_session,
        )
        info = extractor.extract("https://vider.info/vid/+fDEMO99")

        assert info.id == "DEMO99"
        assert info.title == "Demo Clip: Part 1"
        assert info.extension == "mp4"  # 'exe' neutralized by allowlist
        assert info.default_filename == "Demo Clip Part 1.mp4"
        assert info.duration == 125
        assert info.file_size == 1048576
        assert info.stream_url == stream_url

    def test_extract_captcha_via_callback(self, tmp_path):
        stream_url = "https://stream.vider.info/video/777/ok.mp4"
        encoded = _encode_vider_url(stream_url)
        captcha_html = '<img src="/streaming/ca-pt-cha.png?12345" />'
        ok_html = f'<div id="video_player" data-video-url="{encoded}" data-file-name="After Captcha"></div>'

        first_resp = MagicMock(status_code=200, text=captcha_html)
        img_resp = MagicMock(status_code=200, content=b"PNG_FAKE_BYTES")
        post_resp = MagicMock(status_code=200, text="<html>OK</html>")
        second_resp = MagicMock(status_code=200, text=ok_html)
        probe_resp = MagicMock(status_code=206, headers={"Content-Range": "bytes 0-0/2048"})
        probe_resp.__enter__.return_value = probe_resp
        probe_resp.__exit__.return_value = None

        mock_session = MagicMock()
        mock_session.headers = {}
        mock_session.cookies.get_dict.return_value = {"sid": "abc"}
        mock_session.get.side_effect = [first_resp, img_resp, second_resp, probe_resp]
        mock_session.post.return_value = post_resp

        received_bytes = []

        def fake_handler(img_bytes: bytes) -> str:
            received_bytes.append(img_bytes)
            return "XY42"

        extractor = ViderExtractor(
            session_file=tmp_path / "session.json",
            captcha_handler=fake_handler,
            session=mock_session,
        )
        info = extractor.extract("DEMO77")

        assert received_bytes == [b"PNG_FAKE_BYTES"]
        assert info.title == "After Captcha"
        assert (tmp_path / "session.json").exists()

    def test_extract_captcha_without_handler_raises(self, tmp_path):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_session.get.return_value = MagicMock(
            status_code=200, text='<img src="/streaming/ca-pt-cha.png?99" />'
        )
        extractor = ViderExtractor(session_file=tmp_path / "s.json", session=mock_session)
        with pytest.raises(CaptchaRequiredError):
            extractor.extract("DEMO88")

    def test_extract_missing_player_raises_vider_error(self, tmp_path):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_session.get.return_value = MagicMock(status_code=404, text="<html>Not found</html>")
        extractor = ViderExtractor(session_file=tmp_path / "s.json", session=mock_session)
        with pytest.raises(ViderError):
            extractor.extract("MISSING1")
