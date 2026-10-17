"""Refrigeration duty and the part of it that heat pump sources take over (steps 5 and 6).

One model, used by the grass-roots economics (``pinch.economic_analysis``) and by the
retrofit (``pinch.retrofit``). Before the redundancy audit (item 1.2) each had its own:
the economics capped the cascade's Q̇c reduction at the refrigeration duty, the retrofit
used min(Σ Q_source, refrigeration) behind an on/off temperature check.

Model
-----
All temperatures are shifted temperatures T* [°C]; heat pump sources are utilities
(dT_shift = 0) and are compared with T* directly. Cooling is described by a heat cascade
H(T*) (heat flowing down past T*), built in one of three ways:

* ``CoolingCascade.from_table``: heat recovery at the energy target; H is the feasible
  cascade of the Problem Table (the GCC);
* ``CoolingCascade.from_hot_streams``: no heat recovery; H is the heat of the hot
  streams above T* (no cold streams take any of it);
* ``CoolingCascade.from_coolers``: an existing network; H is the heat of its residual
  coolers above T*.

Cooling water or air can take heat at T*_top = min(ambient, pinch) and no lower; it can
take at most the smallest heat flow at or below T*_top, X = min_{T* <= T*_top} H(T*)
(taking more would leave a negative flow lower down). The rest of the cold utility,
Q̇c - X with Q̇c = H(bottom), is refrigeration.

A heat pump source at T*_src that takes Q from the process lowers H by Q at every
T* <= T*_src. It may take only what keeps H >= 0 there (otherwise Q̇h would rise); the
rest of its source duty Q_source = Q_sink (1 - 1/COP) is external (ambient air).
Units are served warmest source first. Then

    refrigeration taken over = fraction x [refrigeration(H) - refrigeration(H - sources)]

This is exact on the piecewise-linear cascade and needs no further Problem Table runs.
Two consequences, both physical:

* a source at or above T*_top takes over no refrigeration (it takes heat that cooling
  water would have taken anyway);
* a source below T*_top takes over at most the refrigeration located between its own
  temperature and T*_top; the refrigeration below its temperature remains.

``fraction`` is the refrigeration credit fraction of the economics block (1.0 by
default; 0.5 is the batch-mismatch sensitivity). Gliding sources are placed at their
inlet (warmest) temperature: conservative, since the evaporator must then be colder
than everything it takes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from pinch.heat_pump import HeatPump
from pinch.problem_table import ProblemTable
from pinch.streams import StreamSet


@dataclass(frozen=True)
class CoolingCascade:
    """Heat flow H(T*) on the cooling side of a site.

    Attributes
    ----------
    T_star_C : np.ndarray
        Boundaries in shifted temperature, descending [°C].
    H : np.ndarray
        Heat flowing down past each boundary [energy unit]; H >= 0.
    T_top_C : float
        Lowest T* at which cooling water or air can take heat: min(ambient, pinch) [°C].
    """

    T_star_C: np.ndarray
    H: np.ndarray
    T_top_C: float

    # ------------------------------------------------------------ builders
    @classmethod
    def from_table(cls, table: ProblemTable, T_amb_C: float | None) -> "CoolingCascade | None":
        """Heat recovery at the target: the feasible cascade (GCC). None without an ambient temperature."""
        if T_amb_C is None:
            return None
        pinch = min(table.pinch_T_star_C) if table.pinch_T_star_C else float(table.T_star_C[0])
        return cls(np.asarray(table.T_star_C, float), np.asarray(table.cascade_feasible, float), min(T_amb_C, pinch))

    @classmethod
    def from_pieces(cls, pieces: Iterable[tuple[float, float, float]], T_amb_C: float | None) -> "CoolingCascade | None":
        """Cooling of hot pieces (T*_lo, T*_hi, CP) by utilities only (no heat recovery between them)."""
        if T_amb_C is None:
            return None
        parts = [(lo, hi, cp) for lo, hi, cp in pieces if hi > lo and cp > 0]
        if not parts:
            return cls(np.array([T_amb_C]), np.array([0.0]), T_amb_C)
        T = np.array(sorted({t for lo, hi, _ in parts for t in (lo, hi)}, reverse=True))
        H = [0.0]
        for a, b in zip(T[:-1], T[1:]):
            H.append(H[-1] + sum(cp for lo, hi, cp in parts if lo <= b and hi >= a) * (a - b))
        return cls(T, np.array(H), min(T_amb_C, float(T[0])))

    @classmethod
    def from_hot_streams(cls, streams: StreamSet, T_amb_C: float | None) -> "CoolingCascade | None":
        """No heat recovery: every hot stream is cooled by utilities."""
        return cls.from_pieces(((min(s.T_star_in_C, s.T_star_out_C), max(s.T_star_in_C, s.T_star_out_C), s.CP)
                                for s in streams.hot), T_amb_C)

    @classmethod
    def from_coolers(cls, streams: StreamSet, coolers: pd.DataFrame, T_amb_C: float | None) -> "CoolingCascade | None":
        """An existing network: its residual coolers (columns stream, T_from_C, T_to_C, real temperatures)."""
        by_name = {s.name: s for s in streams.streams}
        pieces = []
        for _, c in coolers.iterrows():
            s = by_name[c["stream"]]
            lo, hi = sorted((float(c["T_from_C"]) - s.dT_shift_K, float(c["T_to_C"]) - s.dT_shift_K))
            pieces.append((lo, hi, s.CP))
        return cls.from_pieces(pieces, T_amb_C)

    # ------------------------------------------------------------ evaluation
    def _grid(self, extra: Iterable[float]) -> tuple[np.ndarray, np.ndarray]:
        """(T* descending, H) on the cascade boundaries plus the given temperatures (linear in between)."""
        T = np.array(sorted(set(self.T_star_C.tolist()) | {float(t) for t in extra}, reverse=True))
        H = np.interp(T, self.T_star_C[::-1], self.H[::-1])
        return T, H

    def _refrigeration(self, T: np.ndarray, H: np.ndarray) -> float:
        """Cold utility at the bottom minus what cooling water takes at T*_top (grid contains T*_top)."""
        cooling_water = max(0.0, float(np.min(H[T <= self.T_top_C])))
        return max(0.0, float(H[-1]) - cooling_water)

    @property
    def refrigeration(self) -> float:
        """Refrigeration duty: cold utility below T*_top [energy unit]."""
        return self._refrigeration(*self._grid([self.T_top_C]))

    def take(self, units: Iterable[HeatPump]) -> tuple[dict[str, float], float]:
        """Process source per unit and the refrigeration left after the units' sources [energy unit]."""
        with_source = sorted((u for u in units if u.has_source), key=lambda u: -_source_T(u))
        T, H = self._grid([self.T_top_C] + [_source_T(u) for u in with_source])
        H = H.copy()
        taken: dict[str, float] = {}
        for u in with_source:
            below = T <= _source_T(u)
            q = max(0.0, min(u.Q_source, float(np.min(H[below]))))
            H[below] -= q
            taken[u.name] = taken.get(u.name, 0.0) + q
        return taken, self._refrigeration(T, H)


def _source_T(unit: HeatPump) -> float:
    """Source temperature used for the credit: the inlet (warmest) end."""
    return max(unit.T_source_in_C, unit.T_source_out_C)


def refrigeration_taken_over(units: Iterable[HeatPump], cooling: CoolingCascade | None,
                             fraction: float = 1.0) -> float:
    """Refrigeration the units' sources take over [energy unit] (model in the module docstring)."""
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("refrigeration credit fraction must be in [0, 1]")
    if cooling is None:
        return 0.0
    _, after = cooling.take(units)
    return fraction * max(0.0, cooling.refrigeration - after)
