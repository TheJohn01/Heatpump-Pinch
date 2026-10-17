"""Per-case ΔTmin supertargeting (workflow step 3, research question 2).

Reads the case's "area_targeting" block:
    film_coefficients_kW_per_m2K : {stream name: h}, with a source
    dTmin_grid_K                 : list of ΔTmin values to scan
    cost_law                     : {"a", "b", "c", "source"}, a list of such
                                   laws, or null
    specific_area_cost_sweep_EUR_per_m2 : list of b values (a = 0, c = 1),
                                   used when no sourced cost law is available

Loads are converted to kW with the case's annual basis and operating hours, so
areas come out in m². Hot-utility cost per kW-year = hours x gas price / boiler
efficiency (the economics block); cold-utility cost per kW-year is
'cold_utility_cost_EUR_per_kW_year', or, if that is null and the economics
block sets chiller_cop, hours x electricity price / chiller COP (all of Q̇c,min
treated as refrigeration: an upper bound when part could go to cooling water).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from pinch.area import CostLaw, supertarget
from pinch.case import Case, display_name, to_MWh_per_year
from pinch.economics import load_economics
from pinch.plotting import supertargeting_figure
from pinch.results import Outputs
from pinch.streams import StreamSet


def to_kW(stream_set: StreamSet, case: Case, hours: float) -> StreamSet:
    """Rescale loads to kW of continuous duty."""
    factor = to_MWh_per_year(1.0, stream_set.energy_unit, case.basis) * 1000 / hours
    return replace(stream_set, energy_unit="kW",
                   streams=tuple(replace(s, Q=s.Q * factor) for s in stream_set.streams))


def area_targeting_outputs(case: Case, streams: StreamSet) -> Outputs:
    """Supertargeting in memory: summary, table and figure (nothing written)."""
    block = getattr(case, "area_targeting", None) or {}
    if not block:
        return Outputs({"skipped": "no area_targeting block"})
    if case.basis is None:
        return Outputs({"skipped": "no annual basis (needed to convert loads to kW)"})
    params = load_economics(case.economics)
    hours = params.operating_hours_per_year
    s_kW = to_kW(streams, case, hours)
    h = block["film_coefficients_kW_per_m2K"]
    grid = block.get("dTmin_grid_K", list(np.arange(1, 31, 1.0)))
    c_hot = hours * params.gas_price_EUR_per_kWh / params.boiler_efficiency
    if block.get("hot_utility_cost_EUR_per_kW_year") is not None:   # e.g. heat-pump heat after electrification
        c_hot = float(block["hot_utility_cost_EUR_per_kW_year"])
    c_cold_given = block.get("cold_utility_cost_EUR_per_kW_year")
    cw = block.get("cooling_water")   # {"electricity_kWh_per_kWh": e, "other_EUR_per_kWh": o} per kWh of heat removed
    if cw:
        c_cold = hours * (params.electricity_price_EUR_per_kWh * float(cw["electricity_kWh_per_kWh"])
                          + float(cw.get("other_EUR_per_kWh", 0.0)))
    elif c_cold_given is None and params.chiller_cop:
        c_cold = hours * params.electricity_price_EUR_per_kWh / params.chiller_cop   # refrigeration electricity
    else:
        c_cold = float(c_cold_given or 0.0)
    crf = 1 / params.annuity_factor

    laws: list[CostLaw] = []
    given = block.get("cost_law") or []
    for cl in ([given] if isinstance(given, dict) else given):
        laws.append(CostLaw(float(cl["a"]), float(cl["b"]), float(cl["c"]), cl.get("label", cl["source"])))
    for b in block.get("specific_area_cost_sweep_EUR_per_m2", []):
        laws.append(CostLaw(0.0, float(b), 1.0, f"sweep: {b} EUR/m2 installed, linear (not a sourced estimate)"))
    if not laws:
        return Outputs({"skipped": "no cost law and no sweep given"})

    results, frames = [], []
    for law in laws:
        rows = supertarget(s_kW, h, grid, law, crf, c_hot, c_cold)
        df = pd.DataFrame(rows)
        df["cost_law"] = law.source
        frames.append(df)
        best = df.loc[df["TAC_EUR"].idxmin()]
        flat = {}
        for tol in (0.01, 0.02):     # range of ΔTmin with TAC within tol of the minimum (flat optimum)
            near = df[df["TAC_EUR"] <= best["TAC_EUR"] * (1 + tol)]["dTmin_K"]
            flat[tol] = (float(near.min()), float(near.max()))
        results.append({"cost_law": law.source, "a": law.a, "b": law.b, "c": law.c,
                        "dTmin_opt_K": float(best["dTmin_K"]), "TAC_min_EUR": round(float(best["TAC_EUR"]), 0),
                        "area_m2": round(float(best["area_m2"]), 1), "Qh_min_kW": round(float(best["Qh_min"]), 1),
                        "at_grid_edge": bool(best["dTmin_K"] in (min(grid), max(grid))),
                        "dTmin_within_1pct_K": list(flat[0.01]), "dTmin_within_2pct_K": list(flat[0.02]),
                        "energy_share_of_TAC": round(float(best["energy_cost_EUR"] / best["TAC_EUR"]), 3)})

    fig = supertargeting_figure(frames, results, f"ΔTmin supertargeting: {display_name(case.name)}")

    summary = {"hot_utility_cost_EUR_per_kW_year": round(c_hot, 2), "cold_utility_cost_EUR_per_kW_year": c_cold,
               "crf_per_year": round(crf, 4), "film_coefficients_source": block.get("film_coefficients_source", ""),
               "RQ2": results}
    return Outputs(summary, {"supertargeting": pd.concat(frames)}, {"supertargeting": fig})
