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

Validation (tests/test_time_slices.py, scripts/validation/reproduce_stampfli2019.py) on the dairy site of Stampfli et al.
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


def time_averaged(schedule: Schedule) -> StreamSet:
    """Every stream's load averaged over the cycle: the Time Average Model's stream set."""
    avg = tuple(replace(s, Q=s.Q * (schedule.t_end_h[s.name] - schedule.t_start_h[s.name]) / schedule.cycle_h)
                for s in schedule.streams.streams)
    return replace(schedule.streams, streams=avg)


def tam_targets(schedule: Schedule) -> dict[str, float]:
    """Time Average Model: loads averaged over the cycle (storage at any temperature). Energies per cycle [kWh]."""
    t = problem_table(time_averaged(schedule))
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


# ------------------------------------------------------------------ hourly dispatch with storage (step 6)

def hourly_profile(per_slice_kW: tuple[float, ...] | list[float], slices: list[Slice], cycle_h: float = 24.0) -> np.ndarray:
    """Mean load of each clock hour of the cycle [kW] from per-slice loads (energy-conserving)."""
    hours = int(round(cycle_h))
    out = np.zeros(hours)
    for q, s in zip(per_slice_kW, slices):
        for h in range(hours):
            overlap = max(0.0, min(s.t1_h, h + 1) - max(s.t0_h, h))
            out[h] += q * overlap
    return out


def dispatch_day(demand_kW: np.ndarray, source_kW: np.ndarray, price_el_EUR_per_kWh: np.ndarray, *,
                 heat_cost_EUR_per_kWh: float, cop: float, eta_drive: float, capacity_kW: float,
                 hot_storage_kWh: float, cold_storage_kWh: float, fixed_kW: float | None = None) -> dict:
    """Least-cost hourly operation of a heat pump with hot and cold storage over one cyclic day (linear program).

    Per hour t (1 h steps): condenser heat q_t <= capacity; back-up heat b_t (boiler, at ``heat_cost``); hot
    storage S_t, cold storage C_t within their capacities, both cyclic (end = start). Demand: q_t + b_t + S_t -
    S_t+1 = demand_t. The evaporator takes q_t (1 - eta_drive / COP) from the cold storage, which the process fills
    with source_t; heat the cold storage cannot take goes to the cold utility (d_t >= 0, no cost here). COP is
    constant (the time-slice model's Carnot fraction); electricity = q_t / COP. ``fixed_kW``: the heat pump runs at
    this constant rate every hour (the design operation of Stampfli et al. 2019, Sec. 2.4), for comparison.
    """
    from scipy.optimize import linprog
    n = len(demand_kW)
    w = 1 - eta_drive / cop                       # evaporator heat per unit of condenser heat
    # variables: q (n), b (n), S (n), C (n), d (n); S_t, C_t = level at the start of hour t, cyclic
    nv = 5 * n
    iq, ib, iS, iC, idd = (np.arange(n) + k * n for k in range(5))
    c = np.zeros(nv)
    c[iq] = price_el_EUR_per_kWh / cop
    c[ib] = heat_cost_EUR_per_kWh
    A, rhs = [], []
    for t in range(n):
        nxt = (t + 1) % n
        row = np.zeros(nv)                        # q + b + S_t - S_t+1 = demand
        row[iq[t]], row[ib[t]], row[iS[t]] = 1, 1, 1
        row[iS[nxt]] -= 1
        A.append(row)
        rhs.append(demand_kW[t])
        row = np.zeros(nv)                        # C_t+1 = C_t + source - w q - d
        row[iC[nxt]], row[iC[t]], row[iq[t]], row[idd[t]] = 1, -1, w, 1
        if nxt == t:
            row[iC[t]] = 0
        A.append(row)
        rhs.append(source_kW[t])
    q_bound = (fixed_kW, fixed_kW) if fixed_kW is not None else (0, capacity_kW)
    bounds = ([q_bound] * n + [(0, None)] * n + [(0, hot_storage_kWh)] * n + [(0, cold_storage_kWh)] * n
              + [(0, None)] * n)
    r = linprog(c, A_eq=np.array(A), b_eq=np.array(rhs), bounds=bounds, method="highs")
    if r.status != 0:
        raise ValueError(f"dispatch: {r.message}")
    x = r.x
    return {"cost_EUR": float(r.fun), "heat_pump_kWh": float(x[iq].sum()), "backup_kWh": float(x[ib].sum()),
            "electricity_kWh": float(x[iq].sum() / cop), "condenser_kW": x[iq], "backup_kW": x[ib],
            "hot_storage_kWh": x[iS], "cold_storage_kWh": x[iC]}



