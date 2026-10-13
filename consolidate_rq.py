"""Consolidated answers to the three research questions, with sensitivities.

Usage:
    python consolidate_rq.py cases/brewery_padulles2026.json

Definitions (all against the site as it is today, i.e. the case's baseline
network, step 5):

* RQ1: largest share of today's gas use that heat recovery and heat pumps can
  replace with a simple payback <= the threshold (5 years). Searched over the
  retrofit options and their electrification curves (partial heat pump duty,
  highest-COP unit first). Options flagged "cycle_based" are a variant of the
  COP model and are excluded here (they are a sensitivity row instead).
* RQ2: ΔTmin minimising the total annual cost (supertargeting) with the
  case's primary installed cost law (the law whose label contains
  "installed").
* The warm-water heat pump is also judged on its own: payback of its
  increment over the heat-recovery-only retrofit (so the cheap recovery
  measure does not carry it).
* RQ3: electricity-to-gas price ratio at which NPV = 0, (a) for full
  electrification (retrofit + all heat pumps) and (b) for the RQ1 option.

Each sensitivity row changes one input from the base case; the source of each
range is in the "basis" column. Writes outputs/<case>/rq_consolidated.csv,
.md and rq_tornado.png.
"""

from __future__ import annotations

import argparse
import copy
import math
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from pinch import load_streams, with_extra_shift
from pinch.area_analysis import area_targeting_outputs
from pinch.case import Case, load_case
from pinch.cycle_analysis import load_selected
from pinch.economic_analysis import _params_and_converter
from pinch.retrofit import run_retrofit

ROOT = Path(__file__).resolve().parent

#: (row label, kind, value, basis). kind: "econ" = economics overrides; others handled in _apply.
SENSITIVITIES = [
    ("Prices 2025-S1 (0.1230 / 0.0546; ratio 2.25)", "econ",
     {"electricity_price_EUR_per_kWh": 0.1230, "gas_price_EUR_per_kWh": 0.0546}, "Eurostat, bands ID / I3, excl. VAT"),
    ("Prices 2025-S2 (0.1216 / 0.0481; ratio 2.53)", "econ",
     {"electricity_price_EUR_per_kWh": 0.1216, "gas_price_EUR_per_kWh": 0.0481}, "Eurostat, bands ID / I3, excl. VAT"),
    ("Electricity band IE (0.0897; ratio 1.75)", "econ", {"electricity_price_EUR_per_kWh": 0.0897},
     "Eurostat 2026-S1; IE applies above 20 GWh/year"),
    ("Boiler efficiency 0.817", "econ", {"boiler_efficiency": 0.817}, "US DOE Steam Tip Sheet #15"),
    ("Boiler efficiency 0.929", "econ", {"boiler_efficiency": 0.929}, "implied by Padullés App. B (DK1)"),
    ("Boiler efficiency 1.0 (bound)", "econ", {"boiler_efficiency": 1.0}, "as in Padullés Sec. 5"),
    ("No refrigeration credit", "econ", {"chiller_cop": None}, "as in Padullés et al. (2026)"),
    ("Chiller COP 3.14", "econ", {"chiller_cop": 3.14}, "Sinnott & Towler Example 6.7 (cooling water 40 °C)"),
    ("Chiller COP 6.68", "econ", {"chiller_cop": 6.68}, "Sinnott & Towler: 0.9 x Carnot (complex cycles)"),
    ("CO2 price 82.4 EUR/t", "econ", {"co2_price_EUR_per_t": 82.4}, "EUA, 5 Oct 2026"),
    ("Horizon 20 years", "econ", {"horizon_years": 20}, "DEA sheet 2.a: HTHP technical lifetime 20 y"),
    ("Lorenz efficiency 0.45", "eta", 0.45, "DEA HTHP data, implied 0.45-0.52"),
    ("Lorenz efficiency 0.63", "eta", 0.63, "Andersen et al. (2024) polynomial, HTHP"),
    ("Cycle-based COP per unit", "cycle", None, "CoolProp screening (step 4b)"),
    ("Heat pump CAPEX -25 %", "hp_capex", 0.75, "DEA sheet 2.a: 0.9-1.5 vs 1.2 MEUR/MW"),
    ("Heat pump CAPEX +25 %", "hp_capex", 1.25, "DEA sheet 2.a: 0.9-1.5 vs 1.2 MEUR/MW"),
    ("Retrofit exchanger CAPEX x3", "hx_capex", 3.0, "stress test"),
    ("Production 0.25 Mhl/year", "scale", 0.25e6, "Padullés Table 1 range (UK case)"),
    ("Production 0.5 Mhl/year", "scale", 0.5e6, "Padullés Table 1 range"),
    ("Production 1.5 Mhl/year", "scale", 1.5e6, "Padullés Table 1 range (TH case)"),
    ("Combined: Padullés conventions (boiler 1.0, no refrigeration credit)", "combo",
     [("econ", {"boiler_efficiency": 1.0, "chiller_cop": None})], "Padullés et al. (2026), Sec. 5"),
    ("Combined pessimistic: no credit, cycle-based COP, HP CAPEX +25 %", "combo",
     [("econ", {"chiller_cop": None}), ("cycle", None), ("hp_capex", 1.25)], "one-at-a-time ranges above, together"),
]


