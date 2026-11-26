# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-26

### Added
- Parallel downloads: user-selectable number of simultaneous downloads (1-10) in the GUI, persisted in settings.
- Per-item "Błędna captcha" indicator in the queue when the entered Captcha code is rejected.

### Changed
- Captcha prompts are serialized so only one dialog is shown at a time during parallel downloads.

## [1.0.0] - 2026-11-24

### Added
- Desktop GUI built with `CustomTkinter` for easy use without terminal or Python setup.
- Batch download queue (`BatchQueueManager`) supporting pasting multiple links, clipboard paste, `.txt` import, automatic deduplication, live per-item progress/speed/ETA, cancellation, and one-click retry for failed items.
- Core extraction engine for `vider.info` and `vider.pl` videos with reverse Base64 + XOR(7) stream URL decoding and just-in-time metadata resolution.
- Resumable segmented HTTP Range downloader with `.part` resume, retry backoff, and safe cancellation.
- In-app Captcha dialog rendering verification images directly in memory without temporary files.
- Persistent per-user settings and local session storage (`config.py`) compatible with standalone executables.
- Full CLI mode (`main.py` / `vider-dl`) with multi-URL arguments, `--batch`, `--info`, `--overwrite`, `--gui`, `--cli`, and `--version`.
- Automated GitHub Actions CI (`ruff` + `pytest`) and release builds for Windows (`.exe`) and Linux with `SHA256SUMS.txt`.
- Cross-platform filename and video extension sanitization protecting against path traversal and reserved OS names.
