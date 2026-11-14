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
   temperatures; it reports any approach below the required minimum.
3. ``evaluate_exchangers``: area of each exchanger in counter-current flow, U from film coefficients and
   fouling resistances (1/U = 1/h_h + 1/h_c + R_f,h + R_f,c), cost from a per-unit law a + b A^c.
4. ``pinch_design``: the Pinch Design Method (Linnhoff and Hindmarsh 1983, Chem. Eng. Sci. 38, 745-763; the
   paper was not available, the rules are those of every textbook account): design starts at the pinch on
   each side with the number-of-streams and CP rules, splits streams where they fail, ticks off loads, and
   leaves heaters above and coolers below the pinch: a maximum-energy-recovery network in the
   ``pinch.network`` format. ``break_loops`` then removes loops (smallest unit first) and restores the
   approach by energy relaxation along utility paths, with temperatures from ``series_network``.

Validation (tests/test_hen_design.py) on the four-stream problem of Sagli et al. (1990) as given by Polley
and Panjeh Shahi (1991), Trans IChemE 69 A, 445-457 (Table 1, Figs 2-3, Tables 2, 4, 5): the Problem
Table gives Q̇h 1075 kW and Q̇c 400 kW; the minimum-units programme finds 5 units, the matches and loads
of their Network 5.1; ``series_network`` reproduces its temperatures and ``evaluate_exchangers`` its
expected sizes and capital cost at U = 50 W/m²K (published k$ 717.3); Network 6.1, entered from Fig. 2,
gives the published 716.0 k$. The Pinch Design Method keeps the published targets of that problem, the
Aromatics Plant and Kemp's four-stream process with the fewest MER units, and its loop breaking reaches the
5 units of Network 5.1 at the same energy (scripts/benchmarks/benchmark_pinch_design.py).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from pinch.network import Match, Network, Segment
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


# ------------------------------------------------------------------ Pinch Design Method

TOL_K = 1e-6


@dataclass(frozen=True)
class DesignMatch:
    """One unit of a designed network. Segments are (T_from_C, T_to_C, split fraction), real temperatures."""

    hot: str
    cold: str
    Q: float
    hot_seg: tuple[float, float, float]
    cold_seg: tuple[float, float, float]


@dataclass(frozen=True)
class PinchDesign:
    """Maximum-energy-recovery network from the Pinch Design Method, with its heaters and coolers.

    ``heaters`` and ``coolers``: (stream, T_from_C, T_to_C, Q) on the unmatched ends of the streams.
    """

    matches: tuple[DesignMatch, ...]
    heaters: tuple[tuple[str, float, float, float], ...]
    coolers: tuple[tuple[str, float, float, float], ...]
    pinch_T_star_C: float
    units_target: int              # (N - 1) above + (N - 1) below the pinch, utilities counted as streams
    hot_utility: str = "HU"
    cold_utility: str = "CU"

    @property
    def units(self) -> int:
        return len(self.matches) + len(self.heaters) + len(self.coolers)

    @property
    def splits(self) -> int:
        """Number of split streams."""
        return len({(m.hot, m.hot_seg[:2]) for m in self.matches if m.hot_seg[2] < 1 - 1e-9}
                   | {(m.cold, m.cold_seg[:2]) for m in self.matches if m.cold_seg[2] < 1 - 1e-9})

    def unit_loads(self) -> tuple[MatchLoad, ...]:
        """Every unit as a ``MatchLoad`` (heaters from ``hot_utility``, coolers to ``cold_utility``)."""
        return (tuple(MatchLoad(m.hot, m.cold, m.Q) for m in self.matches)
                + tuple(MatchLoad(self.hot_utility, s, q) for s, _, _, q in self.heaters)
                + tuple(MatchLoad(s, self.cold_utility, q) for s, _, _, q in self.coolers))

    def to_network(self, name: str, description: str = "") -> Network:
        """The process-process matches in the ``pinch.network`` format (utilities are the residuals)."""
        return Network(name, tuple(
            Match(f"E{i} {m.hot}-{m.cold}", (Segment(m.hot, *m.hot_seg),), (Segment(m.cold, *m.cold_seg),))
            for i, m in enumerate(self.matches, 1)), description)


