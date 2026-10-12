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
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pinch.case import Case, to_MWh_per_year
from pinch.design import HeatPumpDesign
from pinch.economics import (DEFAULTS, EconomicParameters, Option, break_even_ratio, capacity_kW, evaluate,
                             load_economics)


@dataclass(frozen=True)
class CurvePoint:
    fraction: float
    option: Option


def electrification_curve(design: HeatPumpDesign, Qh_base_MWh: float, to_MWh, params: EconomicParameters,
                          extra_equipment: tuple = (), n_points: int = 201) -> list[CurvePoint]:
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
    """
    units = sorted(design.units, key=lambda u: -u.COP)
    total = sum(u.Q_sink for u in units)
    points = []
    for target in np.linspace(0.0, total, n_points):
        remaining, W, equipment = target, 0.0, list(extra_equipment)
        for u in units:
            q = min(u.Q_sink, remaining)
            if q <= 0:
                break
            remaining -= q
            W += q / u.COP
            equipment.append(("heat_pump", capacity_kW(to_MWh(q), params)))
        delivered = to_MWh(target)
        fraction = target / design.Qh_before if design.Qh_before > 0 else 0.0
        points.append(CurvePoint(fraction, Option(f"{100 * fraction:.1f} %", Qh_base_MWh - delivered,
                                                  to_MWh(W), tuple(equipment))))
    return points


def run_economics(case: Case, design: HeatPumpDesign, Q_cold_total: float, energy_unit: str, out: Path) -> dict:
    """Evaluate the design, write tables and figures, and return a summary."""
    if case.basis is None:
        return {"skipped": "no annual basis in the case file"}
    block = dict(case.economics or {})
    if case.basis["type"] == "power":  # one set of operating hours for the whole case
        block.setdefault("operating_hours_per_year", case.basis["operating_hours_per_year"])
        if block["operating_hours_per_year"] != case.basis["operating_hours_per_year"]:
            raise ValueError("economics.operating_hours_per_year must equal basis.operating_hours_per_year")
    params = load_economics(block)
    to_MWh = lambda x: to_MWh_per_year(x, energy_unit, case.basis)  # noqa: E731

    Qh_MWh = to_MWh(design.Qh_before)
    baseline = Option("baseline: gas boiler, heat recovery installed", Qh_MWh, 0.0)
    curve = electrification_curve(design, Qh_MWh, to_MWh, params)
    evals = [(pt.fraction, evaluate(pt.option, baseline, params)) for pt in curve]
    full = evals[-1][1]
    full_option = curve[-1].option

    threshold = params.payback_threshold_years
    within = [f for f, e in evals if f > 0 and e.payback_years <= threshold]
    best_npv_f, best_npv = max(evals, key=lambda fe: fe[1].npv_EUR)
    rq1 = {
        "max_fraction_with_payback_below_threshold": round(max(within), 4) if within else 0.0,
        "_definition": "fraction = heat pump heat / Q̇h,min of the site with heat recovery installed",
        "threshold_years": threshold,
        "fraction_with_max_NPV": round(best_npv_f, 4),
        "max_NPV_EUR": round(best_npv.npv_EUR, 0),
    }
    rq3 = {
        "break_even_ratio_NPV": round(break_even_ratio(full_option, baseline, params, "npv"), 3),
        "break_even_ratio_payback": round(break_even_ratio(full_option, baseline, params, "payback"), 3),
        "ratio_used": round(params.price_ratio, 3),
    }

    results = {"full design (heat recovery installed)": full.as_dict()}
    hr_equipment = tuple(tuple(x) for x in block.get("heat_recovery_equipment", []))
    if hr_equipment:  # second baseline: no heat recovery yet
        base_noHR = Option("baseline: gas boiler, no heat recovery", to_MWh(Q_cold_total), 0.0)
        hr_only = Option("heat recovery only", Qh_MWh, 0.0, hr_equipment)
        hr_hp = replace(full_option, name="heat recovery + heat pumps", equipment=hr_equipment + full_option.equipment)
        results["heat recovery only (vs no HR)"] = evaluate(hr_only, base_noHR, params).as_dict()
        results["heat recovery + heat pumps (vs no HR)"] = evaluate(hr_hp, base_noHR, params).as_dict()
        rq3["break_even_ratio_NPV_with_HR_investment"] = round(break_even_ratio(hr_hp, base_noHR, params, "npv"), 3)
        # RQ1 for a site without heat recovery: one project = heat recovery + heat pumps
        curve_hr = electrification_curve(design, Qh_MWh, to_MWh, params, extra_equipment=hr_equipment)
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

    # boiler-efficiency sensitivity: sourced value 0.817 (DOE), bound 1.0
    for eta_b in (0.817, 0.90, 1.0):
        e = evaluate(full_option, baseline, replace(params, boiler_efficiency=eta_b))
        results[f"full design, boiler efficiency {eta_b}"] = e.as_dict()

    # tables
    curve_df = pd.DataFrame([{"fraction_of_Qh_min": round(f, 4), **e.as_dict()} for f, e in evals])
    curve_df.to_csv(out / "electrification_curve.csv", index=False)
    ratios = np.round(np.arange(1.0, 4.01, 0.1), 2)
    sweep = pd.DataFrame([{"ratio": r, **evaluate(full_option, baseline, params.with_ratio(r)).as_dict()} for r in ratios])
    sweep.to_csv(out / "price_ratio_sweep.csv", index=False)

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
    fig.savefig(out / "electrification_curve.png", dpi=200)
    plt.close(fig)

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
    fig.savefig(out / "price_ratio_sweep.png", dpi=200)
    plt.close(fig)

    summary = {
        "parameters": {k: getattr(params, k, None) for k in (
            "gas_price_EUR_per_kWh", "electricity_price_EUR_per_kWh", "boiler_efficiency", "operating_hours_per_year",
            "discount_rate", "horizon_years", "payback_threshold_years", "gas_EF_kg_per_kWh", "grid_EF_kg_per_kWh",
            "co2_price_EUR_per_t", "pef_electricity", "pef_gas")},
        "price_ratio": round(params.price_ratio, 3),
        "default_sources": {k: v[1] for k, v in DEFAULTS.items() if k not in block},
        "case_sources": block.get("sources", {}),
        "RQ1": rq1,
        "RQ3": rq3,
        "results": results,
    }
    (out / "economics.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return summary
