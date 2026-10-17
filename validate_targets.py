"""Workflow steps 1-2: energy targets, composite curves and GCC.

Runs every case in data/reference_targets.json and writes the validation report
(outputs/validation_report.csv; the same comparison the tests assert, through
``pinch.validation``). Problem tables and figures are written to outputs/ only for
reference cases that no case file covers (same stream file and extra shift):
the others are already in outputs/<case>/, written by analyse.py, and writing them
twice gave byte-identical duplicates (redundancy audit, item 6).

Usage:  python validate_targets.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pinch.case import display_name
from pinch import energy_balance, load_streams, problem_table, with_extra_shift
from pinch.case import load_case
from pinch.plotting import composite_curves_figure, gcc_figure, save_figure
from pinch.validation import ROOT, load_references, validation_report


@dataclass(frozen=True)
class Config:
    """Run parameters (inputs are the CSV files named in the reference file)."""

    output_dir: Path = ROOT / "outputs"


def covered_by_case_files(cases_dir: Path = ROOT / "cases") -> set[tuple[Path, float]]:
    """(stream file, extra shift) of every case file, whose outputs analyse.py writes to outputs/<case>/."""
    out = set()
    for f in cases_dir.glob("*.json"):
        if f.stem == "TEMPLATE":
            continue
        c = load_case(f)
        out.add((c.stream_file.resolve(), c.extra_shift_K))
    return out


def main(config: Config = Config()) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    references = load_references()
    covered = covered_by_case_files()

    for name, case in references.items():
        streams = with_extra_shift(load_streams(ROOT / case["data_file"]), case["extra_shift_K"])
        table = problem_table(streams)
        balance = energy_balance(streams)
        unit = streams.energy_unit

        if ((ROOT / case["data_file"]).resolve(), float(case["extra_shift_K"])) not in covered:
            table.to_frame().to_csv(config.output_dir / f"{name}_problem_table.csv", index=False)
            save_figure(composite_curves_figure(streams, table, title=f"Shifted composite curves: {display_name(name)}"),
                        config.output_dir / f"{name}_composite_curves.png")
            save_figure(gcc_figure(table, title=f"Grand Composite Curve: {display_name(name)}"),
                        config.output_dir / f"{name}_gcc.png")

        print(f"\n== {name} (extra shift {case['extra_shift_K']} K)")
        print(f"   Hot / cold totals : {balance['Q_hot_total']:.2f} / {balance['Q_cold_total']:.2f} {unit}")
        print(f"   Qh_min / Qc_min   : {table.Qh_min:.2f} / {table.Qc_min:.2f} {unit}")
        print(f"   Heat recovery     : {table.heat_recovery:.2f} {unit}")
        print(f"   Pinch T*          : {table.pinch_T_star_C} °C")

    report = validation_report(references)
    report.to_csv(config.output_dir / "validation_report.csv", index=False)
    print("\n" + report.to_string(index=False))


if __name__ == "__main__":
    main()
