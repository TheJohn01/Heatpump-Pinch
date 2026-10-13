"""Working-fluid screening for a GCC-based design (workflow step 4b).

For each heat pump of the design, every fluid/layout listed in the case file
("heat_pumps.cycle_screening") is optimised with ``pinch.cycle`` between the
unit's source and sink temperatures. The best feasible configuration (highest
COP) gives a cycle-based Lorenz efficiency, η_cycle = COP_cycle / COP_Lorenz,
which can replace the assumed η_L in the design and the economics.

Case-file block::

    "cycle_screening": {
        "fluids": ["CarbonDioxide", "n-Propane", ...],     # CoolProp names
        "layouts": ["std", "slhx", "exp"],                  # single stage variants
        "cascades": [["Ammonia", "n-Butane"], ...],         # [bottom, top]; top with SLHX
        "units": ["HTHP (wort boiling)"]                    # optional: restrict cascades to these units
    }

Selection is by COP only. Pressure ratio and discharge temperature are
reported for each option but not screened (no sourced limits); the engineer
should reject impractical options explicitly in the case file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from pinch.cycle import CycleAssumptions, CycleResult, SecondaryStream, cascade, single_stage
from pinch.design import HeatPumpDesign


def _row(unit_name: str, r: CycleResult, eta_assumed: float) -> dict:
    d = {"unit": unit_name, "fluid": r.fluid, "layout": r.layout, "feasible": r.feasible,
         "COP": r.COP, "COP_lorenz": r.COP_lorenz, "eta_lorenz_cycle": r.eta_lorenz,
         "eta_lorenz_assumed": eta_assumed, "T_evap_C": r.T_evap_C, "T_cond_C": r.T_cond_C,
         "P_low_bar": r.P_low_bar, "P_high_bar": r.P_high_bar, "pressure_ratio": r.pressure_ratio,
         "T_discharge_C": r.T_discharge_C, "transcritical": r.transcritical, "note": r.note}
    if r.stages:
        b, t = r.stages
        d.update({"T_evap_C": b.T_evap_C, "pressure_ratio": f"{b.pressure_ratio:.2f} / {t.pressure_ratio:.2f}",
                  "P_high_bar": f"{b.P_high_bar:.1f} / {t.P_high_bar:.1f}",
                  "T_discharge_C": f"{b.T_discharge_C:.0f} / {t.T_discharge_C:.0f}",
                  "T_cond_C": t.T_cond_C})
    return {k: (round(v, 4) if isinstance(v, float) and math.isfinite(v) else v) for k, v in d.items()}


def screen_design(design: HeatPumpDesign, block: dict,
                  assumptions: CycleAssumptions = CycleAssumptions()) -> tuple[pd.DataFrame, dict]:
    """Screen working fluids for every unit of a design.

    Returns
    -------
    (table, selected)
        table: one row per unit and configuration; selected: per unit, the best
        feasible configuration with its cycle-based Lorenz efficiency.
    """
    rows, selected = [], {}
    layouts = block.get("layouts", ["std", "slhx"])
    cascade_units = block.get("units")
    for u in design.units:
        source = SecondaryStream(u.T_source_in_C, u.T_source_out_C)
        sink = SecondaryStream(u.T_sink_in_C, u.T_sink_out_C)
        results: list[CycleResult] = []
        for fl in block.get("fluids", []):
            for lay in layouts:
                results.append(single_stage(fl, source, sink, assumptions, slhx="slhx" in lay, expander="exp" in lay))
        if cascade_units is None or u.name in cascade_units:
            for lo, hi in block.get("cascades", []):
                results.append(cascade(lo, hi, source, sink, assumptions, slhx_high=True))
        rows += [_row(u.name, r, u.eta_lorenz) for r in results]
        ok = [r for r in results if r.feasible]
        if ok:
            best = max(ok, key=lambda r: r.COP)
            selected[u.name] = {"fluid": best.fluid, "layout": best.layout, "COP": round(best.COP, 4),
                                "eta_lorenz_cycle": round(best.eta_lorenz, 4), "eta_lorenz_assumed": u.eta_lorenz,
                                "COP_assumed": round(u.COP, 4), "note": best.note}
    table = pd.DataFrame(rows).sort_values(["unit", "feasible", "COP"], ascending=[True, False, False])
    return table, selected


def write_screening(table: pd.DataFrame, selected: dict, assumptions: CycleAssumptions, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "cycle_screening.csv", index=False)
    path = out / "cycle_screening.json"
    path.write_text(json.dumps({"assumptions": assumptions.__dict__, "selected": selected}, indent=2,
                               ensure_ascii=False), encoding="utf-8")
    return path


def load_selected(path: Path) -> dict | None:
    """Selected configurations per unit from a screening file, or None if absent."""
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("selected")