# One side is designed in "above the pinch" orientation: intervals of shifted temperature [lo, hi] with the
# pinch at lo. ``must`` streams (hot above, cold below the pinch) are satisfied by process matches only; the
# ``other`` streams take the utility. Below the pinch the temperatures are mirrored (T' = -T*).
_Item = dict          # {"name", "CP", "lo", "hi"}
_Raw = tuple          # (must name, other name, Q, must (lo, hi, fraction), other (lo, hi, fraction))


def _fill(need: list[float], room: list[float], total: float, cap: list[float] | None = None) -> list[float]:
    """Loads between ``need`` and ``room`` adding up to ``total``, ticking off (load = ``cap``) as many
    streams as possible: those whose room reaches their whole load first, smallest first."""
    cap = room if cap is None else cap
    q = list(need)
    for k in sorted(range(len(q)), key=lambda k: (room[k] < cap[k] - 1e-9, room[k] - need[k])):
        q[k] += min(room[k] - need[k], max(total - sum(q), 0.0))
    return q


def _group(c: _Item, S: list[_Item], P: float) -> list[_Raw] | None:
    """Pinch matches of one other stream c (split if S has several) with the must streams S.

    Branch k of c serves must stream k over the common range [P, P + rc] of c; the CP rule holds when the
    must stream rises at least rc. Either every must stream is ticked off, or c is (over rc), with the
    loads chosen to tick off as many must streams as possible.
    """
    dTc, dTh = c["hi"] - P, [h["hi"] - P for h in S]
    Qh = [h["CP"] * d for h, d in zip(S, dTh)]
    if sum(Qh) <= c["CP"] * dTc * (1 + 1e-9):
        rc, q = sum(Qh) / c["CP"], Qh
    else:
        rc = min(dTc, *dTh)
        need = [h["CP"] * rc for h in S]
        if sum(need) > c["CP"] * rc * (1 + 1e-9):
            return None
        q = _fill(need, Qh, c["CP"] * rc)
    if any(qk / h["CP"] < rc - TOL_K for qk, h in zip(q, S)):
        return None
    return [(h["name"], c["name"], qk, (P, P + qk / h["CP"], 1.0), (P, P + rc, qk / sum(q))) for h, qk in zip(S, q)]


def _split(h: _Item, T: list[_Item], P: float) -> list[_Raw] | None:
    """Pinch matches of must stream h split over the other streams T, over a common range [P, P + rh] of h.

    Branch k may take at most CP_k min(rh, its range) (CP rule and capacity); rh is the largest range the
    branches can absorb, and the loads tick off as many other streams as possible.
    """
    def room(r: float) -> list[float]:
        return [c["CP"] * min(r, c["hi"] - P) for c in T]

    lo, hi = 0.0, h["hi"] - P
    if sum(room(hi)) < h["CP"] * hi:
        for _ in range(60):                             # largest rh with sum(room(rh)) >= CP_h rh
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if sum(room(mid)) >= h["CP"] * mid else (lo, mid)
    rh = lo if sum(room(hi)) < h["CP"] * hi else hi
    if rh <= TOL_K:
        return None
    q = _fill([0.0] * len(T), room(rh), h["CP"] * rh, [c["CP"] * (c["hi"] - P) for c in T])
    return [(h["name"], c["name"], qk, (P, P + rh, qk / (h["CP"] * rh)), (P, P + qk / c["CP"], 1.0))
            for c, qk in zip(T, q) if qk > TOL_K]


