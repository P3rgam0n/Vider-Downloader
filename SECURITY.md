# Polityka Bezpieczeństwa (Security Policy)

## Prywatność i Bezpieczeństwo Użytkowników

- **Zero telemetrii**: Vider Downloader nie zbiera statystyk, nie wysyła raportów ani nie łączy się z żadnymi zewnętrznymi serwerami poza domenami `vider.info` / `vider.pl` i serwerem strumienia wideo.
- **Lokalne przechowywanie danych**: Ustawienia aplikacji (`settings.json`) oraz ciasteczka sesji po weryfikacji Captcha (`session.json`) są zapisywane wyłącznie lokalnie w katalogu użytkownika:
  - Windows: `%LOCALAPPDATA%\ViderDownloader`
  - Linux: `~/.config/vider-downloader` (z uprawnieniami `0600`)
  - macOS: `~/Library/Application Support/ViderDownloader`
- **Ochrona ścieżek i plików**: Nazwy pobieranych plików oraz ich rozszerzenia są sanityzowane przed zapisem na dysk (ochrona przed *path traversal*, nazwami zarezerwowanymi Windows oraz niedozwolonymi rozszerzeniami wykonywalnymi).
- **Transparentne budowanie plików binarnych**: Gotowe pliki `.exe` oraz binarki Linux publikowane w zakładce *Releases* są budowane automatycznie na czystych środowiskach GitHub Actions (`.github/workflows/release.yml`) bezpośrednio z publicznego kodu źródłowego, wraz z listą sum kontrolnych `SHA256SUMS.txt`.

## Zgłaszanie Podatności

Jeśli zauważysz lukę bezpieczeństwa:
1. **Nie** publikuj szczegółów exploita w publicznym zgłoszeniu (Issue).
2. Skorzystaj z zakładki **Security → Advisories → Report a vulnerability** w tym repozytorium GitHub.
3. Opisz kroki reprodukcji oraz wersję programu — zgłoszenie zostanie sprawdzone najszybciej jak to możliwe.
