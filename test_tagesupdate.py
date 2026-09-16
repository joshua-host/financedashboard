"""
Selbsttest fuer tagesupdate.py - mockt requests.get, damit die Logik ohne
echte API-Keys / Netzwerkzugriff geprueft werden kann.

Ausfuehren mit: python3 test_tagesupdate.py
"""

import json
import unittest
from datetime import date
from unittest.mock import patch, MagicMock

import tagesupdate as tu


def fake_response(json_data, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        def _raise():
            raise Exception("HTTP error")
        resp.raise_for_status.side_effect = _raise
    return resp


class TestFomcDates(unittest.TestCase):
    def test_finds_next_meeting_within_window(self):
        today = date(2026, 9, 1)
        result = tu.get_next_fomc_meeting(today, lookahead_days=30)
        self.assertEqual(result, date(2026, 9, 16))

    def test_no_meeting_when_window_too_small(self):
        today = date(2026, 9, 1)
        result = tu.get_next_fomc_meeting(today, lookahead_days=5)
        self.assertIsNone(result)

    def test_meeting_on_exact_day(self):
        today = date(2026, 9, 16)
        result = tu.get_next_fomc_meeting(today, lookahead_days=0)
        self.assertEqual(result, date(2026, 9, 16))

    def test_rolls_into_next_year(self):
        today = date(2026, 12, 20)
        result = tu.get_next_fomc_meeting(today, lookahead_days=45)
        self.assertEqual(result, date(2027, 1, 27))


class TestFredRate(unittest.TestCase):
    @patch("tagesupdate.requests.get")
    def test_parses_latest_valid_value(self, mock_get):
        mock_get.return_value = fake_response({
            "observations": [{"value": "3.63"}, {"value": "3.63"}]
        })
        rate, err = tu.get_current_fed_rate("dummy_key")
        self.assertIsNone(err)
        self.assertAlmostEqual(rate, 3.63)

    @patch("tagesupdate.requests.get")
    def test_skips_missing_values(self, mock_get):
        mock_get.return_value = fake_response({
            "observations": [{"value": "."}, {"value": "3.58"}]
        })
        rate, err = tu.get_current_fed_rate("dummy_key")
        self.assertIsNone(err)
        self.assertAlmostEqual(rate, 3.58)

    def test_missing_api_key(self):
        rate, err = tu.get_current_fed_rate(None)
        self.assertIsNone(rate)
        self.assertIn("fehlt", err)

    @patch("tagesupdate.requests.get")
    def test_handles_request_exception(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        rate, err = tu.get_current_fed_rate("dummy_key")
        self.assertIsNone(rate)
        self.assertIn("fehlgeschlagen", err)


class TestQuote(unittest.TestCase):
    @patch("tagesupdate.requests.get")
    def test_parses_quote(self, mock_get):
        mock_get.return_value = fake_response([
            {"symbol": "NVDA", "price": 187.32, "changesPercentage": 2.41}
        ])
        quote, err = tu.get_quote("NVDA", "dummy_key")
        self.assertIsNone(err)
        self.assertAlmostEqual(quote["price"], 187.32)
        self.assertAlmostEqual(quote["change_pct"], 2.41)

    @patch("tagesupdate.requests.get")
    def test_empty_response(self, mock_get):
        mock_get.return_value = fake_response([])
        quote, err = tu.get_quote("XXXX", "dummy_key")
        self.assertIsNone(quote)
        self.assertIn("Keine Kursdaten", err)


class TestEarningsCalendar(unittest.TestCase):
    @patch("tagesupdate.requests.get")
    def test_filters_to_wanted_tickers(self, mock_get):
        mock_get.return_value = fake_response([
            {"symbol": "NVDA", "date": "2026-11-19"},
            {"symbol": "AAPL", "date": "2026-10-30"},
            {"symbol": "ORCL", "date": "2026-12-11"},
        ])
        result, err = tu.get_earnings_calendar(["NVDA", "ORCL"], 90, "dummy_key")
        self.assertIsNone(err)
        self.assertEqual(result, {"NVDA": "2026-11-19", "ORCL": "2026-12-11"})


class TestBuildReport(unittest.TestCase):
    def _config(self):
        return {
            "invested": [
                {"ticker": "NOW", "name": "ServiceNow"},
                {"ticker": "NVDA", "name": "Nvidia"},
            ],
            "watching": [
                {"ticker": "MU", "name": "Micron Technology", "target_price": 100.0, "trigger": "below"},
                {"ticker": "META", "name": "Meta Platforms", "target_price": None, "trigger": "below"},
            ],
            "move_threshold_percent": 10,
            "earnings_lookahead_days": 7,
            "fed_lookahead_days": 14,
        }

    @patch("tagesupdate.get_earnings_calendar")
    @patch("tagesupdate.get_quote")
    @patch("tagesupdate.get_current_fed_rate")
    def test_full_report_with_big_move_and_hit_target(self, mock_rate, mock_quote, mock_earnings):
        mock_rate.return_value = (3.63, None)
        mock_earnings.return_value = ({}, None)

        def quote_side_effect(ticker, key):
            data = {
                "NOW": {"price": 900.0, "change_pct": 1.2},
                "NVDA": {"price": 200.0, "change_pct": 12.5},  # große Bewegung
                "MU": {"price": 95.0, "change_pct": -1.0},     # Kursziel 100 unterschritten -> hit
                "META": {"price": 600.0, "change_pct": 0.5},
            }
            return data[ticker], None

        mock_quote.side_effect = quote_side_effect

        report = tu.build_report(self._config(), "fmp_key", "fred_key", today=date(2026, 9, 1))

        self.assertEqual(report["errors"], [])
        text = report["text"]
        self.assertIn("große Bewegung", text)
        self.assertIn("Kursziel von 100.00 Dollar erreicht", text)
        self.assertIn("noch kein Kursziel hinterlegt", text)  # META
        self.assertIn("Leitzins liegt bei 3.63 Prozent", text)

    @patch("tagesupdate.get_earnings_calendar")
    @patch("tagesupdate.get_quote")
    @patch("tagesupdate.get_current_fed_rate")
    def test_quote_error_does_not_crash_report(self, mock_rate, mock_quote, mock_earnings):
        mock_rate.return_value = (None, "FRED_API_KEY fehlt")
        mock_earnings.return_value = ({}, None)
        mock_quote.return_value = (None, "Kursabfrage fehlgeschlagen: timeout")

        report = tu.build_report(self._config(), "fmp_key", None, today=date(2026, 9, 1))

        self.assertTrue(len(report["errors"]) > 0)
        self.assertIn("Kursdaten nicht verfügbar", report["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
