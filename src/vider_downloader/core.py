"""Core extraction, URL decoding, input parsing, and session management for vider.info / vider.pl."""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from vider_downloader.config import get_session_file_path, set_private_permissions
from vider_downloader.models import VideoInfo, sanitize_extension

CaptchaHandler = Callable[[bytes], Optional[str]]


class ViderError(RuntimeError):
    """Base error raised by the extraction engine."""


class CaptchaRequiredError(ViderError):
    """Raised when Vider requests captcha verification and no valid solution is supplied."""


def decode_video_url(raw_base64: str) -> str:
    """
    Decodes obfuscated video stream URL from Vider player.

    Algorithm:
    1. Reverse raw base64 string
    2. Base64 decode to bytes
    3. Byte-wise XOR with key 7
    4. Decode UTF-8 and strip 5 prefix/suffix padding chars
    5. Validate HTTP(S) URL scheme and host
    """
    if not raw_base64 or not raw_base64.strip():
        raise ValueError("Pusty zakodowany adres strumienia wideo.")

    reversed_str = raw_base64.strip()[::-1]
    try:
        decoded_bytes = base64.b64decode(reversed_str, validate=True)
    except Exception as exc:
        raise ValueError("Nieprawidłowy format Base64 adresu strumienia.") from exc

    xor_bytes = bytes(b ^ 7 for b in decoded_bytes)
    payload = xor_bytes.decode("utf-8", errors="ignore")
    if len(payload) <= 10:
        raise ValueError("Zdekodowany adres strumienia jest zbyt krótki.")

    stream_url = payload[5:-5].strip()
    parsed = urlparse(stream_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Zdekodowany adres strumienia nie jest prawidłowym adresem HTTP(S).")
    return stream_url


def extract_video_id(url_or_id: str) -> str:
    """
    Extracts clean video ID from supported Vider URL formats:
    - https://vider.info/vid/+fEXAMPLE
    - https://vider.info/user/sample-title+fEXAMPLE
    - https://vider.pl/embed/video/EXAMPLE
    - https://vider.info/embed/video/EXAMPLE
    - +fEXAMPLE
    - EXAMPLE
    """
    cleaned = url_or_id.strip()
    if not cleaned:
        raise ValueError("Podano pusty adres lub identyfikator wideo.")

    # Match +f<id>
    match = re.search(r"\+f([a-zA-Z0-9]+)", cleaned)
    if match:
        return match.group(1)

    # Match embed/video/<id>
    match = re.search(r"embed/video/([a-zA-Z0-9]+)", cleaned)
    if match:
        return match.group(1)

    # Match /vid/<id>
    match = re.search(r"/vid/([a-zA-Z0-9]+)", cleaned)
    if match:
        return match.group(1)

    # Standalone alphanumeric ID (at least 4 chars to avoid matching stray words)
    if re.match(r"^[a-zA-Z0-9]{4,32}$", cleaned):
        return cleaned

    raise ValueError(f"Nie rozpoznano identyfikatora wideo z podanego adresu: '{url_or_id}'")


def parse_urls_from_text(text: str) -> Tuple[List[Tuple[str, str]], int, List[str]]:
    """
    Parses multi-line or whitespace-separated Vider links/IDs.

    Returns:
        (valid_entries, duplicate_count, invalid_entries)
        where valid_entries is a list of (raw_token, video_id) deduplicated by video_id.
    """
    valid: List[Tuple[str, str]] = []
    invalid: List[str] = []
    seen_ids = set()
    duplicates = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for token in line.split():
            cleaned = token.strip().strip(",;")
            if not cleaned or cleaned.startswith("#"):
                continue
            try:
                video_id = extract_video_id(cleaned)
            except ValueError:
                invalid.append(cleaned)
                continue
            if video_id in seen_ids:
                duplicates += 1
                continue
            seen_ids.add(video_id)
            valid.append((cleaned, video_id))

    return valid, duplicates, invalid


class ViderExtractor:
    """Extractor for vider.info / vider.pl videos with injectable captcha handling."""

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        session_file: Optional[str | Path] = None,
        captcha_handler: Optional[CaptchaHandler] = None,
        session: Optional[requests.Session] = None,
    ):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.DEFAULT_USER_AGENT,
                "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
            }
        )
        self.session_file = Path(session_file) if session_file else get_session_file_path()
        self.captcha_handler = captcha_handler
        self._load_session()

    def _load_session(self) -> None:
        """Loads cached cookies from local storage if present."""
        if not self.session_file.exists():
            return
        try:
            cookies = json.loads(self.session_file.read_text(encoding="utf-8"))
            if isinstance(cookies, dict):
                for key, value in cookies.items():
                    self.session.cookies.set(str(key), str(value))
        except Exception:
            pass

    def _save_session(self) -> None:
        """Saves current session cookies with private file permissions."""
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            cookies = self.session.cookies.get_dict()
            self.session_file.write_text(json.dumps(cookies), encoding="utf-8")
            set_private_permissions(self.session_file)
        except OSError:
            pass

    @staticmethod
    def extract_id(url_or_id: str) -> str:
        """Backwards-compatible static wrapper around extract_video_id."""
        return extract_video_id(url_or_id)

    def _handle_captcha(self, response_text: str, target_url: str) -> bool:
        """Detects Vider anti-bot captcha and delegates solving to the injected handler."""
        match_captcha = re.search(
            r'src=["\'](/streaming/ca-pt-cha\.png\?[0-9]+)["\']', response_text
        )
        if not match_captcha:
            return False

        if self.captcha_handler is None:
            raise CaptchaRequiredError(
                "Serwis Vider wymaga przepisania kodu Captcha, ale brak skonfigurowanej obsługi Captcha."
            )

        captcha_path = match_captcha.group(1)
        parsed_target = urlparse(target_url)
        base_origin = f"{parsed_target.scheme}://{parsed_target.netloc}" if parsed_target.netloc else "https://vider.info"
        captcha_url = f"{base_origin}{captcha_path}"

        img_resp = self.session.get(captcha_url, headers={"Referer": target_url}, timeout=15)
        if img_resp.status_code != 200 or not img_resp.content:
            raise CaptchaRequiredError("Nie udało się pobrać obrazka Captcha z serwisu Vider.")

        code = self.captcha_handler(img_resp.content)
        if not code or not code.strip():
            raise CaptchaRequiredError("Anulowano rozwiązywanie kodu Captcha.")

        post_resp = self.session.post(
            target_url,
            data={"captcha": code.strip()},
            headers={"Referer": target_url},
            timeout=15,
        )
        self._save_session()

        if "content-404" in post_resp.text or "ca-pt-cha.png" in post_resp.text:
            raise CaptchaRequiredError("Podany kod Captcha jest nieprawidłowy. Spróbuj ponownie.")

        return True

    def extract(self, url_or_id: str) -> VideoInfo:
        """Extracts video metadata and direct stream URL for a Vider video."""
        video_id = self.extract_id(url_or_id)
        page_url = f"https://vider.info/vid/+f{video_id}"
        embed_urls = [
            f"https://vider.pl/embed/video/{video_id}",
            f"https://vider.info/embed/video/{video_id}",
        ]

        html_content = ""
        used_embed_url = embed_urls[0]

        # 1. Try direct embed endpoints first
        for embed_candidate in embed_urls:
            try:
                resp = self.session.get(
                    embed_candidate,
                    headers={"Referer": page_url},
                    timeout=15,
                )
                if "ca-pt-cha.png" in resp.text:
                    if self._handle_captcha(resp.text, embed_candidate):
                        resp = self.session.get(
                            embed_candidate,
                            headers={"Referer": page_url},
                            timeout=15,
                        )

                if resp.status_code == 200 and "video_player" in resp.text:
                    html_content = resp.text
                    used_embed_url = embed_candidate
                    break
            except CaptchaRequiredError:
                raise
            except requests.RequestException:
                continue

        # 2. Fallback to main video page iframe discovery
        if not html_content or "video_player" not in html_content:
            try:
                resp = self.session.get(page_url, timeout=15)
                if "ca-pt-cha.png" in resp.text:
                    if self._handle_captcha(resp.text, page_url):
                        resp = self.session.get(page_url, timeout=15)

                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for iframe in soup.find_all("iframe"):
                        src = str(iframe.get("src") or "")
                        if "embed/video" in src:
                            if src.startswith("//"):
                                src = "https:" + src
                            elif src.startswith("/"):
                                src = "https://vider.info" + src
                            used_embed_url = src
                            break

                    embed_resp = self.session.get(
                        used_embed_url,
                        headers={"Referer": page_url},
                        timeout=15,
                    )
                    if embed_resp.status_code == 200 and "video_player" in embed_resp.text:
                        html_content = embed_resp.text
            except CaptchaRequiredError:
                raise
            except requests.RequestException:
                pass

        if not html_content or "video_player" not in html_content:
            raise ViderError(
                f"Nie udało się odnaleźć odtwarzacza wideo dla ID '{video_id}'. "
                "Upewnij się, że film istnieje, link jest poprawny i masz połączenie z internetem."
            )

        soup = BeautifulSoup(html_content, "html.parser")
        player = soup.find(id="video_player")
        if not player:
            raise ViderError(f"Brak elementu #video_player w kodzie strony dla ID: {video_id}")

        raw_video_url = player.get("data-video-url")
        if not raw_video_url:
            raise ViderError("Element #video_player nie zawiera atrybutu 'data-video-url'.")

        stream_url = decode_video_url(str(raw_video_url))

        title = player.get("data-file-name")
        if not title:
            if soup.title and soup.title.string:
                title = soup.title.string.split("-")[0].strip()
            else:
                title = f"vider_{video_id}"

        title = html.unescape(str(title)).strip()
        extension = sanitize_extension(str(player.get("data-file-extension") or "mp4"))

        duration_str = str(player.get("data-duration") or "0")
        try:
            duration = max(0, int(duration_str))
        except ValueError:
            duration = 0

        poster_url = str(player.get("data-photo-url") or "")
        file_size = self._probe_file_size(stream_url, used_embed_url)

        return VideoInfo(
            id=video_id,
            title=title,
            extension=extension,
            duration=duration,
            stream_url=stream_url,
            embed_url=used_embed_url,
            poster_url=poster_url,
            file_size=file_size,
            page_url=page_url,
        )

    def _probe_file_size(self, stream_url: str, referer: str) -> Optional[int]:
        """Probes total file size using a 1-byte Range request with proper connection cleanup."""
        headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Referer": referer,
            "Range": "bytes=0-0",
        }
        try:
            with self.session.get(stream_url, headers=headers, stream=True, timeout=10) as resp:
                if resp.status_code in (200, 206):
                    content_range = resp.headers.get("Content-Range")
                    if content_range and "/" in content_range:
                        total_str = content_range.split("/")[-1]
                        if total_str.isdigit():
                            return int(total_str)
                    content_length = resp.headers.get("Content-Length")
                    if content_length and content_length.isdigit():
                        return int(content_length)
        except requests.RequestException:
            pass
        return None
