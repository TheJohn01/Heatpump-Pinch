"""Problem Table Algorithm (Linnhoff and Flower, 1978; Kemp, 2007, Ch. 2).

Steps
-----
1. Shift each stream by its own dT_shift_K to obtain shifted temperatures T*.
2. Sort all distinct T* values into temperature intervals (descending).
3. In each interval, net surplus dH = (sum CP_hot - sum CP_cold) * dT*.
4. Cascade the surpluses from the top with zero hot utility (infeasible
   cascade). The most negative value gives the minimum hot utility Qh_min.
5. Add Qh_min at the top (feasible cascade). The bottom value is Qc_min, and
   every interval boundary with zero heat flow is a pinch.

The feasible cascade, plotted as heat flow against T*, is the Grand Composite
Curve (GCC).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pinch.streams import StreamSet


@dataclass(frozen=True)
class ProblemTable:
    """Result of the Problem Table Algorithm.

    Attributes
    ----------
    T_star_C : np.ndarray
        Interval boundaries in shifted temperature, descending [°C], length n.
    dH : np.ndarray
        Net heat surplus per interval (positive = surplus), length n - 1
        [energy unit].
    cascade_infeasible : np.ndarray
        Heat flow at each boundary with zero hot utility, length n.
    cascade_feasible : np.ndarray
        Heat flow at each boundary with Qh_min added, length n. This is the
        GCC heat axis.
    Qh_min, Qc_min : float
        Minimum hot and cold utility [energy unit].
    pinch_T_star_C : tuple[float, ...]
        Shifted temperatures where the feasible cascade is zero.
    energy_unit : str
        Unit of all heat quantities.
    Q_cold_total : float
        Sum of all cold-stream loads, used for the heat recovery target.
    """

    T_star_C: np.ndarray
    dH: np.ndarray
    cascade_infeasible: np.ndarray
    cascade_feasible: np.ndarray
    Qh_min: float
    Qc_min: float
    pinch_T_star_C: tuple[float, ...]
    energy_unit: str
    Q_cold_total: float

    @property
    def is_threshold(self) -> bool:
        """True if one utility target is zero (threshold problem, no true pinch)."""
        tol = _tolerance(self.cascade_feasible)
        return self.Qh_min <= tol or self.Qc_min <= tol

    @property
    def heat_recovery(self) -> float:
        """Maximum heat recovery = total cold load - Qh_min [energy unit]."""
        return self.Q_cold_total - self.Qh_min

    def to_frame(self) -> pd.DataFrame:
        """Tabulate the cascade, one row per interval boundary."""
        dH = np.concatenate([[np.nan], self.dH])
        return pd.DataFrame(
            {
                "T_star_C": self.T_star_C,
                f"dH_interval_above_{self.energy_unit}": dH,
                f"cascade_infeasible_{self.energy_unit}": self.cascade_infeasible,
                f"cascade_feasible_{self.energy_unit}": self.cascade_feasible,
            }
        )


def _tolerance(values: np.ndarray) -> float:
    """Absolute tolerance for zero-flow detection, scaled to the problem size."""
    return 1e-9 * max(1.0, float(np.max(np.abs(values))))


def problem_table(stream_set: StreamSet) -> ProblemTable:
    """Run the Problem Table Algorithm on a set of streams.

    Parameters
    ----------
    stream_set : StreamSet
        Validated streams with individual temperature shifts.

    Returns
    -------
    ProblemTable
        Interval data, cascades, utility targets and pinch temperature(s).
    """
    streams = stream_set.streams
    T_star_C = np.array(
        sorted({t for s in streams for t in (s.T_star_in_C, s.T_star_out_C)}, reverse=True)
    )

    dH = np.zeros(len(T_star_C) - 1)
    for i, (T_top, T_bot) in enumerate(zip(T_star_C[:-1], T_star_C[1:])):
        net_CP = 0.0
        for s in streams:
            lo, hi = sorted((s.T_star_in_C, s.T_star_out_C))
            if lo <= T_bot and hi >= T_top:  # stream spans the whole interval
                net_CP += s.CP if s.kind == "hot" else -s.CP
        dH[i] = net_CP * (T_top - T_bot)

    cascade_infeasible = np.concatenate([[0.0], np.cumsum(dH)])
    Qh_min = max(0.0, -float(cascade_infeasible.min()))
    cascade_feasible = cascade_infeasible + Qh_min
    Qc_min = float(cascade_feasible[-1])

    tol = _tolerance(cascade_feasible)
    cascade_feasible[np.abs(cascade_feasible) < tol] = 0.0  # remove round-off noise
    pinch = tuple(float(T) for T, q in zip(T_star_C, cascade_feasible) if q == 0.0)

    return ProblemTable(
        T_star_C=T_star_C,
        dH=dH,
        cascade_infeasible=cascade_infeasible,
        cascade_feasible=cascade_feasible,
        Qh_min=Qh_min,
        Qc_min=Qc_min,
        pinch_T_star_C=pinch,
        energy_unit=stream_set.energy_unit,
        Q_cold_total=sum(s.Q for s in stream_set.cold),
    )
