import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_selection as app


class SelectionTests(unittest.TestCase):
    def test_forced_closed_date_wins(self):
        cfg = {"market": {"forced_closed_dates": ["2026-08-17"], "forced_open_dates": []}}
        self.assertFalse(app.is_trade_day(date(2026, 8, 17), cfg))

    def test_example_filter(self):
        cfg = {"strategy": {"max_results": 30, "exclude_prefixes": [], "filters": {"min_close": 3, "min_amount_thousand_yuan": 100000, "min_pct_chg": .5, "max_pct_chg": 7, "min_price_position": .55}}}
        rows = [{"ts_code":"000001.SZ","high":12,"low":10,"close":11.5,"amount":100001,"pct_chg":2.1}]
        self.assertEqual(app.select(rows, cfg)[0]["ts_code"], "000001.SZ")


if __name__ == "__main__":
    unittest.main()
