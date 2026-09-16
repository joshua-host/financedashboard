# Tagesupdate

Automatisches Aktien-/Fed-Update, das zweimal täglich läuft und einen fertigen
Sprachtext erzeugt, den ein iPhone-Kurzbefehl abrufen und vorlesen kann.

## Dateien

| Datei | Zweck |
|---|---|
| `tagesupdate.py` | Hauptskript: holt Fed-Termine, Kurse, Earnings, baut den Text |
| `watchlist.json` | Deine Konfiguration: investierte Aktien, Watchlist mit Kurszielen |
| `.github/workflows/tagesupdate.yml` | Führt das Skript automatisch 2x täglich (werktags) aus |
| `requirements.txt` | Python-Abhängigkeiten |
| `test_tagesupdate.py` | Selbsttests (mit gemockten API-Antworten, kein Netzwerk nötig) |

## Einmaliges Setup

1. **Dateien ins Repo legen.** Alle Dateien aus diesem Paket in dein
   bestehendes GitHub-Pages-Repo hochladen (gleiche Ordnerstruktur
   beibehalten, `.github/workflows/tagesupdate.yml` muss in genau diesem
   Unterordner liegen).

2. **Secrets hinterlegen.** Im Repo unter *Settings → Secrets and variables →
   Actions → New repository secret* zwei Secrets anlegen:
   - `FMP_API_KEY` – dein vorhandener Financial-Modeling-Prep-Key
   - `FRED_API_KEY` – dein vorhandener FRED-Key

3. **Actions aktivieren**, falls noch nicht geschehen (*Settings → Actions →
   General → Allow all actions*).

4. **Testlauf.** Im Tab *Actions* den Workflow "Tagesupdate" öffnen und über
   *Run workflow* manuell starten. Danach prüfen, ob `tagesupdate.txt` im
   Repo aktualisiert wurde und ob es Fehlermeldungen im Log gibt.

5. **Erreichbarkeit prüfen.** Die Datei muss über deine GitHub-Pages-URL
   abrufbar sein, z. B. `https://<username>.github.io/<repo>/tagesupdate.txt`.
   Falls dein Pages-Branch/Ordner nicht der Repo-Root ist (z. B. `/docs`),
   die Datei entsprechend dorthin legen oder den Workflow anpassen.

6. **Kursziele eintragen.** In `watchlist.json` bei den Watchlist-Einträgen
   `target_price` von `null` auf deinen gewünschten Wert setzen (Zahl, kein
   String). `trigger: "below"` löst aus, wenn der Kurs auf/unter das Ziel
   fällt (Einstiegslevel); `"above"` für den umgekehrten Fall.

7. **Kurzbefehl bauen** (Apple Shortcuts):
   - Aktion "Inhalt von URL abrufen" → deine `tagesupdate.txt`-URL
   - Aktion "Text sprechen" mit dem abgerufenen Inhalt
   - Davor optional: Datum/Uhrzeit abfragen und je nach Tageszeit
     "Guten Morgen/Tag/Abend Joshua" voranstellen (wie bei deiner
     bestehenden Wetter-Shortcut)
   - Als Siri-Satz z. B. "Tagesupdate" hinterlegen

## Wichtige Hinweise

- **FOMC-Termine sind hardcodiert** (siehe `FOMC_DECISION_DATES` in
  `tagesupdate.py`), weil es dafür keine kostenlose Kalender-API gibt. Die
  2026er-Termine sind final, die 2027er vorläufig. Einmal jährlich
  aktualisieren, sobald die Fed den neuen Kalender veröffentlicht:
  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- **Cron-Zeiten sind UTC** und verschieben sich durch die US-/EU-Zeitumstellung
  gegenüber der US-Marktzeit um etwa eine Stunde. Für ein tägliches Update
  unkritisch, bei Bedarf in `tagesupdate.yml` anpassen.
- **FMP Free-Plan**: 250 Requests/Tag, nur US-Ticker. Bei 9 beobachteten
  Aktien und 2 Läufen/Tag werden ca. 20-25 Requests/Tag verbraucht -
  unkritisch. Der `/stable/earnings-calendar`-Endpunkt könnte je nach
  Plan-Stufe eingeschränkt sein (konnte ohne Netzwerkzugriff nicht live
  gegen deinen Key getestet werden) - schlägt der Earnings-Teil mit
  401/403 fehl, steht das im Actions-Log, und notfalls auf den älteren
  `/api/v3/earning_calendar`-Endpunkt wechseln.
- Schlägt ein einzelner Kurs- oder Earnings-Abruf fehl, wird das im Text als
  "Kursdaten nicht verfügbar" markiert statt den ganzen Lauf abzubrechen.
  Fehlerdetails stehen im Actions-Log und in `tagesupdate.json` unter
  `errors`.

## Lokal testen (ohne GitHub Actions)

```bash
pip install -r requirements.txt
export FMP_API_KEY="dein_key"
export FRED_API_KEY="dein_key"
python3 tagesupdate.py
python3 test_tagesupdate.py   # Selbsttests, brauchen keine Keys
```
