"""Pinch analysis toolkit for the heat pump integration dissertation.

Modules (a test checks that this list and README.md name every module)
-------
streams                  Stream data loading, validation and energy-balance checks (step 1).
problem_table_algorithm  Problem Table Algorithm: heat cascade, targets, pinch; the GCC (step 2).
curves                   Composite curves; the one piecewise composite sum (step 2).
area                     Area and units targets, ΔTmin supertargeting (step 3).
area_analysis            Per-case supertargeting, RQ2 (step 3).
heat_pump                Lorenz COP, heat pump units, integration, sizing read from the GCC (step 4).
design                   Multi-level design from the GCC, partial designs, plausibility screening (step 4).
cycle                    Vapour-compression cycles with CoolProp (step 4b).
cycle_analysis           Working-fluid screening of a design (step 4b).
network                  Existing heat-exchanger networks: utilities, diagnostics, constrained streams (step 5).
retrofit                 Retrofit options and bounds against the existing plant (step 5).
refrigeration            Refrigeration duty and the part heat pump sources take over (steps 5 and 6).
economics                Cost functions, evaluation, break-even ratio, defaults with sources (step 6).
economic_analysis        Grass-roots reference economics of a GCC design (step 6).
research_questions       RQ1-RQ3 against today's site, for any case (step 6; Dashboard).
sensitivity              The case's single sensitivity list (steps 3-6).
investment               IRR, tax and depreciation, estimate accuracy, grants, Monte Carlo (step 6).
reconciliation           Data reconciliation of measured CP and T (step 1).
uncertainty              Stream-data uncertainty of the targets, SRC ranking (steps 1-2).
restricted_matches       Targets with forbidden or limited matches (step 2).
time_slices              Non-continuous processes: time slices, storage, heat pump with storage (steps 2-4).
utilities                Targets for several utility levels, placed against the GCC (step 2).
refrigerants             Working-fluid GWP, safety group and EU F-gas prohibitions (step 4b).
provenance               Tool version and input hashes in outputs; run metadata (QA).
hen_design               Network synthesis (minimum units), series placement, exchanger sizing and cost (step 5).
pressure_drop            Film coefficients from allowable pressure drop; fouling (steps 3 and 5).
case                     Case files and annual conversion.
validation               Reference targets vs computed values.
results                  Outputs container (summary, tables, figures).
plotting                 Matplotlib figures for files and the dissertation.
charts                   Altair charts for the app.
"""

__version__ = "0.8.0"   # keep equal to pyproject.toml and CITATION.cff (tests/test_quality.py)

import matplotlib as _mpl

# Deterministic figures on every machine: DejaVu Sans ships with matplotlib, so PNG outputs do not depend on
# the fonts installed locally (supervisor review C2).
_mpl.rcParams["font.family"] = "DejaVu Sans"

from pinch.curves import composite_curve  # noqa: E402 (after the font setting, by design)
from pinch.problem_table_algorithm import ProblemTable, problem_table  # noqa: E402 (after the font setting, by design)
from pinch.streams import (  # noqa: E402 (after the font setting, by design)
    Stream,
    StreamSet,
    energy_balance,
    load_streams,
    with_extra_shift,
)

__all__ = [
    "Stream",
    "StreamSet",
    "load_streams",
    "with_extra_shift",
    "energy_balance",
    "ProblemTable",
    "problem_table",
    "composite_curve",
]