def _pinch_structures(H: list[_Item], C: list[_Item], P: float) -> list[list[_Raw]]:
    """Sets of pinch matches obeying the number-of-streams and CP rules, best first.

    Every must stream at the pinch gets a partner there with a CP at least its own. Options per must stream:
    one partner (several must streams on one partner split the partner) or a split over two partners. Order:
    fewest splits, then the largest pinch-match load (tick-off). Splits are only tried when no set without
    them exists.
    """
    Hp = [h for h in H if abs(h["lo"] - P) <= TOL_K]
    Cp = [c for c in C if abs(c["lo"] - P) <= TOL_K]
    if not Hp:
        return [[]]
    for with_splits in (False, True):
        found: list[tuple[tuple[int, float], list[_Raw]]] = []
        opts = [[("one", (j,)) for j in range(len(Cp))]
                + ([("split", pair) for pair in itertools.combinations(range(len(Cp)), 2)] if with_splits else [])
                for _ in Hp]
        for choice in itertools.product(*opts):
            hosted: dict[int, list[_Item]] = {}
            exclusive = [k for kind, js in choice if kind == "split" for k in js]
            for h, (kind, js) in zip(Hp, choice):
                if kind == "one":
                    hosted.setdefault(js[0], []).append(h)
            if len(set(exclusive)) < len(exclusive) or set(exclusive) & set(hosted):
                continue
            parts = [_group(Cp[j], S, P) for j, S in hosted.items()]
            parts += [_split(h, [Cp[k] for k in js], P) for h, (kind, js) in zip(Hp, choice) if kind == "split"]
            if any(p is None for p in parts):
                continue
            raws = [r for p in parts if p is not None for r in p]
            n_split = sum(len(S) > 1 for S in hosted.values()) + sum(kind == "split" for kind, _ in choice)
            found.append(((n_split, -sum(r[2] for r in raws)), raws))
        if found:
            return [r for _, r in sorted(found, key=lambda x: x[0])]
    raise ValueError(f"no pinch matches obey the CP rule at T* = {abs(P):g} °C, even with one split per stream")


def _away(H: list[_Item], C: list[_Item], budget: list[int], width: int = 3) -> list[_Raw] | None:
    """Matches away from the pinch until every must stream is satisfied (None if impossible).

    Candidates: each must/other pair, the other stream from its pinch-side end, the must stream from its far
    end or its pinch side, the largest feasible load. Tick-off matches first, then larger loads; depth-first
    over the best ``width`` candidates at each step, within a budget of steps.
    """
    H = [h for h in H if h["hi"] - h["lo"] > TOL_K]
    C = [c for c in C if c["hi"] - c["lo"] > TOL_K]
    if not H:
        return []
    budget[0] -= 1
    if budget[0] < 0:
        return None
    cands = []
    for i, h in enumerate(H):
        Qh = h["CP"] * (h["hi"] - h["lo"])
        for j, c in enumerate(C):
            Qc = c["CP"] * (c["hi"] - c["lo"])
            d = h["hi"] - c["lo"]
            if d <= TOL_K:
                continue
            for top in (True, False):
                Q = min(Qh, Qc, h["CP"] * d, c["CP"] * d) if top else min(Qh, Qc)
                ch = (c["lo"], c["lo"] + Q / c["CP"])
                hh = (h["hi"] - Q / h["CP"], h["hi"]) if top else (h["lo"], h["lo"] + Q / h["CP"])
                if Q <= TOL_K or hh[1] < ch[1] - TOL_K or hh[0] < ch[0] - TOL_K:
                    continue
                ticks = (abs(Q - Qh) <= 1e-9 * Qh) + (abs(Q - Qc) <= 1e-9 * Qc)
                cands.append(((ticks > 0, Q, min(hh[1] - ch[1], hh[0] - ch[0])), i, j, Q, hh, ch, top))
    for _, i, j, Q, hh, ch, top in sorted(cands, key=lambda x: x[0], reverse=True)[:width]:
        H2, C2 = [dict(x) for x in H], [dict(x) for x in C]
        C2[j]["lo"] = ch[1]
        H2[i]["hi" if top else "lo"] = hh[0] if top else hh[1]
        rest = _away(H2, C2, budget, width)
        if rest is not None:
            return [(H[i]["name"], C[j]["name"], Q, (*hh, 1.0), (*ch, 1.0)), *rest]
    return None


def _design_side(H: list[_Item], C: list[_Item], P: float, budget: int = 5000) -> tuple[list[_Raw], list[_Item]]:
    """Pinch matches, then matches away from the pinch; returns the matches and what the utility takes."""
    H = [h for h in H if h["hi"] - h["lo"] > TOL_K]
    C = [c for c in C if c["hi"] - c["lo"] > TOL_K]
    left = [budget]
    for raws in _pinch_structures(H, C, P):
        H2, C2 = [dict(x) for x in H], [dict(x) for x in C]
        for x in H2 + C2:                               # pinch matches use [P, top] of each stream they touch
            tops = [r[3][1] for r in raws if r[0] == x["name"]] + [r[4][1] for r in raws if r[1] == x["name"]]
            if tops:
                x["lo"] = max(tops)
        rest = _away(H2, C2, left)
        if rest is not None:
            for _, cn, Q, _, _ in rest:
                c = next(x for x in C2 if x["name"] == cn)
                c["lo"] += Q / c["CP"]
            return raws + rest, [c for c in C2 if c["hi"] - c["lo"] > TOL_K]
        if left[0] < 0:
            break
    raise ValueError("Pinch Design Method: no feasible set of matches found for "
                     + ", ".join(h["name"] for h in H) + f" (T* side of {abs(P):g} °C)")


