"""Energy targets with forbidden and restricted matches (workflow step 2).

The Problem Table Algorithm assumes that any hot stream can heat any cold stream. On a real site some
pairs must not exchange heat directly: product quality and hygiene, safety (leakage between two fluids
that react), distance, or operation at different times (Becker and Maréchal 2012, Sec. 1; Wang et al.
2021, Sec. 1). This module computes the minimum utilities when such matches are forbidden or limited.

Sources
-------
* Becker and Maréchal (2012), "Energy integration of industrial sites with heat exchange restrictions",
  Computers and Chemical Engineering 37, 104-118, DOI 10.1016/j.compchemeng.2011.09.014: motivation;
  they extend a MILP heat cascade with restrictions and intermediate heat-transfer units.
* Wang, Klemeš, Varbanov, Zeng, Liang (2021), "Heat Exchanger Network synthesis considering prohibited
  and restricted matches", Energy 225, 120214, DOI 10.1016/j.energy.2021.120214: the distinction between
  prohibited matches (no heat at all) and restricted ones (allowed under conditions), after Nemet et al.;
  restrictions may also apply to utilities (e.g. steam hotter than a stream can tolerate).
* Both cite the transshipment formulation of Papoulias and Grossmann (1983) for forbidden matches. That
  paper was not available to us; the model below is the standard expanded transshipment linear
  programme, and it is validated by reproducing the Problem Table targets when nothing is restricted
  (tests/test_plant_data.py).

Model
-----
Temperature intervals k = 1..K in shifted temperature T* (the Problem Table's intervals, individual
ΔT_shift kept). q_ik = heat released by hot stream i in interval k; d_jk = heat taken by cold stream j.
Hot utility "HU" releases its heat in the top interval; cold utility "CU" takes heat below the bottom one.

    Q_ijk >= 0   heat from hot i to cold j in interval k (allowed only if hot i reaches interval k or above)
    R_ik  >= 0   heat of hot i carried down from interval k to k+1 (R_i0 = 0; R_iK goes to the cold utility)

    hot balance   R_ik = R_i,k-1 + q_ik - sum_j Q_ijk         for every hot i (incl. HU) and interval k
    cold balance  sum_i Q_ijk = d_jk                         for every cold j and interval k
    restriction   sum_k Q_ijk <= U_ij                        (U_ij = 0: forbidden)
    cold utility  Q_i,CU = R_iK; "i -> CU" forbidden means R_iK = 0

Objective: minimise the hot utility. Then Qc,min = Qh,min + sum q - sum d.

Not modelled: intermediate heat-transfer loops (a hot-water circuit between two forbidden partners),
which Becker and Maréchal (2012) add as extra streams; model them by adding the loop as a stream pair.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from pinch.problem_table_algorithm import problem_table
from pinch.streams import StreamSet

HU, CU = "HU", "CU"


@dataclass(frozen=True)
class RestrictedTargets:
    Qh_min: float
    Qc_min: float
    Qh_min_unrestricted: float
    Qc_min_unrestricted: float
    matches: dict[tuple[str, str], float]   # heat per (hot, cold) pair, including HU and CU, nonzero only
    energy_unit: str

    @property
    def penalty(self) -> float:
        """Extra hot utility caused by the restrictions [energy unit]."""
        return self.Qh_min - self.Qh_min_unrestricted


def restricted_targets(streams: StreamSet, limits: dict[tuple[str, str], float]) -> RestrictedTargets:
    """Minimum utilities with match limits.

    ``limits`` maps (hot name, cold name) to the most heat that pair may exchange [energy unit]; 0 forbids
    the match. Use "HU" as the hot name for the hot utility and "CU" as the cold name for the cold
    utility. Pairs not listed are unrestricted.
    """
    hot = [s for s in streams.hot]
    cold = [s for s in streams.cold]
    names = {s.name for s in streams.streams} | {HU, CU}
    for (h, c), u in limits.items():
        if h not in names or c not in names:
            raise ValueError(f"unknown stream in restriction ({h}, {c})")
        if h != HU and h not in {s.name for s in hot}:
            raise ValueError(f"'{h}' is not a hot stream")
        if c != CU and c not in {s.name for s in cold}:
            raise ValueError(f"'{c}' is not a cold stream")
        if u < 0:
            raise ValueError("a match limit must be >= 0")

    table = problem_table(streams)
    T = table.T_star_C                       # descending boundaries
    K = len(T) - 1

    def load(s, k):
        lo, hi = sorted((s.T_star_in_C, s.T_star_out_C))
        top, bot = T[k], T[k + 1]
        return s.CP * (top - bot) if lo <= bot and hi >= top else 0.0

    H = [HU] + [s.name for s in hot]
    C = [s.name for s in cold]
    q = np.array([[0.0] * K] + [[load(s, k) for k in range(K)] for s in hot])      # (len(H), K)
    d = np.array([[load(s, k) for k in range(K)] for s in cold])                   # (len(C), K)
    # highest interval each hot source reaches: HU = 0 (top), hot stream = its first interval with heat
    first = [0] + [int(np.argmax(row > 0)) if row.any() else K for row in q[1:]]

    # variables: Q[i, j, k] for allowed (i, j, k) with k >= first[i]; Qh; R[i, k] for k = 0..K-1 (R[i,K-1] -> CU)
    qidx, n = {}, 0
    for i in range(len(H)):
        for j, cname in enumerate(C):
            if limits.get((H[i], cname), np.inf) == 0:
                continue
            for k in range(first[i], K):
                if d[j, k] > 0:
                    qidx[i, j, k] = n
                    n += 1
    i_Qh = n
    n += 1
    ridx = {}
    for i in range(len(H)):
        for k in range(K):
            ridx[i, k] = n
            n += 1

    A_eq, b_eq = [], []
    for i in range(len(H)):                  # hot balances
        for k in range(K):
            row = np.zeros(n)
            row[ridx[i, k]] = 1.0
            if k > 0:
                row[ridx[i, k - 1]] = -1.0
            for (ii, j, kk), col in qidx.items():
                if ii == i and kk == k:
                    row[col] = 1.0
            if i == 0 and k == 0:
                row[i_Qh] = -1.0             # hot utility enters at the top
            A_eq.append(row)
            b_eq.append(q[i, k])
    for j in range(len(C)):                  # cold balances
        for k in range(K):
            if d[j, k] == 0:
                continue
            row = np.zeros(n)
            for (i, jj, kk), col in qidx.items():
                if jj == j and kk == k:
                    row[col] = 1.0
            A_eq.append(row)
            b_eq.append(d[j, k])

    A_ub, b_ub = [], []
    for (h, c), u in limits.items():
        if c == CU:
            if u == 0:
                row = np.zeros(n)
                row[ridx[H.index(h), K - 1]] = 1.0
                A_eq.append(row)
                b_eq.append(0.0)
            elif np.isfinite(u):
                row = np.zeros(n)
                row[ridx[H.index(h), K - 1]] = 1.0
                A_ub.append(row)
                b_ub.append(u)
            continue
        if u == 0 or not np.isfinite(u):
            continue
        i, j = H.index(h), C.index(c)
        row = np.zeros(n)
        for (ii, jj, _), col in qidx.items():
            if ii == i and jj == j:
                row[col] = 1.0
        A_ub.append(row)
        b_ub.append(u)

    cost = np.zeros(n)
    cost[i_Qh] = 1.0
    res = linprog(cost, A_ub=np.array(A_ub) if A_ub else None, b_ub=b_ub or None, A_eq=np.array(A_eq),
                  b_eq=b_eq, bounds=[(0, None)] * n, method="highs")
    if res.status != 0:
        raise ValueError(f"no feasible heat cascade with these restrictions ({res.message})")
    x = res.x
    Qh = float(x[i_Qh])
    Qc = Qh + float(q.sum()) - float(d.sum())
    matches: dict[tuple[str, str], float] = {}
    for (i, j, _), col in qidx.items():
        matches[H[i], C[j]] = matches.get((H[i], C[j]), 0.0) + float(x[col])
    for i in range(len(H)):
        matches[H[i], CU] = float(x[ridx[i, K - 1]])
    tol = 1e-9 * max(1.0, float(q.sum()) + Qh)
    matches = {k: v for k, v in matches.items() if v > tol}
    return RestrictedTargets(Qh_min=Qh, Qc_min=Qc, Qh_min_unrestricted=table.Qh_min,
                             Qc_min_unrestricted=table.Qc_min, matches=matches, energy_unit=streams.energy_unit)
