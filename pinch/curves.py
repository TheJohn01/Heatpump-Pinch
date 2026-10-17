"""Composite curves (the GCC is the Problem Table's feasible cascade: ``ProblemTable.cascade_feasible``
against ``ProblemTable.T_star_C``).

Composite curves are returned as (H, T) arrays, with enthalpy H increasing with
temperature and H = 0 at the lowest temperature of the hot composite.

With individual temperature shifts the *shifted* composite curves (T*) touch at
the pinch; the curves in real temperatures do not, because the gap at the pinch
is the sum of the two streams' shifts. Both are available through ``shifted``.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from pinch.streams import StreamSet

#: A stream or stream segment for composite curves: (T_lo, T_hi, CP) [°C, °C, energy unit / K].
Piece = tuple[float, float, float]


def piecewise_composite(pieces: Iterable[Piece], descending: bool = False,
                        H_start: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Composite of linear pieces: the sum of CP over each temperature interval, accumulated.

    The only implementation of the composite-curve sum (redundancy audit, item 2); used for the
    composite curves, the area target (real temperatures), network match profiles (shifted
    segments) and the cooling cascades of ``pinch.refrigeration``.

    Parameters
    ----------
    pieces : iterable of (T_lo, T_hi, CP)
        Temperature range [°C] and heat capacity flow rate of each piece.
    descending : bool
        False: T ascending, H accumulated from the cold end. True: T descending, H from the hot end.
    H_start : float
        Enthalpy at the first temperature [energy unit].

    Returns
    -------
    T_C, H : np.ndarray
        Breakpoint temperatures [°C] and cumulative enthalpy [energy unit], in the order chosen.
    """
    pieces = list(pieces)
    T = sorted({t for lo, hi, _ in pieces for t in (lo, hi)}, reverse=descending)
    H = [H_start]
    for a, b in zip(T[:-1], T[1:]):
        lo, hi = (b, a) if descending else (a, b)
        H.append(H[-1] + sum(cp for p_lo, p_hi, cp in pieces if p_lo <= lo and p_hi >= hi) * (hi - lo))
    return np.array(T), np.array(H)


def stream_pieces(streams, shifted: bool = True) -> list[Piece]:
    """(T_lo, T_hi, CP) of each stream, in shifted (T*) or real temperatures."""
    out = []
    for s in streams:
        ends = (s.T_star_in_C, s.T_star_out_C) if shifted else (s.T_in_C, s.T_out_C)
        out.append((min(ends), max(ends), s.CP))
    return out


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

    T_C, H = piecewise_composite(stream_pieces(streams, shifted), H_start=H_offset)
    return H, T_C
