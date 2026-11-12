"""Regenerate every committed output from the inputs, in dependency order (design review C2).

Usage:
    python regenerate_outputs.py            # rerun everything
    python regenerate_outputs.py --check    # rerun, then fail if any committed CSV/JSON/MD output changed

The CI workflow runs ``--check``: a result in outputs/ that no longer follows from the code and the case
files fails the build. The same holds for the generated blocks of README.md (the table of economic
defaults, written from ``pinch.economics``). PNG files are regenerated but excluded from the comparison (font rasterisation
differs between machines); their data are in the CSV files next to them.

Order: step-1/2 validation and reproductions, cycle screening (read by scripts/analysis/analyse.py), all cases, then the
brewery checks that read scripts/analysis/analyse.py's outputs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BREWERY = "cases/brewery.json"
STEPS: tuple[tuple[str, ...], ...] = (
    ("-m", "scripts.validation.validate_targets"),
    ("-m", "scripts.validation.reproduce_padulles2026"),
    ("-m", "scripts.validation.reproduce_padulles2026_economics"),
    ("-m", "scripts.validation.verify_padulles2026_assumptions"),
    ("-m", "scripts.validation.verify_walmsley2024"),
    ("-m", "scripts.validation.reproduce_stampfli2019"),
    ("-m", "scripts.benchmarks.benchmark_openpinch"),
    ("-m", "scripts.benchmarks.benchmark_hen"),
    ("-m", "scripts.benchmarks.benchmark_min_matches"),
    ("-m", "scripts.benchmarks.benchmark_exchanger_rating"),
    ("-m", "scripts.analysis.screen_cycles", BREWERY),
    ("-m", "scripts.analysis.heat_pump_partload", BREWERY),
    ("-m", "scripts.analysis.analyse", "--all"),
    ("-m", "scripts.analysis.consolidate_rq", BREWERY),
    ("-m", "scripts.analysis.consolidate_rq", "cases/spray_dryer.json"),
    ("-m", "scripts.checks.batch_check", BREWERY),
    ("-m", "scripts.checks.mvr_check", BREWERY),
    ("-m", "scripts.checks.investment_check", BREWERY),
    ("-m", "scripts.checks.plant_data_check", BREWERY),
    ("-m", "scripts.validation.reproduce_secondary_economics"),
)


def run_all() -> None:
    env = dict(os.environ, MPLBACKEND="Agg")
    for step in STEPS:
        print(f"--> python {' '.join(step)}", flush=True)   # e.g. python -m scripts.analysis.analyse --all
        subprocess.run([sys.executable, *step], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)


README = ROOT / "README.md"
BEGIN, END = "<!-- BEGIN generated: pinch.economics.defaults_markdown() -->", "<!-- END generated -->"


def update_readme() -> None:
    """Rewrite README.md's generated block from the code."""
    from pinch.economics import defaults_markdown
    text = README.read_text(encoding="utf-8")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    README.write_text(f"{head}{BEGIN}\n{defaults_markdown()}{END}{tail}", encoding="utf-8")


def changed_outputs() -> list[str]:
    """Committed outputs (excluding PNG) and README.md that differ from HEAD, plus untracked new outputs."""
    diff = subprocess.run(["git", "status", "--porcelain", "--", "outputs", "README.md"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.splitlines()
    return [line for line in diff if not line.rstrip().endswith(".png")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if a committed non-PNG output changed")
    args = parser.parse_args()
    run_all()
    update_readme()
    if args.check:
        changed = changed_outputs()
        if changed:
            print("Outputs are stale (rerun python regenerate_outputs.py and commit):\n" + "\n".join(changed))
            sys.exit(1)
        print("All committed outputs are reproducible.")


if __name__ == "__main__":
    main()
