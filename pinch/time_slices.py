"""Non-continuous processes: time slices, storage potential and heat pumps with storage (workflow steps 2-4).

A stream table with start and end times describes a process whose requirements change during a cycle
(a day, a batch). This module provides:

1. Time Slice Model (TSM) targets: the cycle is cut wherever a stream starts or stops; each slice is a
   continuous problem solved by the Problem Table. Summed over the slices this is the target with
   direct heat recovery only (no storage). Stampfli et al. (2019), Sec. 2.2, citing Kemp and Deakin (1989).
2. Time Average Model (TAM) targets: every stream's load averaged over the cycle, one Problem Table. This
   assumes heat can be stored at any temperature for any time: the upper bound on recovery. TAM minus TSM
   is the most heat storage can add. (Standard batch-pinch bounds; Kemp and Deakin 1989 was not
   available to us, so the TAM is stated here as the time-averaged problem without further claim.)
3. Heat pump with heat recovery loops and storage, the insight-based method of Stampfli et al. (2019),
   Energy 182, 236-253, Sec. 2.3-2.4 (also Stampfli et al. 2018, CET 70, 1789-1794):
   * constant shifted condensation temperature T*co (chosen by the user from the slices' GCCs; the paper
     chooses it so that no self-sufficient pocket is destroyed);
   * the heat the condenser can deliver in slice l is the slice's GCC heat flow at T*co, and the heat
     the evaporator can take is the GCC heat flow at T*ev;
   * COP_l = ζ Tco / (Tco - Tev) (Eq. 7) with Tco = T*co + 5/4 ΔTmin and Tev = T*ev - 5/4 ΔTmin
     (Eqs 5-6: two loop exchangers and the refrigerant), energy balance Q_e = Q_a + η_drive P_el (Eq. 8);
   * T*ev,opt from Eq. 9: over the cycle, heat the process sends to the cold storage equals heat the
     storage sends to the evaporator;
   * storage capacity from Supply & Demand Curves (Wang and Smith 1995, as used in Sec. 2.4): the heat
     pump supplies a constant rate over its operating window; the storage holds the largest swing of the
     cumulative supply minus demand over the cycle.
   Defaults ζ = 0.35 and η_drive = 0.9 are the paper's (Sec. 2.3).

Units: heat in kW and kWh (power units are required: a per-product stream table has no time base).

Validation (tests/test_time_slices.py, reproduce_stampfli2019.py) on the dairy site of Stampfli et al.
(2019), Table 1: with T*co = 33.8 °C, ΔTmin = 10 K, Eq. 9 gives Tev = -4.57 °C, Tco = 46.3 °C, COP 2.20
(CET 2018, Table 2, graphical method: -4.56 °C, 46.26 °C; text: COP 2.2) and a condenser-side storage
of 1.36 MWh for 24 h operation (Energy 2019, Sec. 3.2: 1.35 MWh).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from pinch.problem_table_algorithm import ProblemTable, problem_table
from pinch.streams import StreamSet, streams_from_frame

KELVIN = 273.15
#: Stampfli et al. (2019), Sec. 2.3: second-law (Carnot) efficiency and compressor drive efficiency.
STAMPFLI_ZETA, STAMPFLI_ETA_DRIVE = 0.35, 0.9


@dataclass(frozen=True)
class Schedule:
    """Stream table with operating times within a repeating cycle."""

    streams: StreamSet               # loads as power (CP in kW/K or Q in kW) while the stream runs
    t_start_h: dict[str, float]
    t_end_h: dict[str, float]
    cycle_h: float = 24.0

    def active(self, t_h: float) -> StreamSet | None:
        on = tuple(s for s in self.streams.streams if self.t_start_h[s.name] <= t_h < self.t_end_h[s.name])
        return replace(self.streams, streams=on) if on else None

    @property
    def boundaries_h(self) -> list[float]:
        b = {0.0, self.cycle_h} | set(self.t_start_h.values()) | set(self.t_end_h.values())
        return sorted(b)


def load_schedule(path: str | Path, cycle_h: float = 24.0) -> Schedule:
    """Stream CSV (``pinch.streams`` format, power units) with extra columns ``t_start_h`` and ``t_end_h``.

    A stream runs from t_start to t_end within the cycle (0 <= t_start < t_end <= cycle). A stream that
    runs across the cycle boundary is entered as two rows.
    """
    df = pd.read_csv(path)
    for c in ("t_start_h", "t_end_h"):
        if c not in df.columns:
            raise ValueError(f"{Path(path).name}: missing column {c}")
    streams = streams_from_frame(df, source=str(path))
    if "/" in streams.energy_unit:
        raise ValueError(f"{Path(path).name}: time slices need loads as power (e.g. Q_kW or CP_kW_per_K), "
                         f"not '{streams.energy_unit}'")
    start = dict(zip(df["stream"].astype(str), df["t_start_h"].astype(float)))
    end = dict(zip(df["stream"].astype(str), df["t_end_h"].astype(float)))
    for n in start:
        if not 0.0 <= start[n] < end[n] <= cycle_h:
            raise ValueError(f"{n}: need 0 <= t_start_h < t_end_h <= {cycle_h}")
    return Schedule(streams, start, end, cycle_h)


@dataclass(frozen=True)
class Slice:
    t0_h: float
    t1_h: float
    table: ProblemTable | None       # None: nothing runs in this slice

    @property
    def duration_h(self) -> float:
        return self.t1_h - self.t0_h

    def gcc_heat(self, T_star_C: float) -> float:
        """Heat flow of the slice's GCC at a shifted temperature [kW] (0 for an empty slice)."""
        if self.table is None:
            return 0.0
        x, y = self.table.T_star_C[::-1], self.table.cascade_feasible[::-1]
        return float(np.interp(T_star_C, x, y))


