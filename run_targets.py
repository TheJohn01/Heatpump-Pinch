"""Workflow steps 1-2: energy targets, composite curves and GCC.

Runs every case in data/reference_targets.json, writes the problem tables and
a validation report to outputs/, and saves the figures.

Usage:  python run_targets.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pinch import energy_balance, load_streams, problem_table, with_extra_shift
from pinch.plotting import plot_composite_curves, plot_gcc
from pinch.validation import ROOT, load_references, validation_report


@dataclass(frozen=True)
class Config:
    """Run parameters (inputs are the CSV files named in the reference file)."""

    output_dir: Path = ROOT / "outputs"


def main(config: Config = Config()) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    references = load_references()

    for name, case in references.items():
        streams = with_extra_shift(load_streams(ROOT / case["data_file"]), case["extra_shift_K"])
        table = problem_table(streams)
        balance = energy_balance(streams)
        unit = streams.energy_unit

        table.to_frame().to_csv(config.output_dir / f"{name}_problem_table.csv", index=False)
        plot_composite_curves(streams, table, config.output_dir / f"{name}_composite_curves.png",
                              title=f"Shifted composite curves: {name}")
        plot_gcc(table, config.output_dir / f"{name}_gcc.png", title=f"Grand Composite Curve: {name}")

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
