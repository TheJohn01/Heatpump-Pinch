"""Economic analysis of a GCC-based heat pump design, for any case (workflow step 6).

Grass-roots reference: the heat pumps on a site whose heat recovery is already at
the energy target (gas supplies Q̇h,min). This is NOT the answer to RQ1 or RQ3, which
are defined against the site as it is today and computed by ``consolidate_rq.py``
(redundancy audit, item 1.1). For a case without a published network it is the
lower-bound baseline of ``pinch.retrofit.retrofit_bounds``. Reported:

* heat pumps' share of Q̇h,min with payback below the threshold, along the
  electrification curve (``pinch.design.partial_designs``);
* break-even electricity-to-gas price ratio of the full design (NPV = 0 and
  payback = threshold).

If the case gives heat-recovery equipment, a second baseline without heat
recovery (gas supplies the total cold-stream load) is evaluated too.

Sensitivities
-------------
* ``econ`` rows of the case's ``sensitivities`` list (``pinch.sensitivity``):
  each overrides economic parameters and reports the full design and the
  grass-roots figures again (``grass_roots_sensitivities.csv``). The other
  rows change the design or the network and are evaluated by consolidate_rq.py.
* ``heat_pumps.eta_lorenz_sensitivity``: list of Lorenz efficiencies; the heat
  pumps are re-sized and re-costed for each (``eta_lorenz_sensitivity.csv``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from pinch.case import Case, to_MWh_per_year
from pinch.plotting import electrification_curve_figure, price_ratio_figure
from pinch.problem_table_algorithm import problem_table
from pinch.refrigeration import CoolingCascade, refrigeration_taken_over
from pinch.results import Outputs
from pinch.sensitivity import apply as apply_sensitivity
from pinch.design import HeatPumpDesign, partial_designs
from pinch.economics import (DEFAULTS, EconomicParameters, Option, break_even_ratio, capacity_kW, evaluate, heat_pump_equipment,
                             load_economics)


def cooling_cascade(streams, T_amb_C: float | None, heat_recovery: bool = True) -> CoolingCascade | None:
    """Cooling side of the grass-roots site (``pinch.refrigeration``): with heat recovery at the
    target (the GCC) or without heat recovery (hot streams on utilities)."""
    if heat_recovery:
        return CoolingCascade.from_table(problem_table(streams), T_amb_C)
    return CoolingCascade.from_hot_streams(streams, T_amb_C)


@dataclass(frozen=True)
class CurvePoint:
    fraction: float
    option: Option


def electrification_curve(design: HeatPumpDesign, Qh_base_MWh: float, to_MWh, params: EconomicParameters,
                          extra_equipment: tuple = (), n_points: int = 201,
                          cooling: CoolingCascade | None = None) -> list[CurvePoint]:
    """Partial designs (``pinch.design.partial_designs``) from 0 to the full design's share of Q̇h,min.

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
    cooling : CoolingCascade or None
        Cooling side of the baseline. With params.chiller_cop, the chiller electricity for the
        refrigeration the heat pump sources do not take over is added to each option.
    """
    refrigeration = cooling.refrigeration if cooling is not None else 0.0
    points = []
    for target, partial in partial_designs(design.units, n_points):
        equipment = list(extra_equipment)
        for u in partial:
            equipment.extend(heat_pump_equipment(params, u, capacity_kW(to_MWh(u.Q_sink), params)))
        fraction = target / design.Qh_before if design.Qh_before > 0 else 0.0
        E = to_MWh(sum(u.W for u in partial))
        if params.chiller_cop and refrigeration > 0:
            taken = refrigeration_taken_over(partial, cooling, params.refrigeration_credit_fraction)
            E += to_MWh(refrigeration - taken) / params.chiller_cop
        points.append(CurvePoint(fraction, Option(f"{100 * fraction:.1f} %", Qh_base_MWh - to_MWh(target),
                                                  E, tuple(equipment))))
    return points


def _core(design: HeatPumpDesign, Qh_MWh: float, to_MWh, params: EconomicParameters,
          streams=None, T_amb_C: float | None = None) -> dict:
    """Electrification curve, full design and grass-roots figures against the heat-recovery baseline.

    With params.chiller_cop, streams and T_amb_C, the baseline includes the
    chiller electricity for the refrigeration duty and each option only the part
    the heat pump sources do not take over.
    """
    cooling = cooling_cascade(streams, T_amb_C) if params.chiller_cop and streams is not None else None
    refr = cooling.refrigeration if cooling is not None else 0.0
    E_base = to_MWh(refr) / params.chiller_cop if refr > 0 else 0.0
    baseline = Option("baseline: gas boiler and chiller, heat recovery installed", Qh_MWh, E_base)
    curve = electrification_curve(design, Qh_MWh, to_MWh, params, cooling=cooling)
    evals = [(pt.fraction, evaluate(pt.option, baseline, params)) for pt in curve]
    threshold = params.payback_threshold_years
    within = [f for f, e in evals if f > 0 and e.payback_years <= threshold]
    best_npv_f, best_npv = max(evals, key=lambda fe: fe[1].npv_EUR)
    full_option = curve[-1].option
    return {
        "refrigeration": refr, "cooling": cooling,
        "baseline": baseline, "curve": curve, "evals": evals, "full": evals[-1][1], "full_option": full_option,
        "grass_roots": {
            "_definition": GRASS_ROOTS_DEFINITION,
            "threshold_years": threshold,
            "hp_share_of_Qh_min_payback_ok": round(max(within), 4) if within else 0.0,
            "hp_share_of_Qh_min_max_NPV": round(best_npv_f, 4),
            "max_NPV_EUR": round(best_npv.npv_EUR, 0),
            "full_design_break_even_ratio_NPV": round(break_even_ratio(full_option, baseline, params, "npv"), 3),
            "full_design_break_even_ratio_payback": round(break_even_ratio(full_option, baseline, params, "payback"), 3),
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
            "grass_roots_hp_share_payback_ok": core["grass_roots"]["hp_share_of_Qh_min_payback_ok"],
            "grass_roots_hp_share_max_NPV": core["grass_roots"]["hp_share_of_Qh_min_max_NPV"],
            "full_design_break_even_ratio_NPV": core["grass_roots"]["full_design_break_even_ratio_NPV"],
            "full_design_break_even_ratio_payback": core["grass_roots"]["full_design_break_even_ratio_payback"]}


#: Keys of the economics block that are not parameters of ``load_economics``.
NON_PARAMETER_KEYS = ("sources", "heat_recovery_equipment", "co2_price_sensitivity_EUR_per_t")

GRASS_ROOTS_DEFINITION = ("grass-roots reference, not the answer to RQ1 or RQ3: heat pump heat / Q̇h,min for a site "
                          "already recovering heat at the energy target. RQ1-RQ3 against today's site: consolidate_rq.py")


def _params_and_converter(case: Case, energy_unit: str):
    block = dict(case.economics or {})
    if case.basis["type"] == "power":  # one set of operating hours for the whole case
        block.setdefault("operating_hours_per_year", case.basis["operating_hours_per_year"])
        if block["operating_hours_per_year"] != case.basis["operating_hours_per_year"]:
            raise ValueError("economics.operating_hours_per_year must equal basis.operating_hours_per_year")
    params = load_economics({k: v for k, v in block.items() if k not in NON_PARAMETER_KEYS})
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
    gr = c["grass_roots"]

    results = {"full design (heat recovery installed)": full.as_dict()}
    hr_equipment = tuple(tuple(x) for x in block.get("heat_recovery_equipment", []))
    if hr_equipment:  # second baseline: no heat recovery yet
        E_noHR = 0.0
        if params.chiller_cop and streams is not None:
            E_noHR = to_MWh(cooling_cascade(streams, case.ambient_T_C, heat_recovery=False).refrigeration) \
                / params.chiller_cop
        base_noHR = Option("baseline: gas boiler, no heat recovery", to_MWh(Q_cold_total), E_noHR)
        hr_only = Option("heat recovery only", Qh_MWh, baseline.electricity_MWh, hr_equipment)
        hr_hp = replace(full_option, name="heat recovery + heat pumps", equipment=hr_equipment + full_option.equipment)
        results["heat recovery only (vs no HR)"] = evaluate(hr_only, base_noHR, params).as_dict()
        results["heat recovery + heat pumps (vs no HR)"] = evaluate(hr_hp, base_noHR, params).as_dict()
        gr["full_design_break_even_ratio_NPV_with_HR_investment"] = round(break_even_ratio(hr_hp, base_noHR, params, "npv"), 3)
        # a site without heat recovery: one project = heat recovery + heat pumps
        curve_hr = electrification_curve(design, Qh_MWh, to_MWh, params, extra_equipment=hr_equipment,
                                         cooling=c["cooling"])
        evals_hr = [(pt.fraction, evaluate(pt.option, base_noHR, params)) for pt in curve_hr]
        ok = [e for f, e in evals_hr if e.payback_years <= threshold]
        gr["site_without_HR: max gas reduction with payback below threshold"] = \
            round(max(e.gas_reduction for e in ok), 4) if ok else 0.0
        gr["site_without_HR: heat pump share of Q̇h,min in that project"] = \
            round(max((f for f, e in evals_hr if e.payback_years <= threshold), default=0.0), 4)

    # CO2-price sensitivity (EU ETS), if given
    co2_sens = block.get("co2_price_sensitivity_EUR_per_t")
    if co2_sens:
        e = evaluate(full_option, baseline, replace(params, co2_price_EUR_per_t=float(co2_sens)))
        results[f"full design, CO2 price {co2_sens} EUR/t"] = e.as_dict()

    # economics rows of the case's single sensitivity list (pinch.sensitivity)
    sens_rows = []
    for sens in case.sensitivities:
        if sens.kind != "econ":
            continue
        _, p_s, _ = _params_and_converter(apply_sensitivity(case, sens.kind, sens.value), energy_unit)
        c_s = _core(design, Qh_MWh, to_MWh, p_s, streams, case.ambient_T_C)
        sens_rows.append({"sensitivity": sens.label, **_headline(c_s, p_s), "basis": sens.basis})
    if sens_rows:
        tables["grass_roots_sensitivities"] = pd.DataFrame(sens_rows)

    # tables
    curve_df = pd.DataFrame([{"fraction_of_Qh_min": round(f, 4), **e.as_dict()} for f, e in evals])
    tables["electrification_curve"] = curve_df
    ratios = np.round(np.arange(1.0, 4.01, 0.1), 2)
    sweep = pd.DataFrame([{"ratio": r, **evaluate(full_option, baseline, params.with_ratio(r)).as_dict()} for r in ratios])
    tables["price_ratio_sweep"] = sweep

    # figures (pinch.plotting)
    figures["electrification_curve"] = electrification_curve_figure(
        curve_df, threshold, params.horizon_years, params.discount_rate,
        f"Electrification curve: {case.plant} (ratio {params.price_ratio:.2f})")
    figures["price_ratio_sweep"] = price_ratio_figure(sweep, threshold, params.horizon_years, params.price_ratio,
                                                      f"Full design vs price ratio: {case.plant}")

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
        "grass_roots_reference": gr,
        "results": results,
        "grass_roots_sensitivities": sens_rows,
    }
    return Outputs(summary, tables, figures)
