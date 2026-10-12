"""Area and units targeting, and ΔTmin supertargeting (workflow step 3).

Area target (Bath formula, vertical heat transfer between composite curves)
--------------------------------------------------------------------------
    A = Σ_k (1 / ΔT_LM,k) Σ_i (q_i,k / h_i)

over enthalpy intervals k of the balanced composite curves, where q_i,k is the
heat of stream i in interval k and h_i its film coefficient (Linnhoff and
Ahmad, 1990; as used in standard pinch texts). With a single overall U this
reduces to A = Σ_k Q_k / (U ΔT_LM,k), the form used in the University of
Oklahoma 'Units and Area Targeting' notes, which serve as the test case.

Scope: by default the area covers process-to-process heat recovery (the
overlap of the hot and cold composite curves). Utility exchangers are excluded
because, in this project, utilities are heat pumps whose exchangers are
included in their per-kW cost. Utility streams can be added to the stream set
to obtain a balanced-composite area.

Units target: N_min = (S - 1) above the pinch + (S - 1) below the pinch, with S
the number of streams present on each side (Linnhoff's (N - 1) rule).

Supertargeting: total annual cost
    TAC(ΔTmin) = CRF · N [a + b (A / N)^c] + Q̇h,min(ΔTmin) c_h + Q̇c,min(ΔTmin) c_c
with every stream contributing ΔTmin / 2. The cost-law coefficients a, b, c
must be supplied by the user with a source; no default is provided.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from pinch.problem_table import problem_table
from pinch.streams import Stream, StreamSet


def log_mean(dT_a_K: float, dT_b_K: float) -> float:
    """Log-mean temperature difference [K]; arithmetic limit when the two are equal."""
    if dT_a_K <= 0 or dT_b_K <= 0:
        raise ValueError(f"non-positive temperature difference ({dT_a_K:.4g}, {dT_b_K:.4g} K): curves cross")
    if math.isclose(dT_a_K, dT_b_K, rel_tol=1e-9):
        return dT_a_K
    return (dT_a_K - dT_b_K) / math.log(dT_a_K / dT_b_K)


def _segments(streams: tuple[Stream, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Composite curve in real temperatures: (T ascending, H ascending from 0)."""
    T = np.array(sorted({t for s in streams for t in (s.T_in_C, s.T_out_C)}))
    H = [0.0]
    for lo, hi in zip(T[:-1], T[1:]):
        H.append(H[-1] + sum(s.CP for s in streams if min(s.T_in_C, s.T_out_C) <= lo and max(s.T_in_C, s.T_out_C) >= hi)
                 * (hi - lo))
    return T, np.array(H)


def _heat_by_stream(streams: tuple[Stream, ...], T_lo: float, T_hi: float) -> dict[str, float]:
    """Heat of each stream between two temperatures [energy unit]."""
    out = {}
    for s in streams:
        lo, hi = sorted((s.T_in_C, s.T_out_C))
        overlap = max(0.0, min(hi, T_hi) - max(lo, T_lo))
        if overlap > 0:
            out[s.name] = s.CP * overlap
    return out


@dataclass(frozen=True)
class AreaTarget:
    """Area and units targets.

    Attributes
    ----------
    area : float
        Area target [m² if h is in energy-unit per m² K, e.g. kW/(m² K) with Q in kW].
    units : int
        Minimum number of exchanger units.
    heat_recovered : float
        Heat exchanged in the region covered [energy unit].
    """

    area: float
    units: int
    heat_recovered: float


