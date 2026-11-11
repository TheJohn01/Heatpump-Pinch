"""Heat-exchanger network synthesis and evaluation (workflow step 5).

Until now the tool targeted networks (Problem Table, area and units targets) and evaluated existing ones,
but did not design new ones. This module does three things:

1. ``min_units_matches``: which hot-cold pairs exchange heat and how much, with the fewest units, at a
   given hot utility (the energy target by default). Mixed-integer linear programme on the expanded
   transshipment model of the heat cascade with match binaries: the "minimum matches" step of sequential
   network synthesis (Papoulias and Grossmann 1983, Comput. Chem. Eng. 7, 707-721, as cited by Polley and
   Panjeh Shahi 1991, ref. 4, Becker and Maréchal 2012 and Wang et al. 2021; the paper itself was not
   available). Utilities are streams of unknown load. Matches are counted over the whole temperature
   range, so a pair exchanging heat on both sides of the pinch is one unit.
2. ``series_network``: places the matches on each stream in series, ordered by temperature (on a hot
   stream, the partner needing the hottest heat first; on a cold stream, the coldest partner first), and
   iterates until the order is stable. Gives a network without stream splits, with every exchanger's end
   temperatures; it reports any approach below the required minimum. Splits and loop breaking (Pinch
   Design Method, Linnhoff and Hindmarsh 1983; not available) are left to the engineer.
3. ``evaluate_exchangers``: area of each exchanger in counter-current flow, U from film coefficients and
   fouling resistances (1/U = 1/h_h + 1/h_c + R_f,h + R_f,c), cost from a per-unit law a + b A^c.

Validation (tests/test_hen_design.py) on the four-stream problem of Sagli et al. (1990) as given by Polley
and Panjeh Shahi (1991), Trans IChemE 69 A, 445-457 (Table 1, Figs 2-3, Tables 2, 4, 5): the Problem
Table gives Q̇h 1075 kW and Q̇c 400 kW; the minimum-units programme finds 5 units, the matches and loads
of their Network 5.1; ``series_network`` reproduces its temperatures and ``evaluate_exchangers`` its
expected sizes and capital cost at U = 50 W/m²K (published k$ 717.3); Network 6.1, entered from Fig. 2,
gives the published 716.0 k$.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from pinch.problem_table_algorithm import problem_table
from pinch.streams import Stream, StreamSet


@dataclass(frozen=True)
class UtilityStream:
    """A utility for synthesis: fixed temperatures, unknown load. Same conventions as process streams."""

    name: str
    kind: str              # "hot" or "cold"
    T_in_C: float
    T_out_C: float
    dT_shift_K: float = 0.0
    isothermal_width_K: float = 1.0

    def as_stream(self, load: float) -> Stream:
        lo, hi = sorted((self.T_in_C, self.T_out_C))
        if hi == lo:
            if self.kind == "hot":
                lo = hi - self.isothermal_width_K
            else:
                hi = lo + self.isothermal_width_K
        T_in, T_out = (hi, lo) if self.kind == "hot" else (lo, hi)
        return Stream(self.name, self.kind, T_in, T_out, max(load, 1e-12), self.dT_shift_K)


@dataclass(frozen=True)
class MatchLoad:
    hot: str
    cold: str
    Q: float


@dataclass(frozen=True)
class MatchResult:
    matches: tuple[MatchLoad, ...]
    hot_utility: dict[str, float]
    cold_utility: dict[str, float]
    units: int
    euler_minimum: int          # number of streams with load (process + utilities used) - 1


def min_units_matches(streams: StreamSet, hot_utilities: list[UtilityStream], cold_utilities: list[UtilityStream],
                      Qh: float | None = None, time_limit_s: float = 60.0) -> MatchResult:
    """Fewest matches that achieve hot utility ``Qh`` (default: the Problem Table target).

    ``Qh`` is the total over the hot utilities. With several hot (or cold) utilities the programme chooses
    their split. Raises ValueError if no network achieves ``Qh``.
    """
    table = problem_table(streams)
    Qh = table.Qh_min if Qh is None else float(Qh)
    Qc = Qh + sum(s.Q for s in streams.hot) - sum(s.Q for s in streams.cold)
    if Qh < table.Qh_min - 1e-9 * max(1.0, table.Qh_min) or Qc < -1e-9:
        raise ValueError(f"Qh = {Qh:g} is below the energy target {table.Qh_min:g}")

    hu = [u.as_stream(1.0) for u in hot_utilities]
    cu = [u.as_stream(1.0) for u in cold_utilities]
    T = sorted({t for s in (*streams.streams, *hu, *cu) for t in (s.T_star_in_C, s.T_star_out_C)}, reverse=True)
    K = len(T) - 1

    def frac(s: Stream, k: int) -> float:
        lo, hi = sorted((s.T_star_in_C, s.T_star_out_C))
        return max(0.0, min(hi, T[k]) - max(lo, T[k + 1])) / (hi - lo)

    # (name, load (0 for a utility: its load is a variable), fraction of the load in each interval, is utility)
    Side = tuple[str, float, list[float], bool]
    hots: list[Side] = [(s.name, s.Q, [frac(s, k) for k in range(K)], False) for s in streams.hot] + \
        [(s.name, 0.0, [frac(s, k) for k in range(K)], True) for s in hu]
    colds: list[Side] = [(s.name, s.Q, [frac(s, k) for k in range(K)], False) for s in streams.cold] + \
        [(s.name, 0.0, [frac(s, k) for k in range(K)], True) for s in cu]
    first = [next((k for k in range(K) if f[k] > 0), K) for _, _, f, _ in hots]

    # variables: Q[i,j,k] (allowed), R[i,k], x_hu[u], x_cu[u], y[i,j]
    idx: dict[tuple, int] = {}
    n = 0
    for i in range(len(hots)):
        for j, (_, _, fc, _) in enumerate(colds):
            for k in range(first[i], K):
                if fc[k] > 0:
                    idx["Q", i, j, k] = n
                    n += 1
    for i in range(len(hots)):
        for k in range(K):
            idx["R", i, k] = n
            n += 1
    for i, h in enumerate(hots):
        if h[3]:
            idx["x", "h", i] = n
            n += 1
    for j, c in enumerate(colds):
        if c[3]:
            idx["x", "c", j] = n
            n += 1
    pairs = sorted({(i, j) for (t, *rest) in idx if t == "Q" for i, j in [rest[:2]]})
    for i, j in pairs:
        idx["y", i, j] = n
        n += 1

    rows: list[np.ndarray] = []
    lo_b: list[float] = []
    hi_b: list[float] = []

    def add(coefs: dict[int, float], lo: float, hi: float) -> None:
        r = np.zeros(n)
        for c, v in coefs.items():
            r[c] += v
        rows.append(r)
        lo_b.append(lo)
        hi_b.append(hi)

    for i, (_, Qi, fi, is_u) in enumerate(hots):              # hot balances
        for k in range(K):
            coef: dict[int, float] = {idx["R", i, k]: 1.0}
            if k > 0:
                coef[idx["R", i, k - 1]] = -1.0
            for j in range(len(colds)):
                if ("Q", i, j, k) in idx:
                    coef[idx["Q", i, j, k]] = 1.0
            if is_u:
                coef[idx["x", "h", i]] = coef.get(idx["x", "h", i], 0.0) - fi[k]
                add(coef, 0.0, 0.0)
            else:
                add(coef, Qi * fi[k], Qi * fi[k])
        add({idx["R", i, K - 1]: 1.0}, 0.0, 0.0)                # all hot heat leaves through matches
    for j, (_, Qj, fj, is_u) in enumerate(colds):             # cold balances
        for k in range(K):
            coef = {idx["Q", i, j, k]: 1.0 for i in range(len(hots)) if ("Q", i, j, k) in idx}
            if is_u:
                coef[idx["x", "c", j]] = -fj[k]
                add(coef, 0.0, 0.0)
            elif fj[k] > 0:
                add(coef, Qj * fj[k], Qj * fj[k])
    add({idx["x", "h", i]: 1.0 for i, h in enumerate(hots) if h[3]}, Qh, Qh)
    big = Qh + Qc + sum(s.Q for s in streams.streams)
    for i, j in pairs:                                        # Q_ij <= M y_ij
        coef = {v: 1.0 for key, v in idx.items() if key[0] == "Q" and key[1] == i and key[2] == j}
        coef[idx["y", i, j]] = -big
        add(coef, -np.inf, 0.0)

    cost = np.zeros(n)
    integrality = np.zeros(n)
    ub = np.full(n, np.inf)
    for i, j in pairs:
        cost[idx["y", i, j]] = 1.0
        integrality[idx["y", i, j]] = 1
        ub[idx["y", i, j]] = 1.0
    res = milp(cost, constraints=LinearConstraint(np.array(rows), lo_b, hi_b), integrality=integrality,
               bounds=Bounds(np.zeros(n), ub), options={"time_limit": time_limit_s})
    if res.x is None:
        raise ValueError(f"no network achieves Qh = {Qh:g} ({res.message})")
    x = res.x
    loads: dict[tuple[int, int], float] = {}
    for key, v in idx.items():
        if key[0] == "Q":
            loads[key[1], key[2]] = loads.get((key[1], key[2]), 0.0) + float(x[v])
    tol = 1e-7 * big
    matches = tuple(MatchLoad(hots[i][0], colds[j][0], q) for (i, j), q in sorted(loads.items()) if q > tol)
    hu_loads = {hots[i][0]: float(x[idx["x", "h", i]]) for i, h in enumerate(hots) if h[3]}
    cu_loads = {colds[j][0]: float(x[idx["x", "c", j]]) for j, c in enumerate(colds) if c[3]}
    used = len(streams.streams) + sum(v > tol for v in (*hu_loads.values(), *cu_loads.values()))
    return MatchResult(matches, hu_loads, cu_loads, len(matches), used - 1)


# ------------------------------------------------------------------ series placement and evaluation

@dataclass(frozen=True)
class Exchanger:
    """One counter-current exchanger: duty and the four end temperatures [°C]."""

    hot: str
    cold: str
    Q: float
    T_hot_in_C: float
    T_hot_out_C: float
    T_cold_in_C: float
    T_cold_out_C: float

    @property
    def approaches_K(self) -> tuple[float, float]:
        return self.T_hot_in_C - self.T_cold_out_C, self.T_hot_out_C - self.T_cold_in_C

    @property
    def lmtd_K(self) -> float:
        a, b = self.approaches_K
        if a <= 0 or b <= 0:
            raise ValueError(f"{self.hot}-{self.cold}: temperature cross (approaches {a:.2f}, {b:.2f} K)")
        return a if math.isclose(a, b, rel_tol=1e-9) else (a - b) / math.log(a / b)


@dataclass(frozen=True)
class SeriesNetwork:
    exchangers: tuple[Exchanger, ...]
    min_approach_K: float
    violations: tuple[str, ...] = field(default_factory=tuple)


def series_network(matches: tuple[MatchLoad, ...], ends: dict[str, tuple[float, float, str]],
                   required_dT_K: dict[tuple[str, str], float] | None = None, max_rounds: int = 20,
                   max_permutations: int = 5040) -> SeriesNetwork:
    """Place matches in series on every stream and compute end temperatures.

    ``ends`` maps every stream and utility name to (T_in_C, T_out_C, kind); an isothermal utility has
    T_in = T_out. ``required_dT_K`` gives the minimum approach per pair (e.g. the sum of the two
    shifts, 0 if absent). The order of the matches on each stream is chosen by coordinate search over
    permutations: stream by stream, the order that maximises the smallest margin (approach minus
    required approach) over all exchangers, repeated until no order improves. A remaining negative
    margin is reported in ``violations``: no series arrangement of these loads exists, and stream
    splits are needed.
    """
    names = {m.hot for m in matches} | {m.cold for m in matches}
    missing = names - set(ends)
    if missing:
        raise ValueError(f"no temperatures for {sorted(missing)}")
    req = required_dT_K or {}
    totals = {s: sum(m.Q for m in matches if s in (m.hot, m.cold)) for s in names}

    def temps(order: dict[str, tuple[MatchLoad, ...]]) -> dict[tuple[str, str], tuple[float, float, float, float]]:
        span: dict[tuple[str, str, str], tuple[float, float]] = {}
        for s, ms in order.items():
            T_in, T_out, _ = ends[s]
            done = 0.0
            for m in ms:
                a = T_in + (T_out - T_in) * done / totals[s]
                done += m.Q
                span[m.hot, m.cold, s] = (a, T_in + (T_out - T_in) * done / totals[s])
        return {(m.hot, m.cold): (*span[m.hot, m.cold, m.hot], *span[m.hot, m.cold, m.cold]) for m in matches}

    def margin(order: dict[str, tuple[MatchLoad, ...]]) -> float:
        t = temps(order)
        return min(min(th_in - tc_out, th_out - tc_in) - req.get(k, 0.0)
                   for k, (th_in, th_out, tc_in, tc_out) in t.items())

    # start: on hot streams the partner with the hottest supply first, on cold streams the coldest first
    order: dict[str, tuple[MatchLoad, ...]] = {}
    for s in names:
        ms = [m for m in matches if s in (m.hot, m.cold)]
        if ends[s][2] == "hot":
            ms.sort(key=lambda m: -max(ends[m.cold][0], ends[m.cold][1]))
        else:
            ms.sort(key=lambda m: min(ends[m.hot][0], ends[m.hot][1]))
        order[s] = tuple(ms)
    best = margin(order)
    for _ in range(max_rounds):
        improved = False
        for s in sorted(names):
            if len(order[s]) < 2:
                continue
            for k, perm in enumerate(itertools.permutations(order[s])):
                if k >= max_permutations:
                    break
                trial = {**order, s: perm}
                v = margin(trial)
                if v > best + 1e-9:
                    order, best, improved = trial, v, True
        if not improved:
            break
    t = temps(order)
    exch = tuple(Exchanger(m.hot, m.cold, m.Q, *t[m.hot, m.cold]) for m in matches)
    viol = tuple(f"{e.hot}-{e.cold}: approach {min(e.approaches_K):.2f} K < {req.get((e.hot, e.cold), 0.0):.2f} K"
                 for e in exch if min(e.approaches_K) < req.get((e.hot, e.cold), 0.0) - 1e-6)
    return SeriesNetwork(exch, min(min(e.approaches_K) for e in exch), viol)


@dataclass(frozen=True)
class CostLaw:
    """Installed cost of one unit, a + b A^c (currency of the source)."""

    a: float
    b: float
    c: float

    def cost(self, area_m2: float) -> float:
        return self.a + self.b * area_m2 ** self.c


def overall_U(h_hot: float, h_cold: float, Rf_hot: float = 0.0, Rf_cold: float = 0.0) -> float:
    """1/U = 1/h_h + 1/h_c + R_f,h + R_f,c (consistent units, e.g. kW/m²K and m²K/kW)."""
    return 1.0 / (1.0 / h_hot + 1.0 / h_cold + Rf_hot + Rf_cold)


def evaluate_exchangers(exchangers: tuple[Exchanger, ...], h: dict[str, float], cost_law: CostLaw | None = None,
                        Rf: dict[str, float] | None = None) -> dict:
    """Area [m²] of each exchanger (Q / (U LMTD), counter-current), total area and cost.

    ``h`` and ``Rf`` per stream name; heat in kW with h in kW/m²K (or W with W/m²K).
    """
    Rf = Rf or {}
    rows = []
    for e in exchangers:
        U = overall_U(h[e.hot], h[e.cold], Rf.get(e.hot, 0.0), Rf.get(e.cold, 0.0))
        A = e.Q / (U * e.lmtd_K)
        rows.append({"hot": e.hot, "cold": e.cold, "Q": e.Q, "U": U, "LMTD_K": e.lmtd_K, "area_m2": A,
                     "cost": cost_law.cost(A) if cost_law else math.nan})
    return {"exchangers": rows, "area_m2": sum(r["area_m2"] for r in rows),
            "cost": sum(r["cost"] for r in rows) if cost_law else math.nan, "units": len(rows)}
