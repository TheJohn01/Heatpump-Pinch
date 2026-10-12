"""Compare computed targets with reference (published or textbook) values.

Reference values live in ``data/reference_targets.json`` so that tests and the
validation report use exactly the same numbers and sources.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pinch.problem_table import ProblemTable, problem_table
from pinch.streams import load_streams, with_extra_shift

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_FILE = ROOT / "data" / "reference_targets.json"


def load_references(path: str | Path = REFERENCE_FILE) -> dict:
    """Load the reference targets dictionary."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def computed_targets(table: ProblemTable) -> dict[str, float]:
    """Extract the comparable quantities from a ProblemTable."""
    return {
        "Qh_min": table.Qh_min,
        "Qc_min": table.Qc_min,
        "heat_recovery": table.heat_recovery,
        "pinch_T_star_C": table.pinch_T_star_C[0] if table.pinch_T_star_C else float("nan"),
        "T_star_max_C": float(table.T_star_C[0]),
        "T_star_min_C": float(table.T_star_C[-1]),
    }


def run_case(case: dict) -> ProblemTable:
    """Load a reference case's data, apply its extra shift and run the PTA."""
    streams = load_streams(ROOT / case["data_file"])
    streams = with_extra_shift(streams, case["extra_shift_K"])
    return problem_table(streams)


def validation_report(references: dict | None = None) -> pd.DataFrame:
    """Tabulate reference vs computed values with absolute and relative deviation."""
    references = references or load_references()
    rows = []
    for name, case in references.items():
        computed = computed_targets(run_case(case))
        for quantity, ref in case["targets"].items():
            value = computed[quantity]
            deviation = value - ref["value"]
            rows.append(
                {
                    "case": name,
                    "quantity": quantity,
                    "unit": "°C" if quantity.endswith("_C") else case["energy_unit"],
                    "reference": ref["value"],
                    "computed": round(value, 4),
                    "deviation": round(deviation, 4),
                    "deviation_%": round(100 * deviation / ref["value"], 2) if ref["value"] else float("nan"),
                    "within_tolerance": abs(deviation) <= ref["tolerance"],
                }
            )
    return pd.DataFrame(rows)
