"""Shell-and-tube rating (``pinch.exchanger_rating``, ht library) against detailed designs (workflow step 5).

Usage:
    python -m scripts.benchmarks.benchmark_exchanger_rating

Source: Polley and Panjeh Shahi (1991), Trans IChemE 69 A, 445-457, Tables 3-5: Bell-Delaware designs of
the exchangers of Networks 6.1 and 5.1 for the four-stream problem of Sagli et al. (1990). Inputs:
data/sagli1990_four_stream.csv, data/benchmarks/sagli1990_networks.json (matches),
data/benchmarks/polley1991_exchanger_designs.json (geometry and results, transcribed).

Checks, per exchanger (end temperatures from ``series_network`` as in benchmark_hen):
1. number of shells in series for F >= 0.8 (ht.hx.F_LMTD_Fakheri) against the published count;
2. tube side (cold stream, Table 3 properties, fouling 0.00018 m²K/W, steel wall k 45 W/mK assumed):
   h_io from the Colburn relation (ht) and ΔP_t from the Darcy factor (fluids) against Tables 4-5; the
   Gnielinski correlation is listed for comparison;
3. actual area from the published U, our F and ΔT_LM: A = Q / (U F ΔT_LM) against the published size.

Writes outputs/benchmark_exchanger_rating.csv and .md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pinch import load_streams
from pinch.exchanger_rating import F_MIN_DEFAULT, TubeBundle, shells_required, tube_side
from pinch.hen_design import MatchLoad, series_network
from pinch.pressure_drop import Fluid

ROOT = Path(__file__).resolve().parents[2]   # repository root
SAGLI = ROOT / "data" / "sagli1990_four_stream.csv"
NETWORKS = ROOT / "data" / "benchmarks" / "sagli1990_networks.json"
DESIGNS = ROOT / "data" / "benchmarks" / "polley1991_exchanger_designs.json"


def _row(check: str, published: float, reproduced: float, source: str) -> dict:
    return {"check": check, "published": published, "reproduced": round(reproduced, 3),
            "deviation_pct": round(100 * (reproduced - published) / published, 2), "source": source}


def run() -> pd.DataFrame:
    nets = json.loads(NETWORKS.read_text(encoding="utf-8"))
    designs = json.loads(DESIGNS.read_text(encoding="utf-8"))["networks"]
    p = nets["detailed_design_data"]
    fluid = Fluid(rho=p["rho_kg_m3"], mu=p["mu_Pa_s"], k=p["k_W_mK"], cp=p["cp_J_kgK"])
    s = load_streams(SAGLI)
    CP_W_K = {x.name: 1e3 * x.Q / abs(x.T_in_C - x.T_out_C) for x in s.streams}
    ends = {x.name: (x.T_in_C, x.T_out_C, x.kind) for x in s.streams}
    ends.update({k: (v[0], v[1], v[2]) for k, v in nets["utilities"].items()})
    rows = []
    for name, nd in nets["networks"].items():
        net = series_network(tuple(MatchLoad(a, b, q) for a, b, q in nd["matches"]), ends)
        for e in net.exchangers:
            key = f"{e.hot}-{e.cold}"
            d = designs[name][key]
            tag = f"Network {name} {d['label']} ({key})"
            n, F = shells_required(e, F_MIN_DEFAULT)
            rows.append(_row(f"{tag} shells", d["shells"], n, "Tables 4-5, no. of shells"))
            if "tubes" not in d:
                continue
            b = TubeBundle(d["tubes"], d["passes"], d["d_i_mm"] / 1e3, d["d_o_mm"] / 1e3, d["length_mm"] / 1e3,
                           shells=d["shells"])
            m = CP_W_K[d["tube_stream"]] / fluid.cp
            col = tube_side(fluid, m, b, p["Rf_m2K_W"], "colburn")
            gni = tube_side(fluid, m, b, p["Rf_m2K_W"], "gnielinski")
            rows += [_row(f"{tag} tube-side h_io [W/m²K], Colburn", d["h_io"], col.h_io_W_m2K, "Tables 4-5"),
                     _row(f"{tag} tube-side h_io [W/m²K], Gnielinski (comparison)", d["h_io"], gni.h_io_W_m2K,
                          "Tables 4-5"),
                     _row(f"{tag} tube-side ΔP [kPa]", d["dP_t_kPa"], col.dP_Pa / 1e3, "Tables 4-5"),
                     _row(f"{tag} area from published U and our F [m²]", d["actual_area_m2"],
                          1e3 * e.Q / (d["U"] * F * e.lmtd_K), "Tables 4-5, actual size")]
    return pd.DataFrame(rows)


def main() -> None:
    df = run()
    out = ROOT / "outputs"
    df.to_csv(out / "benchmark_exchanger_rating.csv", index=False)
    shells = df[df["check"].str.endswith("shells")]
    lines = ["Shell-and-tube rating (ht) against Polley and Panjeh Shahi (1991), Tables 4-5.", "",
             f"Shell counts: {int((shells['deviation_pct'] == 0).sum())} of {len(shells)} as published "
             f"(F >= {F_MIN_DEFAULT}).", "",
             "| Check | Published | Reproduced | Deviation | Source |", "|---|---|---|---|---|"]
    for r in df.itertuples():
        lines.append(f"| {r.check} | {r.published:,.4g} | {r.reproduced:,.4g} | {r.deviation_pct:+.2f} % | {r.source} |")
    text = "\n".join(lines) + "\n"
    (out / "benchmark_exchanger_rating.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