def annual_dispatch(hp: StorageHeatPump, slices: list[Slice], price_EUR_per_kWh, *, heat_cost_EUR_per_kWh: float,
                    eta_drive: float = STAMPFLI_ETA_DRIVE, capacity_factors: tuple[float, ...] = (1.0, 1.5, 2.0),
                    tariff=None, timezone: str = "Europe/Lisbon") -> pd.DataFrame:
    """Constant design operation against least-cost dispatch on every day of an hourly price year.

    ``price_EUR_per_kWh``: hourly delivered energy prices (UTC index; ``pinch.tariffs.hourly_energy_price``); the
    process repeats its daily schedule in local clock time every day. Days with a clock change (23 or 25 h) are
    left out. ``capacity_factors``: heat pump capacity as multiples of the design rate (storage as designed);
    the extra capacity's investment is not counted here. ``tariff``: a ``PeriodTariff`` whose capacity charges
    are added from each mode's own yearly load profile. Rows per mode, totals per year of the price series.
    """
    demand = hourly_profile(hp.condenser_demand_kW, slices)
    source = hourly_profile(hp.evaporator_supply_kW, slices)
    local = price_EUR_per_kWh.tz_convert(timezone)
    days = [g for _, g in local.groupby(local.index.date) if len(g) == len(demand)]
    common = dict(heat_cost_EUR_per_kWh=heat_cost_EUR_per_kWh, cop=hp.COP, eta_drive=eta_drive,
                  hot_storage_kWh=hp.hot_storage_kWh, cold_storage_kWh=hp.cold_storage_kWh)
    modes = [("constant (design)", 1.0, hp.Q_condenser_kW)] + [(f"dispatch, capacity x {f:g}", f, None)
                                                               for f in capacity_factors]
    rows = []
    for label, f, fixed in modes:
        tot = {"cost_EUR": 0.0, "heat_pump_kWh": 0.0, "backup_kWh": 0.0, "electricity_kWh": 0.0}
        load = []
        for g in days:
            r = dispatch_day(demand, source, g.to_numpy(), capacity_kW=f * hp.Q_condenser_kW, fixed_kW=fixed, **common)
            for k in tot:
                tot[k] += r[k]
            load.append(pd.Series(r["condenser_kW"] / hp.COP, index=g.index))
        cap = tariff.capacity_EUR(pd.concat(load).tz_convert("UTC")) if tariff is not None else 0.0
        rows.append({"mode": label, "capacity_kW": round(f * hp.Q_condenser_kW, 1), "days": len(days),
                     "heat_pump_MWh": round(tot["heat_pump_kWh"] / 1000, 2), "backup_MWh": round(tot["backup_kWh"] / 1000, 2),
                     "electricity_MWh": round(tot["electricity_kWh"] / 1000, 2),
                     "energy_cost_EUR": round(tot["cost_EUR"], 0), "capacity_charges_EUR": round(cap, 0),
                     "total_EUR": round(tot["cost_EUR"] + cap, 0)})
    out = pd.DataFrame(rows)
    out["saving_vs_constant"] = (1 - out["total_EUR"] / out["total_EUR"].iloc[0]).round(4)
    return out


