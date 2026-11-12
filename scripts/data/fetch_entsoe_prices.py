"""Fetch hourly day-ahead electricity prices from the ENTSO-E Transparency Platform (workflow step 6).

Usage:
    ENTSOE_API_KEY=... python -m scripts.data.fetch_entsoe_prices PT 2025-01-01 2026-01-01

Uses entsoe-py (EnergieID, MIT licence, github.com/EnergieID/entsoe-py), ``EntsoePandasClient.
query_day_ahead_prices``. A free API key is issued on request by ENTSO-E (account on
transparency.entsoe.eu, then "Restful API access" by e-mail). Quarter-hour prices (since October 2025)
are averaged to hours. Writes data/prices/<zone>_<start>_<end>_day_ahead.csv with provenance comments;
read it with ``pinch.tariffs.load_hourly_prices``. Not part of regenerate_outputs.py (network and key).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

import pandas as pd

from pinch.tariffs import to_hourly

ROOT = Path(__file__).resolve().parents[2]   # repository root


def fetch(zone: str, start: str, end: str, client=None) -> pd.Series:
    """Hourly prices [€/MWh] for a bidding zone (e.g. 'PT', 'ES'); ``client`` defaults to entsoe-py's."""
    if client is None:
        from entsoe import EntsoePandasClient
        key = os.environ.get("ENTSOE_API_KEY")
        if not key:
            raise SystemExit("set ENTSOE_API_KEY (free key from the ENTSO-E Transparency Platform)")
        client = EntsoePandasClient(api_key=key)
    s = client.query_day_ahead_prices(zone, start=pd.Timestamp(start, tz="Europe/Brussels"),
                                      end=pd.Timestamp(end, tz="Europe/Brussels"))
    s = s.tz_convert("UTC").sort_index()
    s = s[~s.index.duplicated(keep="first")]
    return to_hourly(s).rename("price_EUR_per_MWh")


def write(prices: pd.Series, zone: str, start: str, end: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{zone}_{start}_{end}_day_ahead.csv"
    header = (f"# ENTSO-E Transparency Platform, day-ahead prices, bidding zone {zone}, {start} to {end} "
              f"(end exclusive), hourly means, EUR/MWh\n"
              f"# fetched {dt.date.today().isoformat()} with entsoe-py (EnergieID, MIT licence)\n")
    body = pd.DataFrame({"timestamp": prices.index.strftime("%Y-%m-%dT%H:%M:%S%z"),
                         "price_EUR_per_MWh": prices.to_numpy()}).to_csv(index=False)
    path.write_text(header + body, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zone")
    parser.add_argument("start", help="YYYY-MM-DD (inclusive)")
    parser.add_argument("end", help="YYYY-MM-DD (exclusive)")
    args = parser.parse_args()
    prices = fetch(args.zone, args.start, args.end)
    path = write(prices, args.zone, args.start, args.end, ROOT / "data" / "prices")
    print(f"{len(prices)} hours, mean {prices.mean():.2f} EUR/MWh -> {path}")


if __name__ == "__main__":
    main()
