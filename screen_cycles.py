"""Working-fluid screening for the heat pumps of a case (workflow step 4b).

Usage:
    python screen_cycles.py cases/brewery.json

Sizes the heat pumps from the GCC (as analyse.py does), optimises every
fluid/layout in the case's "heat_pumps.cycle_screening" block with the CoolProp
cycle model, and writes outputs/<case>/cycle_screening.csv and .json.
analyse.py then adds a cycle-based design (η_L per unit from the selected
cycle) to the summary. Runtime: a few minutes for ten fluids and ten cascades.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pinch import load_streams, with_extra_shift
from pinch.case import load_case
from pinch.cycle import CycleAssumptions
from pinch.cycle_analysis import screen_design, write_screening
from pinch.design import design_from_gcc

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    case = load_case(args.case_file)
    block = (case.cycle_screening or {})
    if not block:
        parser.error("the case file has no heat_pumps.cycle_screening block")
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    design = design_from_gcc(streams, case.sink_levels, case.eta_lorenz, case.source_T_C)
    a = CycleAssumptions()
    table, selected = screen_design(design, block, a)
    path = write_screening(table, selected, a, ROOT / "outputs" / case.name)
    for unit, sel in selected.items():
        print(f"{unit}: {sel['fluid']} ({sel['layout']}) COP {sel['COP']:.3f}, eta_L {sel['eta_lorenz_cycle']:.3f} "
              f"(assumed {sel['eta_lorenz_assumed']}, COP {sel['COP_assumed']:.3f})")
    print(f"written: {path}")


if __name__ == "__main__":
    main()