def _pinch(streams: StreamSet) -> tuple[float, float, float]:
    """(pinch T*, Qh_min, Qc_min); a threshold problem puts the pinch at the end that needs no utility."""
    t = problem_table(streams)
    if len(t.pinch_T_star_C) > 1:   # shortcut: one pinch only; design each region separately if several
        raise ValueError(f"several pinches {t.pinch_T_star_C}: design each region separately")
    T_all = [T for s in streams.streams for T in (s.T_star_in_C, s.T_star_out_C)]
    P = t.pinch_T_star_C[0] if t.pinch_T_star_C else (max(T_all) if t.Qh_min <= 1e-9 else min(T_all))
    return P, t.Qh_min, t.Qc_min


def units_target_mer(streams: StreamSet) -> int:
    """Fewest units of a maximum-energy-recovery network: (N - 1) above plus (N - 1) below the pinch,
    utilities counted as streams (Linnhoff and Hindmarsh 1983, as summarised by Kemp 2007, Sec. 4.3)."""
    P, Qh, Qc = _pinch(streams)
    above = sum(max(s.T_star_in_C, s.T_star_out_C) > P + TOL_K for s in streams.streams) + (Qh > 1e-9)
    below = sum(min(s.T_star_in_C, s.T_star_out_C) < P - TOL_K for s in streams.streams) + (Qc > 1e-9)
    return max(above - 1, 0) + max(below - 1, 0)


def pinch_design(streams: StreamSet, hot_utility: str = "HU", cold_utility: str = "CU") -> PinchDesign:
    """Maximum-energy-recovery network by the Pinch Design Method (Linnhoff and Hindmarsh 1983).

    Above the pinch, every hot stream at the pinch is matched there with a cold stream (or branch) whose CP
    is at least its own (CP_hot <= CP_cold), below it every cold stream with a hot one (CP_hot >= CP_cold);
    when the number of streams or the CPs do not allow it, streams are split. Each match takes the largest
    load it can (tick-off). Away from the pinch the remaining loads are matched largest first; what the
    process cannot do goes to heaters above and coolers below the pinch. Approaches are those of the stream
    shifts (T* space): no exchanger approaches closer than the sum of its two shifts.

    Single pinch only (or a threshold problem); variable-CP streams entered as several rows are designed as
    separate streams.
    """
    P, _, _ = _pinch(streams)
    by = {s.name: s for s in streams.streams}

    def items(kind: str, above: bool) -> list[_Item]:
        out = []
        for s in streams.streams:
            lo, hi = sorted((s.T_star_in_C, s.T_star_out_C))
            lo, hi = (max(lo, P), hi) if above else (lo, min(hi, P))
            if s.kind == kind and hi - lo > TOL_K:
                out.append({"name": s.name, "CP": s.CP, "lo": lo, "hi": hi} if above else
                           {"name": s.name, "CP": s.CP, "lo": -hi, "hi": -lo})
        return out

    def seg(name: str, lo: float, hi: float, f: float = 1.0) -> tuple[float, float, float]:
        s = by[name]
        d = s.dT_shift_K if s.kind == "hot" else -s.dT_shift_K
        return (hi + d, lo + d, f) if s.kind == "hot" else (lo + d, hi + d, f)

    raws, heat = _design_side(items("hot", True), items("cold", True), P)
    matches = [DesignMatch(hn, cn, Q, seg(hn, *hs), seg(cn, *cs)) for hn, cn, Q, hs, cs in raws]
    heaters = tuple((c["name"], *seg(c["name"], c["lo"], c["hi"])[:2], c["CP"] * (c["hi"] - c["lo"])) for c in heat)
    raws, cool = _design_side(items("cold", False), items("hot", False), -P)
    matches += [DesignMatch(hn, cn, Q, seg(hn, -hh, -hl, hf), seg(cn, -ch, -cl, cf))
                for cn, hn, Q, (cl, ch, cf), (hl, hh, hf) in raws]
    coolers = tuple((h["name"], *seg(h["name"], -h["hi"], -h["lo"])[:2], h["CP"] * (h["hi"] - h["lo"])) for h in cool)
    return PinchDesign(tuple(matches), heaters, coolers, P, units_target_mer(streams), hot_utility, cold_utility)


