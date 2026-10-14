"""Retrofit of an existing heat-exchanger network with heat recovery and heat pumps (step 5).

Reads the case's "retrofit" block::

    "retrofit": {
        "network_file": "../data/<site>_networks.json",
        "baseline": "<network name>",                 # the site as it is today
        "storage": {"kind": "hr_tank", "size_baseline": 520.8},
        "new_exchanger": {"kind": "plate_hex", "medium_h_kW_per_m2K": 2.0},
        "options": [
            {"name": "...", "network": "<name>", "heat_pumps": true},       # all sink levels
            {"name": "...", "network": "<name>", "heat_pumps": ["<level>"]},  # some levels
            {"name": "...", "network": "<name>", "heat_pumps": false}
        ]
    }

For each option:

1. the network is evaluated (``pinch.network``): utilities, diagnostics;
2. new heat recovery = hot segments of indirect matches that the baseline
   network does not have. Each gets an exchanger to the storage medium, sized
   with U = 1 / (1/h_stream + 1/h_medium) and a uniform approach equal to the
   stream shift plus half the indirect extra approach (parallel profiles, equal
   capacity flows: an assumption). Storage grows in proportion to the heat it
   receives (same temperature range: an assumption);
3. heat pumps are sized from the GCC of the network-constrained stream set
   (``pinch.network.constrained_streams``) at the case's sink levels; their
   sources take over refrigeration first (they evaporate at the cold utility
   level), the rest comes from ambient;
4. economics against the baseline network: gas = residual hot utility /
   boiler efficiency; electricity = heat pumps + chiller for the refrigeration
   not taken over (if chiller_cop is set).
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pinch.case import Case, to_MWh_per_year
from pinch.design import design_from_gcc
from pinch.economics import Option, break_even_ratio, capacity_kW, evaluate
from pinch.network import NetworkResult, constrained_streams, evaluate_network, load_networks
from pinch.problem_table import problem_table
from pinch.results import Outputs
from pinch.streams import StreamSet


def _new_hot_segments(base, option) -> list[tuple]:
    """(match, segment, extra_dT_K) for hot segments of indirect matches absent from the baseline."""
    old = {(g.stream, g.T_from_C, g.T_to_C) for m in base.matches for g in m.hot}
    return [(m, g, m.extra_dT_K) for m in option.matches if m.indirect for g in m.hot
            if (g.stream, g.T_from_C, g.T_to_C) not in old]


def _indirect_duty(streams: StreamSet, net) -> float:
    total = 0.0
    for m in net.matches:
        if m.indirect:
            for g in m.hot:
                s = next(x for x in streams.streams if x.name == g.stream)
                total += s.CP * abs(g.T_from_C - g.T_to_C)
    return total


def run_retrofit(case: Case, streams: StreamSet, energy_unit: str, params, cycle_selected: dict | None = None) -> Outputs:
    """Evaluate every retrofit option in memory (summary, tables, figure)."""
    block = getattr(case, "retrofit", None) or {}
    if not block:
        return Outputs({"skipped": "no retrofit block"})
    if case.basis is None:
        return Outputs({"skipped": "no annual basis"})
    nets = load_networks(block["network_file_resolved"])
    base_net = nets[block["baseline"]]
    to_MWh = lambda x: to_MWh_per_year(x, energy_unit, case.basis)  # noqa: E731
    h = (case.area_targeting or {}).get("film_coefficients_kW_per_m2K", {})
    medium_h = float(block.get("new_exchanger", {}).get("medium_h_kW_per_m2K", 2.0))
    hx_kind = block.get("new_exchanger", {}).get("kind", "plate_hex")
    storage = block.get("storage")
    cop_ch = params.chiller_cop

    base_res = evaluate_network(streams, base_net, case.ambient_T_C)
    E_base = to_MWh(base_res.refrigeration) / cop_ch if cop_ch else 0.0
    baseline = Option(f"baseline: {base_net.name}", to_MWh(base_res.Qh), E_base)
    base_indirect = _indirect_duty(streams, base_net)

    tables, rows, networks_out, curves = {}, [], {}, {}
    for opt in block["options"]:
        net = nets[opt["network"]]
        res = evaluate_network(streams, net, case.ambient_T_C)
        networks_out[net.name] = res.summary()
        for part in ("matches", "heaters", "coolers"):
            tables[f"retrofit_{_slug(net.name)}_{part}"] = getattr(res, part)

        # new heat recovery equipment
        equipment, hx_rows = [], []
        for m, g, extra in _new_hot_segments(base_net, net):
            s = next(x for x in streams.streams if x.name == g.stream)
            Q_kW = to_MWh(s.CP * abs(g.T_from_C - g.T_to_C)) * 1000 / params.operating_hours_per_year
            U = 1 / (1 / h[g.stream] + 1 / medium_h)
            dT = s.dT_shift_K + extra / 2
            A = Q_kW / (U * dT)
            equipment.append((hx_kind, A))
            hx_rows.append({"option": opt["name"], "segment": f"{g.stream} {g.T_from_C:g}->{g.T_to_C:g} °C",
                            "Q_kW": round(Q_kW, 1), "U_kW_per_m2K": round(U, 3), "approach_K": dT, "area_m2": round(A, 1)})
        if storage and _indirect_duty(streams, net) > base_indirect + 1e-9:
            V0 = float(storage["size_baseline"])
            V1 = V0 * _indirect_duty(streams, net) / base_indirect
            dC = params.cost_functions[storage["kind"]].cost(V1) - params.cost_functions[storage["kind"]].cost(V0)
            equipment.append(("lump_sum_EUR", dC))   # cost difference of the larger storage
            hx_rows.append({"option": opt["name"], "segment": f"storage {V0:.1f} -> {V1:.1f} m3",
                            "Q_kW": None, "U_kW_per_m2K": None, "approach_K": None, "area_m2": None,
                            "cost_EUR": round(dC, 0)})
        if hx_rows:
            tables.setdefault("retrofit_new_equipment", pd.DataFrame())
            tables["retrofit_new_equipment"] = pd.concat([tables["retrofit_new_equipment"], pd.DataFrame(hx_rows)])

        # heat pumps on the network-constrained stream set
        hp = opt.get("heat_pumps", False)
        units, Qh_after, W, Q_src = (), res.Qh, 0.0, 0.0
        cs = constrained_streams(streams, net)
        Qh_cs = problem_table(cs).Qh_min
        if abs(Qh_cs - res.Qh) > 1e-3:
            raise AssertionError(f"{net.name}: constrained stream set gives Q̇h {Qh_cs:.4f}, network {res.Qh:.4f}")
        if hp:
            levels = tuple(lv for lv in case.sink_levels if hp is True or lv.name in hp)
            if cycle_selected and opt.get("cycle_based"):
                levels = tuple(replace(lv, eta_lorenz=cycle_selected[lv.name]["eta_lorenz_cycle"])
                               if lv.name in cycle_selected else lv for lv in levels)
            d = design_from_gcc(cs, levels, case.eta_lorenz, case.source_T_C)
            units, Qh_after = d.units, d.Qh_residual
            W = sum(u.W for u in units)
            Q_src = sum(u.Q_source for u in units)
        replaced = min(Q_src, res.refrigeration) * params.refrigeration_credit_fraction
        E = to_MWh(W) + (to_MWh(res.refrigeration - replaced) / cop_ch if cop_ch else 0.0)
        eq = tuple(equipment) + tuple((k, capacity_kW(to_MWh(u.Q_sink), params))
                                      for u in units for k in params.heat_pump_cost_items(u)[0])
        option = Option(opt["name"], to_MWh(Qh_after), E, eq)
        ev = _evaluate(option, baseline, params)
        rows.append({"option": opt["name"], "network": net.name,
                     "Qh_network": round(res.Qh, 4), "heat_pumps": ", ".join(f"{u.name} {u.Q_sink:.2f} (COP {u.COP:.2f})"
                                                                         for u in units) or "none",
                     "Qh_residual": round(Qh_after, 4), "W_heat_pumps": round(W, 4),
                     "refrigeration_taken_over": round(replaced, 4),
                     "capex_EUR": round(ev.capex_EUR, 0), "savings_EUR": round(ev.savings_EUR, 0),
                     "payback_years": round(ev.payback_years, 2) if math.isfinite(ev.payback_years) else ev.payback_years,
                     "npv_EUR": round(ev.npv_EUR, 0), "gas_reduction_vs_baseline": round(ev.gas_reduction, 4),
                     "co2_avoided_t": round(ev.co2_avoided_t, 0),
                     "primary_energy_reduction": round(ev.primary_energy_reduction, 4),
                     "break_even_ratio_NPV": round(_be(option, baseline, params), 3)})
        if units:
            curves[opt["name"]] = _curve(units, res, option, baseline, params, to_MWh, tuple(equipment))

    table = pd.DataFrame(rows)
    tables["retrofit_options"] = table
    rq1 = {}
    for name, cv in curves.items():
        ok = cv[cv["payback_years"] <= params.payback_threshold_years]
        rq1[name] = {"max_gas_reduction_payback_ok": round(float(ok["gas_reduction_vs_baseline"].max()), 4) if len(ok) else 0.0,
                     "gas_reduction_at_max_NPV": round(float(cv.loc[cv["npv_EUR"].idxmax(), "gas_reduction_vs_baseline"]), 4),
                     "max_NPV_EUR": round(float(cv["npv_EUR"].max()), 0)}
        tables[f"retrofit_curve_{_slug(name)}"] = cv
    summary = {"baseline": base_res.summary(), "networks": networks_out, "options": rows,
               "RQ1_vs_existing_site": rq1,
               "assumptions": {"new exchanger": f"{hx_kind}, U from film coefficients and medium h {medium_h} kW/m2K, "
                                                "approach = stream shift + half the indirect extra approach",
                               "storage": "volume proportional to the heat charged (same temperature range)",
                               "heat pump sources": "take over refrigeration first; remainder from ambient"}}
    return Outputs(summary, tables, {"retrofit_options": _figure(table, case.name)})


def _evaluate(option, baseline, params):
    return evaluate(option, baseline, params)


def _be(option, baseline, params):
    return break_even_ratio(option, baseline, params, "npv")


def _curve(units, res: NetworkResult, option, baseline, params, to_MWh, equipment, n: int = 201) -> pd.DataFrame:
    """Partial heat pump duty (highest COP first) on top of the option's network changes."""
    units = sorted(units, key=lambda u: -u.COP)
    total = sum(u.Q_sink for u in units)
    out = []
    for target in np.linspace(0.0, total, n):
        remaining, W, src, eq = target, 0.0, 0.0, list(equipment)
        for u in units:
            q = min(u.Q_sink, remaining)
            if q <= 0:
                break
            remaining -= q
            W += q / u.COP
            src += q * (1 - 1 / u.COP)
            eq.extend((k, capacity_kW(to_MWh(q), params)) for k in params.heat_pump_cost_items(u)[0])
        refr_left = res.refrigeration - min(src, res.refrigeration) * params.refrigeration_credit_fraction
        E = to_MWh(W) + (to_MWh(refr_left) / params.chiller_cop if params.chiller_cop else 0.0)
        ev = _evaluate(Option(f"{target:.3f}", to_MWh(res.Qh - target), E, tuple(eq)), baseline, params)
        out.append({"heat_pump_heat": round(target, 4), "payback_years": ev.payback_years, "npv_EUR": ev.npv_EUR,
                    "gas_reduction_vs_baseline": ev.gas_reduction, "capex_EUR": ev.capex_EUR})
    return pd.DataFrame(out)


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_").lower()[:40]


def _figure(table: pd.DataFrame, case_name: str):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.5))
    y = np.arange(len(table))
    a1.barh(y, table["gas_reduction_vs_baseline"] * 100, color="#2471A3")
    a1.set_yticks(y, table["option"], fontsize=8)
    a1.set_xlabel("Gas reduction vs existing site [%]")
    a1.invert_yaxis()
    a1.grid(axis="x", alpha=0.3)
    pbp = table["payback_years"].replace([np.inf], np.nan)
    a2.barh(y, pbp, color="#C0392B")
    a2.set_yticks(y, [""] * len(y))
    a2.set_xlabel("Simple payback [years]")
    a2.set_xlim(0, 1.35 * float(np.nanmax(pbp)) if np.isfinite(np.nanmax(pbp)) else 10)
    a2.invert_yaxis()
    a2.grid(axis="x", alpha=0.3)
    for i, (p, npv) in enumerate(zip(pbp, table["npv_EUR"])):
        if np.isfinite(p):
            a2.annotate(f"NPV {npv / 1e6:+.2f} M€", (p, i), xytext=(3, 0), textcoords="offset points",
                        va="center", fontsize=7)
    fig.suptitle(f"Retrofit options against the existing network: {case_name}")
    fig.tight_layout()
    return fig
