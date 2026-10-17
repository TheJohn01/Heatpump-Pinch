"""Existing heat-exchanger networks: evaluation, pinch diagnostics and retrofit (workflow step 5).

A network is a list of matches. Each match transfers heat from one or more hot
stream *segments* to one or more cold stream segments:

* direct match: a heat exchanger between process streams; the approach must
  respect the individual shifts, T_hot - T_cold >= shift_hot + shift_cold;
* indirect match: heat transfer through an intermediate medium (e.g. a
  stratified hot-water tank). It needs ``extra_dT_K`` more approach, the
  penalty of two transfers instead of one (Padullés et al., 2026, Sec. 4.1 use
  2 K per stream, i.e. 4 K per hot-cold pair).

What is not covered by matches goes to utilities (heaters, coolers).

Diagnostics follow the network pinch analysis of Tjoe and Linnhoff (1986), as
summarised in standard texts: with the pinch of the stream data,

    Q̇h,network - Q̇h,min = Σ cross-pinch transfer in matches
                          + Σ heater duty below the pinch
                          + Σ cooler duty above the pinch,

an identity the code checks (tests). Each term points to a retrofit action.

For heat pump design on an existing network, ``constrained_streams`` builds
the stream set in which a heat pump can act: residual heaters plus the streams
of indirect systems (where storage lets heat be reassigned freely), with the
extra approach of the indirect transfer put on the hot (charging) side.
Direct matches and residual coolers are left out (they stay as they are).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from pinch.curves import piecewise_composite
from pinch.problem_table_algorithm import problem_table
from pinch.streams import Stream, StreamSet

TOL = 1e-6


@dataclass(frozen=True)
class Segment:
    """Part of a stream between two temperatures, in the stream's own direction [°C]."""

    stream: str
    T_from_C: float
    T_to_C: float


@dataclass(frozen=True)
class Match:
    """A heat exchanger (direct) or a storage-based transfer (indirect)."""

    name: str
    hot: tuple[Segment, ...]
    cold: tuple[Segment, ...]
    indirect: bool = False
    extra_dT_K: float = 0.0
    note: str = ""


@dataclass(frozen=True)
class Network:
    name: str
    matches: tuple[Match, ...]
    description: str = ""
    provenance: dict = field(default_factory=dict)