def operation_outputs(case) -> tuple[dict, dict, dict]:
    """Time-slice targets, the heat pump with storage and its hourly operation for a case with a ``schedule``.

    Returns (summary, tables, figures) for ``scripts.analysis.analyse.compute``.
    """
    import matplotlib.pyplot as plt

    from pinch.economics import load_economics
    from pinch.tariffs import PeriodTariff, hourly_energy_price

    sc = case.schedule
    sched = load_schedule(sc["file_resolved"], float(sc.get("cycle_h", 24)))
    sl = time_slices(sched)
    hp = storage_heat_pump(sched, float(sc["heat_pump"]["T_co_star_C"]), float(sc["heat_pump"]["dTmin_K"]),
                           operating_h=sc["heat_pump"].get("operating_h"))
    tsm, tam = tsm_targets(sched), tam_targets(sched)
    summary = {"note": "Time Slice Model (direct heat recovery only) and Time Average Model (storage at any "
                       "temperature) per cycle; heat pump with hot and cold storage loops after Stampfli et al. "
                       "(2019); hourly operation against the year's hourly prices (pinch.time_slices.annual_dispatch).",
               "cycle_h": sched.cycle_h, "TSM": {k: round(v, 1) for k, v in tsm.items()},
               "TAM": {k: round(v, 1) for k, v in tam.items()},
               "heat_pump": {"T_co_C": round(hp.T_co_C, 2), "T_ev_C": round(hp.T_ev_C, 2), "COP": round(hp.COP, 3),
                             "Q_condenser_kW": round(hp.Q_condenser_kW, 2), "P_el_kW": round(hp.P_el_kW, 2),
                             "hot_storage_kWh": round(hp.hot_storage_kWh, 1),
                             "cold_storage_kWh": round(hp.cold_storage_kWh, 1),
                             "heat_per_cycle_kWh": round(hp.heat_per_cycle_kWh, 1)}}
    tables = {"time_slices": pd.DataFrame([{
        "t0_h": s.t0_h, "t1_h": s.t1_h, "Qh_min_kW": round(s.table.Qh_min, 2) if s.table else 0.0,
        "Qc_min_kW": round(s.table.Qc_min, 2) if s.table else 0.0,
        "condenser_demand_kW": round(q, 2), "evaporator_supply_kW": round(e, 2)}
        for s, q, e in zip(sl, hp.condenser_demand_kW, hp.evaporator_supply_kW)])}
    figures: dict = {}
    d = sc.get("dispatch")
    if d:
        p = load_economics({k: v for k, v in (case.economics or {}).items() if k not in ("sources", "_note")})
        prices = hourly_energy_price(p.electricity_price_EUR_per_kWh, d["tariff"])
        tariff = PeriodTariff.load(d["tariff"]["network_tariff"])
        heat_cost = p.gas_price_EUR_per_kWh / p.boiler_efficiency
        table = annual_dispatch(hp, sl, prices, heat_cost_EUR_per_kWh=heat_cost, tariff=tariff, timezone=tariff.timezone,
                                capacity_factors=tuple(float(x) for x in d.get("capacity_factors", (1.0, 1.5, 2.0))))
        tables["operation"] = table
        summary["operation"] = {"prices": d["tariff"], "heat_cost_EUR_per_kWh": round(heat_cost, 5),
                                "modes": table.to_dict("records"),
                                "limits": "COP constant at part load; extra capacity's investment not counted; "
                                          "days with a clock change left out"}
        # a typical day: the day whose mean price is the year's median
        local = prices.tz_convert(tariff.timezone)
        days = {k: g for k, g in local.groupby(local.index.date) if len(g) == 24}
        day = sorted(days, key=lambda k: days[k].mean())[len(days) // 2]
        demand, source = hourly_profile(hp.condenser_demand_kW, sl), hourly_profile(hp.evaporator_supply_kW, sl)
        common = dict(heat_cost_EUR_per_kWh=heat_cost, cop=hp.COP, eta_drive=STAMPFLI_ETA_DRIVE,
                      hot_storage_kWh=hp.hot_storage_kWh, cold_storage_kWh=hp.cold_storage_kWh)
        f_max = max(float(x) for x in d.get("capacity_factors", (2.0,)))
        best = dispatch_day(demand, source, days[day].to_numpy(), capacity_kW=f_max * hp.Q_condenser_kW, **common)
        fig, ax = plt.subplots(figsize=(8, 4))
        h = np.arange(24)
        ax.step(h, demand, where="post", label="heat demand at the condenser level", color="black")
        ax.axhline(hp.Q_condenser_kW, ls="--", color="grey", label="constant design operation")
        ax.bar(h, best["condenser_kW"], width=1, align="edge", alpha=0.6, label=f"heat pump, dispatch (x {f_max:g})")
        ax.bar(h, best["backup_kW"], width=1, align="edge", bottom=best["condenser_kW"], alpha=0.6, label="back-up boiler")
        ax2 = ax.twinx()
        ax2.step(h, days[day].to_numpy() * 1000, where="post", color="tab:red", label="electricity price")
        ax.set(xlabel="Local clock hour", ylabel="Heat [kW]", title=f"Hourly operation on a median-price day ({day})")
        ax2.set_ylabel("Delivered energy price [EUR/MWh]")
        lines, labels = ax.get_legend_handles_labels()
        l2, lab2 = ax2.get_legend_handles_labels()
        fig.legend(lines + l2, labels + lab2, loc="lower center", ncol=3, fontsize=7, frameon=False)
        fig.tight_layout(rect=(0, 0.1, 1, 1))
        figures["operation_day"] = fig
    return summary, tables, figures
