"""Composite curves and Grand Composite Curve (GCC) data.

Composite curves are returned as (H, T) arrays, with enthalpy H increasing with
temperature and H = 0 at the lowest temperature of the hot composite.

With individual temperature shifts the *shifted* composite curves (T*) touch at
the pinch; the curves in real temperatures do not, because the gap at the pinch
is the sum of the two streams' shifts. Both are available through ``shifted``.
"""

from __future__ import annotations

import numpy as np

from pinch.problem_table import ProblemTable
from pinch.streams import StreamSet


def composite_curve(
    stream_set: StreamSet, kind: str, shifted: bool = True, H_offset: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """Hot or cold composite curve.

    Parameters
    ----------
    stream_set : StreamSet
        Validated streams.
    kind : str
        "hot" or "cold".
    shifted : bool
        If True, use shifted temperatures T*; otherwise real temperatures.
    H_offset : float
        Enthalpy at the curve's lowest temperature [energy unit]. For the
        cold composite this is normally Qc_min, so that the shifted curves
        touch at the pinch.

    Returns
    -------
    H, T_C : np.ndarray
        Cumulative enthalpy [energy unit] and temperature [°C], ascending in T.
    """
    if kind not in ("hot", "cold"):
        raise ValueError("kind must be 'hot' or 'cold'")
    streams = stream_set.hot if kind == "hot" else stream_set.cold
    if not streams:
        return np.array([H_offset]), np.array([np.nan])

    def ends(s):
        return (s.T_star_in_C, s.T_star_out_C) if shifted else (s.T_in_C, s.T_out_C)

    T_C = np.array(sorted({t for s in streams for t in ends(s)}))
    H = [H_offset]
    for T_lo, T_hi in zip(T_C[:-1], T_C[1:]):
        CP_sum = sum(s.CP for s in streams if min(ends(s)) <= T_lo and max(ends(s)) >= T_hi)
        H.append(H[-1] + CP_sum * (T_hi - T_lo))
    return np.array(H), T_C


def grand_composite_curve(table: ProblemTable) -> tuple[np.ndarray, np.ndarray]:
    """GCC as (net heat flow, shifted temperature), descending in T*.

    Returns
    -------
    H, T_star_C : np.ndarray
        Feasible cascade heat flow [energy unit] and boundaries T* [°C].
    """
    return table.cascade_feasible.copy(), table.T_star_C.copy()
