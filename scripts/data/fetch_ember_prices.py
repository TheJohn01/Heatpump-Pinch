"""Hourly day-ahead electricity prices without an API key: Ember's European wholesale price data (step 6).

Usage:
    python -m scripts.data.fetch_ember_prices                     # Portugal, Spain, Germany, 2025
    python -m scripts.data.fetch_ember_prices --countries France --year 2024

Ember, "European wholesale electricity price data" (https://ember-energy.org/data/european-wholesale-electricity-
price-data), hourly file, CC BY 4.0. Ember takes the hourly day-ahead prices from the ENTSO-E Transparency Platform
and interpolates missing values from neighbouring hours. Writes data/prices/<country>_<year>_day_ahead.csv
(read with ``pinch.tariffs.load_hourly_prices``); the year runs over UTC hours. Not part of
regenerate_outputs.py (network). For other zones or periods with an ENTSO-E key: scripts/data/fetch_entsoe_prices.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import zipfile
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]   # repository root
URL = "https://files.ember-energy.org/public-downloads/price/outputs/european_wholesale_electricity_price_data_hourly.zip"


def extract(archive: bytes, country: str, year: int) -> pd.Series:
    """Hourly prices [EUR/MWh] of one country and calendar year (UTC) from the Ember zip."""
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        d = pd.read_csv(z.open(f"{country}.csv"))
    ts = pd.to_datetime(d["Datetime (UTC)"], utc=True)
    s = pd.Series(d["Price (EUR/MWhe)"].to_numpy(dtype=float), index=ts, name="price_EUR_per_MWh").sort_index()
    s = s[(s.index >= pd.Timestamp(f"{year}-01-01", tz="UTC")) & (s.index < pd.Timestamp(f"{year + 1}-01-01", tz="UTC"))]
    expected = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="1h", tz="UTC", inclusive="left")
    if not s.index.equals(expected):
        raise ValueError(f"{country} {year}: {len(s)} hours, expected a complete year of {len(expected)}")
    return s


def write(prices: pd.Series, country: str, year: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{country.lower().replace(' ', '_')}_{year}_day_ahead.csv"
    header = (f"# Ember, European wholesale electricity price data, hourly, {country}, {year} (UTC hours), day-ahead, "
              "EUR/MWh. CC BY 4.0 (https://ember-energy.org/data/european-wholesale-electricity-price-data); Ember's "
              "source: ENTSO-E Transparency Platform, missing values interpolated by Ember.\n"
              f"# fetched {dt.date.today().isoformat()} with scripts/data/fetch_ember_prices.py\n")
    body = pd.DataFrame({"timestamp": prices.index.strftime("%Y-%m-%dT%H:%M:%S%z"),
                         "price_EUR_per_MWh": prices.to_numpy()}).to_csv(index=False, lineterminator="\n")
    path.write_text(header + body, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--countries", nargs="+", default=["Portugal", "Spain", "Germany"])
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()
    with urlopen(URL) as r:
        archive = r.read()
    for c in args.countries:
        print(write(extract(archive, c, args.year), c, args.year, ROOT / "data" / "prices").relative_to(ROOT))


if __name__ == "__main__":
    main()
