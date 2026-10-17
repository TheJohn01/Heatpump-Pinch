"""Consolidated answers to the three research questions, with sensitivities.

Usage:
    python consolidate_rq.py cases/brewery_padulles2026.json

Definitions (against the site as it is today, i.e. the case's baseline network, step 5; supervisor
review 2026-10-17, items A1-A4):

* RQ1: share of today's gas use that the heat pumps replace with an INCREMENTAL simple payback <= the
  threshold (5 years) over the heat-recovery-only retrofit (``retrofit.heat_pump_reference``), searched
  along the electrification curve (partial duty, highest-COP unit first). The heat-recovery retrofit is
  reported separately (its own share and payback), so it does not carry the heat pumps. One denominator:
  today's gas.
* RQ2: ΔTmin minimising the total annual cost with the installed cost law, reported with the range of
  ΔTmin over which the total cost stays within 1 % of the minimum (the optimum is flat).
* RQ3: electricity-to-gas price ratio at which the NPV of each heat pump's increment is zero, per unit
  (``retrofit.heat_pump_increments``): warm-water heat pump over the heat-recovery retrofit; HTHP over
  the warm-water heat pump. The "full electrification" ratio is a capacity-weighted mix of both and is
  kept for information only.

Each sensitivity row changes one input from the base case. The rows are the case file's
``sensitivities`` list, the only sensitivity list of the case (``pinch.sensitivity``; the
grass-roots table of step 6 reads its "econ" rows). The source of each value is in the
"basis" column. Writes outputs/<case>/rq_consolidated.csv, .md and rq_tornado.png.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path

import pandas as pd

from pinch import load_streams, with_extra_shift
from pinch.area_analysis import area_targeting_outputs
from pinch.case import Case, display_name, load_case
from pinch.cycle_analysis import load_selected
from pinch.economic_analysis import _params_and_converter
from pinch.plotting import save_figure, tornado_figure
from pinch.retrofit import run_retrofit
from pinch.sensitivity import apply

ROOT = Path(__file__).resolve().parent

def answers(case: Case, streams, unit: str, selected: dict | None, source_limited: bool = False) -> dict:
    """RQ1, RQ2, RQ3 for one case variant (definitions in the module docstring).

    ``source_limited``: no ambient heat source (supervisor review B2). The warm-water heat pump may only take
    the refrigeration duty as its source, so its heat is capped at refrigeration / (1 - 1/COP); the HTHP,
    whose source would be ambient, is excluded."""
    params = _params_and_converter(case, unit)[1]
    case_nc = replace(case, retrofit={**case.retrofit,
                                      "options": [o for o in case.retrofit["options"] if not o.get("cycle_based")]})
    r = run_retrofit(case_nc, streams, unit, params, selected)
    r.close_figures()
    opts = {o["option"]: o for o in r.summary["options"]}
    ref = opts.get(case.retrofit.get("heat_pump_reference"))
    rq1 = r.summary["RQ1_vs_existing_site"]
    inc = {i["increment"]: i for i in r.summary.get("increments", [])}
    ww = next((v for k, v in inc.items() if "warm" in k.lower()), None)
    ht = next((v for k, v in inc.items() if "hthp" in k.lower()), None)
    # stacked per unit, so one unit never carries another (A2): the warm-water heat pump at its best partial
    # duty with incremental payback <= threshold over the heat-recovery retrofit, plus the HTHP only if its
    # own increment over the warm-water heat pump also pays back within the threshold
    thr = params.payback_threshold_years
    ww_curve = next((v for k, v in rq1.items() if ww and k == ww["option"]), {})
    hp_share = ww_curve.get("heat_pump_share_incremental_payback_ok", 0.0)
    if ht and ht["payback_years"] <= thr and hp_share >= (ww["gas_share_of_today"] if ww else 0) - 1e-9:
        hp_share += ht["gas_share_of_today"]
    if source_limited and ww:
        from pinch.retrofit import _slug
        o = opts[ww["option"]]
        u = o["units"][0]
        cap = o["refrigeration"] / (1 - 1 / u["COP"])            # heat the refrigeration source can supply
        cv = r.tables[f"retrofit_curve_{_slug(ww['option'])}"]
        pts = cv[cv["heat_pump_heat"] <= cap + 1e-9]
        at_cap = pts.iloc[-1]
        ok = pts[(pts["incremental_payback_years"] <= thr) & (pts["hp_gas_share_of_today"] > 0)]
        hp_share = float(ok["hp_gas_share_of_today"].max()) if len(ok) else 0.0
        ww = {**ww, "payback_years": round(float(at_cap["incremental_payback_years"]), 2),
              "delta_npv_EUR": float(at_cap["incremental_npv_EUR"]), "break_even_ratio_NPV": math.nan,
              "co2_avoided_t": math.nan}
        ht = None
    full = max((o for o in opts.values() if o["Qh_residual"] < 1e-6),
               key=lambda o: o["gas_reduction_vs_baseline"] - 1e-9 * o["capex_EUR"])
    at = area_targeting_outputs(case, streams)
    at.close_figures()
    law = next((x for x in at.summary.get("RQ2", []) if "installed" in x["cost_law"]), None)
    nan = math.nan
    return {
        "RQ1_HP_gas_share": round(hp_share, 4),
        "WW_HP_incremental_payback_y": ww["payback_years"] if ww else nan,
        "WW_HP_incremental_NPV_MEUR": round(ww["delta_npv_EUR"] / 1e6, 3) if ww else nan,
        "WW_HP_CO2_avoided_t": ww.get("co2_avoided_t", nan) if ww else nan,
        "HTHP_incremental_payback_y": ht["payback_years"] if ht else nan,
        "HTHP_incremental_NPV_MEUR": round(ht["delta_npv_EUR"] / 1e6, 3) if ht else nan,
        "HR_retrofit_gas_share": ref["gas_reduction_vs_baseline"] if ref else nan,
        "HR_retrofit_payback_y": ref["payback_years"] if ref else nan,
        "RQ2_dTmin_opt_K": law["dTmin_opt_K"] if law else nan,
        "RQ2_dTmin_within_1pct_K": f"{law['dTmin_within_1pct_K'][0]:g}-{law['dTmin_within_1pct_K'][1]:g}" if law else "",
        "RQ3_ratio_WW_HP": ww["break_even_ratio_NPV"] if ww else nan,
        "RQ3_ratio_HTHP": ht["break_even_ratio_NPV"] if ht else nan,
        "RQ3_ratio_full_electrification_info": full["break_even_ratio_NPV"],
        "full_electrification_payback_y": full["payback_years"], "full_electrification_NPV_MEUR": round(full["npv_EUR"] / 1e6, 3),
        "price_ratio": round(params.price_ratio, 3),
    }


def hp_hot_utility_cost(case: Case, streams, unit: str) -> float:
    """Annual cost of 1 kW of hot utility supplied by the top heat pump (HTHP) instead of gas [EUR/(kW year)]:
    electricity at the HTHP's COP, variable and fixed O&M, and the annualised marginal investment (alpha of
    the heat pump cost function; the fixed term beta does not scale with ΔTmin). Its source is ambient at the
    margin (the warm-water heat pump already takes over the refrigeration)."""
    from pinch.design import design_from_gcc
    params = _params_and_converter(case, unit)[1]
    d = design_from_gcc(streams, case.sink_levels, case.eta_lorenz, case.source_T_C)
    top = max(d.units, key=lambda u: u.T_sink_out_C)
    cf = params.cost_functions[params.heat_pump_cost_items(top)[0][0]]
    h = params.operating_hours_per_year
    return (h * (params.electricity_price_EUR_per_kWh / top.COP + cf.variable_om_EUR_per_MWh / 1000)
            + cf.alpha / params.annuity_factor + cf.fixed_om_EUR_per_unit_year)


def production_threshold(case: Case, streams, unit: str, selected: dict | None, target_y: float = 5.0) -> dict:
    """Production [per year] above which the warm-water heat pump's incremental payback is <= target (A3);
    bisection between 0.1 and 3 times the case's production. Also reports whether the HTHP increment pays
    back within the target anywhere in that range."""
    base = case.basis["production_per_year"]

    def pb(x):
        a = answers(apply(case, "scale", x, selected), streams, unit, selected)
        return a["WW_HP_incremental_payback_y"], a["HTHP_incremental_payback_y"]

    lo, hi = 0.1 * base, 3.0 * base
    if pb(hi)[0] > target_y:
        return {"threshold": None, "note": "warm-water heat pump above the target even at 3x production"}
    if pb(lo)[0] <= target_y:
        return {"threshold": lo, "note": "warm-water heat pump within the target down to 0.1x production"}
    for _ in range(18):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if pb(mid)[0] <= target_y else (mid, hi)
    return {"threshold": round(hi, -3), "HTHP_payback_at_3x_y": pb(3.0 * base)[1]}


def consolidate(case_file: Path) -> pd.DataFrame:
    """Consolidated table for a case file (cycle screening read from outputs/<case>/)."""
    case = load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json")
    df = consolidate_case(case, streams, selected)
    df.loc[0, "basis"] = "sourced inputs (see sources_case_studies.md)"
    return df


def consolidate_case(case: Case, streams, selected: dict | None) -> pd.DataFrame:
    """Consolidated table for a case already in memory (used by the app for edited inputs)."""
    if not case.retrofit or case.basis is None:
        raise ValueError("the consolidated table needs a retrofit block and an annual basis")
    unit = streams.energy_unit
    rows = [{"sensitivity": "Base case", "basis": "current inputs",
             **answers(case, streams, unit, selected)}]
    c_hp = hp_hot_utility_cost(case, streams, unit)
    rows.append({"sensitivity": "No ambient source: heat pumps limited to the refrigeration heat",
                 "basis": "the base case draws part of the heat pumps' source from ambient air evaporating at -1 °C "
                          "(frosting, defrost and air-coil costs not included); here only the refrigeration duty is "
                          "a source (supervisor review B2)",
                 **answers(case, streams, unit, selected, source_limited=True)})
    for sens in case.sensitivities:
        kind, value, basis = sens.kind, sens.value, sens.basis
        if kind == "hp_hot_utility":
            kind, value = "area", {"hot_utility_cost_EUR_per_kW_year": c_hp}
            basis = f"{basis}: {c_hp:.0f} EUR/(kW year)"
        if sens.uses_cycle_screening and not selected:
            continue
        rows.append({"sensitivity": sens.label, "basis": basis,
                     **answers(apply(case, kind, value, selected), streams, unit, selected)})
    return pd.DataFrame(rows)


def _f(x, fmt="{:.2f}", unit=""):
    """Number for the table: 'never' for an infinite payback, 'none' for a break-even ratio <= 0."""
    if isinstance(x, float) and math.isinf(x):
        return "never"
    if x != x:
        return "n/a"
    if unit == "ratio" and x <= 0:
        return "none"
    return fmt.format(x) + unit if unit != "ratio" else fmt.format(x)


def _markdown(df: pd.DataFrame, threshold: float, prod: dict | None = None) -> str:
    lines = []
    if prod:
        t = prod.get("threshold")
        lines += [f"RQ1 condition (A3): the warm-water heat pump's incremental payback is ≤ {threshold:g} years above "
                  f"about {t / 1e6:.2f} Mhl/year" if t else f"RQ1 condition: {prod.get('note', '')}",
                  f"(HTHP increment at 3x production: payback {_f(prod.get('HTHP_payback_at_3x_y', math.nan), unit=' y')}).", ""]
    lines += ["| Sensitivity | RQ1: heat-pump share of today's gas, incremental payback ≤ 5 y | Warm-water HP: "
              "payback / NPV₁₀ | HTHP: payback / NPV₁₀ | Heat-recovery retrofit: share / payback | RQ2: ΔTmin,opt "
              "(within 1 %) [K] | RQ3 per unit: WW HP / HTHP | WW HP CO₂ avoided [t/y] | Current ratio | Basis |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        lines.append(f"| {r['sensitivity']} | {100 * r['RQ1_HP_gas_share']:.1f} % | "
                     f"{_f(r['WW_HP_incremental_payback_y'], unit=' y')} / {_f(r['WW_HP_incremental_NPV_MEUR'], '{:+.2f}', ' M€')} | "
                     f"{_f(r['HTHP_incremental_payback_y'], '{:.0f}', ' y')} / {_f(r['HTHP_incremental_NPV_MEUR'], '{:+.2f}', ' M€')} | "
                     f"{100 * r['HR_retrofit_gas_share']:.1f} % / {_f(r['HR_retrofit_payback_y'], unit=' y')} | "
                     f"{r['RQ2_dTmin_opt_K']:g} ({r['RQ2_dTmin_within_1pct_K']}) | "
                     f"{_f(r['RQ3_ratio_WW_HP'], unit='ratio')} / {_f(r['RQ3_ratio_HTHP'], unit='ratio')} | "
                     f"{_f(r['WW_HP_CO2_avoided_t'], '{:,.0f}')} | {r['price_ratio']:.2f} | {r['basis']} |")
    return "\n".join(lines) + "\n"


def _tornado(df: pd.DataFrame, path: Path, title: str) -> None:
    """Break-even ratio of the warm-water heat pump's increment (the unit that answers RQ1)."""
    save_figure(tornado_figure(df, "RQ3_ratio_WW_HP", title,
                               "Break-even price ratio, warm-water heat pump increment (NPV = 0) [-]"), path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    case = load_case(args.case_file)
    df = consolidate(args.case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json")
    prod = production_threshold(case, streams, streams.energy_unit, selected)
    out = ROOT / "outputs" / case.name
    df.to_csv(out / "rq_consolidated.csv", index=False)
    (out / "rq1_production_threshold.json").write_text(json.dumps(prod, indent=2), encoding="utf-8")
    (out / "rq_consolidated.md").write_text(_markdown(df, 5.0, prod), encoding="utf-8")
    _tornado(df, out / "rq_tornado.png", f"RQ3, warm-water heat pump: {display_name(case.name)} (base {df.iloc[0]['RQ3_ratio_WW_HP']:.2f})")
    print(_markdown(df, 5.0, prod))


if __name__ == "__main__":
    main()