def time_slices(schedule: Schedule) -> list[Slice]:
    """Slices between consecutive start/end times, each with its Problem Table."""
    b = schedule.boundaries_h
    out = []
    for t0, t1 in zip(b[:-1], b[1:]):
        active = schedule.active((t0 + t1) / 2)
        out.append(Slice(t0, t1, None if active is None else problem_table(active)))
    return out


def tsm_targets(schedule: Schedule) -> dict[str, float]:
    """Time Slice Model: direct heat recovery only. Energies per cycle [kWh]."""
    sl = time_slices(schedule)
    Qh = sum(s.table.Qh_min * s.duration_h for s in sl if s.table)
    Qc = sum(s.table.Qc_min * s.duration_h for s in sl if s.table)
    cold = sum(s.table.Q_cold_total * s.duration_h for s in sl if s.table)
    return {"Qh_kWh": Qh, "Qc_kWh": Qc, "recovery_kWh": cold - Qh}


def tam_targets(schedule: Schedule) -> dict[str, float]:
    """Time Average Model: loads averaged over the cycle (storage at any temperature). Energies per cycle [kWh]."""
    avg = tuple(replace(s, Q=s.Q * (schedule.t_end_h[s.name] - schedule.t_start_h[s.name]) / schedule.cycle_h)
                for s in schedule.streams.streams)
    t = problem_table(replace(schedule.streams, streams=avg))
    c = schedule.cycle_h
    return {"Qh_kWh": t.Qh_min * c, "Qc_kWh": t.Qc_min * c, "recovery_kWh": t.heat_recovery * c}


# ------------------------------------------------------------------ heat pump with storage (Stampfli 2019)

def stampfli_cop(T_co_star_C: float, T_ev_star_C: float, dTmin_K: float, zeta: float = STAMPFLI_ZETA) -> float:
    """COP = ζ Tco / (Tco - Tev), real temperatures from shifted ones (Stampfli et al. 2019, Eqs 5-7)."""
    Tco = T_co_star_C + 1.25 * dTmin_K + KELVIN
    Tev = T_ev_star_C - 1.25 * dTmin_K + KELVIN
    if Tco <= Tev:
        raise ValueError("condensation must be above evaporation")
    return zeta * Tco / (Tco - Tev)


def storage_for_constant_supply(demand_kW: list[float], durations_h: list[float],
                                operating_h: float | None = None, start_h: float = 0.0) -> dict[str, float]:
    """Constant supply that meets a cyclic demand profile through a storage (Supply & Demand Curves).

    ``demand_kW`` per slice (in cycle order), ``durations_h`` per slice. The supply runs at a constant
    rate for ``operating_h`` hours from ``start_h`` (default: the whole cycle) and delivers the cycle's
    demand. In cyclic steady state the storage must hold the largest swing of cumulative supply minus
    demand. Returns supply rate [kW], storage capacity [kWh] and energy per cycle [kWh].
    """
    if len(demand_kW) != len(durations_h):
        raise ValueError("demand and durations need the same length")
    cycle = float(sum(durations_h))
    op = cycle if operating_h is None else float(operating_h)
    if not 0 < op <= cycle:
        raise ValueError("operating_h must be in (0, cycle]")
    energy = float(sum(q * d for q, d in zip(demand_kW, durations_h)))
    rate = energy / op
    # piecewise-linear cumulative difference on a fine common grid (exact at all breakpoints)
    edges = np.concatenate([[0.0], np.cumsum(durations_h)])
    grid = np.unique(np.concatenate([edges, [start_h % cycle, (start_h + op) % cycle]]))
    grid = np.unique(np.concatenate([grid, [cycle]]))

    def on(t: float) -> bool:
        x = (t - start_h) % cycle
        return x < op - 1e-12 or op >= cycle

    cum, lo, hi = 0.0, 0.0, 0.0
    for a, b in zip(grid[:-1], grid[1:]):
        mid = (a + b) / 2
        k = int(np.searchsorted(edges, mid, side="right") - 1)
        cum += ((rate if on(mid) else 0.0) - demand_kW[k]) * (b - a)
        lo, hi = min(lo, cum), max(hi, cum)
    return {"supply_kW": rate, "storage_kWh": hi - lo, "energy_kWh": energy}


