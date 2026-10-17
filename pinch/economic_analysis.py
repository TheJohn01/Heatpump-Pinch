"""Economic analysis of a GCC-based heat pump design, for any case (workflow step 6).

Answers, for one site:
* RQ1  What fraction of the gas (hot-utility) demand can heat pumps replace with
       a payback below the threshold? Electrification curve: heat pump duty is
       added in order of decreasing COP (cheapest heat first), the last unit
       partially, and each partial design is evaluated.
* RQ3  Up to which electricity-to-gas price ratio does electrification stay
       competitive? Break-even ratios for NPV = 0 and for payback = threshold.

Baseline: the process with its heat recovery installed (gas supplies Q̇h,min).
If the case gives heat-recovery equipment, a second baseline without heat
recovery (gas supplies the total cold-stream load) is evaluated too.

Sensitivities
-------------
* ``economics.scenarios``: {name: {parameter: value, ...}}. Each scenario
  overrides economic parameters (prices, boiler efficiency, emission factors...)
  and reports the full design, RQ1 and RQ3 again (``scenarios.csv``).
* ``heat_pumps.eta_lorenz_sensitivity``: list of Lorenz efficiencies; the heat
  pumps are re-sized and re-costed for each (``eta_lorenz_sensitivity.csv``).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pinch.case import Case, to_MWh_per_year
from pinch.results import Outputs
from pinch.design import HeatPumpDesign
from pinch.economics import (DEFAULTS, EconomicParameters, Option, break_even_ratio, capacity_kW, evaluate, heat_pump_equipment,
                             load_economics)


def refrigeration_duty(streams, T_amb_C: float | None, heat_recovery: bool = True) -> float:
    """Cooling that must be done below ambient (refrigeration), in the stream-data unit.

    With heat recovery at target: Q̇c,min minus the GCC heat flow at T* = ambient
    (heat released between the pinch and ambient can go to ambient) if ambient
    lies below the pinch, else all of Q̇c,min.
    Without heat recovery: the heat of every hot stream below T* = ambient.
    Cooling above ambient is assumed to go to cooling water or air, at no energy cost.
    """
    from pinch import problem_table
    if T_amb_C is None:
        return 0.0
    if not heat_recovery:
        return sum(max(0.0, min(T_amb_C, max(s.T_star_in_C, s.T_star_out_C)) - min(s.T_star_in_C, s.T_star_out_C))
                   * s.CP for s in streams.hot)
    t = problem_table(streams)
    pinch = min(t.pinch_T_star_C) if t.pinch_T_star_C else -math.inf
    if T_amb_C >= pinch:
        return t.Qc_min
    # cascade heat flow at T* = ambient: surplus released between the pinch and ambient,
    # which cooling water/air can take; the rest of Q̇c,min is released below ambient
    T = t.T_star_C[::-1]
    H = t.cascade_feasible[::-1]
    return t.Qc_min - float(np.interp(T_amb_C, T, H))


_REPLACED_CACHE: dict = {}


def cold_utility_replaced_curve(design: HeatPumpDesign, streams, n_points: int = 201) -> list[float]:
    """Process cooling taken over by the heat pump sources at each point of the electrification curve."""
    from pinch.heat_pump import integrate
    key = (id(design), id(streams), n_points)
    if key not in _REPLACED_CACHE:
        units = sorted(design.units, key=lambda u: -u.COP)
        total = sum(u.Q_sink for u in units)
        out = []
        for target in np.linspace(0.0, total, n_points):
            remaining, partial = target, []
            for u in units:
                q = min(u.Q_sink, remaining)
                if q <= 0:
                    break
                remaining -= q
                partial.append(u.with_sink_duty(q))
            out.append(integrate(streams, partial).Q_cold_utility_replaced if partial else 0.0)
        _REPLACED_CACHE[key] = out
    return _REPLACED_CACHE[key]


@dataclass(frozen=True)
class CurvePoint:
    fraction: float
    option: Option


def electrification_curve(design: HeatPumpDesign, Qh_base_MWh: float, to_MWh, params: EconomicParameters,
                          extra_equipment: tuple = (), n_points: int = 201,
                          refrigeration: float = 0.0, replaced: list[float] | None = None) -> list[CurvePoint]:
    """Partial designs from 0 to the full design's share of Q̇h,min.

    Parameters
    ----------
    design : HeatPumpDesign
        Full GCC-based design.
    Qh_base_MWh : float
        Gas heat of the baseline [MWh/year].
    to_MWh : callable
        Converts a heat quantity in the stream-data unit to MWh/year.
    extra_equipment : tuple
        Equipment always included (e.g. a heat-recovery tank).
    refrigeration, replaced : float, list of float
        Refrigeration duty of the baseline and the part taken over by the heat
        pump sources at each point [stream-data unit]; with params.chiller_cop the
        remaining chiller electricity is added to each option.
    """
    units = sorted(design.units, key=lambda u: -u.COP)
    total = sum(u.Q_sink for u in units)
    points = []
    for i, target in enumerate(np.linspace(0.0, total, n_points)):
        remaining, W, equipment = target, 0.0, list(extra_equipment)
        for u in units:
            q = min(u.Q_sink, remaining)
            if q <= 0:
                break
            remaining -= q
            W += q / u.COP
            equipment.extend(heat_pump_equipment(params, u, capacity_kW(to_MWh(q), params)))
        delivered = to_MWh(target)
        fraction = target / design.Qh_before if design.Qh_before > 0 else 0.0
        E = to_MWh(W)
        if params.chiller_cop and refrigeration > 0:
            taken = min(replaced[i] if replaced else 0.0, refrigeration) * params.refrigeration_credit_fraction
            E += to_MWh(refrigeration - taken) / params.chiller_cop
        points.append(CurvePoint(fraction, Option(f"{100 * fraction:.1f} %", Qh_base_MWh - delivered,
                                                  E, tuple(equipment))))
    return points


def _core(design: HeatPumpDesign, Qh_MWh: float, to_MWh, params: EconomicParameters,
          streams=None, T_amb_C: float | None = None) -> dict:
    """Electrification curve, full design, RQ1 and RQ3 against the heat-recovery baseline.

    With params.chiller_cop, streams and T_amb_C, the baseline includes the
    chiller electricity for the refrigeration duty and each option only the part
    the heat pump sources do not take over.
    """
    refr, replaced = 0.0, None
    if params.chiller_cop and streams is not None:
        refr = refrigeration_duty(streams, T_amb_C)
        replaced = cold_utility_replaced_curve(design, streams)
    E_base = to_MWh(refr) / params.chiller_cop if refr > 0 else 0.0
    baseline = Option("baseline: gas boiler and chiller, heat recovery installed", Qh_MWh, E_base)
    curve = electrification_curve(design, Qh_MWh, to_MWh, params, refrigeration=refr, replaced=replaced)
    evals = [(pt.fraction, evaluate(pt.option, baseline, params)) for pt in curve]
    threshold = params.payback_threshold_years
    within = [f for f, e in evals if f > 0 and e.payback_years <= threshold]
    best_npv_f, best_npv = max(evals, key=lambda fe: fe[1].npv_EUR)
    full_option = curve[-1].option
    return {
        "refrigeration": refr,
        "baseline": baseline, "curve": curve, "evals": evals, "full": evals[-1][1], "full_option": full_option,
        "rq1": {
            "max_fraction_with_payback_below_threshold": round(max(within), 4) if within else 0.0,
            "_definition": "fraction = heat pump heat / Q̇h,min of the site with heat recovery installed",
            "threshold_years": threshold,
            "fraction_with_max_NPV": round(best_npv_f, 4),
            "max_NPV_EUR": round(best_npv.npv_EUR, 0),
        },
        "rq3": {
            "break_even_ratio_NPV": round(break_even_ratio(full_option, baseline, params, "npv"), 3),
            "break_even_ratio_payback": round(break_even_ratio(full_option, baseline, params, "payback"), 3),
            "ratio_used": round(params.price_ratio, 3),
        },
    }


def _headline(core: dict, params: EconomicParameters) -> dict:
    """One row of key results for sensitivity tables."""
    f = core["full"]
    return {"price_ratio": round(params.price_ratio, 3), "boiler_efficiency": params.boiler_efficiency,
            "gas_EF_kg_per_kWh": params.gas_EF_kg_per_kWh, "grid_EF_kg_per_kWh": params.grid_EF_kg_per_kWh,
            "co2_price_EUR_per_t": params.co2_price_EUR_per_t, "chiller_cop": params.chiller_cop,
            "full_capex_EUR": round(f.capex_EUR, 0), "full_savings_EUR": round(f.savings_EUR, 0),
            "full_payback_years": round(f.payback_years, 2), "full_npv_EUR": round(f.npv_EUR, 0),
            "full_co2_avoided_t": round(f.co2_avoided_t, 0),
            "full_primary_energy_reduction": round(f.primary_energy_reduction, 4),
            "RQ1_max_fraction_payback_ok": core["rq1"]["max_fraction_with_payback_below_threshold"],
            "RQ1_fraction_max_NPV": core["rq1"]["fraction_with_max_NPV"],
            "RQ3_break_even_ratio_NPV": core["rq3"]["break_even_ratio_NPV"],
            "RQ3_break_even_ratio_payback": core["rq3"]["break_even_ratio_payback"]}


def _params_and_converter(case: Case, energy_unit: str):
    block = dict(case.economics or {})
    if case.basis["type"] == "power":  # one set of operating hours for the whole case
        block.setdefault("operating_hours_per_year", case.basis["operating_hours_per_year"])
        if block["operating_hours_per_year"] != case.basis["operating_hours_per_year"]:
            raise ValueError("economics.operating_hours_per_year must equal basis.operating_hours_per_year")
    _strip = ("scenarios", "sources", "heat_recovery_equipment", "co2_price_sensitivity_EUR_per_t")
    params = load_economics({k: v for k, v in block.items() if k not in _strip})
    to_MWh = lambda x: to_MWh_per_year(x, energy_unit, case.basis)  # noqa: E731
    return block, params, to_MWh


def eta_lorenz_sensitivity(case: Case, streams, energy_unit: str, out: Path | None = None) -> list[dict]:
    """Re-size and re-cost the heat pumps for each Lorenz efficiency in the case file."""
    from pinch.design import design_from_gcc
    values = getattr(case, "eta_lorenz_sensitivity", ()) or ()
    if not values or case.basis is None:
        return []
    _, params, to_MWh = _params_and_converter(case, energy_unit)
    rows = []
    for eta in values:
        d = design_from_gcc(streams, case.sink_levels, float(eta), case.source_T_C)
        c = _core(d, to_MWh(d.Qh_before), to_MWh, params, streams, case.ambient_T_C)
        rows.append({"eta_lorenz": float(eta), "COP_system": round(d.COP_system, 3),
                     f"W_total_{energy_unit.replace('/', '_per_')}": round(d.W_total, 4), **_headline(c, params)})
    if out is not None and rows:
        pd.DataFrame(rows).to_csv(Path(out) / "eta_lorenz_sensitivity.csv", index=False)
    return rows


def cycle_based_design(case: Case, streams, energy_unit: str, selected: dict | None) -> dict:
    """Re-size and re-cost the design with the cycle-based Lorenz efficiency of each unit (step 4b).

    ``selected``: output of ``pinch.cycle_analysis.screen_design`` (per unit name).
    Units without a screening result keep the case's η_L.
    """
    from pinch.design import design_from_gcc
    if not selected:
        return {}
    levels = tuple(replace(lv, eta_lorenz=selected[lv.name]["eta_lorenz_cycle"]) if lv.name in selected else lv
                   for lv in case.sink_levels)
    d = design_from_gcc(streams, levels, case.eta_lorenz, case.source_T_C)
    out = {"units": {u.name: {"COP": round(u.COP, 3), "eta_lorenz": round(u.eta_lorenz, 4),
                              **({k: selected[u.name][k] for k in ("fluid", "layout")} if u.name in selected else {})}
                     for u in d.units},
           "COP_system": round(d.COP_system, 3), "W_total": round(d.W_total, 4),
           "fraction_of_Qh_min_electrified": round(d.fraction_electrified, 4)}
    if case.basis is not None and case.economics:
        _, params, to_MWh = _params_and_converter(case, energy_unit)
        out["economics"] = _headline(_core(d, to_MWh(d.Qh_before), to_MWh, params, streams, case.ambient_T_C), params)
    return out


def run_economics(case: Case, design: HeatPumpDesign, Q_cold_total: float, energy_unit: str, out: Path,
                  streams=None) -> dict:
    """Evaluate the design, write tables, figures and economics.json to ``out``; return the summary."""
    res = economics_outputs(case, design, Q_cold_total, energy_unit, streams)
    if "skipped" not in res.summary:
        res.write(out, "economics.json")
    return res.summary


def economics_outputs(case: Case, design: HeatPumpDesign, Q_cold_total: float, energy_unit: str,
                      streams=None) -> Outputs:
    """Evaluate the design in memory: summary, tables and figures (nothing written).

    ``streams`` (the process stream set) is needed for the refrigeration credit
    when the economics block sets ``chiller_cop``.
    """
    if case.basis is None:
        return Outputs({"skipped": "no annual basis in the case file"})
    tables, figures = {}, {}
    block, params, to_MWh = _params_and_converter(case, energy_unit)

    Qh_MWh = to_MWh(design.Qh_before)
    c = _core(design, Qh_MWh, to_MWh, params, streams, case.ambient_T_C)
    baseline, evals, full, full_option = c["baseline"], c["evals"], c["full"], c["full_option"]
    threshold = params.payback_threshold_years
    rq1, rq3 = c["rq1"], c["rq3"]

    results = {"full design (heat recovery installed)": full.as_dict()}
    hr_equipment = tuple(tuple(x) for x in block.get("heat_recovery_equipment", []))
    if hr_equipment:  # second baseline: no heat recovery yet
        E_noHR = 0.0
        if params.chiller_cop and streams is not None:
            E_noHR = to_MWh(refrigeration_duty(streams, case.ambient_T_C, heat_recovery=False)) / params.chiller_cop
        base_noHR = Option("baseline: gas boiler, no heat recovery", to_MWh(Q_cold_total), E_noHR)
        hr_only = Option("heat recovery only", Qh_MWh, baseline.electricity_MWh, hr_equipment)
        hr_hp = replace(full_option, name="heat recovery + heat pumps", equipment=hr_equipment + full_option.equipment)
        results["heat recovery only (vs no HR)"] = evaluate(hr_only, base_noHR, params).as_dict()
        results["heat recovery + heat pumps (vs no HR)"] = evaluate(hr_hp, base_noHR, params).as_dict()
        rq3["break_even_ratio_NPV_with_HR_investment"] = round(break_even_ratio(hr_hp, base_noHR, params, "npv"), 3)
        # RQ1 for a site without heat recovery: one project = heat recovery + heat pumps
        curve_hr = electrification_curve(design, Qh_MWh, to_MWh, params, extra_equipment=hr_equipment,
                                         refrigeration=c["refrigeration"],
                                         replaced=cold_utility_replaced_curve(design, streams)
                                         if c["refrigeration"] > 0 else None)
        evals_hr = [(pt.fraction, evaluate(pt.option, base_noHR, params)) for pt in curve_hr]
        ok = [e for f, e in evals_hr if e.payback_years <= threshold]
        rq1["site_without_HR: max gas reduction with payback below threshold"] = \
            round(max(e.gas_reduction for e in ok), 4) if ok else 0.0
        rq1["site_without_HR: heat pump share of Q̇h,min in that project"] = \
            round(max((f for f, e in evals_hr if e.payback_years <= threshold), default=0.0), 4)

    # CO2-price sensitivity (EU ETS), if given
    co2_sens = block.get("co2_price_sensitivity_EUR_per_t")
    if co2_sens:
        e = evaluate(full_option, baseline, replace(params, co2_price_EUR_per_t=float(co2_sens)))
        results[f"full design, CO2 price {co2_sens} EUR/t"] = e.as_dict()

    # named scenarios: parameter overrides from the case file
    scenario_rows = []
    base_block = {k: v for k, v in block.items()
                  if k not in ("scenarios", "sources", "heat_recovery_equipment", "co2_price_sensitivity_EUR_per_t")}
    for name, overrides in (block.get("scenarios") or {}).items():
        overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
        merged = {**base_block, **overrides}
        if "electricity_to_gas_ratio" in overrides:
            merged.pop("electricity_price_EUR_per_kWh", None)
        p_s = load_economics(merged)
        c_s = _core(design, Qh_MWh, to_MWh, p_s, streams, case.ambient_T_C)
        scenario_rows.append({"scenario": name, **_headline(c_s, p_s)})
    if scenario_rows:
        tables["scenarios"] = pd.DataFrame(scenario_rows)

    # tables
    curve_df = pd.DataFrame([{"fraction_of_Qh_min": round(f, 4), **e.as_dict()} for f, e in evals])
    tables["electrification_curve"] = curve_df
    ratios = np.round(np.arange(1.0, 4.01, 0.1), 2)
    sweep = pd.DataFrame([{"ratio": r, **evaluate(full_option, baseline, params.with_ratio(r)).as_dict()} for r in ratios])
    tables["price_ratio_sweep"] = sweep

    # figures
    f = curve_df["fraction_of_Qh_min"] * 100
    fig, ax1 = plt.subplots(figsize=(7, 4.5))
    pbp = curve_df["payback_years"].replace(np.inf, np.nan)
    ax1.plot(f, pbp, color="#1F77B4", lw=2, label="Payback")
    ax1.axhline(threshold, color="#1F77B4", ls=":", lw=1)
    ax1.set_xlabel("Share of Q̇h,min supplied by heat pumps [%]")
    ax1.set_ylabel("Simple payback [years]", color="#1F77B4")
    ax1.set_ylim(0, max(3 * threshold, 1))
    ax2 = ax1.twinx()
    ax2.plot(f, curve_df["npv_EUR"] / 1e6, color="#D62728", lw=2, label=f"NPV{params.horizon_years}")
    ax2.axhline(0, color="#D62728", ls=":", lw=1)
    ax2.set_ylabel(f"NPV{params.horizon_years} at {100 * params.discount_rate:.0f} % [M EUR]", color="#D62728")
    ax1.set_title(f"Electrification curve: {case.name} (ratio {params.price_ratio:.2f})")
    ax1.grid(alpha=0.3)
    fig.tight_layout()
    figures["electrification_curve"] = fig

    fig, ax1 = plt.subplots(figsize=(7, 4.5))
    ax1.plot(sweep["ratio"], sweep["payback_years"].replace(np.inf, np.nan), color="#1F77B4", lw=2)
    ax1.axhline(threshold, color="#1F77B4", ls=":", lw=1)
    ax1.set_ylim(0, max(3 * threshold, 1))
    ax1.set_xlabel("Electricity-to-gas price ratio [-]")
    ax1.set_ylabel("Simple payback [years]", color="#1F77B4")
    ax2 = ax1.twinx()
    ax2.plot(sweep["ratio"], sweep["npv_EUR"] / 1e6, color="#D62728", lw=2)
    ax2.axhline(0, color="#D62728", ls=":", lw=1)
    ax2.set_ylabel(f"NPV{params.horizon_years} [M EUR]", color="#D62728")
    ax1.axvline(params.price_ratio, color="grey", ls="--", lw=1)
    ax1.annotate(f"case ratio {params.price_ratio:.2f}", xy=(params.price_ratio, 0.5), xytext=(4, 0),
                 textcoords="offset points", fontsize=8, color="grey")
    ax1.set_title(f"Full design vs price ratio: {case.name}")
    ax1.grid(alpha=0.3)
    fig.tight_layout()
    figures["price_ratio_sweep"] = fig

    summary = {
        "parameters": {k: getattr(params, k, None) for k in (
            "gas_price_EUR_per_kWh", "electricity_price_EUR_per_kWh", "boiler_efficiency", "operating_hours_per_year",
            "discount_rate", "horizon_years", "payback_threshold_years", "gas_EF_kg_per_kWh", "grid_EF_kg_per_kWh",
            "co2_price_EUR_per_t", "pef_electricity", "pef_gas", "chiller_cop")},
        "price_ratio": round(params.price_ratio, 3),
        "refrigeration_duty": round(c["refrigeration"], 4),
        "default_sources": {k: v[1] for k, v in DEFAULTS.items() if k not in block},
        "case_sources": block.get("sources", {}),
        "heat_pump_cost_class": {u.name: (lambda k: " + ".join(k[0]) + (" (extrapolated: sink above every class)"
                                                                         if k[1] else ""))(params.heat_pump_cost_items(u))
                                 for u in design.units},
        "RQ1": rq1,
        "RQ3": rq3,
        "results": results,
        "scenarios": scenario_rows,
    }
    return Outputs(summary, tables, figures)
