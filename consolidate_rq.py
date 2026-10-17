"""Consolidated answers to the three research questions, with sensitivities, for any case.

Usage:
    python consolidate_rq.py cases/brewery.json
    python consolidate_rq.py cases/spray_dryer.json

RQ1-RQ3 are defined once, in ``pinch.research_questions``: against the site as it is today (the
case's existing network, or the baseline its ``retrofit_bounds`` status implies), with the heat
pumps judged as increments HP1, HP2, ... (decreasing COP) over the heat-recovery step.

Each sensitivity row changes one input from the base case. The rows are the case file's
``sensitivities`` list, the only sensitivity list of the case (``pinch.sensitivity``; the
grass-roots table of step 6 reads its "econ" rows). The source of each value is in the
"basis" column. Writes outputs/<case>/rq_consolidated.csv, .md and rq_tornado.png (and, for a
per-product basis, rq1_production_threshold.json). A case needs an annual basis.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from pinch import load_streams, with_extra_shift
from pinch.case import Case, load_case
from pinch.cycle_analysis import load_selected
from pinch.economic_analysis import _params_and_converter
from pinch.plotting import save_figure, tornado_figure
from pinch import research_questions as rq
from pinch.sensitivity import apply

ROOT = Path(__file__).resolve().parent

def answers(case: Case, streams, unit: str, selected: dict | None = None, source_limited: bool = False) -> dict | None:
    """RQ1, RQ2, RQ3 for one case variant (``pinch.research_questions.answers``).

    ``selected`` is not used here: cycle-based rows set their Lorenz efficiencies before (``pinch.sensitivity``).
    """
    return rq.answers(case, streams, _params_and_converter(case, unit)[1], source_limited=source_limited)


def hp_hot_utility_cost(case: Case, streams, unit: str) -> float | None:
    """Annual cost of 1 kW of hot utility supplied by the top heat pump instead of gas [EUR/(kW year)]:
    electricity at its COP, variable and fixed O&M, and the annualised marginal investment (alpha of the
    heat pump cost function; the fixed term beta does not scale with ΔTmin). Its source is ambient at the
    margin (a lower unit already takes over the refrigeration). None if no heat pump is designed."""
    from pinch.design import design_from_gcc
    params = _params_and_converter(case, unit)[1]
    d = design_from_gcc(streams, case.sink_levels, case.eta_lorenz, case.source_T_C)
    if not d.units:
        return None
    top = max(d.units, key=lambda u: u.T_sink_out_C)
    cf = params.cost_functions[params.heat_pump_cost_items(top)[0][0]]
    h = params.operating_hours_per_year
    return (h * (params.electricity_price_EUR_per_kWh / top.COP + cf.variable_om_EUR_per_MWh / 1000)
            + cf.alpha / params.annuity_factor + cf.fixed_om_EUR_per_unit_year)


def production_threshold(case: Case, streams, unit: str, selected: dict | None, target_y: float = 5.0) -> dict | None:
    """Production [per year] above which HP1's incremental payback is <= target (A3); bisection between 0.1
    and 3 times the case's production. Also reports the last unit's payback at 3x production. None unless
    the case has a per-product basis (production is then a case input)."""
    if not case.basis or case.basis.get("type") != "per_product":
        return None
    base = case.basis["production_per_year"]

    def pb(x):
        a = answers(apply(case, "scale", x, selected), streams, unit, selected)
        n = len(rq.unit_names(a))
        return a.get("HP1_incremental_payback_y", math.inf), a.get(f"HP{n}_incremental_payback_y", math.nan)

    lo, hi = 0.1 * base, 3.0 * base
    if pb(hi)[0] > target_y:
        return {"threshold": None, "note": "HP1 above the target even at 3x production"}
    if pb(lo)[0] <= target_y:
        return {"threshold": lo, "note": "HP1 within the target down to 0.1x production"}
    for _ in range(18):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if pb(mid)[0] <= target_y else (mid, hi)
    return {"threshold": round(hi, -3), "last_unit_payback_at_3x_y": pb(3.0 * base)[1]}


def consolidate(case_file: Path | Case) -> pd.DataFrame:
    """Consolidated table for a case file or loaded case (cycle screening read from outputs/<case>/)."""
    case = case_file if isinstance(case_file, Case) else load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json")
    df = consolidate_case(case, streams, selected)
    df.loc[0, "basis"] = "sourced inputs (see sources_case_studies.md)"
    return df


def consolidate_case(case: Case, streams, selected: dict | None) -> pd.DataFrame:
    """Consolidated table for a case already in memory (used by the app for edited inputs)."""
    if case.basis is None:
        raise ValueError("the consolidated table needs an annual basis (Workflow, step 1)")
    unit = streams.energy_unit
    rows = [{"sensitivity": "Base case", "basis": "current inputs",
             **answers(case, streams, unit, selected)}]
    c_hp = hp_hot_utility_cost(case, streams, unit)
    limited = answers(case, streams, unit, selected, source_limited=True)
    if limited is not None:
        rows.append({"sensitivity": "No ambient source: heat pumps limited to the refrigeration heat",
                     "basis": "the base case may draw part of the heat pumps' source from ambient air (frosting, "
                              "defrost and air-coil costs not included); here HP1 takes only the refrigeration duty "
                              "as its source and the other units are left out (supervisor review B2)",
                     **limited})
    for sens in case.sensitivities:
        kind, value, basis = sens.kind, sens.value, sens.basis
        if kind == "hp_hot_utility":
            if c_hp is None:
                continue
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
    base = df.iloc[0]
    names = rq.unit_names(base)
    lines = [f"Today's site: {base['todays_site']}.",
             "Heat pumps (decreasing COP): " + "; ".join(f"HP{i} = {n}" for i, n in enumerate(names, 1)) + ".", ""]
    if prod:
        t = prod.get("threshold")
        lines += [f"RQ1 condition (A3): HP1's incremental payback is ≤ {threshold:g} years above about "
                  f"{t / 1e6:.2f} M units/year" if t else f"RQ1 condition: {prod.get('note', '')}",
                  f"(HP{len(names)} increment at 3x production: payback "
                  f"{_f(prod.get('last_unit_payback_at_3x_y', math.nan), unit=' y')}).", ""]
    hp_cols = " | ".join(f"HP{i}: payback / NPV" for i in range(1, len(names) + 1))
    lines += [f"| Sensitivity | RQ1: heat-pump share of today's gas, incremental payback ≤ {threshold:g} y | {hp_cols} | "
              "Heat-recovery step: share / payback | RQ2: ΔTmin,opt (within 1 %) [K] | RQ3 per unit | "
              "HP1 CO₂ avoided [t/y] | Current ratio | Basis |",
              "|---|---|" + "---|" * len(names) + "---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        hp = " | ".join(f"{_f(r.get(f'HP{i}_incremental_payback_y', math.nan), unit=' y')} / "
                        f"{_f(r.get(f'HP{i}_incremental_NPV_MEUR', math.nan), '{:+.2f}', ' M€')}"
                        for i in range(1, len(names) + 1))
        ratios = " / ".join(_f(r.get(f"RQ3_ratio_HP{i}", math.nan), unit="ratio") for i in range(1, len(names) + 1))
        hr = (f"{100 * r['HR_retrofit_gas_share']:.1f} % / {_f(r['HR_retrofit_payback_y'], unit=' y')}"
              if r["HR_retrofit_gas_share"] == r["HR_retrofit_gas_share"] else "none (site at target)")
        rq2 = f"{r['RQ2_dTmin_opt_K']:g} ({r['RQ2_dTmin_within_1pct_K']})" if r["RQ2_dTmin_opt_K"] == r["RQ2_dTmin_opt_K"] \
            else "n/a"
        lines.append(f"| {r['sensitivity']} | {100 * r['RQ1_HP_gas_share']:.1f} % | {hp} | {hr} | {rq2} | {ratios} | "
                     f"{_f(r.get('HP1_CO2_avoided_t', math.nan), '{:,.0f}')} | {r['price_ratio']:.2f} | {r['basis']} |")
    return "\n".join(lines) + "\n"


def _tornado(df: pd.DataFrame, path: Path, title: str) -> None:
    """Break-even ratio of HP1's increment (the unit that answers RQ1)."""
    save_figure(tornado_figure(df, "RQ3_ratio_HP1", title,
                               f"Break-even price ratio, {df.iloc[0]['HP1_name']} increment (NPV = 0) [-]"), path)


def write_consolidated(case: Case, output_dir: Path | None = None) -> pd.DataFrame:
    """Compute and write the consolidated table, its Markdown, the tornado and the production threshold."""
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json")
    df = consolidate(case)
    prod = production_threshold(case, streams, streams.energy_unit, selected)
    out = output_dir if output_dir is not None else ROOT / "outputs" / case.name
    out.mkdir(parents=True, exist_ok=True)
    thr = _params_and_converter(case, streams.energy_unit)[1].payback_threshold_years
    df.to_csv(out / "rq_consolidated.csv", index=False)
    if prod is not None:
        (out / "rq1_production_threshold.json").write_text(json.dumps(prod, indent=2), encoding="utf-8")
    (out / "rq_consolidated.md").write_text(_markdown(df, thr, prod), encoding="utf-8")
    _tornado(df, out / "rq_tornado.png", f"RQ3, {df.iloc[0]['HP1_name']}: {case.plant} (base {df.iloc[0]['RQ3_ratio_HP1']:.2f})")
    print(_markdown(df, thr, prod))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    write_consolidated(load_case(args.case_file))


if __name__ == "__main__":
    main()
