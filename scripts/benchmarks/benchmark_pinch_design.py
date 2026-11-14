"""Pinch Design Method, loop breaking and energy relaxation against published results (Phase A6).

Usage:
    python -m scripts.benchmarks.benchmark_pinch_design

Problems and sources:
* four-stream problem of Linnhoff and Hindmarsh (1983) with CPs x 10, as used by Sagli, Gundersen and Yee
  (1990) and tabulated by Polley and Panjeh Shahi (1991), Trans IChemE 69 A, 445-457: targets Table 1
  (Q̇h 1075 kW, Q̇c 400 kW at ΔTmin 20 K), Network 5.1 (Fig. 3: 5 units at Q̇h 1075 kW, smallest approach
  8 K) and its capital cost (Fig. 1: 717.3 k$ at U = 50 W/m²K, 8600 + 670 A^0.83 $);
  data/sagli1990_four_stream.csv, data/benchmarks/sagli1990_networks.json;
* Aromatics Plant (IChemE User Guide; Linnhoff and Ahmad 1990) as tabulated by Polley and Panjeh Shahi
  (1991), Table 6, target Table 12 (Q̇h 21.68 MW); data/aromatics_plant_streams.csv;
* four-stream process of Kemp (2007) as given by the University of Oklahoma design notes, Example 1.1
  (Q̇h 7.5 MW, Q̇c 10 MW at ΔTmin 10 K); data/four_stream_process_streams.csv.

Checks: the MER network of ``pinch_design`` keeps the published energy targets with no transfer across the
pinch and has the fewest units an MER network can have ((N - 1) above plus (N - 1) below the pinch); loop
breaking at constant energy reaches the Euler minimum of 5 units of Network 5.1 (published), with the
smallest approach and the capital cost compared with 5.1; energy relaxation restores a 12 K approach and
reports the extra utility (no published value). The Linnhoff and Hindmarsh (1983) paper itself was not
available, so their own MER network and loop-breaking steps are not compared.

Writes outputs/benchmark_pinch_design.csv and .md, and the designed networks in the network-file format
(pinch.network.load_networks) to outputs/benchmark_pinch_design_networks.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pinch import load_streams
from pinch.hen_design import (
    CostLaw,
    LoopBreaking,
    PinchDesign,
    break_loops,
    evaluate_exchangers,
    pinch_design,
    series_to_network,
)
from pinch.network import evaluate_network, network_to_json
from pinch.streams import StreamSet

ROOT = Path(__file__).resolve().parents[2]   # repository root
SAGLI = ROOT / "data" / "sagli1990_four_stream.csv"
AROMATICS = ROOT / "data" / "aromatics_plant_streams.csv"
KEMP = ROOT / "data" / "four_stream_process_streams.csv"
NETWORKS = ROOT / "data" / "benchmarks" / "sagli1990_networks.json"
# utilities for the Aromatics Plant: not tabulated by the source; assumed hot and cold enough for every stream
AROMATICS_UTILITIES = {"ST": (350.0, 350.0, "hot"), "CW": (20.0, 30.0, "cold")}
NAN = float("nan")


def _row(problem: str, check: str, published: float, reproduced: float, source: str) -> dict:
    dev = round(100 * (reproduced - published) / published, 2) if published == published and published else NAN
    return {"problem": problem, "check": check, "published": published, "reproduced": round(float(reproduced), 3),
            "deviation_pct": dev, "source": source}


def _loops(streams: StreamSet, design: PinchDesign, utilities: dict, emat: float | None) -> LoopBreaking:
    """Break the loops of an MER design; ``emat`` None keeps the energy and lets the approach fall."""
    ends = {x.name: (x.T_in_C, x.T_out_C, x.kind) for x in streams.streams}
    ends.update(utilities)
    process = {x.name for x in streams.streams}
    req = {(a, b): emat or 0.0 for a in process for b in process}
    return break_loops(design.unit_loads(), ends, req, {"ST"}, {"CW"}, relax=emat is not None)


def run() -> tuple[pd.DataFrame, dict]:
    data = json.loads(NETWORKS.read_text(encoding="utf-8"))
    rows: list[dict] = []
    networks: dict = {}
    problems = [("four-stream (Sagli et al. 1990)", SAGLI, (1075.0, "Table 1"), (400.0, "Table 1")),
                ("Aromatics Plant", AROMATICS, (21680.0, "Table 12, targeting"), (NAN, "not tabulated")),
                ("four-stream (Kemp 2007)", KEMP, (7.5, "Oklahoma notes, Example 1.1"),
                 (10.0, "Oklahoma notes, Example 1.1"))]
    for label, path, qh, qc in problems:
        s = load_streams(path)
        d = pinch_design(s, "ST", "CW")
        net = d.to_network(f"{label}: MER (Pinch Design Method)",
                           f"pinch_design on {path.name}; heaters and coolers are the unmatched stream ends")
        networks[net.name] = network_to_json(net)
        r = evaluate_network(s, net)
        u = s.energy_unit
        rows += [_row(label, f"MER network Q̇h [{u}]", qh[0], r.Qh, qh[1]),
                 _row(label, f"MER network Q̇c [{u}]", qc[0], r.Qc, qc[1]),
                 _row(label, f"MER network transfer across the pinch [{u}]", 0.0,
                      r.cross_pinch_matches + r.heaters_below_pinch + r.coolers_above_pinch, "pinch rule"),
                 _row(label, "MER network units", NAN, d.units,
                      f"fewest units of an MER network, (N - 1) above + (N - 1) below the pinch: {d.units_target}"),
                 _row(label, "MER network stream splits", NAN, d.splits, "not published")]

    label = "four-stream (Sagli et al. 1990)"
    s = load_streams(SAGLI)
    d = pinch_design(s, "ST", "CW")
    nd = data["networks"]["5.1"]
    utilities = {k: (v[0], v[1], v[2]) for k, v in data["utilities"].items()}
    process = {x.name for x in s.streams}
    lb = _loops(s, d, utilities, None)
    h = dict.fromkeys([*utilities, *process], data["h_kW_per_m2K"])
    cost = evaluate_exchangers(lb.network.exchangers, h, CostLaw(**data["cost_law"]))["cost"]
    rows += [_row(label, "loops broken at constant energy: units", len(nd["matches"]), len(lb.units),
                  "Network 5.1 (Fig. 3), the Euler minimum"),
             _row(label, "loops broken at constant energy: Q̇h [kW]", sum(q for a, _, q in nd["matches"] if a == "ST"),
                  lb.hot_utility, "Network 5.1 (Fig. 3)"),
             _row(label, "loops broken at constant energy: smallest approach [K]", 8.0, lb.network.min_approach_K,
                  "Network 5.1 (Fig. 3); comparison, a different network"),
             _row(label, "loops broken at constant energy: capital cost [$]", nd["published_capital_cost"], cost,
                  "Network 5.1 (Fig. 1) at U = 50 W/m²K; comparison, a different network")]
    networks[f"{label}: loops broken at constant energy"] = network_to_json(
        series_to_network("loops broken", lb.network, process))
    lb12 = _loops(s, d, utilities, 12.0)
    rows += [_row(label, "loops broken, approach restored to 12 K: units", NAN, len(lb12.units),
                  "energy relaxation; not published"),
             _row(label, "loops broken, approach restored to 12 K: Q̇h [kW]", NAN, lb12.hot_utility,
                  "energy relaxation; not published")]
    networks[f"{label}: loops broken, 12 K approach"] = network_to_json(
        series_to_network("loops broken, 12 K", lb12.network, process))

    s = load_streams(AROMATICS)
    lb = _loops(s, pinch_design(s, "ST", "CW"), AROMATICS_UTILITIES, 10.0)
    rows += [_row("Aromatics Plant", "loops broken, approach >= 10 K: units", NAN, len(lb.units),
                  "energy relaxation; not published (utilities assumed)"),
             _row("Aromatics Plant", f"loops broken, approach >= 10 K: Q̇h [{s.energy_unit}]", 21680.0,
                  lb.hot_utility, "Table 12 target; utilities assumed")]
    return pd.DataFrame(rows), networks


def markdown(df: pd.DataFrame) -> str:
    lines = ["Pinch Design Method, loop breaking and energy relaxation (pinch.hen_design).", "",
             "| Problem | Check | Published | Reproduced | Deviation | Source |", "|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        pub = "–" if pd.isna(r["published"]) else f"{r['published']:,.6g}"
        dev = "–" if pd.isna(r["deviation_pct"]) else f"{r['deviation_pct']:+.2f} %"
        lines.append(f"| {r['problem']} | {r['check']} | {pub} | {r['reproduced']:,.6g} | {dev} | {r['source']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    df, networks = run()
    out = ROOT / "outputs"
    df.to_csv(out / "benchmark_pinch_design.csv", index=False)
    (out / "benchmark_pinch_design_networks.json").write_text(
        json.dumps({"networks": networks}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    text = markdown(df)
    (out / "benchmark_pinch_design.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