@dataclass(frozen=True)
class StorageHeatPump:
    T_co_star_C: float
    T_ev_star_C: float
    T_co_C: float
    T_ev_C: float
    COP: float
    condenser_demand_kW: tuple[float, ...]     # per slice: GCC heat flow at T*co
    evaporator_supply_kW: tuple[float, ...]    # per slice: GCC heat flow at T*ev
    Q_condenser_kW: float                      # constant over the operating window
    Q_evaporator_kW: float
    P_el_kW: float
    hot_storage_kWh: float
    cold_storage_kWh: float
    heat_per_cycle_kWh: float
    electricity_per_cycle_kWh: float
    cold_side_imbalance_kWh: float             # process heat to cold storage minus evaporator heat, per cycle


def storage_heat_pump(schedule: Schedule, T_co_star_C: float, dTmin_K: float, *, zeta: float = STAMPFLI_ZETA,
                      eta_drive: float = STAMPFLI_ETA_DRIVE, operating_h: float | None = None,
                      start_h: float = 0.0, T_ev_star_C: float | None = None) -> StorageHeatPump:
    """Heat pump with hot and cold storage loops (Stampfli et al. 2019, Sec. 2.3-2.4).

    If ``T_ev_star_C`` is None it is found from Eq. 9 (cold storage balanced over the cycle); otherwise the
    given value is used and ``cold_side_imbalance_kWh`` reports what the cold storage does not balance
    (positive: surplus process heat left to the cold utility; negative: the evaporator lacks heat). The
    cold storage is then sized for the process side's own profile.
    """
    sl = time_slices(schedule)
    dur = [s.duration_h for s in sl]
    demand = [s.gcc_heat(T_co_star_C) for s in sl]
    E_cond = sum(q * d for q, d in zip(demand, dur))
    if E_cond <= 0:
        raise ValueError("no heat demand at the chosen condensation temperature")

    def imbalance(T_ev_star: float) -> float:
        cop = stampfli_cop(T_co_star_C, T_ev_star, dTmin_K, zeta)
        return sum((s.gcc_heat(T_ev_star) - q * (1 - eta_drive / cop)) * d for s, q, d in zip(sl, demand, dur))

    if T_ev_star_C is None:
        tables = [s.table for s in sl if s.table]
        lo = min(float(t.T_star_C[-1]) for t in tables)
        hi = min(T_co_star_C, max(max(t.pinch_T_star_C) if t.pinch_T_star_C else float(t.T_star_C[-1]) for t in tables))
        a, b = imbalance(lo), imbalance(hi - 1e-6)
        if a * b > 0:
            raise ValueError("Eq. 9 has no root between the bottom of the GCCs and the pinch")
        T_ev_star_C = float(brentq(imbalance, lo, hi - 1e-6, xtol=1e-9))
    cop = stampfli_cop(T_co_star_C, T_ev_star_C, dTmin_K, zeta)
    supply_ev = [s.gcc_heat(T_ev_star_C) for s in sl]
    hot = storage_for_constant_supply(demand, dur, operating_h, start_h)
    Q_e = hot["supply_kW"]
    P = Q_e / cop
    Q_a = Q_e - eta_drive * P
    op = schedule.cycle_h if operating_h is None else operating_h
    # cold side: the process fills the storage (supply_ev), the evaporator empties it at Q_a while running
    cold = storage_for_constant_supply(supply_ev, dur, op, start_h)
    return StorageHeatPump(T_co_star_C=T_co_star_C, T_ev_star_C=T_ev_star_C,
                           T_co_C=T_co_star_C + 1.25 * dTmin_K, T_ev_C=T_ev_star_C - 1.25 * dTmin_K, COP=cop,
                           condenser_demand_kW=tuple(demand), evaporator_supply_kW=tuple(supply_ev),
                           Q_condenser_kW=Q_e, Q_evaporator_kW=Q_a, P_el_kW=P,
                           hot_storage_kWh=hot["storage_kWh"], cold_storage_kWh=cold["storage_kWh"],
                           heat_per_cycle_kWh=E_cond, electricity_per_cycle_kWh=P * op,
                           cold_side_imbalance_kWh=cold["energy_kWh"] - Q_a * op)
