# Vider Downloader

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-brightgreen.svg)](VERSION)

Lekki, szybki i przejrzysty program z **okienkowym interfejsem graficznym (GUI)** oraz **trybem terminalowym (CLI)** do pobierania pojedynczych materiałów wideo oraz całych list (**Batch Download**) z serwisów `vider.info` oraz `vider.pl`.

---

## Szybki start (dla każdego — bez instalacji Pythona)

Nie musisz znać programowania ani nic kompilować:

1. Wejdź w zakładkę **Releases** po prawej stronie repozytorium.
2. Pobierz gotowy plik dla swojego systemu:
   - **Windows**: `ViderDownloader-Windows-x64.exe`
   - **Linux**: `ViderDownloader-Linux-x64`
3. Uruchom pobrany plik podwójnym kliknięciem.
4. Wklej jeden lub kilka linków (każdy w nowej linii), kliknij **„Dodaj do kolejki”**, a następnie **„Pobierz wszystko”**.

> **Uwaga dotycząca Windows SmartScreen:** Ponieważ program jest darmowym projektem open-source i nie posiada płatnego certyfikatu komercyjnego, system Windows może wyświetlić przy pierwszym uruchomieniu ekran *„System Windows ochronił ten komputer”* (*Więcej informacji → Uruchom mimo to*). Wszystkie pliki w zakładce *Releases* są budowane automatycznie z tego publicznego kodu przez GitHub Actions — ich autentyczność możesz w każdej chwili sprawdzić za pomocą dołączonego pliku `SHA256SUMS.txt`.

---

## Najważniejsze funkcje

- **Lekki i przejrzysty interfejs graficzny (GUI)**:
  - Wklejanie wielu linków naraz, szybkie wklejanie ze schowka i import listy z pliku `.txt`.
  - Automatyczne usuwanie duplikatów i podsumowanie stanu kolejki.
  - Przejrzyste karty zadań z paskiem postępu, prędkością (MB/s), szacowanym czasem (ETA) i możliwością ponowienia nieudanych pobrań.
  - Wbudowane okienko obsługi Captcha (obrazek wyświetlany bezpośrednio w aplikacji, bez zapisywania plików tymczasowych).
- **Wznawianie przerwanych pobrań (Resume)**:
  - Przerwanie pobierania lub utrata sieci zachowuje postęp w pliku `.part` — kolejne uruchomienie automatycznie wznawia transfer od miejsca przerwania.
- **Obsługa wszystkich formatów linków Vider**:
  - `https://vider.info/vid/+fEXAMPLE1`
  - `https://vider.info/user/sample-title+fEXAMPLE1`
  - `https://vider.pl/embed/video/EXAMPLE1`
  - `+fEXAMPLE1` lub samo `EXAMPLE1`
- **Prywatność i bezpieczeństwo**:
  - Zero telemetrii, zero reklam, brak kont i zewnętrznych serwerów.
  - Bezpieczna sanityzacja nazw i rozszerzeń plików (ochrona przed path traversal i niedozwolonymi znakami Windows/Linux/macOS).
  - Pełny tryb CLI dostępny z tego samego programu.

---

## Uruchamianie ze źródeł (dla programistów i zaawansowanych)

### Instalacja

```bash
git clone https://github.com/P3rgam0n/Vider-Downloader.git
cd Vider-Downloader
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### Uruchomienie GUI

```bash
python main.py
```

### Tryb wiersza poleceń (CLI)

```bash
# Pobranie pojedynczego filmu:
python main.py https://vider.info/vid/+fEXAMPLE1

# Pobranie kilku linków naraz (batch z linii poleceń):
python main.py https://vider.info/vid/+fEXAMPLE1 https://vider.info/vid/+fEXAMPLE2 -o ./moje_filmy

# Pobranie listy linków z pliku tekstowego:
python main.py --batch lista_linkow.txt -o ./moje_filmy

# Tylko podgląd metadanych bez pobierania:
python main.py --info https://vider.info/vid/+fEXAMPLE1

# Interaktywny tryb terminalowy:
python main.py --cli
```

---

## Struktura projektu

```text
Vider-Downloader/
├── .github/workflows/
│   ├── ci.yml                 # Automatyczny lint (ruff) i testy (pytest)
│   └── release.yml            # Czysty build .exe / Linux + SHA256SUMS.txt
├── src/vider_downloader/
│   ├── __init__.py            # Metadane i wersja pakietu
│   ├── config.py              # Katalog danych aplikacji, ustawienia i sesja
│   ├── models.py              # Modele danych, statusy kolejki i sanityzacja
│   ├── core.py                # Ekstrakcja metadanych, dekodowanie, parser batch
│   ├── downloader.py          # Silnik pobierania z wznawianiem i anulowaniem
│   ├── queue_manager.py       # Wielowątkowy menedżer kolejki wsadowej
│   ├── cli.py                 # Interfejs wiersza poleceń (Rich)
│   └── gui/
│       ├── theme.py           # Paleta ciemnego motywu
│       ├── captcha_dialog.py  # Wbudowane okno Captcha w pamięci
│       └── app.py             # Główne okno desktopowe (CustomTkinter)
├── tests/                     # Testy jednostkowe i integracyjne (pytest)
├── main.py                    # Punkt wejścia (GUI / CLI)
├── LICENSE                    # Licencja MIT
├── SECURITY.md                # Polityka bezpieczeństwa i prywatności
├── CONTRIBUTING.md            # Wytyczne dla współtwórców
└── CHANGELOG.md               # Dziennik zmian (SemVer)
```

---

## Uruchamianie testów

```bash
pip install -e ".[dev]"
pytest -v
ruff check src tests main.py
```

---

## Zastrzeżenie prawne (Disclaimer)

Projekt **Vider Downloader** jest udostępniany na licencji [MIT](LICENSE) wyłącznie w celach edukacyjnych oraz do prywatnej archiwizacji materiałów, do których użytkownik posiada odpowiednie uprawnienia. Autorzy projektu nie hostują żadnych treści wideo, nie są powiązani z serwisami `vider.info` / `vider.pl` i nie ponoszą odpowiedzialności za sposób wykorzystania narzędzia przez użytkowników końcowych.
