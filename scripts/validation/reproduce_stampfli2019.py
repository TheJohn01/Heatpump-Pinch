"""Reproduction of the non-continuous dairy site of Stampfli et al. (2019), the validation case of
``pinch.time_slices`` (workflow steps 2-4).

Usage:
    python -m scripts.validation.reproduce_stampfli2019

Source: Stampfli, Atkins, Olsen, Walmsley, Wellig (2019), "Practical heat pump and storage integration into
non-continuous processes: A hybrid approach utilizing insight based and nonlinear programming techniques",
Energy 182, 236-253, DOI 10.1016/j.energy.2019.05.218 (CC BY). Stream data: Table 1, transcribed to
data/stampfli2019_dairy_streams.csv (CP, temperatures and times; ΔTmin 10 K, so ΔT_shift 5 K, Sec. 3.2).
Companion paper: Stampfli et al. (2018), CET 70, 1789-1794, DOI 10.3303/CET1870299 (Table 2, graphical
method: the temperatures of the same heat pump).

Checks
------
* Table 1 internal consistency: ΔH = CP x ΔT and kWh = kW x running time (one known mismatch in the
  source: wash water heating, CP x ΔT = 242.9 vs 260.25 kW printed).
* With the paper's T*co,sel = 33.8 °C, ζ = 0.35, η_drive = 0.9 (Sec. 2.3, 3.2): T*ev from Eq. 9, real
  temperatures (Eqs 5-6), COP (Eq. 7), and storage capacities for 24 h operation (Sec. 2.4, 3.2).
* Time Slice and Time Average targets (not published; reported for the comparison of the two bounds).

Writes outputs/stampfli2019_checks.csv and outputs/stampfli2019_slices.csv.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pinch.time_slices import (
    load_schedule,
    storage_heat_pump,
    tam_targets,
    time_slices,
    tsm_targets,
)

ROOT = Path(__file__).resolve().parents[2]   # repository root
DATA = ROOT / "data" / "stampfli2019_dairy_streams.csv"
T_CO_STAR_C, DTMIN_K = 33.8, 10.0
#: Published values. CET 2018 = Stampfli et al. (2018), Table 2 and text; Energy 2019 = Sec. 3.2.
PUBLISHED = {
    "T_co_C": (46.26, "CET 2018, Table 2 (graphical method)"),
    "T_ev_C": (-4.56, "CET 2018, Table 2 (graphical method)"),
    "COP": (2.2, "CET 2018, Sec. 4 text"),
    "T_ev_star_C": (8.3, "Energy 2019, Sec. 3.2 (inconsistent with CET 2018 Table 2: -4.56 + 12.5 = 7.94)"),
    "hot_storage_MWh": (1.35, "Energy 2019, Sec. 3.2 (condenser side)"),
    "cold_storage_MWh": (0.68, "Energy 2019, Sec. 3.2 (evaporator side, at T*ev = 8.3 °C)"),
}


def table1_consistency(path: Path = DATA) -> pd.DataFrame:
    """CP x ΔT for each stream; the kWh column follows from the running times."""
    d = pd.read_csv(path)
    d["dH_kW"] = d["CP_kW_per_K"] * (d["T_out_C"] - d["T_in_C"]).abs()
    d["dH_kWh"] = d["dH_kW"] * (d["t_end_h"] - d["t_start_h"])
    return d[["stream", "dH_kW", "dH_kWh"]]


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    sched = load_schedule(DATA)
    hp = storage_heat_pump(sched, T_CO_STAR_C, DTMIN_K)
    hp_83 = storage_heat_pump(sched, T_CO_STAR_C, DTMIN_K, T_ev_star_C=8.3)
    got = {"T_co_C": hp.T_co_C, "T_ev_C": hp.T_ev_C, "COP": hp.COP, "T_ev_star_C": hp.T_ev_star_C,
           "hot_storage_MWh": hp.hot_storage_kWh / 1000, "cold_storage_MWh": hp.cold_storage_kWh / 1000}
    rows = [{"quantity": k, "published": v, "reproduced": round(got[k], 3),
             "deviation": round(got[k] - v, 3), "source": src} for k, (v, src) in PUBLISHED.items()]
    rows.append({"quantity": "cold_storage_MWh at T*ev = 8.3 °C", "published": 0.68,
                 "reproduced": round(hp_83.cold_storage_kWh / 1000, 3),
                 "deviation": round(hp_83.cold_storage_kWh / 1000 - 0.68, 3),
                 "source": "Energy 2019 value of T*ev imposed; cold side then unbalanced by "
                           f"{hp_83.cold_side_imbalance_kWh:+.0f} kWh/day"})
    tsm, tam = tsm_targets(sched), tam_targets(sched)
    for k in ("Qh_kWh", "Qc_kWh", "recovery_kWh"):
        rows.append({"quantity": f"TSM {k} per day (direct recovery only)", "published": float("nan"),
                     "reproduced": round(tsm[k], 1), "deviation": float("nan"), "source": "not published"})
        rows.append({"quantity": f"TAM {k} per day (storage at any temperature)", "published": float("nan"),
                     "reproduced": round(tam[k], 1), "deviation": float("nan"), "source": "not published"})
    slices = pd.DataFrame([{"t0_h": s.t0_h, "t1_h": s.t1_h,
                            "Qh_min_kW": round(s.table.Qh_min, 2) if s.table else 0.0,
                            "Qc_min_kW": round(s.table.Qc_min, 2) if s.table else 0.0,
                            "pinch_T_star_C": max(s.table.pinch_T_star_C) if s.table and s.table.pinch_T_star_C else None,
                            "condenser_demand_kW": round(q, 2), "evaporator_supply_kW": round(e, 2)}
                           for s, q, e in zip(time_slices(sched), hp.condenser_demand_kW, hp.evaporator_supply_kW)])
    return pd.DataFrame(rows), slices


def main() -> None:
    checks, slices = run()
    out = ROOT / "outputs"
    checks.to_csv(out / "stampfli2019_checks.csv", index=False)
    slices.to_csv(out / "stampfli2019_slices.csv", index=False)
    print(checks.to_string(index=False))
    print()
    print(slices.to_string(index=False))


if __name__ == "__main__":
    main()
