"""RQ1-RQ3 for any case, against the site as it is today (step 6; dashboard and consolidate_rq.py).

Definitions (supervisor review 2026-10-17, A1-A4), for every case:

* **Today's site** (the baseline):
  - a case with a published existing network (``retrofit`` block): that network;
  - otherwise, from ``retrofit_bounds.baseline_status``: "published" means the source says the plant
    recovers no heat, so today's site is the plant with every stream on utilities; any other status
    (heat-integrated plant whose exchangers are not published, textbook example) takes the plant at its
    energy target, the lower bound of ``pinch.retrofit.retrofit_bounds``. The label says which.
* **Heat-recovery step** (the reference): the heat-recovery-only retrofit named by
  ``retrofit.heat_pump_reference``; for a plant without heat recovery, a new network at the energy target
  (cost from the area and units targets); none when today's site is already at the target.
* **Heat pumps**: sized from the GCC of the stream set after the heat-recovery step (the
  network-constrained set for a retrofit) at the case's sink levels, then numbered HP1, HP2, ... in order
  of decreasing COP (cheapest heat first, as in ``pinch.design.partial_designs``).
* **RQ1**: share of today's gas that the heat pumps replace with an INCREMENTAL simple payback no longer
  than the threshold. HP1 is searched along its partial duty over the heat-recovery step; HP2, HP3, ... are
  added in full, each only if HP1..HPk-1 are fully in and its own increment pays back within the threshold.
  The heat-recovery step is reported separately (its own share and payback), so it does not carry the
  heat pumps.
* **RQ2**: ΔTmin minimising the total annual cost with the installed cost law (``pinch.area_analysis``),
  reported with the range within 1 % of the minimum; n/a without a sourced cost law.
* **RQ3**: electricity-to-gas price ratio at which the NPV of each unit's increment is zero.

Numbers that also appear in the retrofit tables are computed with the same functions (``pinch.retrofit``,
``pinch.refrigeration``, ``pinch.economics``) and rounded the same way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pinch.area_analysis import area_targeting_outputs
from pinch.case import Case, to_MWh_per_year
from pinch.design import design_from_gcc, partial_designs
from pinch.economics import (EconomicParameters, Option, break_even_ratio, capacity_kW, evaluate,
                             heat_pump_equipment)
from pinch.heat_pump import HeatPump
from pinch.network import Network, constrained_streams, evaluate_network, load_networks
from pinch.problem_table_algorithm import problem_table
from pinch.refrigeration import CoolingCascade, refrigeration_taken_over
from pinch.streams import StreamSet

NO_HEAT_RECOVERY = "no heat recovery (all utilities)"


@dataclass(frozen=True)
class Site:
    """Today's site, the heat-recovery step and the heat pumps sized after it.

    Heat quantities in the stream-data unit unless the name says MWh.
    """

    label: str                              # what "today's site" is, in words
    baseline: Option                        # today's site
    reference: Option                       # after the heat-recovery step (= baseline when there is none)
    has_hr_step: bool
    Qh_reference: float                     # hot utility after the heat-recovery step
    refrigeration_reference: float          # refrigeration after the heat-recovery step
    cooling: CoolingCascade | None          # cooling side after the heat-recovery step
    reference_equipment: tuple
    units: tuple[HeatPump, ...]             # HP1, HP2, ... (decreasing COP)


def _chiller_MWh(refrigeration: float, to_MWh, params: EconomicParameters) -> float:
    return to_MWh(refrigeration) / params.chiller_cop if params.chiller_cop else 0.0


def build_site(case: Case, streams: StreamSet, params: EconomicParameters) -> Site:
    """Today's site, heat-recovery step and heat pumps for a case (definitions in the module docstring)."""
    from pinch.economic_analysis import cooling_cascade
    from pinch.retrofit import network_cooling, new_network_at_target, new_recovery_equipment
    if case.basis is None:
        raise ValueError("RQ1-RQ3 need an annual basis (Workflow, step 1)")
    to_MWh = lambda x: to_MWh_per_year(x, streams.energy_unit, case.basis)  # noqa: E731

    if case.retrofit:
        block = case.retrofit
        nets = load_networks(block["network_file_resolved"])
        base_net = nets[block["baseline"]]
        ref_opt = next((o for o in block["options"] if o["name"] == block.get("heat_pump_reference")), None)
        ref_net = nets[ref_opt["network"]] if ref_opt else base_net
        base_res = evaluate_network(streams, base_net, case.ambient_T_C)
        ref_res = evaluate_network(streams, ref_net, case.ambient_T_C)
        baseline = Option(f"baseline: {base_net.name}", to_MWh(base_res.Qh),
                          _chiller_MWh(base_res.refrigeration, to_MWh, params))
        equipment = tuple(new_recovery_equipment(case, streams, base_net, ref_net, params, to_MWh)[0]) if ref_opt else ()
        sizing, Qh_ref = constrained_streams(streams, ref_net), ref_res.Qh
        cooling, refr = network_cooling(streams, ref_res, case.ambient_T_C), ref_res.refrigeration
        label = f"existing network '{base_net.name}'"
        has_step = ref_opt is not None
    else:
        status = (case.retrofit_bounds or {}).get("baseline_status", "upper_bound")
        table = problem_table(streams)
        coolT = cooling_cascade(streams, case.ambient_T_C, heat_recovery=True)
        refrT = coolT.refrigeration if coolT is not None else 0.0
        sizing, Qh_ref, cooling, refr = streams, table.Qh_min, coolT, refrT
        if status == "published":          # the source says the plant recovers no heat
            b0 = evaluate_network(streams, Network(NO_HEAT_RECOVERY, ()), case.ambient_T_C)
            baseline = Option("baseline: no heat recovery", to_MWh(b0.Qh), _chiller_MWh(b0.refrigeration, to_MWh, params))
            equipment = new_network_at_target(case, streams, params)[1]
            label = "no heat recovery (as published); heat-recovery step: new network at the energy target"
            has_step = True
        else:
            baseline = Option("baseline: heat recovery at target", to_MWh(Qh_ref), _chiller_MWh(refr, to_MWh, params))
            equipment = ()
            label = ("heat recovery at the energy target (lower bound: no real plant)" if status == "hypothetical" else
                     "heat recovery at the energy target (lower bound: the exchangers in place are not published)")
            has_step = False

    reference = Option("heat recovery step", to_MWh(Qh_ref), _chiller_MWh(refr, to_MWh, params), equipment) \
        if has_step else baseline
    design = design_from_gcc(sizing, case.sink_levels, case.eta_lorenz, case.source_T_C)
    units = tuple(sorted(design.units, key=lambda u: -u.COP))
    return Site(label, baseline, reference, has_step, Qh_ref, refr, cooling, equipment, units)


