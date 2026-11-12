"""Minimum number of matches against the Letsios et al. (2018) benchmark (workflow step 5).

Usage:
    python -m scripts.benchmarks.benchmark_min_matches

Runs ``pinch.hen_design.min_units_matches`` on the Furman and Sahinidis (2004) instances as digitised by
Letsios, Kouyialis and Misener (2018), Computers and Chemical Engineering 113, 57-85, and compares the
number of units with their exact results (CPLEX and Gurobi, relative gap 4 %). The instances and the
published values are in data/benchmarks/letsios2018/ (Apache License 2.0; repository
github.com/TYT0710/min_matches_heuristics).

Conventions: a global ΔTmin becomes an individual shift of ΔTmin/2 on every stream and utility, which gives
the same feasible matches. The hot utility is the smallest one these utilities allow
(``min_hot_utility``), as in the paper's minimum-utility step; with one hot and one cold utility, the
utility costs in the files play no role.

Writes outputs/benchmark_min_matches.csv and .md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pinch.hen_design import UtilityStream, min_units_matches
from pinch.problem_table_algorithm import problem_table
from pinch.streams import Stream, StreamSet

ROOT = Path(__file__).resolve().parents[2]   # repository root
DATA = ROOT / "data" / "benchmarks" / "letsios2018"
TIME_LIMIT_S = 60.0


def load_instance(path: Path) -> tuple[StreamSet, list[UtilityStream], list[UtilityStream], float]:
    """Read a minimum-utility-cost instance (.dat: DTmin, HS/CS/HU/CU lines with Tin Tout FCp-or-cost)."""
    dT_min = None
    streams: list[Stream] = []
    hot_u: list[UtilityStream] = []
    cold_u: list[UtilityStream] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        f = line.split()
        if not f:
            continue
        if f[0] == "DTmin":
            dT_min = float(f[1])
            continue
        if f[0][:2] not in ("HS", "CS", "HU", "CU"):
            continue                                   # citation lines at the top of each file
        if dT_min is None:
            raise ValueError(f"{path.name}: DTmin must come before the streams")
        T_in, T_out, value = (float(v) for v in f[1:4])
        shift = dT_min / 2
        if f[0].startswith("HS"):
            streams.append(Stream(f[0], "hot", T_in, T_out, value * (T_in - T_out), shift))
        elif f[0].startswith("CS"):
            streams.append(Stream(f[0], "cold", T_in, T_out, value * (T_out - T_in), shift))
        elif f[0].startswith("HU"):
            hot_u.append(UtilityStream(f[0], "hot", T_in, T_out, shift))
        else:
            cold_u.append(UtilityStream(f[0], "cold", T_in, T_out, shift))
    if dT_min is None:
        raise ValueError(f"{path.name}: no DTmin line")
    return StreamSet(tuple(streams), "kW"), hot_u, cold_u, dT_min


def run(names: list[str] | None = None) -> pd.DataFrame:
    """Units found here and published, per instance (all instances with a published value by default)."""
    published = json.loads((DATA / "published_min_matches.json").read_text(encoding="utf-8"))
    values: dict[str, int] = published["minimum_matches"]
    rows = []
    for name in names or list(values):
        streams, hot_u, cold_u, dT_min = load_instance(DATA / f"{name}.dat")
        Qh = problem_table(streams).Qh_min
        r = min_units_matches(streams, hot_u, cold_u, Qh=Qh, time_limit_s=TIME_LIMIT_S)
        pub = values[name]
        rows.append({"instance": name, "streams": len(streams.streams),
                     "utilities": len(hot_u) + len(cold_u), "dTmin_K": dT_min, "Qh_min": round(Qh, 3),
                     "units_here": r.units, "units_published": pub,
                     "published_proven_optimal": 0.04 * pub < 1, "agrees": r.units == pub})
    return pd.DataFrame(rows)


def main() -> None:
    df = run()
    out = ROOT / "outputs"
    df.to_csv(out / "benchmark_min_matches.csv", index=False)
    ok = int(df["agrees"].sum())
    text = ("# Minimum number of matches: Letsios et al. (2018) benchmark\n\n"
            f"{ok} of {len(df)} instances give the published number of units "
            f"({int(df['published_proven_optimal'].sum())} published values are proven optima).\n"
            "Instances: Furman and Sahinidis (2004) test set, digitised by Letsios, Kouyialis and Misener "
            "(2018), Apache License 2.0 (data/benchmarks/letsios2018/). Excluded instances and why: "
            "published_min_matches.json, key _excluded. The whole set solves in a few seconds with HiGHS.\n\n"
            + df.to_markdown(index=False) + "\n")
    (out / "benchmark_min_matches.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
