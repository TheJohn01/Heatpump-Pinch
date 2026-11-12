"""Benchmark against an independent tool: OpenPinch (gap group 8: validation).

Usage:
    python -m scripts.benchmarks.benchmark_openpinch                        # compare with the stored OpenPinch results
    python -m scripts.benchmarks.benchmark_openpinch --refresh PYTHON314    # rerun OpenPinch first (needs Python >= 3.14 with
                                                         # openpinch installed), then compare

Independent tool: Walmsley (2026), "OpenPinch: An Open-Source Python Library for Advanced Pinch Analysis and
Total Site Integration", Process Integration and Optimization for Sustainability 10, 3947-3963,
DOI 10.1007/s41660-026-00729-6 (CC BY); PyPI package ``openpinch`` 0.8.3, direct heat integration target.
OpenPinch requires Python >= 3.14 while this repository's CI runs 3.13, so its results are stored in
data/benchmarks/openpinch_0.8.3.json, written by ``--refresh`` and committed; the comparison then needs no
OpenPinch.

Both directions:
* our data sets (validated cases of this repository) run through OpenPinch;
* OpenPinch's single-zone, single-period sample cases (basic_pinch, Four-stream-Yee-and-Grossmann-1990-1,
  crude_preheat_train) run through this tool. Repeated stream names in OpenPinch are segments of one stream
  (``segment_of``). Their streams without a contribution take OpenPinch's default THERMAL_DT_CONT = 5 K.
  The samples are stored, converted, in data/benchmarks/openpinch_samples/ with their source noted.

Compared: Q̇h,min, Q̇c,min and the shifted pinch temperature. Units: OpenPinch works in kW; a data set in
another energy unit (kWh/hl) is passed as numbers, which leaves the targets in the same unit.
Writes outputs/benchmark_openpinch.csv and .md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

from pinch import load_streams, problem_table, with_extra_shift
from pinch.streams import StreamSet, streams_from_frame

ROOT = Path(__file__).resolve().parents[2]   # repository root
REFERENCE = ROOT / "data" / "benchmarks" / "openpinch_0.8.3.json"
SAMPLES = ROOT / "data" / "benchmarks" / "openpinch_samples"
OPENPINCH_DEFAULT_DT_CONT_K = 5.0      # OpenPinch configuration_fields.py, THERMAL_DT_CONT
OPENPINCH_SAMPLE_NAMES = ("basic_pinch", "Four-stream-Yee-and-Grossmann-1990-1", "crude_preheat_train")

#: our data sets: (label, file, extra shift)
OUR_CASES = (
    ("four-stream (OU notes, Kemp ch. 2)", "data/four_stream_process_streams.csv", 0.0),
    ("Northwestern four-stream", "data/northwestern_4stream.csv", 0.0),
    ("Sagli et al. four-stream", "data/sagli1990_four_stream.csv", 0.0),
    ("brewery (Padullés et al. 2026)", "data/brewery_streams.csv", 0.0),
    ("brewery, +2 K indirect", "data/brewery_streams.csv", 2.0),
    ("milk evaporator (Walmsley et al. 2024)", "data/milk_evaporator_streams.csv", 0.0),
    ("spray dryer (Walmsley et al. 2024)", "data/spray_dryer_streams.csv", 0.0),
    ("Aromatics Plant (Linnhoff and Ahmad)", "data/aromatics_plant_streams.csv", 0.0),
)

RUNNER = '''
import json, sys
from OpenPinch import PinchProblem
out = {}
for name, path in json.loads(sys.argv[1]).items():
    t = PinchProblem(path).target.direct_heat_integration()
    out[name] = {"Qh": t.hot_utility_target, "Qc": t.cold_utility_target,
                 "hot_pinch_T_star_C": t.hot_pinch, "cold_pinch_T_star_C": t.cold_pinch}
print(json.dumps(out))
'''


def _q(v: float, unit: str) -> dict:
    return {"value": float(v), "unit": unit}


def to_openpinch(streams: StreamSet) -> dict:
    """OpenPinch input (one zone, no utilities) for a stream set."""
    return {"streams": [{"zone": "Plant", "name": s.name, "t_supply": _q(s.T_in_C, "degC"),
                         "t_target": _q(s.T_out_C, "degC"), "heat_flow": _q(s.Q, "kW"),
                         "dt_cont": _q(s.dT_shift_K, "delta_degC"), "htc": _q(1.0, "kW/m^2/K")}
                        for s in streams.streams]}


def _value_C(x) -> float:
    v, unit = (x["value"], x.get("unit", "degC")) if isinstance(x, dict) else (x, "degC")
    return float(v) - 273.15 if unit == "K" else float(v)


def from_openpinch(case: dict) -> pd.DataFrame:
    """Stream table in this tool's format from an OpenPinch case (single zone, ordinary streams)."""
    rows, count = [], {}
    for s in case["streams"]:
        count[s["name"]] = count.get(s["name"], 0) + 1
    seen: dict[str, int] = {}
    for s in case["streams"]:
        T_in, T_out = _value_C(s["t_supply"]), _value_C(s["t_target"])
        if s.get("heat_flow") is not None:
            Q = float(s["heat_flow"]["value"] if isinstance(s["heat_flow"], dict) else s["heat_flow"])
        else:
            cp = s["heat_capacity_flowrate"]
            Q = float(cp["value"] if isinstance(cp, dict) else cp) * abs(T_out - T_in)
        dt = s.get("dt_cont")
        dT = OPENPINCH_DEFAULT_DT_CONT_K if dt is None else float(dt["value"] if isinstance(dt, dict) else dt)
        name = s["name"]
        seen[name] = seen.get(name, 0) + 1
        segmented = count[name] > 1
        rows.append({"stream": f"{name} [{seen[name]}]" if segmented else name,
                     "type": "hot" if T_in > T_out else "cold", "T_in_C": T_in, "T_out_C": T_out, "Q_kW": Q,
                     "dT_shift_K": dT, "segment_of": name if segmented else ""})
    return pd.DataFrame(rows)