def _option(site: Site, units, params: EconomicParameters, to_MWh, name: str = "") -> Option:
    """The heat-recovery step plus the given heat pumps (at the duties they carry)."""
    if not units:
        return site.reference
    taken = refrigeration_taken_over(units, site.cooling, params.refrigeration_credit_fraction)
    E = to_MWh(sum(u.W for u in units)) + _chiller_MWh(site.refrigeration_reference - taken, to_MWh, params)
    eq = site.reference_equipment + tuple(x for u in units for x in
                                          heat_pump_equipment(params, u, capacity_kW(to_MWh(u.Q_sink), params)))
    return Option(name or " + ".join(u.name for u in units),
                  to_MWh(site.Qh_reference - sum(u.Q_sink for u in units)), E, eq)


def _payback(x: float) -> float:
    return round(x, 2) if math.isfinite(x) else x


def answers(case: Case, streams: StreamSet, params: EconomicParameters, source_limited: bool = False) -> dict:
    """RQ1, RQ2, RQ3 for one case variant (definitions in the module docstring).

    ``source_limited``: no ambient heat source (supervisor review B2). HP1 may take as its source only the
    refrigeration after the heat-recovery step that its evaporator can reach (``pinch.refrigeration``), so its
    heat is capped at that refrigeration / (1 - 1/COP); the other units, whose source would be ambient, are
    left out. Returns None when the site has no refrigeration at all.
    """
    site = build_site(case, streams, params)
    to_MWh = lambda x: to_MWh_per_year(x, streams.energy_unit, case.basis)  # noqa: E731
    thr = params.payback_threshold_years
    nan = math.nan
    ev_ref = evaluate(site.reference, site.baseline, params)
    units = site.units

    # increments: HP1 over the heat-recovery step, HPk over HP1..HPk-1
    options = [site.reference] + [_option(site, units[:k], params, to_MWh) for k in range(1, len(units) + 1)]
    inc = []
    for k in range(1, len(options)):
        o, over = options[k], options[k - 1]
        ev = evaluate(o, over, params)
        inc.append({"payback_years": _payback(ev.payback_years), "delta_npv_EUR": round(ev.npv_EUR, 0),
                    "co2_avoided_t": round(ev.co2_avoided_t, 0),
                    "gas_share_of_today": round(evaluate(o, site.baseline, params).gas_reduction
                                                - evaluate(over, site.baseline, params).gas_reduction, 4),
                    "break_even_ratio_NPV": round(break_even_ratio(o, over, params, "npv"), 3)})

    # HP1 along its partial duty over the heat-recovery step
    curve = []
    if units:
        for target, partial in partial_designs(units[:1], 201):
            point = _option(site, partial, params, to_MWh, f"{target:.3f}")
            ev, inc_ev = evaluate(point, site.baseline, params), evaluate(point, site.reference, params)
            curve.append((round(target, 4), ev.gas_reduction - ev_ref.gas_reduction, inc_ev.payback_years, inc_ev.npv_EUR))

    ok = [share for _, share, pb, _ in curve if pb <= thr and share > 0]
    hp_share = round(max(ok), 4) if ok else 0.0
    for k in range(1, len(inc)):           # HP2, HP3, ...: whole units, each paying back on its own
        if inc[k]["payback_years"] <= thr and hp_share >= sum(i["gas_share_of_today"] for i in inc[:k]) - 1e-9:
            hp_share += inc[k]["gas_share_of_today"]
        else:
            break

    if source_limited:
        if not units or site.refrigeration_reference <= 0:
            return None
        u1 = units[0]
        big = u1.with_sink_duty(1e6 * max(1.0, site.Qh_reference))       # a source large enough to take all it can
        reachable = refrigeration_taken_over([big], site.cooling, 1.0)
        cap = reachable / (1 - 1 / u1.COP)                                # heat the refrigeration source can supply
        pts = [p for p in curve if p[0] <= cap + 1e-9]
        ok = [share for _, share, pb, _ in pts if pb <= thr and share > 0]
        hp_share = float(max(ok)) if ok else 0.0
        if len(pts) > 1:
            at_cap = pts[-1]
            inc = [{**inc[0], "payback_years": round(float(at_cap[2]), 2), "delta_npv_EUR": float(at_cap[3]),
                    "break_even_ratio_NPV": nan, "co2_avoided_t": nan}]
        else:                               # its evaporator reaches no refrigeration: no heat pump at all
            inc = [{"payback_years": nan, "delta_npv_EUR": nan, "break_even_ratio_NPV": nan, "co2_avoided_t": nan}]
        units = units[:1]

    full = options[-1]
    ev_full = evaluate(full, site.baseline, params)
    rq2 = _rq2(case, streams)
    out = {"RQ1_HP_gas_share": round(hp_share, 4),
           "HR_retrofit_gas_share": round(ev_ref.gas_reduction, 4) if site.has_hr_step else nan,
           "HR_retrofit_payback_y": _payback(ev_ref.payback_years) if site.has_hr_step else nan}
    for i, (u, row) in enumerate(zip(units, inc), start=1):
        out.update({f"HP{i}_name": u.name,
                    f"HP{i}_incremental_payback_y": row["payback_years"],
                    f"HP{i}_incremental_NPV_MEUR": round(row["delta_npv_EUR"] / 1e6, 3),
                    f"HP{i}_CO2_avoided_t": row["co2_avoided_t"],
                    f"RQ3_ratio_HP{i}": row["break_even_ratio_NPV"]})
    out.update({
        "RQ2_dTmin_opt_K": rq2["dTmin_opt_K"] if rq2 else nan,
        "RQ2_dTmin_within_1pct_K": f"{rq2['dTmin_within_1pct_K'][0]:g}-{rq2['dTmin_within_1pct_K'][1]:g}" if rq2 else "",
        "RQ3_ratio_full_electrification_info": round(break_even_ratio(full, site.baseline, params, "npv"), 3),
        "full_electrification_payback_y": _payback(ev_full.payback_years),
        "full_electrification_NPV_MEUR": round(round(ev_full.npv_EUR, 0) / 1e6, 3),
        "price_ratio": round(params.price_ratio, 3),
        "todays_site": site.label,
    })
    return out


def _rq2(case: Case, streams: StreamSet) -> dict | None:
    """RQ2 row of the supertargeting: the installed sourced cost law, else the first sourced law. A cost sweep
    ("sweep: ... not a sourced estimate") never answers RQ2; without a sourced law RQ2 is n/a."""
    at = area_targeting_outputs(case, streams)
    at.close_figures()
    laws = [x for x in at.summary.get("RQ2", []) if not x["cost_law"].startswith("sweep")]
    return next((x for x in laws if "installed" in x["cost_law"]), laws[0] if laws else None)


def unit_names(row: dict | object) -> list[str]:
    """HP1, HP2, ... names present in a result row (dict or DataFrame row)."""
    names, i = [], 1
    while True:
        key = f"HP{i}_name"
        v = row.get(key) if hasattr(row, "get") else None
        if not isinstance(v, str):
            return names
        names.append(v)
        i += 1
