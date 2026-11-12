"""Regenerate every committed output from the inputs, in dependency order (design review C2).

Usage:
    python regenerate_outputs.py            # rerun everything
    python regenerate_outputs.py --check    # rerun, then fail if any committed CSV/JSON/MD output changed

The CI workflow runs ``--check``: a result in outputs/ that no longer follows from the code and the case
files fails the build. The same holds for the generated blocks of README.md (the table of economic
defaults, written from ``pinch.economics``). PNG figures are compared with a tolerance (``png_change``): after
averaging over 8 x 8 pixel blocks, a block differing by more than 40 grey levels counts as a change. On the
machine that produced the committed figures, text antialiasing stays below 16, so a rerun restores every figure
whose only difference is rasterisation and leaves no spurious diffs. Across machines the tolerance cannot
decide: a different FreeType build changes text metrics, and tight layout then moves whole plot areas (GitHub's
runner exceeds the tolerance on every figure). So ``--check`` reports changed figures but fails only on CSV,
JSON, Markdown and README changes; every figure's data are in a CSV file that is checked.

Order: step-1/2 validation and reproductions, cycle screening (read by scripts/analysis/analyse.py), all cases, then the
brewery checks that read scripts/analysis/analyse.py's outputs.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

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
    ("-m", "scripts.checks.design_consistency_check", BREWERY),
    ("-m", "scripts.checks.vendor_data_check", BREWERY),
    ("-m", "scripts.checks.benchmark_check", BREWERY),
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


PNG_BLOCK_PX = 8
PNG_TOLERANCE = 40.0       # grey levels, on block means (0-255)


def png_change(old: bytes, new: bytes, block: int = PNG_BLOCK_PX) -> float:
    """Largest block-mean grey-level difference between two PNG images (inf if the sizes differ)."""
    a = np.asarray(Image.open(io.BytesIO(old)).convert("L"), dtype=float)
    b = np.asarray(Image.open(io.BytesIO(new)).convert("L"), dtype=float)
    if a.shape != b.shape:
        return float("inf")
    h, w = (a.shape[0] // block) * block, (a.shape[1] // block) * block

    def means(x: np.ndarray) -> np.ndarray:
        return x[:h, :w].reshape(h // block, block, w // block, block).mean(axis=(1, 3))

    return float(np.abs(means(a) - means(b)).max())


def _status() -> list[str]:
    return subprocess.run(["git", "status", "--porcelain", "--", "outputs", "README.md"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.splitlines()


def settle_pngs() -> list[str]:
    """Restore modified PNGs that differ from HEAD only by rasterisation; return the ones that really changed."""
    changed = []
    for line in _status():
        path = line[3:].strip()
        if not (line.startswith(" M") and path.endswith(".png")):
            continue
        old = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, check=True, capture_output=True).stdout
        if png_change(old, (ROOT / path).read_bytes()) <= PNG_TOLERANCE:
            subprocess.run(["git", "checkout", "--", path], cwd=ROOT, check=True)
        else:
            changed.append(line)
    return changed


def changed_outputs() -> tuple[list[str], list[str]]:
    """(data, figures): committed CSV/JSON/MD outputs and README.md that differ from HEAD (plus untracked new
    outputs), and PNG figures that differ beyond the rasterisation tolerance (reported, not failed)."""
    figures = settle_pngs()
    data = [line for line in _status() if not line.rstrip().endswith(".png")]
    return data, figures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if a committed CSV/JSON/MD output changed")
    args = parser.parse_args()
    run_all()
    update_readme()
    if args.check:
        data, figures = changed_outputs()
        if figures:
            print("Figures differ beyond the rasterisation tolerance (reported only; their data are checked "
                  "through the CSV files):\n" + "\n".join(figures))
        if data:
            print("Outputs are stale (rerun python regenerate_outputs.py and commit):\n" + "\n".join(data))
            sys.exit(1)
        print("All committed outputs are reproducible.")
    else:
        figures = settle_pngs()
        if figures:
            print("Figures that changed (beyond rasterisation):\n" + "\n".join(figures))


if __name__ == "__main__":
    main()