def load_networks(path: str | Path) -> dict[str, Network]:
    """Read a JSON file holding one or more networks: {"networks": {name: {...}}}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for name, n in raw["networks"].items():
        matches = tuple(
            Match(m["name"],
                  tuple(Segment(*s) for s in m["hot"]),
                  tuple(Segment(*s) for s in m["cold"]),
                  bool(m.get("indirect", False)), float(m.get("extra_dT_K", 0.0)), m.get("note", ""))
            for m in n["matches"])
        out[name] = Network(name, matches, n.get("description", ""), n.get("provenance", {}))
    return out


# ------------------------------------------------------------------ helpers
def _stream(streams: StreamSet, name: str) -> Stream:
    for s in streams.streams:
        if s.name == name:
            return s
    raise ValueError(f"network refers to unknown stream '{name}'")


def _check_segment(s: Stream, seg: Segment) -> float:
    """Validate a segment against its stream; return its duty."""
    lo, hi = sorted((s.T_in_C, s.T_out_C))
    if not (lo - TOL <= seg.T_from_C <= hi + TOL and lo - TOL <= seg.T_to_C <= hi + TOL):
        raise ValueError(f"segment {seg} outside stream '{s.name}' ({s.T_in_C} -> {s.T_out_C} °C)")
    going_down = seg.T_to_C < seg.T_from_C
    if (s.kind == "hot") != going_down:
        raise ValueError(f"segment {seg} runs against the direction of '{s.name}'")
    return s.CP * abs(seg.T_to_C - seg.T_from_C)


def _profile(streams: StreamSet, segs: tuple[Segment, ...], extra_K: float, sign: int):
    """Composite of segments as (H from the hot end, shifted T) breakpoints.

    sign = -1 for hot (T* = T - shift - extra), +1 for cold (T* = T + shift).
    """
    pieces = []
    for seg in segs:
        s = _stream(streams, seg.stream)
        lo, hi = sorted((seg.T_from_C, seg.T_to_C))
        shift = s.dT_shift_K + (extra_K if sign < 0 else 0.0)
        pieces.append((lo + sign * shift, hi + sign * shift, s.CP))
    T, H = piecewise_composite(pieces, descending=True)
    return H, T


def _T_at(H_prof, T_prof, H):
    return np.interp(H, H_prof, T_prof)


# ------------------------------------------------------------------ evaluation
@dataclass
class NetworkResult:
    """Evaluation of a network on a stream set (all heat in the stream-data unit)."""

    name: str
    Qh: float
    Qc: float
    Qh_min: float
    Qc_min: float
    pinch_T_star_C: float
    matches: pd.DataFrame
    heaters: pd.DataFrame
    coolers: pd.DataFrame
    cross_pinch_matches: float
    heaters_below_pinch: float
    coolers_above_pinch: float
    refrigeration: float           # cooler duty below T* = ambient

    @property
    def energy_gap(self) -> float:
        return self.Qh - self.Qh_min

    @property
    def heat_recovered(self) -> float:
        return float(self.matches["duty"].sum()) if len(self.matches) else 0.0

    def summary(self) -> dict:
        return {"network": self.name, "Qh": round(self.Qh, 4), "Qc": round(self.Qc, 4),
                "Qh_min": round(self.Qh_min, 4), "Qc_min": round(self.Qc_min, 4),
                "energy_gap": round(self.energy_gap, 4), "heat_recovered": round(self.heat_recovered, 4),
                "cross_pinch_in_matches": round(self.cross_pinch_matches, 4),
                "heaters_below_pinch": round(self.heaters_below_pinch, 4),
                "coolers_above_pinch": round(self.coolers_above_pinch, 4),
                "refrigeration_below_ambient": round(self.refrigeration, 4),
                "pinch_T_star_C": self.pinch_T_star_C}


def _residual(streams: StreamSet, network: Network) -> dict[str, list[tuple[float, float]]]:
    """Uncovered temperature intervals per stream (ascending (lo, hi) pairs)."""
    used: dict[str, list[tuple[float, float]]] = {}
    for m in network.matches:
        for seg in m.hot + m.cold:
            used.setdefault(seg.stream, []).append(tuple(sorted((seg.T_from_C, seg.T_to_C))))
    out = {}
    for s in streams.streams:
        lo, hi = sorted((s.T_in_C, s.T_out_C))
        ivs = sorted(used.get(s.name, []))
        for (a1, b1), (a2, b2) in zip(ivs[:-1], ivs[1:]):
            if a2 < b1 - TOL:
                raise ValueError(f"stream '{s.name}': segments overlap ({a1}-{b1} and {a2}-{b2} °C)")
        free, cur = [], lo
        for a, b in ivs:
            if a > cur + TOL:
                free.append((cur, a))
            cur = max(cur, b)
        if hi > cur + TOL:
            free.append((cur, hi))
        out[s.name] = free
    return out


def _portion(s: Stream, lo: float, hi: float, T_star_limit: float, below: bool) -> float:
    """Duty of [lo, hi] (real T) lying below (or above) T* = limit."""
    a, b = s._shift(lo), s._shift(hi)
    a, b = min(a, b), max(a, b)
    width = max(0.0, min(b, T_star_limit) - a) if below else max(0.0, b - max(a, T_star_limit))
    return width * s.CP


def evaluate_network(streams: StreamSet, network: Network, T_amb_C: float | None = None, n: int = 400) -> NetworkResult:
    """Utilities, match feasibility and pinch diagnostics of an existing network."""
    t = problem_table(streams)
    pinch = t.pinch_T_star_C[0] if t.pinch_T_star_C else float("nan")

    rows = []
    xp_total = 0.0
    for m in network.matches:
        q_hot = sum(_check_segment(_stream(streams, g.stream), g) for g in m.hot)
        q_cold = sum(_check_segment(_stream(streams, g.stream), g) for g in m.cold)
        if abs(q_hot - q_cold) > 1e-3 * max(q_hot, q_cold, 1e-9):
            raise ValueError(f"match '{m.name}': hot duty {q_hot:.4g} differs from cold duty {q_cold:.4g}")
        extra = m.extra_dT_K if m.indirect else 0.0
        Hh, Th = _profile(streams, m.hot, extra, -1)
        Hc, Tc = _profile(streams, m.cold, 0.0, +1)
        grid = np.linspace(0, q_hot, n + 1)
        margin = float(np.min(_T_at(Hh, Th, grid) - _T_at(Hc, Tc, np.minimum(grid, Hc[-1]))))
        # cross-pinch: hot above the pinch paired with cold below it (counter-current, by duty)
        mid = 0.5 * (grid[1:] + grid[:-1])
        Hh0, Th0 = _profile(streams, m.hot, 0.0, -1)        # pinch side judged with the stream shifts only
        crossing = (_T_at(Hh0, Th0, mid) > pinch) & (_T_at(Hc, Tc, np.minimum(mid, Hc[-1])) < pinch)
        xp = float(np.sum(crossing) * q_hot / n)
        xp_total += xp
        rows.append({"match": m.name, "type": "indirect" if m.indirect else "direct", "duty": round(q_hot, 4),
                     "min_shifted_approach_K": round(margin, 3), "feasible": margin >= -1e-3,
                     "cross_pinch": round(xp, 4), "note": m.note})
    match_df = pd.DataFrame(rows)
    if len(match_df) and not match_df["feasible"].all():
        bad = match_df.loc[~match_df["feasible"], "match"].tolist()
        raise ValueError(f"temperature-infeasible matches: {bad}")

    heaters, coolers = [], []
    for name, ivs in _residual(streams, network).items():
        s = _stream(streams, name)
        for lo, hi in ivs:
            row = {"stream": name, "T_from_C": hi if s.kind == "hot" else lo, "T_to_C": lo if s.kind == "hot" else hi,
                   "duty": s.CP * (hi - lo)}
            if s.kind == "cold":
                row["below_pinch"] = _portion(s, lo, hi, pinch, below=True)
                heaters.append(row)
            else:
                row["above_pinch"] = _portion(s, lo, hi, pinch, below=False)
                row["below_ambient"] = _portion(s, lo, hi, T_amb_C, below=True) if T_amb_C is not None else 0.0
                coolers.append(row)
    H = pd.DataFrame(heaters, columns=["stream", "T_from_C", "T_to_C", "duty", "below_pinch"])
    C = pd.DataFrame(coolers, columns=["stream", "T_from_C", "T_to_C", "duty", "above_pinch", "below_ambient"])
    return NetworkResult(network.name, float(H["duty"].sum()), float(C["duty"].sum()), t.Qh_min, t.Qc_min, pinch,
                         match_df, H, C, xp_total, float(H["below_pinch"].sum()), float(C["above_pinch"].sum()),
                         float(C["below_ambient"].sum()))


def constrained_streams(streams: StreamSet, network: Network) -> StreamSet:
    """Stream set in which heat pumps can be added to an existing network.

    * residual heaters of every stream, as streams;
    * for each indirect match: its hot segments (shift + extra_dT_K) and the
      whole of every cold stream it serves (storage lets the heat be reassigned
      along those streams); the cold side keeps its own shift, because a heat
      pump can heat the storage medium directly.
    Direct matches and residual coolers are excluded.
    """
    res = _residual(streams, network)
    out: list[Stream] = []
    tank_cold = {g.stream for m in network.matches if m.indirect for g in m.cold}
    for m in network.matches:
        if not m.indirect:
            continue
        for g in m.hot:
            s = _stream(streams, g.stream)
            out.append(replace(s, name=f"{s.name} [{g.T_from_C:g}->{g.T_to_C:g}] via {m.name}", T_in_C=g.T_from_C,
                               T_out_C=g.T_to_C, Q=s.CP * abs(g.T_from_C - g.T_to_C),
                               dT_shift_K=s.dT_shift_K + m.extra_dT_K))
    for name in tank_cold:
        out.append(_stream(streams, name))
    for name, ivs in res.items():
        s = _stream(streams, name)
        if s.kind != "cold" or name in tank_cold:
            continue
        for lo, hi in ivs:
            out.append(replace(s, name=f"{s.name} [{lo:g}->{hi:g}]", T_in_C=lo, T_out_C=hi, Q=s.CP * (hi - lo)))
    return replace(streams, streams=tuple(out), source=f"{streams.source} constrained by {network.name}")