# ------------------------------------------------------------------ loops and paths

def _merged(units: list[MatchLoad]) -> tuple[MatchLoad, ...]:
    """Units of the same pair summed into one (``series_network`` places one exchanger per pair)."""
    q: dict[tuple[str, str], float] = {}
    for u in units:
        q[u.hot, u.cold] = q.get((u.hot, u.cold), 0.0) + u.Q
    return tuple(MatchLoad(h, c, v) for (h, c), v in q.items())


def _route(units: list[MatchLoad], start: str, end: str, skip: int) -> list[int] | None:
    """Unit indices of a shortest route from ``start`` to ``end`` that does not use unit ``skip``."""
    prev: dict[str, tuple[str, int] | None] = {start: None}
    todo = [start]
    while todo:
        node = todo.pop(0)
        for k, u in enumerate(units):
            if k == skip or node not in (u.hot, u.cold):
                continue
            nxt = u.cold if node == u.hot else u.hot
            if nxt not in prev:
                prev[nxt] = (node, k)
                todo.append(nxt)
    if end not in prev:
        return None
    out, node = [], end
    while (step := prev[node]) is not None:
        node, k = step
        out.append(k)
    return out[::-1]


def find_loop(units: tuple[MatchLoad, ...], keep: frozenset[MatchLoad] = frozenset()) -> list[int] | None:
    """A loop through the smallest unit that lies on one, as unit indices in order around the loop.

    Units are edges between streams (utilities included, as in the Euler count); a loop is a closed route,
    two units between the same pair included. Units in ``keep`` are not removed. None when no loop is left.
    """
    for k in sorted(range(len(units)), key=lambda k: units[k].Q):
        if units[k] in keep:
            continue
        r = _route(list(units), units[k].cold, units[k].hot, k)
        if r is not None:
            return [k, *r]
    return None


def _paths(units: tuple[MatchLoad, ...], hot_utilities: set[str], cold_utilities: set[str]) -> list[list[int]]:
    """Every simple route from a hot utility to a cold utility (unit indices, heater first)."""
    out: list[list[int]] = []

    def walk(node: str, seen: set[str], route: list[int]) -> None:
        for k, u in enumerate(units):
            if k in route or node not in (u.hot, u.cold):
                continue
            nxt = u.cold if node == u.hot else u.hot
            if nxt in cold_utilities:
                out.append([*route, k])
            elif nxt not in seen and nxt not in hot_utilities:
                walk(nxt, seen | {nxt}, [*route, k])
    for h in sorted(hot_utilities):
        walk(h, {h}, [])
    return out


def _shift(units: tuple[MatchLoad, ...], route: list[int], x: float, first: float) -> tuple[MatchLoad, ...]:
    """Add ``first`` * x to the first unit of the route and alternate signs along it; drop emptied units."""
    q = [u.Q for u in units]
    for n, k in enumerate(route):
        q[k] += first * x * (1 if n % 2 == 0 else -1)
    return tuple(MatchLoad(u.hot, u.cold, v) for u, v in zip(units, q) if v > 1e-9 * max(q))


def series_to_network(name: str, net: SeriesNetwork, process: set[str], description: str = "") -> Network:
    """Process-process exchangers of a series network in the ``pinch.network`` format (utilities = residuals)."""
    return Network(name, tuple(
        Match(f"E{i} {e.hot}-{e.cold}", (Segment(e.hot, e.T_hot_in_C, e.T_hot_out_C),),
              (Segment(e.cold, e.T_cold_in_C, e.T_cold_out_C),))
        for i, e in enumerate((e for e in net.exchangers if e.hot in process and e.cold in process), 1)), description)


