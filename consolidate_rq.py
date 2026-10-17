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

Each sensitivity row changes one input from the base case; the source of each
range is in the "basis" column. Writes outputs/<case>/rq_consolidated.csv,
.md and rq_tornado.png.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from pinch import load_streams, with_extra_shift
from pinch.area_analysis import area_targeting_outputs
from pinch.case import Case, display_name, load_case
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
    ("Refrigeration credit 50 % (batch mismatch)", "econ", {"refrigeration_credit_fraction": 0.5},
     "advisory bound: heat pump and cooling loads not simultaneous; also covers the paper's lower Q̇c (3.2 vs 3.44)"),
    ("Chiller COP 3.14", "econ", {"chiller_cop": 3.14}, "Sinnott & Towler Example 6.7 (cooling water 40 °C)"),
    ("Chiller COP 6.68", "econ", {"chiller_cop": 6.68}, "Sinnott & Towler: 0.9 x Carnot (complex cycles)"),
    ("CO2 price 82.4 EUR/t", "econ", {"co2_price_EUR_per_t": 82.4}, "EUA, 5 Oct 2026"),
    ("Portuguese CO2 addition 67.4 EUR/t", "econ", {"co2_price_EUR_per_t": 67.395},
     "CIEC Art. 92.º-A; 2025 rate set by Portaria n.º 355-A/2024/1, Art. 2.º (Diário da República, 27 Dec 2024); "
     "applies to natural gas outside the EU ETS (ERSE 2020); "
     "upper value: up to 3.8 EUR/MWh of non-recoverable taxes (about 21 EUR/t) may already be in the Eurostat price, "
     "and energy-intensive consumers (SGCIE) may be exempt"),
    ("Horizon 20 years", "econ", {"horizon_years": 20}, "DEA sheet 2.a: HTHP technical lifetime 20 y"),
    ("Lorenz efficiency 0.45", "eta", 0.45, "DEA HTHP data, implied 0.45-0.52"),
    ("Lorenz efficiency 0.55 (Padullés et al.)", "eta", 0.55, "published value used by Padullés et al. (2026)"),
    ("Lorenz efficiency 0.63", "eta", 0.63, "Andersen et al. (2024) polynomial, HTHP"),
    ("Cycle-based COP per unit", "cycle", None, "CoolProp screening (step 4b), practical options only"),
    ("Cycle-based COP -17 %", "cycle_scaled", 0.83,
     "advisory: our model is 17 % above Andersen et al. (2024) Fig. 2 at one point"),
    ("Heat pump CAPEX -25 %", "hp_capex", 0.75, "DEA sheet 2.a: 0.9-1.5 vs 1.2 MEUR/MW"),
    ("Heat pump CAPEX +25 %", "hp_capex", 1.25, "DEA sheet 2.a: 0.9-1.5 vs 1.2 MEUR/MW"),
    ("Retrofit exchanger CAPEX x3", "hx_capex", 3.0, "stress test"),
    ("HTHP sink 110 °C (boiling driving force)", "hthp_sink", 110.0,
     "103 °C leaves 2 K to boiling wort; nucleate boiling needs some K of wall superheat plus hydrostatic "
     "boiling-point rise (no sourced value); Padullés Fig. 11 spans 100-180 °C (supervisor review B1)"),
    ("HTHP sink 120 °C (boiling driving force)", "hthp_sink", 120.0, "as above"),
    ("Grid emission factor 0.167 (5-year average)", "econ", {"grid_EF_kg_per_kWh": 0.167},
     "APA 2025, Table T2 (5-year moving average); affects CO2 avoided only"),
    ("Grid emission factor 0.367 (marginal gas CCGT, assumed)", "econ", {"grid_EF_kg_per_kWh": 0.367},
     "marginal plant = gas combined cycle: 0.202 kg/kWh (IPCC 2006, NCV) / 55 % efficiency (assumed, not "
     "sourced); affects CO2 avoided only (supervisor review B5)"),
    ("Batch: HTHP sized for the boil window, F = 1.14", "econ",
     {"heat_pump_capacity_factors": {"HTHP (wort boiling)": 24 / (14 * 1.5)}},
     "14 brews/day x 90 min (most continuous): installed = 24 h / (brews x boil time) x average"),
    ("Batch: HTHP sized for the boil window, F = 1.75", "econ",
     {"heat_pump_capacity_factors": {"HTHP (wort boiling)": 24 / (11 * 1.25)}},
     "11 brews/day x 75 min (central); 8-14 brews/day (Briggs of Burton 2017, industry), 60-90 min boil (assumed)"),
    ("Batch: HTHP sized for the boil window, F = 3.0", "econ",
     {"heat_pump_capacity_factors": {"HTHP (wort boiling)": 24 / (8 * 1.0)}},
     "8 brews/day x 60 min (least continuous); no high-temperature storage"),
    ("RQ2 with heat-pump heat as hot utility", "hp_hot_utility", None,
     "after electrification the marginal hot utility is HTHP heat: hours x (p_el / COP + variable O&M) "
     "+ CRF x 600 EUR/kW + fixed O&M (supervisor review A4)"),
    ("Film coefficients x5 (gasketed plates)", "film", 5.0,
     "Sinnott & Towler Table 12.1: plate, water-water U 5,000-7,500 W/m2K vs 1,000 implied by Stampfli"),
    ("Production 0.25 Mhl/year", "scale", 0.25e6, "Padullés Table 1 range (UK case)"),
    ("Production 0.5 Mhl/year", "scale", 0.5e6, "Padullés Table 1 range"),
    ("Production 1.5 Mhl/year", "scale", 1.5e6, "Padullés Table 1 range (TH case)"),
    ("No O&M (as Padullés et al.)", "no_om", None, "Padullés et al. (2026) include no O&M; base uses DEA O&M"),
    ("Combined: Padullés conventions (boiler 1.0, no refrigeration credit, no O&M)", "combo",
     [("econ", {"boiler_efficiency": 1.0, "chiller_cop": None}), ("no_om", None)], "Padullés et al. (2026), Sec. 5"),
    ("Combined pessimistic: no credit, cycle-based COP, HP CAPEX +25 %", "combo",
     [("econ", {"chiller_cop": None}), ("cycle", None), ("hp_capex", 1.25)], "one-at-a-time ranges above, together"),
    ("Combined conservative: credit 50 %, cycle COP -17 %, HP CAPEX +25 %, boiler 0.929", "combo",
     [("econ", {"refrigeration_credit_fraction": 0.5, "boiler_efficiency": 0.929}), ("cycle_scaled", 0.83),
      ("hp_capex", 1.25)], "advisory envelope for the items that cannot be verified"),
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
    if kind in ("cycle", "cycle_scaled"):
        k = 1.0 if kind == "cycle" else float(value)
        return replace(case, sink_levels=tuple(replace(lv, eta_lorenz=k * selected[lv.name]["eta_lorenz_cycle"])
                                               if lv.name in selected else lv for lv in case.sink_levels))
    if kind in ("hp_capex", "hx_capex"):
        key = "heat_pump" if kind == "hp_capex" else "plate_hex"
        cf = copy.deepcopy(case.economics.get("cost_functions", {}))
        from pinch.economics import DEFAULT_COST_FUNCTIONS
        base = {**DEFAULT_COST_FUNCTIONS.get(key, {}), **cf.get(key, {})}
        cf[key] = {**base, "alpha": base["alpha"] * value, "beta": base["beta"] * value}
        return replace(case, economics={**case.economics, "cost_functions": cf})
    if kind == "no_om":
        from pinch.economics import NO_OM
        cf = copy.deepcopy(case.economics.get("cost_functions", {}))
        for k, v in NO_OM["cost_functions"].items():
            cf[k] = {**cf.get(k, {}), **v}
        return replace(case, economics={**case.economics, "cost_functions": cf,
                                        "boiler_variable_om_EUR_per_MWh": 0.0})
    if kind == "hthp_sink":
        return replace(case, sink_levels=tuple(replace(lv, T_sink_in_C=float(value), T_sink_out_C=float(value))
                                               if "HTHP" in lv.name else lv for lv in case.sink_levels))
    if kind == "area":
        return replace(case, area_targeting={**case.area_targeting, **value})
    if kind == "film":
        at = dict(case.area_targeting)
        at["film_coefficients_kW_per_m2K"] = {k: v * float(value) for k, v in at["film_coefficients_kW_per_m2K"].items()}
        return replace(case, area_targeting=at)
    if kind == "scale":
        f = value / case.basis["production_per_year"]
        retro = copy.deepcopy(case.retrofit)
        retro["storage"]["size_baseline"] *= f          # tank scaled with production, as in Padullés Sec. 5.1
        return replace(case, basis={**case.basis, "production_per_year": value}, retrofit=retro)
    raise ValueError(kind)


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
        a = answers(_apply(case, "scale", x, selected), streams, unit, selected)
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
    for label, kind, value, basis in SENSITIVITIES:
        if kind == "hp_hot_utility":
            kind, value = "area", {"hot_utility_cost_EUR_per_kW_year": c_hp}
            basis = f"{basis}: {c_hp:.0f} EUR/(kW year)"
        if (kind.startswith("cycle") or (kind == "combo" and any(k.startswith("cycle") for k, _ in value))) and not selected:
            continue
        rows.append({"sensitivity": label, "basis": basis, **answers(_apply(case, kind, value, selected), streams, unit, selected)})
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
    col = "RQ3_ratio_WW_HP"
    base = df.iloc[0]
    d = df.iloc[1:].copy()
    d["delta"] = d[col] - base[col]
    d = d.reindex(d["delta"].abs().sort_values().index)
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.barh(d["sensitivity"], d["delta"], left=base[col], color=["#2471A3" if v > 0 else "#C0392B" for v in d["delta"]])
    ax.axvline(base[col], color="black", lw=1)
    ax.axvline(base["price_ratio"], color="grey", ls="--", lw=1)
    ax.annotate(f"today's ratio {base['price_ratio']:.2f}", (base["price_ratio"], 0), xytext=(3, -12),
                textcoords="offset points", fontsize=7, color="grey")
    ax.set_xlabel("Break-even price ratio, warm-water heat pump increment (NPV = 0) [-]")
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
