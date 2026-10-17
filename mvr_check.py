"""Configuration 3 of Padullés et al. (2026): MVR for wort boiling (supervisor review B4).

Usage:
    python mvr_check.py cases/brewery.json

Compares, as increments over the site with the heat-recovery retrofit N1 and the warm-water heat pump
(residual gas 3.0 kWh/hl: wort preheating 95 -> 100 °C, 0.6, and boiling, 2.4):

* Config. 2 (step 5): one HTHP, isothermal sink 103 °C, 3.0 kWh/hl.
* Config. 3 (Padullés Sec. 4.3.3, Figs. 16-17): an MVR recompresses the boil-off vapour to boil the wort
  (2.4 kWh/hl). The vapour no longer reaches the Pfaduko, so the wort preheating 75 -> 100 °C (3.0 kWh/hl)
  must be supplied: 75 -> 82 °C from the heat-recovery tank (the warm-water heat pump grows by 0.84 kWh/hl)
  and 82 -> 100 °C by a booster heat pump (2.16 kWh/hl, gliding sink, source -1 °C as the HTHP). The
  sensible heat of the MVR condensate (about 0.1 kWh/hl) is neglected.

MVR model (CoolProp, water): saturated vapour at 100 °C compressed to the saturation pressure of
100 °C + lift, isentropic efficiency 70 %, heat loss 5 % of the shaft work, motor 95 % (the assumptions of
Andersen et al. 2024 used in step 4b); delivered heat = condensing the compressed vapour to saturated liquid.
Lift 10 K (central), 5-15 K range: the paper's MVR COP of 15 corresponds to about 16 K. Costs: Padullés
Table 3 (MVR 280,000 + 350 EUR/kW; heat pump 520,000 + 600 EUR/kW) with DEA O&M (sheets 4 and 2.a). The
MVR (about 300 kW) lies below the DEA sheet-4 range (5-50 MW). The booster and the MVR only run in the
boil window: capacity factor F applies to both (batch_check.py).

Writes outputs/<case>/mvr_check.csv and .md.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import CoolProp.CoolProp as CP
import pandas as pd

from pinch import load_streams, with_extra_shift
from pinch.case import load_case
from pinch.design import design_from_gcc
from pinch.economic_analysis import _params_and_converter
from pinch.economics import CostFunction, Option, break_even_ratio, capacity_kW, evaluate
from pinch.heat_pump import lorenz_cop

ROOT = Path(__file__).resolve().parent
RESIDUAL_GAS = 3.0      # kWh/hl after N1 + warm-water heat pump (retrofit table)
BOIL, PREHEAT_TANK, PREHEAT_BOOST = 2.4, 0.84, 2.16   # kWh/hl: boiling; 75 -> 82 °C; 82 -> 100 °C (CP 0.12 kWh/hl K)


def mvr_cop(lift_K: float, T_C: float = 100.0, eta_is: float = 0.70, f_loss: float = 0.05, eta_motor: float = 0.95):
    """(COP, pressure ratio) of an open MVR on saturated water vapour at T_C."""
    p1 = CP.PropsSI("P", "T", T_C + 273.15, "Q", 1, "Water")
    h1, s1 = CP.PropsSI("H", "P", p1, "Q", 1, "Water"), CP.PropsSI("S", "P", p1, "Q", 1, "Water")
    p2 = CP.PropsSI("P", "T", T_C + lift_K + 273.15, "Q", 0, "Water")
    w = (CP.PropsSI("H", "P", p2, "S", s1, "Water") - h1) / eta_is
    q = h1 + w * (1 - f_loss) - CP.PropsSI("H", "P", p2, "Q", 0, "Water")
    return q / (w / eta_motor), p2 / p1


def check(case_file: Path) -> pd.DataFrame:
    case = load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    unit = streams.energy_unit
    _, params, to_MWh = _params_and_converter(case, unit)
    eta, src = case.eta_lorenz, case.source_T_C
    d = design_from_gcc(streams, case.sink_levels, eta, src)
    ww = next(u for u in d.units if "Warm" in u.name)
    cop_hthp = lorenz_cop(103, 103, src, src, eta)
    cop_boost = lorenz_cop(82, 100, src, src, eta)
    # extra warm-water capacity: marginal investment only (the unit exists) and its O&M
    hp = params.cost_functions["heat_pump"]
    costs = dict(params.cost_functions)
    costs["ww_extra"] = CostFunction(hp.alpha, 0.0, 1.0, "kW", hp.fixed_om_EUR_per_unit_year, hp.variable_om_EUR_per_MWh)
    p = replace(params, cost_functions=costs)
    kW = lambda q: capacity_kW(to_MWh(q), p)  # noqa: E731
    base = Option("N1 + warm-water heat pump", to_MWh(RESIDUAL_GAS), 0.0)
    rows = []
    for F in (1.0, 1.75):
        cfg2 = Option("config. 2: HTHP 103 °C", 0.0, to_MWh(RESIDUAL_GAS / cop_hthp),
                      (("heat_pump", kW(RESIDUAL_GAS)), ("lump_sum_EUR", hp.cost(kW(RESIDUAL_GAS) * F) - hp.cost(kW(RESIDUAL_GAS)))))
        mvr = p.cost_functions["mvr"]
        options = [(cfg2, f"COP {cop_hthp:.2f}")]
        for lift in (5.0, 10.0, 15.0):
            cop_mvr, pr = mvr_cop(lift)
            cfg3 = Option(f"config. 3: MVR ({lift:g} K) + booster", 0.0,
                          to_MWh(BOIL / cop_mvr + PREHEAT_BOOST / cop_boost + PREHEAT_TANK / ww.COP),
                          (("mvr", kW(BOIL)), ("lump_sum_EUR", mvr.cost(kW(BOIL) * F) - mvr.cost(kW(BOIL))),
                           ("heat_pump", kW(PREHEAT_BOOST)), ("lump_sum_EUR", hp.cost(kW(PREHEAT_BOOST) * F) - hp.cost(kW(PREHEAT_BOOST))),
                           ("ww_extra", kW(PREHEAT_TANK))))
            options.append((cfg3, f"MVR COP {cop_mvr:.1f} (pressure ratio {pr:.2f}), booster COP {cop_boost:.2f}"))
        for o, cop_note in options:
            ev = evaluate(o, base, p)
            rows.append({"option": o.name, "capacity_factor_F": F, "COPs": cop_note,
                         "electricity_kWh_per_hl": round(o.electricity_MWh / to_MWh(1.0), 3),
                         "capex_EUR": round(ev.capex_EUR, 0), "savings_EUR": round(ev.savings_EUR, 0),
                         "payback_years": round(ev.payback_years, 1) if ev.payback_years != float("inf") else ev.payback_years,
                         "npv_EUR": round(ev.npv_EUR, 0), "break_even_ratio_NPV": round(break_even_ratio(o, base, p), 3)})
    return pd.DataFrame(rows)


def markdown(df: pd.DataFrame) -> str:
    lines = ["| Option | F | COPs | Electricity [kWh/hl] | Investment [k€] | Savings [k€/y] | Payback | NPV₁₀ [M€] | "
             "Break-even ratio |", "|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        pb = "never" if r["payback_years"] == float("inf") else f"{r['payback_years']:g} y"
        be = "none" if r["break_even_ratio_NPV"] <= 0 else f"{r['break_even_ratio_NPV']:.2f}"
        lines.append(f"| {r['option']} | {r['capacity_factor_F']:g} | {r['COPs']} | {r['electricity_kWh_per_hl']:.2f} | "
                     f"{r['capex_EUR'] / 1e3:,.0f} | {r['savings_EUR'] / 1e3:+,.1f} | {pb} | {r['npv_EUR'] / 1e6:+.2f} | {be} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    case = load_case(args.case_file)
    df = check(args.case_file)
    out = ROOT / "outputs" / case.name
    df.to_csv(out / "mvr_check.csv", index=False)
    text = markdown(df)
    (out / "mvr_check.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
