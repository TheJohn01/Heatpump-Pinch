"""Pinch analysis toolkit for the heat pump integration dissertation.

Modules
-------
streams        Stream data loading, validation and energy-balance checks.
problem_table  Problem Table Algorithm: heat cascade and energy targets.
curves         Composite curves and Grand Composite Curve (GCC) data.
plotting       Figures saved to file with labelled axes and units.
"""

import matplotlib as _mpl

# Deterministic figures on every machine: DejaVu Sans ships with matplotlib, so PNG outputs do not depend on
# the fonts installed locally (supervisor review C2).
_mpl.rcParams["font.family"] = "DejaVu Sans"

from pinch.streams import Stream, StreamSet, load_streams, with_extra_shift, energy_balance
from pinch.problem_table import ProblemTable, problem_table
from pinch.curves import composite_curve, grand_composite_curve

__all__ = [
    "Stream",
    "StreamSet",
    "load_streams",
    "with_extra_shift",
    "energy_balance",
    "ProblemTable",
    "problem_table",
    "composite_curve",
    "grand_composite_curve",
]