@dataclass(frozen=True)
class LoopBreaking:
    """Steps of loop breaking and the resulting network (``network`` from ``series_network``)."""

    units: tuple[MatchLoad, ...]
    network: SeriesNetwork
    steps: tuple[dict, ...]

    @property
    def hot_utility(self) -> float:
        return self.steps[-1]["hot_utility"] if self.steps else math.nan


def break_loops(units: tuple[MatchLoad, ...], ends: dict[str, tuple[float, float, str]],
                required_dT_K: dict[tuple[str, str], float], hot_utilities: set[str], cold_utilities: set[str],
                relax: bool = True, max_loops: int = 50) -> LoopBreaking:
    """Remove loops one at a time, smallest unit first, and restore the minimum approach by energy relaxation.

    Breaking a loop: the load of its smallest unit is subtracted from it and added to and subtracted from the
    other units of the loop in turn, which keeps every stream's duty; the unit disappears (Linnhoff and
    Hindmarsh 1983). Temperatures then follow from ``series_network`` (matches on each stream in series, so
    stream splits are not kept). If an exchanger approaches closer than required and ``relax`` is set, a
    path from a hot to a cold utility is relaxed: x more on its heater and cooler, -x/+x on the matches in
    between, with the smallest x (grid, then bisection) that restores every approach, or, when the series
    network already fell short before the break (lost splits), brings the shortfall back to what it was;
    the path needing the least
    extra utility is used; when no path can, the loop is kept (step marked ``kept``). Without ``relax`` the
    approach is left to fall, as in networks that keep the energy target with closer approaches.
    """
    def evaluate(u: tuple[MatchLoad, ...]) -> SeriesNetwork:
        m = _merged(list(u))
        return series_network(m, ends, {(x.hot, x.cold): required_dT_K.get((x.hot, x.cold), 0.0) for x in m})

    def margin(net: SeriesNetwork) -> float:
        return min(min(e.approaches_K) - required_dT_K.get((e.hot, e.cold), 0.0) for e in net.exchangers)

    def qh(u: tuple[MatchLoad, ...]) -> float:
        return sum(x.Q for x in u if x.hot in hot_utilities)

    def relaxation(u: tuple[MatchLoad, ...], target: float) -> tuple[float, list[int]] | None:
        """Smallest relaxation x over all utility paths that brings the margin to ``target``."""
        best = None
        for route in _paths(u, hot_utilities, cold_utilities):
            x_max = min([u[k].Q for n, k in enumerate(route) if n % 2] + [sum(x.Q for x in u)])
            grid = np.linspace(0.0, x_max, 41)[1:]           # first feasible x on a grid, then bisection
            ok = next((x for x in grid if margin(evaluate(_shift(u, route, float(x), 1.0))) >= target), None)
            if ok is None:
                continue
            lo, hi = float(ok - grid[0]), float(ok)
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                lo, hi = (lo, mid) if margin(evaluate(_shift(u, route, mid, 1.0))) >= target else (mid, hi)
            if best is None or hi < best[0]:
                best = (hi, route)
        return best

    steps: list[dict] = []
    keep: frozenset[MatchLoad] = frozenset()
    for _ in range(max_loops):
        loop = find_loop(units, keep)
        if loop is None:
            break
        before = units
        floor = min(0.0, margin(evaluate(units))) - 1e-6      # shortfall of the series network before
        removed = units[loop[0]]
        units = _shift(units, loop, removed.Q, -1.0)
        net = evaluate(units)
        step = {"removed": f"{removed.hot}-{removed.cold}", "load": removed.Q, "loop": len(loop),
                "relaxed_by": 0.0, "path": "", "kept": False}
        if relax and margin(net) < floor:
            best = relaxation(units, -1e-6) or relaxation(units, floor)
            if best is None:                          # relaxation cannot restore the approach: keep the loop
                units, keep = before, keep | {removed}
                net = evaluate(units)
                step.update(kept=True)
            else:
                x, route = best
                step.update(relaxed_by=x, path=" > ".join(f"{units[k].hot}-{units[k].cold}" for k in route))
                units = _shift(units, route, x, 1.0)
                net = evaluate(units)
        step.update(units=len(units), hot_utility=float(qh(units)), min_approach_K=float(net.min_approach_K))
        steps.append(step)
    return LoopBreaking(units, evaluate(units), tuple(steps))
