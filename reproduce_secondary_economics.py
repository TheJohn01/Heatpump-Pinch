"""Economics of the secondary cases on an ASSUMED annual basis (supervisor review C3).

Usage:
    python reproduce_secondary_economics.py

The milk evaporator (Walmsley et al. 2024) and the four-stream example publish no operating hours, so
``analyse.py`` keeps them in kW and skips steps 3, 5 and 6. This script reruns them with an assumed
8000 h/year (the case files' ``basis_hint``: an upper bound for the seasonal milk plant; within the
7,880-8,320 h/year of continuous plants, Sinnott and Towler 2020, Sec. 1.3.1, for the four-stream
example), so that every step of the tool has been exercised on more than one case. The spray dryer
already has a published basis (6000 h/year, Liang et al. 2022) and runs in ``analyse.py --all``.

These are ASSUMED-basis results, not reproductions: they are written to
outputs/secondary_8000h_assumed/<case>/ so they cannot be mistaken for the published-basis outputs.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from analyse import analyse
from pinch.case import load_case

ROOT = Path(__file__).resolve().parent
HOURS = 8000
CASES = ("walmsley2024_milk_evaporator", "fourstream_example")
OUT = ROOT / "outputs" / f"secondary_{HOURS}h_assumed"


def main() -> None:
    for name in CASES:
        case = load_case(ROOT / "cases" / f"{name}.json")
        prov = dict(case.provenance)
        prov["basis"] = (f"ASSUMED for reproduce_secondary_economics.py: {HOURS} h/year "
                         f"(case basis_hint). Original: {case.provenance.get('basis', 'none')}")
        case = replace(case, basis={"type": "power", "operating_hours_per_year": HOURS}, provenance=prov)
        s = analyse(case, output_root=OUT)
        eco = s.get("economics") or {}
        print(f"{name}: economics {'skipped' if not eco or 'skipped' in eco else 'computed'}; outputs in {OUT / name}")


if __name__ == "__main__":
    main()
