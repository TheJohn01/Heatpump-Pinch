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

from pinch.case import Case, display_name, to_MWh_per_year
from pinch.design import design_from_gcc
from pinch.economics import Option, break_even_ratio, capacity_kW, evaluate, heat_pump_equipment
from pinch.network import NetworkResult, constrained_streams, evaluate_network, load_networks
from pinch.problem_table import problem_table
from pinch.results import Outputs
from pinch.streams import StreamSet


def sources_can_replace_refrigeration(streams: StreamSet, T_source_C: float, T_amb_C: float | None) -> bool:
    """True if heat pump sources at ``T_source_C`` (T*) are cold enough to take over the refrigeration:
    at or below the lowest shifted target temperature of the hot streams cooled below ambient."""
    if T_amb_C is None:
        return False
    cold_ends = [s.T_out_C - s.dT_shift_K for s in streams.streams
                 if s.kind == "hot" and min(s.T_in_C, s.T_out_C) - s.dT_shift_K < T_amb_C]
    return bool(cold_ends) and T_source_C <= min(cold_ends) + 1e-9


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
    option_objs, option_net, curve_args = {}, {}, {}
    can_replace = sources_can_replace_refrigeration(streams, case.source_T_C, case.ambient_T_C)
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
        replaced = (min(Q_src, res.refrigeration) * params.refrigeration_credit_fraction
                    if sources_can_replace_refrigeration(streams, case.source_T_C, case.ambient_T_C) else 0.0)
        E = to_MWh(W) + (to_MWh(res.refrigeration - replaced) / cop_ch if cop_ch else 0.0)
        eq = tuple(equipment) + tuple(x for u in units for x in heat_pump_equipment(params, u, capacity_kW(to_MWh(u.Q_sink), params)))
        option = Option(opt["name"], to_MWh(Qh_after), E, eq)
        option_objs[opt["name"]], option_net[opt["name"]] = option, net.name
        ev = _evaluate(option, baseline, params)
        rows.append({"option": opt["name"], "network": net.name,
                     "Qh_network": round(res.Qh, 4), "heat_pumps": ", ".join(f"{u.name} {u.Q_sink:.2f} (COP {u.COP:.2f})"
                                                                         for u in units) or "none",
                     "units": [{"name": u.name, "Q_sink": u.Q_sink, "COP": u.COP, "Q_source": u.Q_source} for u in units],
                     "refrigeration": res.refrigeration,
                     "Qh_residual": round(Qh_after, 4), "W_heat_pumps": round(W, 4),
                     "refrigeration_taken_over": round(replaced, 4),
                     "capex_EUR": round(ev.capex_EUR, 0), "savings_EUR": round(ev.savings_EUR, 0),
                     "payback_years": round(ev.payback_years, 2) if math.isfinite(ev.payback_years) else ev.payback_years,
                     "npv_EUR": round(ev.npv_EUR, 0), "gas_reduction_vs_baseline": round(ev.gas_reduction, 4),
                     "co2_avoided_t": round(ev.co2_avoided_t, 0),
                     "primary_energy_reduction": round(ev.primary_energy_reduction, 4),
                     "break_even_ratio_NPV": round(_be(option, baseline, params), 3)})
        if units:
            curve_args[opt["name"]] = (units, res, option, tuple(equipment))

    # heat pumps judged on their own: increments over the heat-recovery-only reference option (RQ1, RQ3 per unit)
    ref_name = block.get("heat_pump_reference")
    ref = option_objs.get(ref_name)
    for name, (units, res, option, equipment) in curve_args.items():
        same_net = ref is not None and option_net[name] == option_net[ref_name]
        curves[name] = _curve(units, res, option, baseline, params, to_MWh, equipment, can_replace=can_replace,
                              reference=ref if same_net else None)
    inc_rows = []
    for inc in block.get("heat_pump_increments", []):
        o, over = option_objs[inc["option"]], option_objs[inc["over"]]
        ev = _evaluate(o, over, params)
        inc_rows.append({"increment": inc["name"], "option": inc["option"], "over": inc["over"],
                         "delta_capex_EUR": round(ev.capex_EUR, 0), "delta_savings_EUR": round(ev.savings_EUR, 0),
                         "payback_years": round(ev.payback_years, 2) if math.isfinite(ev.payback_years) else ev.payback_years,
                         "delta_npv_EUR": round(ev.npv_EUR, 0), "co2_avoided_t": round(ev.co2_avoided_t, 0),
                         "gas_share_of_today": round(_evaluate(o, baseline, params).gas_reduction
                                                     - _evaluate(over, baseline, params).gas_reduction, 4),
                         "break_even_ratio_NPV": round(_be(o, over, params), 3)})
    if inc_rows:
        tables["retrofit_increments"] = pd.DataFrame(inc_rows)

    table = pd.DataFrame(rows).drop(columns=["units", "refrigeration"])
    tables["retrofit_options"] = table
    rq1 = {}
    for name, cv in curves.items():
        ok = cv[cv["payback_years"] <= params.payback_threshold_years]
        rq1[name] = {"max_gas_reduction_payback_ok": round(float(ok["gas_reduction_vs_baseline"].max()), 4) if len(ok) else 0.0,
                     "gas_reduction_at_max_NPV": round(float(cv.loc[cv["npv_EUR"].idxmax(), "gas_reduction_vs_baseline"]), 4),
                     "max_NPV_EUR": round(float(cv["npv_EUR"].max()), 0)}
        if "incremental_payback_years" in cv:
            okh = cv[(cv["incremental_payback_years"] <= params.payback_threshold_years) & (cv["hp_gas_share_of_today"] > 0)]
            rq1[name]["heat_pump_share_incremental_payback_ok"] = round(float(okh["hp_gas_share_of_today"].max()), 4) if len(okh) else 0.0
        tables[f"retrofit_curve_{_slug(name)}"] = cv
    summary = {"baseline": base_res.summary(), "networks": networks_out, "options": rows,
               "heat_pump_reference": ref_name, "increments": inc_rows,
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


def _curve(units, res: NetworkResult, option, baseline, params, to_MWh, equipment, n: int = 201,
           can_replace: bool = True, reference: Option | None = None) -> pd.DataFrame:
    """Partial heat pump duty (highest COP first) on top of the option's network changes.

    With a ``reference`` option (heat recovery only, same network), each point is also judged as an
    increment over it: the heat pumps' share of today's gas and their incremental payback and NPV."""
    ev_ref = _evaluate(reference, baseline, params) if reference is not None else None
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
            eq.extend(heat_pump_equipment(params, u, capacity_kW(to_MWh(q), params)))
        refr_left = res.refrigeration - (min(src, res.refrigeration) * params.refrigeration_credit_fraction
                                         if can_replace else 0.0)
        E = to_MWh(W) + (to_MWh(refr_left) / params.chiller_cop if params.chiller_cop else 0.0)
        point = Option(f"{target:.3f}", to_MWh(res.Qh - target), E, tuple(eq))
        ev = _evaluate(point, baseline, params)
        row = {"heat_pump_heat": round(target, 4), "payback_years": ev.payback_years, "npv_EUR": ev.npv_EUR,
               "gas_reduction_vs_baseline": ev.gas_reduction, "capex_EUR": ev.capex_EUR}
        if ev_ref is not None:
            inc = _evaluate(point, reference, params)
            row.update({"hp_gas_share_of_today": ev.gas_reduction - ev_ref.gas_reduction,
                        "incremental_payback_years": inc.payback_years, "incremental_npv_EUR": inc.npv_EUR})
        out.append(row)
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
    fig.suptitle(f"Retrofit options against the existing network: {display_name(case_name)}")
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ bounds when no network is published
BASELINE_STATUS = {
    "published": "the source states that the plant has no heat recovery: this baseline is the real plant",
    "upper_bound": ("the real plant recovers some heat, but its exchangers are not published: savings against "
                    "'no heat recovery' are an upper bound, savings against 'already at target' a lower bound"),
    "hypothetical": "textbook example, no real plant: both baselines are hypothetical bounds",
    "likely_at_target": ("the source describes a heat-integrated plant whose exchangers are not published: the "
                         "lower bound ('already at target') is the realistic estimate; 'no heat recovery' greatly "
                         "overstates the savings"),
}


def _hen_cost_law(block: dict, override_EUR_per_m2: float | None = None, override_note: str = ""):
    """(CostLaw, note) for a new heat-recovery network: the installed (x 3.5) law if given, else the first law,
    else the median of the cost sweep (not a cost estimate); (None, reason) if none is available."""
    from pinch.area import CostLaw
    if override_EUR_per_m2 is not None:
        b = float(override_EUR_per_m2)
        return CostLaw(0.0, b, 1.0, f"{b:g} EUR/m2"), f"{b:g} €/m² installed ({override_note or 'case value'})"
    given = block.get("cost_law") or []
    laws = [given] if isinstance(given, dict) else list(given)
    if laws:
        pick = next((cl for cl in laws if "3.5" in cl.get("label", "")), laws[0])
        return CostLaw(float(pick["a"]), float(pick["b"]), float(pick["c"]), pick.get("label", pick.get("source", ""))), \
            pick.get("label", pick.get("source", ""))
    sweep = sorted(block.get("specific_area_cost_sweep_EUR_per_m2") or [])
    if sweep:
        b = float(sweep[(len(sweep) - 1) // 2])
        return CostLaw(0.0, b, 1.0, f"sweep {b:g} EUR/m2"), (f"{b:g} €/m² installed (middle of the sweep "
                                                             f"{sweep[0]:g}-{sweep[-1]:g} €/m²; not a cost estimate)")
    return None, "no film coefficients or cost law: new-network cost not included"


def retrofit_bounds(case: Case, streams: StreamSet, energy_unit: str, params) -> Outputs:
    """Retrofit bracket for a case without a published existing network (step 5).

    Two baselines bound the plant as it is today:

    * **no heat recovery**: every stream on utilities (a network with no exchangers). Real for plants
      whose source says so; otherwise an upper bound on the savings;
    * **heat recovery at the energy target**: the grass-roots comparison of step 6; a lower bound.

    Options against the first baseline: heat pumps only (sized on the network-constrained stream set),
    a new heat-recovery network at the targets (cost from the area and units targets with the case's film
    coefficients and cost law: ``pinch.area``), and both. The last row repeats the heat pumps against the
    second baseline.
    """
    from pinch.area import area_target
    from pinch.area_analysis import to_kW
    from pinch.economic_analysis import refrigeration_duty
    from pinch.network import Network

    if case.basis is None:
        return Outputs({"skipped": "no annual basis"})
    info = dict(getattr(case, "retrofit_bounds", None) or {})
    status = info.get("baseline_status", "upper_bound")
    to_MWh = lambda x: to_MWh_per_year(x, energy_unit, case.basis)  # noqa: E731
    cop_ch, frac = params.chiller_cop, params.refrigeration_credit_fraction

    b0_net = Network("no heat recovery (all utilities)", ())
    b0 = evaluate_network(streams, b0_net, case.ambient_T_C)
    refr0 = b0.refrigeration
    base0 = Option("baseline: no heat recovery", to_MWh(b0.Qh), to_MWh(refr0) / cop_ch if cop_ch else 0.0)

    table = problem_table(streams)
    refrT = refrigeration_duty(streams, case.ambient_T_C, heat_recovery=True)
    baseT = Option("baseline: heat recovery at target", to_MWh(table.Qh_min), to_MWh(refrT) / cop_ch if cop_ch else 0.0)

    # new heat-recovery network at the targets
    block = case.area_targeting or {}
    h = block.get("film_coefficients_kW_per_m2K", {})
    law, law_note = _hen_cost_law(block, info.get("hen_cost_EUR_per_m2"), info.get("hen_cost_note", ""))
    hen = {"cost_law": law_note}
    hen_equipment: tuple = ()
    if law is not None and h and all(s.name in h for s in streams.streams):
        at = area_target(to_kW(streams, case, params.operating_hours_per_year), h)
        capex_hen = law.network_cost(at.area, at.units)
        hen.update({"area_m2": round(at.area, 1), "units": at.units, "capex_EUR": round(capex_hen, 0)})
        hen_equipment = (("lump_sum_EUR", capex_hen),)
    else:
        hen.update({"area_m2": None, "units": None, "capex_EUR": None,
                    "cost_law": "film coefficients missing for some streams: new-network cost not included"})

    def heat_pumps(stream_set, refr):
        d = design_from_gcc(stream_set, case.sink_levels, case.eta_lorenz, case.source_T_C)
        W = sum(u.W for u in d.units)
        # sources take over refrigeration only if they are as cold as the refrigeration duty (as in run_retrofit)
        ok = sources_can_replace_refrigeration(streams, case.source_T_C, case.ambient_T_C)
        taken = min(sum(u.Q_source for u in d.units), refr) * frac if ok else 0.0
        E = to_MWh(W) + (to_MWh(refr - taken) / cop_ch if cop_ch else 0.0)
        eq = tuple(x for u in d.units for x in heat_pump_equipment(params, u, capacity_kW(to_MWh(u.Q_sink), params)))
        return d, E, eq

    d0, E0, eq0 = heat_pumps(constrained_streams(streams, b0_net), refr0)
    dT, ET, eqT = heat_pumps(streams, refrT)
    E_hen = to_MWh(refrT) / cop_ch if cop_ch else 0.0
    cases = [
        ("Heat pumps only", base0, Option("heat pumps only", to_MWh(d0.Qh_residual), E0, eq0), d0),
        ("New heat recovery at target", base0, Option("new HEN", to_MWh(table.Qh_min), E_hen, hen_equipment), None),
        ("New heat recovery at target + heat pumps", base0,
         Option("new HEN + heat pumps", to_MWh(dT.Qh_residual), ET, hen_equipment + eqT), dT),
        ("Lower bound: plant already at target, heat pumps only", baseT,
         Option("heat pumps at target", to_MWh(dT.Qh_residual), ET, eqT), dT),
    ]
    rows = []
    for label, base, option, d in cases:
        ev = evaluate(option, base, params)
        rows.append({"option": label, "baseline": base.name.removeprefix("baseline: "),
                     "heat_pumps": ", ".join(f"{u.name} {u.Q_sink:.4g} (COP {u.COP:.2f})" for u in d.units) if d else "none",
                     "Qh_baseline": round(b0.Qh if base is base0 else table.Qh_min, 4),
                     "Qh_after": round(option.gas_heat_MWh / to_MWh(1.0), 2) if to_MWh(1.0) else None,
                     "capex_EUR": round(ev.capex_EUR, 0), "savings_EUR": round(ev.savings_EUR, 0),
                     "payback_years": round(ev.payback_years, 2) if math.isfinite(ev.payback_years) else ev.payback_years,
                     "npv_EUR": round(ev.npv_EUR, 0), "gas_reduction_vs_baseline": round(ev.gas_reduction, 4),
                     "co2_avoided_t": round(ev.co2_avoided_t, 0),
                     "break_even_ratio_NPV": round(_be(option, base, params), 3)})
    summary = {"baseline_status": status, "baseline_meaning": BASELINE_STATUS.get(status, status),
               "note": info.get("note", ""),
               "no_heat_recovery": b0.summary(), "Qh_min": round(table.Qh_min, 4),
               "new_heat_recovery_network": hen, "options": rows,
               "assumptions": {"new network": "area target (Bath formula, case film coefficients) and units target "
                                              "at the case's temperature shifts, costed per unit with the cost law",
                               "heat pumps": "case sink levels; on the no-recovery plant they are sized on the "
                                             "network-constrained stream set (no process-to-process transfer)"}}
    return Outputs(summary, {"retrofit_bounds": pd.DataFrame(rows)}, {})
