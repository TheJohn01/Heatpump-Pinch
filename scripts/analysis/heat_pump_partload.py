"""TESPy check of the selected heat pump cycles: design COP, part load and component cost (steps 4b, 6).

Usage:
    python -m scripts.analysis.heat_pump_partload cases/brewery.json

For every unit whose selected cycle (outputs/<case>/cycle_screening.json) is single stage, rebuilds the
plain single-stage cycle of the same fluid in TESPy (``pinch.tespy_heat_pump``) at the unit's average
capacity, and writes
* outputs/<case>/heat_pump_partload.csv: COP from ``pinch.cycle`` and from TESPy at the design point
  (no compressor heat loss, motor efficiency 1, no SLHX, so both models describe the same cycle), and
  TESPy's off-design COP at 100-60 % of the design heat;
* outputs/<case>/heat_pump_cost_check.csv: component cost (Kosmadakis et al. 2020, as implemented in
  heatpumps) against the case's heat pump cost function (Padullés et al. 2026, Table 3) at the same
  capacity.
Units with a cascade or two-stage cycle are listed as not rebuilt.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from pinch import load_streams, with_extra_shift
from pinch.case import load_case, to_MWh_per_year
from pinch.cycle import CycleAssumptions, SecondaryStream, single_stage
from pinch.cycle_analysis import load_selected
from pinch.design import design_from_gcc
from pinch.economics import capacity_kW, load_economics
from pinch.tespy_heat_pump import KOSMADAKIS2020, SingleStageTespy, kosmadakis_cost

ROOT = Path(__file__).resolve().parents[2]   # repository root
FRACTIONS = (1.0, 0.9, 0.8, 0.7, 0.6)
COMPARISON = CycleAssumptions(heat_loss_factor=0.0, eta_motor=1.0)


def run(case_file: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    case = load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    design = design_from_gcc(streams, case.sink_levels, case.eta_lorenz, case.source_T_C)
    selected = load_selected(ROOT / "outputs" / case.name / "cycle_screening.json") or {}
    params = load_economics(case.economics)
    load_rows, cost_rows = [], []
    for u in design.units:
        sel = selected.get(u.name)
        if not sel or not sel["layout"].startswith("single stage"):
            load_rows.append({"unit": u.name, "fluid": sel["fluid"] if sel else "", "load_fraction": math.nan,
                              "COP_pinch_cycle": math.nan, "COP_tespy": math.nan, "eta_s_tespy": math.nan,
                              "note": f"not rebuilt: selected layout '{sel['layout'] if sel else 'none'}'"})
            continue
        source, sink = SecondaryStream(u.T_source_in_C, u.T_source_out_C), SecondaryStream(u.T_sink_in_C,
                                                                                            u.T_sink_out_C)
        r = single_stage(sel["fluid"], source, sink, COMPARISON)
        kW = capacity_kW(to_MWh_per_year(u.Q_sink, streams.energy_unit, case.basis), params)
        model = SingleStageTespy(sel["fluid"], source, sink, r, kW, COMPARISON)
        d = model.design(r.COP)
        for f in FRACTIONS:
            cop, eta_s, ok = model.part_load(f)
            load_rows.append({"unit": u.name, "fluid": sel["fluid"], "load_fraction": f,
                              "COP_pinch_cycle": round(r.COP, 4) if f == 1.0 else math.nan,
                              "COP_tespy": (round(cop, 4) if f == 1.0 else round(cop, 3)) if ok else math.nan,
                              "eta_s_tespy": round(eta_s, 3) if ok else math.nan,
                              "note": "design point" if f == 1.0 else
                              ("TESPy default characteristic lines" if ok else "TESPy did not converge cleanly")})
        c = kosmadakis_cost(d.V_suction_m3_h, d.UA_evaporator_W_K, d.UA_condenser_W_K)
        padulles = sum(params.cost_functions[k].cost(kW) for k in params.heat_pump_cost_items(u)[0])
        cost_rows.append({"unit": u.name, "fluid": sel["fluid"], "Q_sink_kW": round(kW, 1),
                          "V_suction_m3_h": round(d.V_suction_m3_h, 1),
                          "A_evaporator_m2": round(d.UA_evaporator_W_K / 1500.0, 1),
                          "A_condenser_m2": round(d.UA_condenser_W_K / 3500.0, 1),
                          "components_EUR": round(c.compressor + c.evaporator + c.condenser),
                          "equipment_EUR": round(c.equipment), "total_capital_EUR": round(c.total_capital),
                          "cost_year": c.year, "case_cost_function_EUR": round(padulles),
                          "ratio_total_to_case": round(c.total_capital / padulles, 3),
                          "method": KOSMADAKIS2020})
    return pd.DataFrame(load_rows), pd.DataFrame(cost_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    load, cost = run(args.case_file)
    out = ROOT / "outputs" / load_case(args.case_file).name
    load.to_csv(out / "heat_pump_partload.csv", index=False)
    cost.to_csv(out / "heat_pump_cost_check.csv", index=False)
    print(load.to_string(index=False))
    print(cost.drop(columns="method").to_string(index=False))


if __name__ == "__main__":
    main()
