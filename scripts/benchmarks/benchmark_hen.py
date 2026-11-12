"""Network design checks against published results (gap groups 5 and 8; workflow steps 2, 3, 5).

Usage:
    python -m scripts.benchmarks.benchmark_hen

Source: Polley and Panjeh Shahi (1991), "Interfacing heat exchanger network synthesis and detailed heat
exchanger design", Trans IChemE 69 A, 445-457, with the four-stream problem of Sagli, Gundersen and Yee
(1990) and the Aromatics Plant of the IChemE User Guide (Linnhoff and Ahmad 1990) as they tabulate them.
Inputs: data/sagli1990_four_stream.csv, data/aromatics_plant_streams.csv, data/benchmarks/sagli1990_networks.json.

1. Targets: four-stream problem at ΔTmin 20 K (Table 1: Q̇h 1075 kW, Q̇c 400 kW); Aromatics Plant at
   ΔTmin 20 K (Table 12, targeting stage: 21.68 MW).
2. Network evaluation: Networks 6.1 and 5.1 entered from Figs 2-3, placed in series (``series_network``),
   sized at U = 50 W/m²K and costed with 8600 + 670 A^0.83 $ (Table 1): exchanger sizes against Tables 4-5
   ("expected size") and capital cost against Fig. 1 (k$ 716.0, 717.3).
3. Synthesis (``min_units_matches``) at Q̇h 1075 kW: with every exchanger at ≥ 20 K, and with exchanger
   approaches down to 8 K, the smallest approach in Network 5.1 (the published networks keep the energy
   of ΔTmin 20 K but let single exchangers approach closer: 8 K in 5.1, 12.9 K in 6.1).
4. Film coefficients from pressure drop (``pinch.pressure_drop``, tube-side relation, Table 3 properties,
   90 % of the allowable drop usable): process-exchanger areas of 6.1 and 5.1 against the detailed
   Bell-Delaware designs (Tables 4-5, "actual size"). A comparison: their designs put some streams on a
   shell side, whose correlation constant is not published.

Writes outputs/benchmark_hen.csv and .md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pinch import load_streams, problem_table
from pinch.hen_design import CostLaw, MatchLoad, UtilityStream, evaluate_exchangers, min_units_matches, series_network
from pinch.pressure_drop import TUBE_EXPONENT, Fluid, coefficients_from_pressure_drop, tube_side_K

ROOT = Path(__file__).resolve().parents[2]   # repository root
SAGLI = ROOT / "data" / "sagli1990_four_stream.csv"
AROMATICS = ROOT / "data" / "aromatics_plant_streams.csv"
NETWORKS = ROOT / "data" / "benchmarks" / "sagli1990_networks.json"


def _row(check: str, published: float, reproduced: float, source: str) -> dict:
    return {"check": check, "published": published, "reproduced": round(reproduced, 3),
            "deviation_pct": round(100 * (reproduced - published) / published, 2) if published else float("nan"),
            "source": source}


def run() -> pd.DataFrame:
    data = json.loads(NETWORKS.read_text(encoding="utf-8"))
    s = load_streams(SAGLI)
    rows = []
    t = problem_table(s)
    rows += [_row("four-stream Q̇h,min [kW]", 1075.0, t.Qh_min, "Table 1"),
             _row("four-stream Q̇c,min [kW]", 400.0, t.Qc_min, "Table 1"),
             _row("Aromatics Plant Q̇h,min [kW]", 21680.0, problem_table(load_streams(AROMATICS)).Qh_min,
                  "Table 12, targeting")]

    ends = {x.name: (x.T_in_C, x.T_out_C, x.kind) for x in s.streams}
    ends.update({k: (v[0], v[1], v[2]) for k, v in data["utilities"].items()})
    h = {k: data["h_kW_per_m2K"] for k in ends}
    law = CostLaw(**data["cost_law"])
    networks = {}
    for name, nd in data["networks"].items():
        matches = tuple(MatchLoad(a, b, q) for a, b, q in nd["matches"])
        net = series_network(matches, ends)
        networks[name] = net
        ev = evaluate_exchangers(net.exchangers, h, law)
        for x in ev["exchangers"]:
            key = f"{x['hot']}-{x['cold']}"
            rows.append(_row(f"Network {name} {key} area [m²]", nd["published_expected_area_m2"][key], x["area_m2"],
                             "Tables 4-5, expected size"))
        rows.append(_row(f"Network {name} capital cost [$]", nd["published_capital_cost"], ev["cost"], "Fig. 1"))
        rows.append(_row(f"Network {name} smallest approach [K]", float("nan"), net.min_approach_K,
                         "not published; read from Figs 2-3"))

    for emat in (20.0, 8.0):
        sh = load_streams(SAGLI)
        sh = type(sh)(tuple(type(x)(x.name, x.kind, x.T_in_C, x.T_out_C, x.Q, emat / 2) for x in sh.streams),
                      sh.energy_unit, sh.source)
        r = min_units_matches(sh, [UtilityStream("ST", "hot", 180, 180, emat / 2)],
                              [UtilityStream("CW", "cold", 10, 15, emat / 2)], Qh=1075.0)
        rows.append({"check": f"minimum units at Q̇h 1075 kW, exchanger approach ≥ {emat:g} K",
                     "published": 5.0 if emat == 8.0 else float("nan"), "reproduced": r.units,
                     "deviation_pct": float("nan"),
                     "source": "Network 5.1 has 5 units at an 8 K approach; Euler minimum " + str(r.euler_minimum)})

    dd = data["detailed_design_data"]
    f = Fluid(dd["rho_kg_m3"], dd["mu_Pa_s"], dd["k_W_mK"], dd["cp_J_kgK"])
    K = {x.name: tube_side_K(f, dd["tube_bore_m"], x.CP * 1000 / (dd["rho_kg_m3"] * dd["cp_J_kgK"])) for x in s.streams}
    pd_res = coefficients_from_pressure_drop(s, {k: v * 1000 for k, v in dd["dP_kPa"].items()}, K,
                                             {x.name: TUBE_EXPONENT for x in s.streams},
                                             {x.name: dd["Rf_m2K_W"] for x in s.streams})
    hk = {k: v / 1000 for k, v in pd_res.h.items()}
    Rk = {k: dd["Rf_m2K_W"] * 1000 for k in hk}
    for name, nd in data["networks"].items():
        proc = {tuple(k.split("-")) for k in nd["published_actual_area_m2"]}
        ex = tuple(e for e in networks[name].exchangers if (e.hot, e.cold) in proc)
        ev = evaluate_exchangers(ex, hk, None, Rk)
        rows.append(_row(f"Network {name} process area, pressure-drop basis [m²]",
                         sum(nd["published_actual_area_m2"].values()), ev["area_m2"],
                         "Tables 4-5, actual size (Bell-Delaware); comparison"))
        assumed = evaluate_exchangers(ex, h, None)
        rows.append(_row(f"Network {name} process area, assumed h = 100 W/m²K [m²]",
                         sum(nd["published_actual_area_m2"].values()), assumed["area_m2"],
                         "the coefficient Sagli et al. assumed; comparison"))
    for k, v in pd_res.h.items():
        rows.append({"check": f"film coefficient {k}, pressure-drop basis [W/m²K]", "published": float("nan"),
                     "reproduced": round(v, 1), "deviation_pct": float("nan"),
                     "source": "Tables 4-5 give 600-1230 W/m²K from detailed design"})
    return pd.DataFrame(rows)


def markdown(df: pd.DataFrame) -> str:
    lines = ["Network design checks against Polley and Panjeh Shahi (1991).", "",
             "| Check | Published | Reproduced | Deviation | Source |", "|---|---|---|---|---|"]
    for _, r in df.iterrows():
        pub = "–" if pd.isna(r["published"]) else f"{r['published']:,.6g}"
        dev = "–" if pd.isna(r["deviation_pct"]) else f"{r['deviation_pct']:+.2f} %"
        lines.append(f"| {r['check']} | {pub} | {r['reproduced']:,.6g} | {dev} | {r['source']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    df = run()
    out = ROOT / "outputs"
    df.to_csv(out / "benchmark_hen.csv", index=False)
    text = markdown(df)
    (out / "benchmark_hen.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
