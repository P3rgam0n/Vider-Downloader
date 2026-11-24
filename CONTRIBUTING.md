# Współtworzenie Projektu (Contributing)

Dziękujemy za zainteresowanie rozwojem **Vider Downloader**!

## Konfiguracja Środowiska Deweloperskiego

Wymagany Python `3.9+`:

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

## Uruchamianie Testów i Lintera

Przed wysłaniem Pull Requesta upewnij się, że testy i linter przechodzą bez błędów:

```bash
pytest -v
ruff check src tests main.py
```

## Standardy Kodu i Commitów

- Stosujemy format **Conventional Commits** w języku angielskim (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
- Zachowujemy wyraźny podział warstw:
  - `src/vider_downloader/core.py` — ekstrakcja i parsowanie (bez zależności od UI/CLI),
  - `src/vider_downloader/downloader.py` — silnik pobierania (bez zależności od UI/CLI),
  - `src/vider_downloader/queue_manager.py` — logika kolejki wsadowej,
  - `src/vider_downloader/gui/` — warstwa okienkowa (`CustomTkinter`),
  - `src/vider_downloader/cli.py` — warstwa wiersza poleceń (`Rich`).
- W testach i dokumentacji używaj wyłącznie generycznych, przykładowych linków (np. `+fEXAMPLE01`) — nie umieszczaj linków do rzeczywistych materiałów chronionych prawem autorskim.