def our_targets(streams: StreamSet) -> dict:
    t = problem_table(streams)
    return {"Qh": t.Qh_min, "Qc": t.Qc_min, "pinch_T_star_C": max(t.pinch_T_star_C) if t.pinch_T_star_C else None}


def _sample_streams(name: str) -> StreamSet:
    case = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    return streams_from_frame(from_openpinch(case), source=name)


def refresh(python314: str, samples_dir: Path | None = None) -> dict:
    """Run OpenPinch on every case and store the results (and the converted samples)."""
    SAMPLES.mkdir(parents=True, exist_ok=True)
    if samples_dir is not None:              # copy OpenPinch's own sample files, unchanged
        for n in OPENPINCH_SAMPLE_NAMES:
            (SAMPLES / f"{n}.json").write_text((samples_dir / f"{n}.json").read_text(encoding="utf-8"),
                                               encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for label, f, extra in OUR_CASES:
            p = Path(tmp) / f"{len(paths)}.json"
            p.write_text(json.dumps(to_openpinch(with_extra_shift(load_streams(ROOT / f), extra))), encoding="utf-8")
            paths[label] = str(p)
        for n in OPENPINCH_SAMPLE_NAMES:
            paths[f"OpenPinch sample: {n}"] = str(SAMPLES / f"{n}.json")
        r = subprocess.run([python314, "-I", "-c", RUNNER, json.dumps(paths)], capture_output=True, text=True,
                           check=True)
    version = subprocess.run([python314, "-I", "-c", "import importlib.metadata as m; print(m.version('openpinch'))"],
                             capture_output=True, text=True, check=True).stdout.strip()
    data = {"openpinch_version": version, "target": "direct_heat_integration", "results": json.loads(r.stdout.strip())}
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def compare(reference: dict | None = None) -> pd.DataFrame:
    ref = reference or json.loads(REFERENCE.read_text(encoding="utf-8"))
    rows = []
    cases = [(label, with_extra_shift(load_streams(ROOT / f), extra)) for label, f, extra in OUR_CASES]
    cases += [(f"OpenPinch sample: {n}", _sample_streams(n)) for n in OPENPINCH_SAMPLE_NAMES]
    for label, streams in cases:
        o, p = our_targets(streams), ref["results"][label]
        scale = max(1.0, abs(p["Qh"]), abs(p["Qc"]))
        rows.append({"case": label, "unit": streams.energy_unit,
                     "Qh_ours": round(o["Qh"], 6), "Qh_OpenPinch": round(p["Qh"], 6),
                     "Qc_ours": round(o["Qc"], 6), "Qc_OpenPinch": round(p["Qc"], 6),
                     "pinch_T_star_ours": o["pinch_T_star_C"], "pinch_T_star_OpenPinch": p["hot_pinch_T_star_C"],
                     "max_rel_deviation": round(max(abs(o["Qh"] - p["Qh"]), abs(o["Qc"] - p["Qc"])) / scale, 9)})
    return pd.DataFrame(rows)


def markdown(df: pd.DataFrame, version: str) -> str:
    lines = [f"Direct heat integration targets: this tool against OpenPinch {version} (Walmsley 2026).", "",
             "| Case | Unit | Q̇h,min ours / OpenPinch | Q̇c,min ours / OpenPinch | Pinch T* ours / OpenPinch [°C] | "
             "Max. relative deviation |", "|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        po = "–" if pd.isna(r["pinch_T_star_ours"]) else f"{r['pinch_T_star_ours']:g}"
        pp = "–" if r["pinch_T_star_OpenPinch"] is None or pd.isna(r["pinch_T_star_OpenPinch"]) \
            else f"{r['pinch_T_star_OpenPinch']:g}"
        lines.append(f"| {r['case']} | {r['unit']} | {r['Qh_ours']:.6g} / {r['Qh_OpenPinch']:.6g} | "
                     f"{r['Qc_ours']:.6g} / {r['Qc_OpenPinch']:.6g} | {po} / {pp} | {r['max_rel_deviation']:.1e} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", metavar="PYTHON314", help="interpreter with openpinch installed")
    parser.add_argument("--samples-dir", type=Path, help="OpenPinch's tutorials/sample_cases folder (with --refresh)")
    args = parser.parse_args()
    ref = refresh(args.refresh, args.samples_dir) if args.refresh else None
    ref = ref or json.loads(REFERENCE.read_text(encoding="utf-8"))
    df = compare(ref)
    out = ROOT / "outputs"
    df.to_csv(out / "benchmark_openpinch.csv", index=False)
    text = markdown(df, ref["openpinch_version"])
    (out / "benchmark_openpinch.md").write_text(text, encoding="utf-8")
    print(text)
    if (df["max_rel_deviation"] > 1e-6).any():
        sys.exit("deviation above 1e-6 in at least one case")


if __name__ == "__main__":
    main()