def _apply(case: Case, kind: str, value, selected: dict | None) -> Case:
    if kind == "combo":
        for k, v in value:
            case = _apply(case, k, v, selected)
        return case
    if kind == "econ":
        eco = {**case.economics, **value}
        return replace(case, economics=eco)
    if kind == "eta":
        return replace(case, eta_lorenz=float(value),
                       sink_levels=tuple(replace(lv, eta_lorenz=None) for lv in case.sink_levels))
    if kind == "cycle":
        return replace(case, sink_levels=tuple(replace(lv, eta_lorenz=selected[lv.name]["eta_lorenz_cycle"])
                                               if lv.name in selected else lv for lv in case.sink_levels))
    if kind in ("hp_capex", "hx_capex"):
        key = "heat_pump" if kind == "hp_capex" else "plate_hex"
        cf = copy.deepcopy(case.economics.get("cost_functions", {}))
        from pinch.economics import DEFAULT_COST_FUNCTIONS
        base = {**DEFAULT_COST_FUNCTIONS.get(key, {}), **cf.get(key, {})}
        cf[key] = {**base, "alpha": base["alpha"] * value, "beta": base["beta"] * value}
        return replace(case, economics={**case.economics, "cost_functions": cf})
    if kind == "scale":
        f = value / case.basis["production_per_year"]
        retro = copy.deepcopy(case.retrofit)
        retro["storage"]["size_baseline"] *= f          # tank scaled with production, as in Padullés Sec. 5.1
        return replace(case, basis={**case.basis, "production_per_year": value}, retrofit=retro)
    raise ValueError(kind)


def answers(case: Case, streams, unit: str, selected: dict | None) -> dict:
    """RQ1, RQ2, RQ3 for one case variant."""
    params = _params_and_converter(case, unit)[1]
    case_nc = replace(case, retrofit={**case.retrofit,
                                      "options": [o for o in case.retrofit["options"] if not o.get("cycle_based")]})
    r = run_retrofit(case_nc, streams, unit, params, selected)
    r.close_figures()
    opts = r.summary["options"]
    thr = params.payback_threshold_years
    cands = [(o["gas_reduction_vs_baseline"], o["option"], o["payback_years"], o["npv_EUR"]) for o in opts
             if o["payback_years"] <= thr]
    for name, cv in r.tables.items():
        if not name.startswith("retrofit_curve_"):
            continue
        ok = cv[cv["payback_years"] <= thr]
        if len(ok):
            i = ok["gas_reduction_vs_baseline"].idxmax()
            cands.append((float(ok.loc[i, "gas_reduction_vs_baseline"]), name.removeprefix("retrofit_curve_") + " (partial)",
                          float(ok.loc[i, "payback_years"]), float(ok.loc[i, "npv_EUR"])))
    rq1 = max(cands) if cands else (0.0, "none", math.nan, math.nan)
    full = max((o for o in opts if o["Qh_residual"] < 1e-6), key=lambda o: o["gas_reduction_vs_baseline"] - 1e-9 * o["capex_EUR"])
    ww = next((o for o in opts if "only" in o["option"]), None)
    # the heat pump on its own merits: incremental to the heat-recovery-only option on the same network
    hr = next((o for o in opts if ww and o["network"] == ww["network"] and o["heat_pumps"] == "none"), None)
    inc = math.nan
    if ww and hr and ww["savings_EUR"] > hr["savings_EUR"]:
        inc = (ww["capex_EUR"] - hr["capex_EUR"]) / (ww["savings_EUR"] - hr["savings_EUR"])
    at = area_targeting_outputs(case, streams)
    at.close_figures()
    law = next((x for x in at.summary.get("RQ2", []) if "installed" in x["cost_law"]), None)
    return {
        "RQ1_gas_share": round(rq1[0], 4), "RQ1_option": rq1[1], "RQ1_payback_y": round(rq1[2], 2),
        "RQ1_NPV_MEUR": round(rq1[3] / 1e6, 3),
        "RQ2_dTmin_opt_K": law["dTmin_opt_K"] if law else math.nan,
        "RQ3_ratio_full_electrification": full["break_even_ratio_NPV"],
        "RQ3_ratio_warm_water_HP_only": ww["break_even_ratio_NPV"] if ww else math.nan,
        "warm_water_HP_incremental_payback_y": round(inc, 2),
        "full_electrification_payback_y": full["payback_years"], "full_electrification_NPV_MEUR": round(full["npv_EUR"] / 1e6, 3),
        "price_ratio": round(params.price_ratio, 3),
    }


