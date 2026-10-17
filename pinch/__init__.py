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
case                     Case files and annual conversion.
validation               Reference targets vs computed values.
results                  Outputs container (summary, tables, figures).
plotting                 Matplotlib figures for files and the dissertation.
charts                   Altair charts for the app.
"""

import matplotlib as _mpl

# Deterministic figures on every machine: DejaVu Sans ships with matplotlib, so PNG outputs do not depend on
# the fonts installed locally (supervisor review C2).
_mpl.rcParams["font.family"] = "DejaVu Sans"

from pinch.streams import Stream, StreamSet, load_streams, with_extra_shift, energy_balance
from pinch.problem_table_algorithm import ProblemTable, problem_table
from pinch.curves import composite_curve

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
