"""Fetch non-household electricity and gas prices and the network-cost component from Eurostat (step 6).

Usage:
    python -m scripts.data.fetch_eurostat_prices                 # PT ES DE, from 2021-S2
    python -m scripts.data.fetch_eurostat_prices PT ES FR --since 2019-S1

Eurostat dissemination API (SDMX 3.0, CSV, no key; https://ec.europa.eu/eurostat/web/user-guides/data-browser/
api-data-access): datasets nrg_pc_205 (electricity, non-household, half-yearly, EUR/kWh), nrg_pc_203 (gas,
non-household, half-yearly, kWh on GCV) and nrg_pc_205_c (electricity price components, non-household, annual).
Writes data/sources/eurostat_prices.csv (EUR, kWh, every band and tax level) and
data/sources/eurostat_electricity_components.csv (EUR/kWh by component). Not part of regenerate_outputs.py
(network). Eurostat data: reuse authorised with acknowledgement of the source (Commission Decision 2011/833/EU).
"""

from __future__ import annotations

import argparse
import datetime as dt
from io import StringIO
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]   # repository root
API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/3.0/data/dataflow/ESTAT/{ds}/1.0/*"
DATASETS = {"electricity": "nrg_pc_205", "gas": "nrg_pc_203"}


def _label(x: str) -> str:
    """'X_VAT: Excluding VAT ...' -> 'Excluding VAT ...' (the labels of the earlier hand-parsed file)."""
    return x.split(": ", 1)[1] if ": " in x else x


def _code(x: str) -> str:
    return x.split(": ", 1)[0]


def fetch_dataset(ds: str, geos: list[str], opener=urlopen) -> pd.DataFrame:
    """One Eurostat dataset for the given countries, codes and labels in each cell ('CODE: label')."""
    url = API.format(ds=ds) + f"?c[geo]={','.join(geos)}&format=csvdata&formatVersion=2.0&compress=false&labels=both"
    with opener(url) as r:
        text = r.read().decode("utf-8")
    d = pd.read_csv(StringIO(text), dtype=str)
    d.columns = [c.split(":", 1)[0] for c in d.columns]
    return d


def prices(geos: list[str], since: str, opener=urlopen) -> pd.DataFrame:
    """Half-yearly prices in EUR/kWh (gas on GCV), every band and tax level, from ``since`` (e.g. '2021-S2')."""
    rows = []
    for carrier, ds in DATASETS.items():
        d = fetch_dataset(ds, geos, opener)
        d = d[(d["unit"].map(_code) == "KWH") & (d["currency"].map(_code) == "EUR") & (d["TIME_PERIOD"] >= since)
              & d["OBS_VALUE"].notna() & d["nrg_cons"].str.contains("band")]
        rows.append(pd.DataFrame({"geo": d["geo"].map(_code), "carrier": carrier, "band": d["nrg_cons"].map(_label),
                                  "unit": d["unit"].map(_label), "taxes": d["tax"].map(_label),
                                  "currency": d["currency"].map(_label), "period": d["TIME_PERIOD"],
                                  "value": d["OBS_VALUE"].astype(float)}))
    out = pd.concat(rows, ignore_index=True)
    return out.sort_values(["geo", "carrier", "band", "taxes", "period"]).reset_index(drop=True)


def components(geos: list[str], since_year: str, opener=urlopen) -> pd.DataFrame:
    """Annual electricity price components [EUR/kWh] by band (nrg_pc_205_c)."""
    d = fetch_dataset("nrg_pc_205_c", geos, opener)
    d = d[(d["currency"].map(_code) == "EUR") & (d["TIME_PERIOD"] >= since_year) & d["OBS_VALUE"].notna()
          & d["nrg_cons"].str.contains("band ")]
    out = pd.DataFrame({"geo": d["geo"].map(_code), "band": d["nrg_cons"].map(_label),
                        "component": d["nrg_prc"].map(_code), "component_label": d["nrg_prc"].map(_label),
                        "year": d["TIME_PERIOD"], "value_EUR_per_kWh": d["OBS_VALUE"].astype(float)})
    return out.sort_values(["geo", "band", "component", "year"]).reset_index(drop=True)


def write(df: pd.DataFrame, path: Path, what: str) -> Path:
    header = (f"# Eurostat, {what}. Fetched {dt.date.today().isoformat()} with scripts/data/fetch_eurostat_prices.py "
              "(dissemination API, SDMX 3.0 CSV). Source: Eurostat; reuse authorised with acknowledgement "
              "(Commission Decision 2011/833/EU).\n")
    path.write_text(header + df.to_csv(index=False, lineterminator="\n"), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("geos", nargs="*", default=["PT", "ES", "DE"])
    parser.add_argument("--since", default="2021-S2", help="first half-year (prices); its year for components")
    args = parser.parse_args()
    src = ROOT / "data" / "sources"
    p = write(prices(args.geos, args.since), src / "eurostat_prices.csv",
              "nrg_pc_205 (electricity) and nrg_pc_203 (gas), non-household consumers, half-yearly, EUR/kWh "
              "(gas on gross calorific value)")
    c = write(components(args.geos, args.since[:4]), src / "eurostat_electricity_components.csv",
              "nrg_pc_205_c, electricity price components, non-household consumers, annual, EUR/kWh")
    print(f"wrote {p.relative_to(ROOT)} and {c.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