def consolidate(case_file: Path) -> pd.DataFrame:
    case = load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    unit = streams.energy_unit
    selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json")
    rows = [{"sensitivity": "Base case", "basis": "sourced inputs (see sources_case_studies.md)",
             **answers(case, streams, unit, selected)}]
    for label, kind, value, basis in SENSITIVITIES:
        if (kind == "cycle" or (kind == "combo" and any(k == "cycle" for k, _ in value))) and not selected:
            continue
        rows.append({"sensitivity": label, "basis": basis, **answers(_apply(case, kind, value, selected), streams, unit, selected)})
    return pd.DataFrame(rows)


def _markdown(df: pd.DataFrame, threshold: float) -> str:
    lines = ["| Sensitivity | RQ1: gas share, payback ≤ 5 y | RQ1 payback / NPV₁₀ | Warm-water HP alone, payback | "
             "RQ2: ΔTmin,opt [K] | RQ3: break-even ratio (full / warm-water HP) | Current ratio | Basis |",
             "|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        lines.append(f"| {r['sensitivity']} | {100 * r['RQ1_gas_share']:.1f} % | {r['RQ1_payback_y']} y / "
                     f"{r['RQ1_NPV_MEUR']:+.2f} M€ | {r['warm_water_HP_incremental_payback_y']} y | {r['RQ2_dTmin_opt_K']:g} | "
                     f"{r['RQ3_ratio_full_electrification']:.2f} / {r['RQ3_ratio_warm_water_HP_only']:.2f} | "
                     f"{r['price_ratio']:.2f} | {r['basis']} |")
    return "\n".join(lines) + "\n"


def _tornado(df: pd.DataFrame, path: Path, title: str) -> None:
    base = df.iloc[0]
    d = df.iloc[1:].copy()
    d["delta"] = d["RQ3_ratio_full_electrification"] - base["RQ3_ratio_full_electrification"]
    d = d.reindex(d["delta"].abs().sort_values().index)
    fig, ax = plt.subplots(figsize=(9, 6.5))
    ax.barh(d["sensitivity"], d["delta"], left=base["RQ3_ratio_full_electrification"],
            color=["#2471A3" if v > 0 else "#C0392B" for v in d["delta"]])
    ax.axvline(base["RQ3_ratio_full_electrification"], color="black", lw=1)
    ax.axvline(base["price_ratio"], color="grey", ls="--", lw=1)
    ax.annotate(f"today's ratio {base['price_ratio']:.2f}", (base["price_ratio"], 0), xytext=(3, -12),
                textcoords="offset points", fontsize=7, color="grey")
    ax.set_xlabel("Break-even price ratio, full electrification (NPV = 0) [-]")
    ax.tick_params(axis="y", labelsize=7)
    ax.set_title(title, fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    case = load_case(args.case_file)
    df = consolidate(args.case_file)
    out = ROOT / "outputs" / case.name
    df.to_csv(out / "rq_consolidated.csv", index=False)
    (out / "rq_consolidated.md").write_text(_markdown(df, 5.0), encoding="utf-8")
    _tornado(df, out / "rq_tornado.png", f"RQ3 sensitivity: {case.name} (base {df.iloc[0]['RQ3_ratio_full_electrification']:.2f})")
    print(_markdown(df, 5.0))


if __name__ == "__main__":
    main()
