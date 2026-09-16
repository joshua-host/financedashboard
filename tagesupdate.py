#!/usr/bin/env python3
"""
Tagesupdate-Skript.

Holt bei jedem Lauf:
 - die naechste FOMC-Zinsentscheidung (Fed) + aktueller Leitzins (FRED)
 - Kurse & Tagesbewegung fuer bestehende Positionen ("invested")
 - Kursziel-Status fuer Watchlist-Aktien ("watching")
 - anstehende Earnings-Termine fuer alle beobachteten Ticker (FMP)

Schreibt das Ergebnis als reinen Text nach OUTPUT_TXT_PATH (wird vom
iPhone-Kurzbefehl abgerufen und vorgelesen) und zusaetzlich als JSON nach
OUTPUT_JSON_PATH (zum Nachvollziehen/Debuggen).

Benoetigte Umgebungsvariablen (als GitHub Secrets hinterlegen):
    FMP_API_KEY   - Financial Modeling Prep API Key
    FRED_API_KEY  - FRED (St. Louis Fed) API Key

Konfiguration: watchlist.json (im selben Verzeichnis, Pfad ueber
WATCHLIST_CONFIG ueberschreibbar).
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------------------
# Konfiguration / Konstanten
# ---------------------------------------------------------------------------

CONFIG_PATH = os.environ.get("WATCHLIST_CONFIG", "watchlist.json")
OUTPUT_TXT_PATH = os.environ.get("OUTPUT_TXT_PATH", "tagesupdate.txt")
OUTPUT_JSON_PATH = os.environ.get("OUTPUT_JSON_PATH", "tagesupdate.json")

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

REQUEST_TIMEOUT = 15  # Sekunden

GERMAN_MONTHS = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November",
    12: "Dezember",
}

# Bekannte FOMC-Sitzungstermine (Datum = letzter Tag der Sitzung / Tag der
# Zinsentscheidung, jeweils 2 Uhr nachmittags Ostkueste-Zeit).
# Quelle: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# WICHTIG: Diese Liste muss jaehrlich aktualisiert werden, sobald die Fed den
# Kalender fuer das naechste Jahr veroeffentlicht (i. d. R. im Spaetsommer).
# Die 2027-Termine sind laut Fed-Kalender vorlaeufig ("tentative").
FOMC_DECISION_DATES = [
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    # 2027 (vorlaeufig)
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
]


def format_date_de(d):
    """Formatiert ein date-Objekt als '16. September 2026'."""
    return f"{d.day}. {GERMAN_MONTHS[d.month]} {d.year}"


# ---------------------------------------------------------------------------
# Daten laden
# ---------------------------------------------------------------------------

def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_next_fomc_meeting(today, lookahead_days):
    """Naechste FOMC-Zinsentscheidung als date-Objekt, wenn sie innerhalb von
    `lookahead_days` liegt - sonst None."""
    horizon = today + timedelta(days=lookahead_days)
    upcoming = []
    for d_str in FOMC_DECISION_DATES:
        d = datetime.strptime(d_str, "%Y-%m-%d").date()
        if today <= d <= horizon:
            upcoming.append(d)
    return min(upcoming) if upcoming else None


def get_current_fed_rate(api_key):
    """Aktueller Effective Federal Funds Rate (taeglich, FRED-Serie DFF)."""
    if not api_key:
        return None, "FRED_API_KEY fehlt"
    params = {
        "series_id": "DFF",
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5,  # ein paar Werte holen, falls der neueste Tag noch "." (kein Wert) ist
    }
    try:
        r = requests.get(FRED_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for obs in data.get("observations", []):
            value = obs.get("value")
            if value not in (None, "."):
                return float(value), None
        return None, "Keine gueltigen FRED-Daten erhalten"
    except Exception as e:
        return None, f"FRED-Abfrage fehlgeschlagen: {e}"


def get_quote(ticker, api_key):
    """Aktueller Kurs + Tagesveraenderung in % ueber FMP Stable Quote API."""
    if not api_key:
        return None, "FMP_API_KEY fehlt"
    params = {"symbol": ticker, "apikey": api_key}
    try:
        r = requests.get(f"{FMP_BASE_URL}/quote", params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None, "Keine Kursdaten erhalten"
        entry = data[0]
        price = entry.get("price")
        change_pct = entry.get("changesPercentage")
        if change_pct is None:
            change_pct = entry.get("changePercentage")
        if price is None or change_pct is None:
            return None, "Unerwartetes FMP-Antwortformat"
        return {"price": float(price), "change_pct": float(change_pct)}, None
    except Exception as e:
        return None, f"Kursabfrage fehlgeschlagen: {e}"


def get_earnings_calendar(tickers, days_ahead, api_key):
    """dict {ticker: 'YYYY-MM-DD'} fuer Ticker mit Earnings in den naechsten
    `days_ahead` Tagen."""
    if not api_key:
        return {}, "FMP_API_KEY fehlt"
    today = date.today()
    horizon = today + timedelta(days=days_ahead)
    params = {
        "from": today.isoformat(),
        "to": horizon.isoformat(),
        "apikey": api_key,
    }
    try:
        r = requests.get(f"{FMP_BASE_URL}/earnings-calendar", params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        result = {}
        wanted = set(tickers)
        for entry in data:
            sym = entry.get("symbol")
            if sym in wanted and sym not in result:
                result[sym] = entry.get("date")
        return result, None
    except Exception as e:
        return {}, f"Earnings-Kalender-Abfrage fehlgeschlagen: {e}"


# ---------------------------------------------------------------------------
# Report-Erstellung
# ---------------------------------------------------------------------------

def build_report(config, fmp_key, fred_key, today=None):
    if today is None:
        today = date.today()

    threshold = config.get("move_threshold_percent", 10)
    fed_lookahead = config.get("fed_lookahead_days", 14)
    earnings_lookahead = config.get("earnings_lookahead_days", 7)

    invested = config.get("invested", [])
    watching = config.get("watching", [])
    all_tickers = [x["ticker"] for x in invested] + [x["ticker"] for x in watching]
    name_by_ticker = {x["ticker"]: x["name"] for x in invested + watching}

    lines = []
    errors = []

    # --- Fed ---
    next_meeting = get_next_fomc_meeting(today, fed_lookahead)
    rate, rate_err = get_current_fed_rate(fred_key)
    if rate_err:
        errors.append(rate_err)

    if next_meeting:
        fed_line = f"Am {format_date_de(next_meeting)} steht die nächste Fed-Zinsentscheidung an."
    else:
        fed_line = f"In den nächsten {fed_lookahead} Tagen steht keine Fed-Zinsentscheidung an."
    if rate is not None:
        fed_line += f" Der aktuelle Leitzins liegt bei {rate:.2f} Prozent."
    lines.append(fed_line)

    # --- Earnings (fuer alle beobachteten Ticker zusammen) ---
    earnings, earnings_err = get_earnings_calendar(all_tickers, earnings_lookahead, fmp_key)
    if earnings_err:
        errors.append(earnings_err)

    if earnings:
        parts = []
        for ticker, edate_str in earnings.items():
            try:
                edate = datetime.strptime(edate_str, "%Y-%m-%d").date()
                edate_fmt = format_date_de(edate)
            except Exception:
                edate_fmt = edate_str
            parts.append(f"{name_by_ticker.get(ticker, ticker)} am {edate_fmt}")
        lines.append(f"Earnings in den nächsten {earnings_lookahead} Tagen: " + ", ".join(parts) + ".")
    else:
        lines.append(
            f"Keine Earnings-Termine in den nächsten {earnings_lookahead} Tagen bei deinen beobachteten Aktien."
        )

    # --- Bereich 1: bestehende Positionen ---
    lines.append("Deine bestehenden Positionen:")
    for stock in invested:
        ticker, name = stock["ticker"], stock["name"]
        quote, q_err = get_quote(ticker, fmp_key)
        if q_err:
            errors.append(f"{ticker}: {q_err}")
            lines.append(f"{name}: Kursdaten nicht verfügbar.")
            continue
        price, change = quote["price"], quote["change_pct"]
        sign = "plus" if change >= 0 else "minus"
        text = f"{name}: {price:.2f} Dollar, {sign} {abs(change):.1f} Prozent heute."
        if abs(change) >= threshold:
            text += " Das ist eine große Bewegung."
        lines.append(text)

    # --- Bereich 2: Watchlist mit Kurszielen ---
    lines.append("Deine Watchlist mit Kurszielen:")
    for stock in watching:
        ticker, name = stock["ticker"], stock["name"]
        target = stock.get("target_price")
        trigger = stock.get("trigger", "below")
        quote, q_err = get_quote(ticker, fmp_key)
        if q_err:
            errors.append(f"{ticker}: {q_err}")
            lines.append(f"{name}: Kursdaten nicht verfügbar.")
            continue
        price = quote["price"]
        if target is None:
            lines.append(f"{name}: aktuell {price:.2f} Dollar, noch kein Kursziel hinterlegt.")
            continue
        target = float(target)
        hit = (price <= target) if trigger == "below" else (price >= target)
        if hit:
            lines.append(f"{name}: Kursziel von {target:.2f} Dollar erreicht, aktuell {price:.2f} Dollar!")
        else:
            diff_pct = abs(price - target) / target * 100
            lines.append(
                f"{name}: aktuell {price:.2f} Dollar, noch {diff_pct:.1f} Prozent vom Kursziel "
                f"{target:.2f} Dollar entfernt."
            )

    report_text = " ".join(lines)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "text": report_text,
        "lines": lines,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    fmp_key = os.environ.get("FMP_API_KEY")
    fred_key = os.environ.get("FRED_API_KEY")

    if not fmp_key:
        print("WARNUNG: FMP_API_KEY nicht gesetzt - Kurse/Earnings werden fehlen.", file=sys.stderr)
    if not fred_key:
        print("WARNUNG: FRED_API_KEY nicht gesetzt - Leitzins wird fehlen.", file=sys.stderr)

    config = load_config(CONFIG_PATH)
    report = build_report(config, fmp_key, fred_key)

    with open(OUTPUT_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(report["text"])

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(report["text"])
    if report["errors"]:
        print("\n--- Fehler während der Ausführung ---", file=sys.stderr)
        for e in report["errors"]:
            print(f"- {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
