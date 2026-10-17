"""Regenerate every committed output from the inputs, in dependency order (supervisor review C2).

Usage:
    python regenerate_outputs.py            # rerun everything
    python regenerate_outputs.py --check    # rerun, then fail if any committed CSV/JSON/MD output changed

The CI workflow runs ``--check``: a result in outputs/ that no longer follows from the code and the case
files fails the build. PNG files are regenerated but excluded from the comparison (font rasterisation
differs between machines); their data are in the CSV files next to them.

Order: step-1/2 validation and reproductions, cycle screening (read by analyse.py), all cases, then the
brewery checks that read analyse.py's outputs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BREWERY = "cases/brewery_padulles2026.json"
STEPS: tuple[tuple[str, ...], ...] = (
    ("validate_targets.py",),
    ("reproduce_padulles2026.py",),
    ("reproduce_padulles2026_economics.py",),
    ("verify_padulles2026_assumptions.py",),
    ("verify_walmsley2024.py",),
    ("screen_cycles.py", BREWERY),
    ("analyse.py", "--all"),
    ("consolidate_rq.py", BREWERY),
    ("batch_check.py", BREWERY),
    ("mvr_check.py", BREWERY),
    ("reproduce_secondary_economics.py",),
)


def run_all() -> None:
    env = dict(os.environ, MPLBACKEND="Agg")
    for step in STEPS:
        print(f"--> python {' '.join(step)}", flush=True)
        subprocess.run([sys.executable, *step], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)


def changed_outputs() -> list[str]:
    """Committed outputs (excluding PNG) that differ from HEAD, plus untracked new outputs."""
    diff = subprocess.run(["git", "status", "--porcelain", "--", "outputs"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.splitlines()
    return [line for line in diff if not line.rstrip().endswith(".png")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if a committed non-PNG output changed")
    args = parser.parse_args()
    run_all()
    if args.check:
        changed = changed_outputs()
        if changed:
            print("Outputs are stale (rerun python regenerate_outputs.py and commit):\n" + "\n".join(changed))
            sys.exit(1)
        print("All committed outputs are reproducible.")


if __name__ == "__main__":
    main()
