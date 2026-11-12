"""Effective electricity price of a case's heat pumps against the RQ3 break-even ratio (step 6).

Usage:
    python -m scripts.checks.tariff_check cases/brewery.json data/prices/PT_2025-01-01_2026-01-01_day_ahead.csv
        [--hours 6-22] [--weekdays 0-4] [--cheapest 16] [--adder 18-21:12.5] [--demand-charge 30]

Reads hourly prices (``scripts.data.fetch_entsoe_prices``), the case's gas price (economics block) and
the RQ3 break-even ratios in outputs/<case>/rq_consolidated.csv (base case), and reports the price a
heat pump pays over its operating hours (``pinch.tariffs``): energy-weighted market price plus optional
network adders (€/MWh by local hour) and a demand charge (€/kW/year), the resulting electricity-to-gas
ratio and the margin to each unit's break-even ratio. Market prices exclude network tariffs and taxes
unless added: compare like with like (the case's flat electricity price is a delivered price).
Not part of regenerate_outputs.py (needs a price file the user fetched). Any source in the same CSV layout
works, e.g. OMIE day-ahead prices for Portugal (published without an API key); 15-minute prices are averaged
to hourly.

ERSE access tariffs (``--erse 2027 --voltage MT --network-share S``): applies the published change of the
network access tariffs (data/sources/erse_access_tariff_changes.csv) to the network-cost share S of the case's
flat electricity price and compares the new ratio with the break-even ratios. S is the user's input from
Eurostat nrg_pc_205_c (component NETC over the total, for the case's band); the repository does not hold it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pinch.case import load_case
from pinch.economics import load_economics
from pinch.tariffs import (
    NetworkTariff,
    OperatingPattern,
    access_tariff_change,
    effective_price,
    load_hourly_prices,
    with_network_change,
)

ROOT = Path(__file__).resolve().parents[2]   # repository root


def _range(text: str, hi: int) -> frozenset[int]:
    out: set[int] = set()
    for part in text.split(","):
        a, _, b = part.partition("-")
        lo_i, hi_i = int(a), int(b) if b else int(a)
        if not 0 <= lo_i <= hi_i <= hi:
            raise argparse.ArgumentTypeError(f"bad range {part!r}")
        out |= set(range(lo_i, hi_i + 1))
    return frozenset(out)


def access_tariff_scenario(case_file: Path, network_share: float, year: int, voltage: str = "MT") -> pd.DataFrame:
    """The case's flat electricity price with the ERSE access-tariff change of ``year`` applied to its
    network-cost share, against each heat pump's RQ3 break-even ratio. ``network_share`` must come from the
    user (Eurostat nrg_pc_205_c, component NETC, for the case's consumption band): it is not in the repository."""
    case = load_case(case_file)
    params = load_economics(case.economics)
    change, status = access_tariff_change(year, voltage)
    p_new = with_network_change(params.electricity_price_EUR_per_kWh, network_share, change)
    rq = pd.read_csv(ROOT / "outputs" / case.name / "rq_consolidated.csv").iloc[0]
    rows = []
    for unit in ("HP1", "HP2"):
        if f"RQ3_ratio_{unit}" in rq:
            ratio = p_new / params.gas_price_EUR_per_kWh
            rows.append({"unit": rq[f"{unit}_name"], "year": year, "voltage": voltage, "status": status,
                         "access_tariff_change": change, "network_share": network_share,
                         "price_before_EUR_per_kWh": params.electricity_price_EUR_per_kWh,
                         "price_after_EUR_per_kWh": round(p_new, 5), "ratio_after": round(ratio, 3),
                         "break_even_ratio": rq[f"RQ3_ratio_{unit}"], "competitive": ratio < rq[f"RQ3_ratio_{unit}"]})
    return pd.DataFrame(rows)


def report(case_file: Path, prices_file: Path, pattern: OperatingPattern, tariff: NetworkTariff) -> pd.DataFrame:
    case = load_case(case_file)
    gas = load_economics(case.economics).gas_price_EUR_per_kWh
    eff = effective_price(load_hourly_prices(prices_file), pattern, tariff)
    rq = pd.read_csv(ROOT / "outputs" / case.name / "rq_consolidated.csv").iloc[0]
    ratio = eff.total_EUR_per_kWh / gas
    rows = []
    for unit in ("HP1", "HP2"):
        if f"RQ3_ratio_{unit}" in rq:
            rows.append({"unit": rq[f"{unit}_name"], "effective_EUR_per_kWh": round(eff.total_EUR_per_kWh, 5),
                         "flat_average_EUR_per_kWh": round(eff.flat_average_EUR_per_kWh, 5),
                         "operating_h_per_year": round(eff.hours_per_year), "gas_EUR_per_kWh": gas,
                         "effective_ratio": round(ratio, 3), "break_even_ratio": rq[f"RQ3_ratio_{unit}"],
                         "competitive": ratio < rq[f"RQ3_ratio_{unit}"]})
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("case_file", type=Path)
    p.add_argument("prices_file", type=Path, nargs="?", help="hourly prices (not needed with --erse)")
    p.add_argument("--erse", type=int, help="apply the ERSE access-tariff change of this year to the case's flat "
                                            "price instead (needs --network-share)")
    p.add_argument("--voltage", default="MT", help="voltage code for --erse: MAT, AT, MT, BTE, BTN")
    p.add_argument("--network-share", type=float, help="network-cost share of the delivered price (Eurostat "
                                                       "nrg_pc_205_c, NETC / total, for the case's band)")
    p.add_argument("--hours", default="0-23", help="local clock hours, e.g. 6-22 or 0-5,22-23")
    p.add_argument("--weekdays", default="0-6", help="0 = Monday")
    p.add_argument("--cheapest", type=int, help="run the N cheapest hours of each day instead (needs storage)")
    p.add_argument("--adder", action="append", default=[], help="HOURS:EUR_per_MWh, repeatable")
    p.add_argument("--demand-charge", type=float, default=0.0, help="EUR/kW/year")
    a = p.parse_args()
    if a.erse:
        if a.network_share is None:
            p.error("--erse needs --network-share (Eurostat nrg_pc_205_c, not in the repository)")
        print(access_tariff_scenario(a.case_file, a.network_share, a.erse, a.voltage).to_string(index=False))
        return
    if a.prices_file is None:
        p.error("prices_file is required unless --erse is given")
    pattern = (OperatingPattern("cheapest", weekdays=_range(a.weekdays, 6), hours_per_day=a.cheapest) if a.cheapest
               else OperatingPattern("fixed", hours=_range(a.hours, 23), weekdays=_range(a.weekdays, 6)))
    adders: dict[int, float] = {}
    for item in a.adder:
        hours, _, value = item.partition(":")
        adders.update({h: float(value) for h in _range(hours, 23)})
    df = report(a.case_file, a.prices_file, pattern, NetworkTariff(adders, a.demand_charge))
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
