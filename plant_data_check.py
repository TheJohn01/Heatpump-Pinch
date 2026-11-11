"""Plant-data checks for a case: stream-data uncertainty and match restrictions (workflow steps 1-2).

Usage:
    python plant_data_check.py cases/brewery.json

1. Uncertainty of the energy targets (``pinch.uncertainty``; Bergamini et al. 2019, 2021): 5000 Latin
   hypercube samples (seed 0) of every heat load (σ 10 %, relative) and temperature (σ 3 K), the nominal
   uncertainty of rough data estimates in Bergamini et al. (2019), Table 1. Reports mean, standard
   deviation, Monte Carlo error and 95 % interval of Qh,min, Qc,min and the pinch T*, and the inputs whose
   squared standardised regression coefficient β² is at least 0.01 (Bergamini et al. 2021, Sec. 3.3).
   For a published stream table such as the brewery's this answers: how far would the targets move if
   the table had the accuracy of a rough plant survey, and which entries would need measuring first.
2. Match restrictions (``pinch.restricted_matches``):
   * restrictions declared in the case file ("restricted_matches", each with its reason): targets with
     and without them;
   * screening: each process hot-cold pair forbidden on its own, and each stream barred from all process
     partners, with the extra hot utility each causes.
     This identifies the matches the energy target depends on. It is not a statement that any of them is
     forbidden: no hygiene or safety rule for these streams was found in the sources.

Uses the case's stream file with its extra shift. Writes outputs/<case>/plant_data_uncertainty.csv,
plant_data_src.csv, plant_data_match_screening.csv, plant_data_stream_isolation.csv and plant_data_check.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pinch import load_streams, with_extra_shift
from pinch.case import load_case
from pinch.restricted_matches import restricted_targets
from pinch.uncertainty import (
    BERGAMINI_2019_SIGMA,
    SRC_BETA2_MIN,
    SRC_R2_MIN,
    target_uncertainty,
)

ROOT = Path(__file__).resolve().parent
N_SAMPLES, SEED = 5000, 0


def check(case_file: Path) -> dict:
    case = load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    u = target_uncertainty(streams, heat_flow_relative=BERGAMINI_2019_SIGMA["heat_flow_relative"],
                           temperature_K=BERGAMINI_2019_SIGMA["temperature_K"], n=N_SAMPLES, seed=SEED)
    src = u.src.copy()
    valid = [c for c in src.columns if u.r2[c] > SRC_R2_MIN]   # rank only on outputs with an acceptable linear model
    src["max_beta2"] = src[valid].max(axis=1) if valid else float("nan")
    src = src.sort_values("max_beta2", ascending=False)

    screening = []
    for h in streams.hot:
        for c in streams.cold:
            r = restricted_targets(streams, {(h.name, c.name): 0.0})
            screening.append({"hot": h.name, "cold": c.name, "Qh_min": r.Qh_min, "penalty": r.penalty})
    screening = pd.DataFrame(screening).sort_values("penalty", ascending=False, kind="stable")

    isolated = []                           # each process stream barred from every process partner
    for s in streams.streams:
        partners = streams.cold if s.kind == "hot" else streams.hot
        limits = {((s.name, p.name) if s.kind == "hot" else (p.name, s.name)): 0.0 for p in partners}
        r = restricted_targets(streams, limits)
        isolated.append({"stream": s.name, "type": s.kind, "load": s.Q, "Qh_min": r.Qh_min, "penalty": r.penalty})
    isolated = pd.DataFrame(isolated).sort_values("penalty", ascending=False, kind="stable")

    declared = None
    if case.restricted_matches:
        limits = {(h, c): m for h, c, m, _ in case.restricted_matches}
        declared = restricted_targets(streams, limits)
    return {"case": case, "unit": streams.energy_unit, "uncertainty": u, "src": src,
            "screening": screening, "isolated": isolated, "declared": declared}


def markdown(res: dict) -> str:
    u, unit = res["uncertainty"], res["unit"]

    def f(x: float) -> str:
        return f"{x:.3g}"

    lines = [f"## Stream-data uncertainty ({N_SAMPLES} Latin hypercube samples, seed {SEED})", "",
             f"Heat loads σ {100 * BERGAMINI_2019_SIGMA['heat_flow_relative']:g} %, temperatures σ "
             f"{BERGAMINI_2019_SIGMA['temperature_K']:g} K (Bergamini et al. 2019, Table 1: rough estimates, dairy "
             "case). Temperature shifts not varied.", "",
             "| Output | Nominal | Mean | Std | Std / mean | MC error | 2.5 % | 97.5 % | R² of linear model |",
             "|---|---|---|---|---|---|---|---|---|"]
    for o, r in u.summary.iterrows():
        un = "°C" if o.startswith("pinch") else unit
        rel = "n/a" if o.startswith("pinch") else f"{100 * r['relative_std']:.0f} %"
        lines.append(f"| {o} [{un}] | {f(r['nominal'])} | {f(r['mean'])} | {f(r['std'])} | {rel} | {f(r['MCerr'])} | "
                     f"{f(r['p2.5'])} | {f(r['p97.5'])} | {u.r2[o]:.2f} |")
    imp = u.important_inputs()
    cols = [c for c in ("Qh_min", "Qc_min", "pinch_T_star_C") if u.r2[c] > SRC_R2_MIN]
    lines += ["", f"Inputs with β² ≥ {SRC_BETA2_MIN:g} for an output whose linear model has R² > {SRC_R2_MIN:g} "
              f"({len(imp)} of {len(u.src)}; ranked by largest β²):", "",
              "| Input | " + " | ".join(f"β² {c}" for c in cols) + " |", "|---|" + "---|" * len(cols)]
    for name, r in res["src"].iterrows():
        if name in imp:
            lines.append(f"| {name} | " + " | ".join(f"{r[c]:.3f}" for c in cols) + " |")
    lines += ["", "## Match restrictions", ""]
    d = res["declared"]
    if d is None:
        lines.append("No restrictions declared in the case file.")
    else:
        lines.append(f"Declared restrictions: Qh,min {d.Qh_min:.3g} vs {d.Qh_min_unrestricted:.3g} {unit} "
                     f"(penalty {d.penalty:.3g}).")
        for h, c, m, why in res["case"].restricted_matches:
            lines.append(f"- {h} → {c}: {'forbidden' if m == 0 else f'at most {m:g} {unit}'} ({why})")
    sc = res["screening"]
    lines += ["", "Screening, one pair forbidden at a time (not a claim that any pair is forbidden): pairs with a "
              "penalty.", "", f"| Hot | Cold | Qh,min [{unit}] | Penalty [{unit}] |", "|---|---|---|---|"]
    for _, r in sc[sc["penalty"] > 1e-9].iterrows():
        lines.append(f"| {r['hot']} | {r['cold']} | {r['Qh_min']:.3f} | {r['penalty']:+.3f} |")
    if not (sc["penalty"] > 1e-9).any():
        lines.append("| (none) | | | |")
    lines.append(f"\n{int((sc['penalty'] <= 1e-9).sum())} of {len(sc)} pairs can be forbidden alone without penalty.")
    lines += ["", "Screening, each stream barred from every process partner (it exchanges with utilities only):", "",
              f"| Stream | Type | Load [{unit}] | Qh,min [{unit}] | Penalty [{unit}] |", "|---|---|---|---|---|"]
    for _, r in res["isolated"].iterrows():
        lines.append(f"| {r['stream']} | {r['type']} | {r['load']:.3g} | {r['Qh_min']:.3f} | {r['penalty']:+.3f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    res = check(args.case_file)
    out = ROOT / "outputs" / res["case"].name
    out.mkdir(parents=True, exist_ok=True)
    res["uncertainty"].summary.round(6).to_csv(out / "plant_data_uncertainty.csv")
    res["src"].round(6).to_csv(out / "plant_data_src.csv", index_label="input")
    res["screening"].round(6).to_csv(out / "plant_data_match_screening.csv", index=False)
    res["isolated"].round(6).to_csv(out / "plant_data_stream_isolation.csv", index=False)
    text = markdown(res)
    (out / "plant_data_check.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