def area_target(stream_set: StreamSet, h: dict[str, float], include_utilities: bool = False) -> AreaTarget:
    """Bath-formula area target and units target.

    Parameters
    ----------
    stream_set : StreamSet
        Streams with their temperature shifts (the shifts set the pinch).
    h : dict
        Film coefficient per stream name, in (energy unit) / (m² K): e.g.
        kW/(m² K) when loads are in kW, MW/(m² K) when loads are in MW.
    include_utilities : bool
        False: area of the process heat-recovery region only (composite overlap).
        True: the stream set already contains utility streams and is balanced
        (Q̇h,min = Q̇c,min = 0); the whole curve is used.
    """
    missing = [s.name for s in stream_set.streams if s.name not in h]
    if missing:
        raise ValueError(f"film coefficient missing for {missing}")
    table = problem_table(stream_set)
    if include_utilities and (table.Qh_min > 1e-9 or table.Qc_min > 1e-9):
        raise ValueError("include_utilities=True needs a balanced stream set (utilities included)")

    hot, cold = stream_set.hot, stream_set.cold
    T_h, H_h = _segments(hot)
    T_c, H_c = _segments(cold)
    H_c = H_c + table.Qc_min  # cold composite starts where cold utility ends
    H_lo, H_hi = table.Qc_min, H_h[-1]          # overlap = heat recovered
    if H_hi <= H_lo:
        return AreaTarget(0.0, 0, 0.0)

    breaks = np.unique(np.concatenate([H_h[(H_h > H_lo) & (H_h < H_hi)], H_c[(H_c > H_lo) & (H_c < H_hi)], [H_lo, H_hi]]))
    T_hot = lambda H: float(np.interp(H, H_h, T_h))   # noqa: E731
    T_cold = lambda H: float(np.interp(H, H_c, T_c))  # noqa: E731

    area = 0.0
    for H_a, H_b in zip(breaks[:-1], breaks[1:]):
        Th_a, Th_b, Tc_a, Tc_b = T_hot(H_a), T_hot(H_b), T_cold(H_a), T_cold(H_b)
        dTlm = log_mean(Th_b - Tc_b, Th_a - Tc_a)
        q_hot = _heat_by_stream(hot, Th_a, Th_b)
        q_cold = _heat_by_stream(cold, Tc_a, Tc_b)
        area += (sum(q / h[n] for n, q in q_hot.items()) + sum(q / h[n] for n, q in q_cold.items())) / dTlm

    return AreaTarget(area=area, units=units_target(stream_set), heat_recovered=H_hi - H_lo)


def units_target(stream_set: StreamSet) -> int:
    """(S - 1) above plus (S - 1) below the pinch, counting process streams present on each side."""
    table = problem_table(stream_set)
    top, bottom = float(table.T_star_C[0]), float(table.T_star_C[-1])
    # zero flow at the top or bottom boundary means a utility is zero (balanced or
    # threshold problem), not a pinch that splits the problem
    interior = [T for T in table.pinch_T_star_C if bottom < T < top]
    if not interior:
        return max(len(stream_set.streams) - 1, 0)
    above = [s for s in stream_set.streams if max(s.T_star_in_C, s.T_star_out_C) > max(interior)]
    below = [s for s in stream_set.streams if min(s.T_star_in_C, s.T_star_out_C) < min(interior)]
    return max(len(above) - 1, 0) + max(len(below) - 1, 0)


def with_uniform_dTmin(stream_set: StreamSet, dTmin_K: float) -> StreamSet:
    """Copy with every stream's shift set to ΔTmin / 2."""
    if dTmin_K <= 0:
        raise ValueError("dTmin must be positive")
    return replace(stream_set, streams=tuple(replace(s, dT_shift_K=dTmin_K / 2) for s in stream_set.streams))


@dataclass(frozen=True)
class CostLaw:
    """Exchanger installed cost per unit: a + b * area_per_unit**c [EUR], with a source."""

    a: float
    b: float
    c: float
    source: str

    def network_cost(self, area: float, units: int) -> float:
        if units <= 0 or area <= 0:
            return 0.0
        return units * (self.a + self.b * (area / units) ** self.c)


def supertarget(stream_set: StreamSet, h: dict[str, float], dTmin_grid_K, cost_law: CostLaw,
                crf_per_year: float, hot_utility_cost: float, cold_utility_cost: float) -> list[dict]:
    """Total annual cost for each ΔTmin.

    Parameters
    ----------
    hot_utility_cost, cold_utility_cost : float
        Cost per unit of Q̇h,min and Q̇c,min per year [EUR per (energy unit) per year],
        e.g. EUR/year per kW of continuous duty.
    crf_per_year : float
        Capital recovery factor [1/year].
    """
    rows = []
    for dT in dTmin_grid_K:
        s = with_uniform_dTmin(stream_set, float(dT))
        t = problem_table(s)
        at = area_target(s, h)
        capital = cost_law.network_cost(at.area, at.units)
        energy = t.Qh_min * hot_utility_cost + t.Qc_min * cold_utility_cost
        rows.append({"dTmin_K": float(dT), "Qh_min": t.Qh_min, "Qc_min": t.Qc_min, "area_m2": at.area,
                     "units": at.units, "capital_EUR": capital, "annualised_capital_EUR": capital * crf_per_year,
                     "energy_cost_EUR": energy, "TAC_EUR": capital * crf_per_year + energy})
    return rows
