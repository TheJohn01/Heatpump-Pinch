"""Batch-operation check of the time-average heat pump design (brewery case).

Usage:
    python batch_check.py cases/brewery.json

Pinch targets and heat pump sizing use time-averaged loads (MWh/year over the operating hours). A
brewhouse is a batch process. This script checks which results survive the batch timing:

* Warm-water heat pump: charges the 24-hour heat-recovery tank (Padullés et al. 2026, Sec. 5.1, validated
  on the DK1 brewery: 375 m3 for 720,000 hl), so it can run continuously at the average duty. Its evaporator
  takes the refrigeration load, which is quasi-continuous (fermentation and beer cooling in parallel
  tanks); its source (about 5 kWh/hl) exceeds the refrigeration duty (3.2 kWh/hl), so the credit does not
  depend on the HTHP's timing.
* HTHP (wort preheating 95 -> 100 °C and boiling): no high-temperature storage, so it must deliver its
  daily heat within the boil windows. Installed capacity = average x F, F = 24 h / (brews/day x window).

Schedule ranges (stated, not from the case paper): 8-14 brews/day for large brewhouses (Briggs of Burton,
'Brewery Sustainability and Energy Integration', Brewing Engineers Association technical day, 2017: an
industry presentation, not peer-reviewed); boil window 60-90 min (typical practice; assumption, no
peer-reviewed source found). The HTHP's extra capacity is added as investment only (heat_pump_equipment).

Writes outputs/<case>/batch_check.csv and .md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from consolidate_rq import answers
from pinch.sensitivity import apply
from pinch import load_streams, with_extra_shift
from pinch.case import load_case
from pinch.cycle_analysis import load_selected
from pinch.research_questions import unit_names

ROOT = Path(__file__).resolve().parent
BREWS_PER_DAY = (8, 10, 12, 14)
BOIL_WINDOW_H = (1.0, 1.25, 1.5)
HTHP = "HTHP (wort boiling)"
WARM_WATER = "Warm-water HP"


def check(case_file: Path) -> pd.DataFrame:
    case = load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json")
    unit = streams.energy_unit
    rows = []
    for n in BREWS_PER_DAY:
        for t in BOIL_WINDOW_H:
            util = n * t / 24
            F = 1 / util
            a = answers(apply(case, "econ", {"heat_pump_capacity_factors": {HTHP: F}}, selected), streams, unit, selected)
            names = unit_names(a)
            ht, ww = f"HP{names.index(HTHP) + 1}", f"HP{names.index(WARM_WATER) + 1}"
            rows.append({"brews_per_day": n, "boil_window_h": t, "HTHP_utilisation": round(util, 3),
                         "capacity_factor_F": round(F, 2), "HTHP_incremental_payback_y": a[f"{ht}_incremental_payback_y"],
                         "HTHP_incremental_NPV_MEUR": a[f"{ht}_incremental_NPV_MEUR"], "RQ3_ratio_HTHP": a[f"RQ3_ratio_{ht}"],
                         "RQ1_HP_gas_share": a["RQ1_HP_gas_share"], "WW_HP_incremental_payback_y": a[f"{ww}_incremental_payback_y"],
                         "RQ3_ratio_WW_HP": a[f"RQ3_ratio_{ww}"]})
    return pd.DataFrame(rows)


def markdown(df: pd.DataFrame) -> str:
    fmt = lambda x: "none" if x <= 0 else f"{x:.2f}"  # noqa: E731
    lines = ["| Brews/day | Boil window [h] | HTHP utilisation | F | HTHP payback | HTHP NPV₁₀ [M€] | HTHP break-even ratio | "
             "RQ1 (HP share) | WW HP payback | WW HP break-even ratio |", "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        pb = r["HTHP_incremental_payback_y"]
        lines.append(f"| {int(r['brews_per_day'])} | {r['boil_window_h']:g} | {100 * r['HTHP_utilisation']:.0f} % | "
                     f"{r['capacity_factor_F']:.2f} | {'never' if pb == float('inf') else f'{pb:.0f} y'} | "
                     f"{r['HTHP_incremental_NPV_MEUR']:+.2f} | {fmt(r['RQ3_ratio_HTHP'])} | {100 * r['RQ1_HP_gas_share']:.1f} % | "
                     f"{r['WW_HP_incremental_payback_y']} y | {fmt(r['RQ3_ratio_WW_HP'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    case = load_case(args.case_file)
    df = check(args.case_file)
    out = ROOT / "outputs" / case.name
    df.to_csv(out / "batch_check.csv", index=False)
    text = markdown(df)
    (out / "batch_check.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
