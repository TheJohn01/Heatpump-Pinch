"""Targets for several utility levels (workflow step 2, feeding step 4).

The Problem Table gives one hot and one cold utility. A real site has several levels: steam at more than
one pressure, hot water, cooling water, chilled water, and, after electrification, heat-pump condensers
at chosen temperatures. Each level can only supply the part of the demand that lies below it (or take
the part of the surplus above it), so the levels compete along the Grand Composite Curve. Placing utility
levels against the process profiles is the basis of Total Site targeting (Klemeš et al. 1997, Applied
Thermal Engineering 17, 993-1003, Figs 3-4: steam mains located against the site source and sink
profiles).

Model
-----
Each utility is a stream of fixed temperatures and unknown load x_u >= 0, with its own temperature
contribution ΔT_shift (default 0, the convention of ``pinch.heat_pump``: utility temperatures are read
directly against T*). The cascade over all interval boundaries must carry no negative heat flow:

    R_k = sum over intervals above k of (process surplus + utility loads) >= 0,   R_top = 0, R_bottom = 0.

The loads minimise sum c_u x_u. With costs that rise with temperature for hot utilities (and fall with
temperature for cold ones), this places the cheapest levels first, which is the usual rule of using the
lowest adequate hot utility and the highest adequate cold utility.

Known answers (tests/test_utilities.py): one hot and one cold utility outside the process range give
Qh,min and Qc,min of the Problem Table; a hot level below the GCC's top supplies exactly the GCC heat flow
at its temperature when the GCC falls monotonically to the pinch; the brewery's two heat-pump sink levels
reproduce the duties of ``pinch.design.design_from_gcc``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from pinch.problem_table_algorithm import problem_table
from pinch.streams import StreamSet


@dataclass(frozen=True)
class Utility:
    """A utility level. ``kind`` "hot" supplies heat (T_in >= T_out), "cold" takes heat (T_in <= T_out).

    Equal temperatures mean an isothermal utility (steam, boiling refrigerant): it is spread over
    ``isothermal_width_K`` below (hot) or above (cold) its temperature, as for latent process loads.
    ``cost`` is a relative cost per unit of heat; only the ranking between levels matters.
    """

    name: str
    kind: str
    T_in_C: float
    T_out_C: float
    cost: float
    dT_shift_K: float = 0.0
    isothermal_width_K: float = 1.0
    max_load: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("hot", "cold"):
            raise ValueError(f"{self.name}: kind must be 'hot' or 'cold'")
        if (self.kind == "hot" and self.T_in_C < self.T_out_C) or (self.kind == "cold" and self.T_in_C > self.T_out_C):
            raise ValueError(f"{self.name}: temperatures run the wrong way for a {self.kind} utility")
        if self.cost < 0 or self.dT_shift_K < 0 or self.isothermal_width_K <= 0:
            raise ValueError(f"{self.name}: cost, dT_shift_K must be >= 0 and the isothermal width > 0")

    def T_star_range(self) -> tuple[float, float]:
        """(low, high) shifted temperatures over which the utility exchanges heat."""
        hi, lo = max(self.T_in_C, self.T_out_C), min(self.T_in_C, self.T_out_C)
        if hi == lo:
            hi, lo = (hi, hi - self.isothermal_width_K) if self.kind == "hot" else (lo + self.isothermal_width_K, lo)
        s = -self.dT_shift_K if self.kind == "hot" else self.dT_shift_K
        return lo + s, hi + s


@dataclass(frozen=True)
class UtilityTargets:
    loads: dict[str, float]
    total_hot: float
    total_cold: float
    Qh_min: float
    Qc_min: float
    energy_unit: str


def utility_targets(streams: StreamSet, utilities: list[Utility]) -> UtilityTargets:
    """Loads of each utility level that close the cascade at minimum total cost."""
    if not utilities:
        raise ValueError("no utilities")
    if len({u.name for u in utilities}) != len(utilities):
        raise ValueError("utility names must be unique")
    base = problem_table(streams)
    T = sorted(set(base.T_star_C.tolist()) | {t for u in utilities for t in u.T_star_range()}, reverse=True)
    K = len(T) - 1

    def proc_surplus(k: int) -> float:
        top, bot = T[k], T[k + 1]
        net = 0.0
        for s in streams.streams:
            lo, hi = sorted((s.T_star_in_C, s.T_star_out_C))
            if lo <= bot and hi >= top:
                net += s.CP if s.kind == "hot" else -s.CP
        return net * (top - bot)

    d = np.array([proc_surplus(k) for k in range(K)])
    # fraction of each utility's load falling in interval k (linear profile)
    A = np.zeros((K, len(utilities)))
    for j, u in enumerate(utilities):
        lo, hi = u.T_star_range()
        for k in range(K):
            overlap = max(0.0, min(hi, T[k]) - max(lo, T[k + 1]))
            A[k, j] = (overlap / (hi - lo)) * (1.0 if u.kind == "hot" else -1.0)
    # cumulative cascade: R_k = cumsum(d + A x) >= 0 for k < K-1, last = 0
    C = np.tril(np.ones((K, K)))
    A_ub = -(C @ A)[:-1]
    b_ub = (C @ d)[:-1]
    A_eq = (C @ A)[-1:]
    b_eq = -(C @ d)[-1:]
    bounds = [(0, u.max_load) for u in utilities]
    res = linprog([u.cost for u in utilities], A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds,
                  method="highs")
    if res.status != 0:
        raise ValueError(f"the utilities cannot close the heat cascade ({res.message}): check that a hot "
                         "utility lies above the GCC's top and a cold one below its bottom")
    loads = {u.name: float(x) for u, x in zip(utilities, res.x)}
    return UtilityTargets(loads=loads,
                          total_hot=sum(v for u, v in zip(utilities, res.x) if u.kind == "hot"),
                          total_cold=sum(v for u, v in zip(utilities, res.x) if u.kind == "cold"),
                          Qh_min=base.Qh_min, Qc_min=base.Qc_min, energy_unit=streams.energy_unit)
