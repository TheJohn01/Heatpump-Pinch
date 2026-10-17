"""Automatic heat pump design from the Grand Composite Curve (any process).

Method
------
Candidate sink levels are processed from the lowest to the highest sink
temperature. Each level is sized to the largest duty the process can fully use
at that level, given the levels already placed (``max_useful_sink_duty``).
Whatever hot utility remains after the highest level is the residual demand
that the chosen levels cannot reach (e.g. it stays on a gas boiler). Sources
are then allocated by ``integrate``: from the process cooling demand first,
the remainder from outside the process (ambient).

This places every sink above the pinch and every process source below it, in
line with the heat pump integration rule, because a sink is only given duty
the GCC can absorb.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pinch.case import SinkLevelSpec
from pinch.heat_pump import HeatPump, IntegrationResult, add_units, integrate, max_useful_sink_duty
from pinch.problem_table import ProblemTable, problem_table
from pinch.streams import StreamSet


def resolve_level(spec: SinkLevelSpec, table: ProblemTable) -> tuple[float, float]:
    """Return (T_sink_in_C, T_sink_out_C), replacing 'gcc_max' by the GCC maximum T*."""
    T_top = float(table.T_star_C[0])

    def value(v):
        return T_top if v == "gcc_max" else float(v)

    return value(spec.T_sink_in_C), value(spec.T_sink_out_C)


@dataclass(frozen=True)
class HeatPumpDesign:
    """Result of a GCC-based heat pump design.

    All heat and work quantities are in the stream-data energy unit.
    """

    units: tuple[HeatPump, ...]
    skipped: tuple[str, ...]
    Qh_before: float
    Qh_residual: float
    integration: IntegrationResult

    @property
    def W_total(self) -> float:
        return sum(u.W for u in self.units)

    @property
    def Q_sink_total(self) -> float:
        return sum(u.Q_sink for u in self.units)

    @property
    def COP_system(self) -> float:
        """Heat delivered per unit of electricity, all units together [-]."""
        return self.Q_sink_total / self.W_total if self.W_total > 0 else float("nan")

    @property
    def fraction_electrified(self) -> float:
        """Share of the minimum hot utility supplied by the heat pumps [-]."""
        return 1 - self.Qh_residual / self.Qh_before if self.Qh_before > 0 else float("nan")


def design_from_gcc(
    stream_set: StreamSet,
    levels: tuple[SinkLevelSpec, ...],
    eta_lorenz: float,
    default_source_T_C: float,
) -> HeatPumpDesign:
    """Size one heat pump per sink level from the GCC.

    Parameters
    ----------
    stream_set : StreamSet
        Process streams.
    levels : tuple of SinkLevelSpec
        Candidate sink levels (any order; sorted by sink outlet temperature).
    eta_lorenz : float
        Lorenz efficiency for units whose level does not set its own [-].
    default_source_T_C : float
        Source temperature for levels that do not set their own [°C].

    Returns
    -------
    HeatPumpDesign
    """
    base = problem_table(stream_set)
    resolved = []
    for spec in levels:
        T_in, T_out = resolve_level(spec, base)
        T_src = default_source_T_C if spec.T_source_C is None else float(spec.T_source_C)
        eta = eta_lorenz if spec.eta_lorenz is None else float(spec.eta_lorenz)
        resolved.append((T_out, spec.name, T_in, T_src, eta))
    resolved.sort()

    current = stream_set
    units: list[HeatPump] = []
    skipped: list[str] = []
    for T_out, name, T_in, T_src, eta in resolved:
        template = HeatPump(name, 1.0, T_in, T_out, T_src, T_src, eta_lorenz=eta)
        duty = max_useful_sink_duty(current, template)
        if duty <= 0.0:
            skipped.append(name)
            continue
        unit = template.with_sink_duty(duty)
        units.append(unit)
        current = add_units(current, [unit], {})

    residual = problem_table(current).Qh_min
    return HeatPumpDesign(
        units=tuple(units),
        skipped=tuple(skipped),
        Qh_before=base.Qh_min,
        Qh_residual=residual,
        integration=integrate(stream_set, units),
    )


def partial_designs(units, n_points: int = 201) -> list[tuple[float, tuple[HeatPump, ...]]]:
    """Electrification curve: partial designs from no heat pump to the full design.

    Heat-pump duty is added in order of decreasing COP (cheapest heat first); the last
    unit at each point runs at part of its design duty. The only implementation of this
    loop (redundancy audit, item 1.3): step 6 and the retrofit evaluate these points.

    Parameters
    ----------
    units : iterable of HeatPump
        Units of the full design.
    n_points : int
        Points from zero to the full duty, inclusive.

    Returns
    -------
    list of (Q_sink_total, partial units)
        Total sink duty at the point [energy unit] and the units at their partial duties.
    """
    ordered = sorted(units, key=lambda u: -u.COP)
    total = sum(u.Q_sink for u in ordered)
    points = []
    for target in np.linspace(0.0, total, n_points):
        remaining, partial = float(target), []
        for u in ordered:
            q = min(u.Q_sink, remaining)
            if q <= 0:
                break
            remaining -= q
            partial.append(u.with_sink_duty(q))
        points.append((float(target), tuple(partial)))
    return points


# ------------------------------------------------------------ plausibility
#: Screening thresholds, overridable per case ("screening" in the case file).
#: Verified 2026-10-12; sources:
#:  sink_warn_C 160: IEA HPT Annex 58, Task 1 report (Aug. 2023) projects commercial
#:      availability up to 120 °C around 2024-25 and 160 °C around 2025-26; above
#:      160 °C, availability is limited. (Replaces the earlier 120 °C value from
#:      Arpagaus et al., 2018, which is out of date.)
#:  sink_max_C 200: IEA HPT Annex 58, Task 1 report (HPT-AN58-2, August 2023,
#:      Zühlsdorf et al.) reviews 34 technologies with maximum supply temperatures of
#:      100-280 °C at TRL 4-9; above 200 °C is beyond near-term commercial availability.
#:      Commercial units up to 200 °C have been announced (e.g. ENERIN, Hannover
#:      Messe news, 20 April 2024; vendor claim, not peer-reviewed).
#:  lift_max_K 130: Arpagaus et al. (2018), 17th Int. Refrigeration and Air
#:      Conditioning Conf., Purdue (EPFL Infoscience record 256729): commercial COPs
#:      reported for lifts up to 130 K (COP about 1.6). Dated; no newer verified source.
DEFAULT_SCREENING = {"sink_warn_C": 160.0, "sink_max_C": 200.0, "lift_max_K": 130.0}


def plausibility_warnings(unit: HeatPump, screening: dict | None = None) -> list[str]:
    """Flag units outside reported heat pump technology ranges (screening only)."""
    s = {**DEFAULT_SCREENING, **(screening or {})}
    warnings = []
    T_sink = max(unit.T_sink_in_C, unit.T_sink_out_C)
    if T_sink > s["sink_max_C"]:
        warnings.append(f"sink {T_sink:.0f} °C above {s['sink_max_C']:.0f} °C: beyond near-term commercial availability (Annex 58: up to 280 °C at TRL 4-9)")
    elif T_sink > s["sink_warn_C"]:
        warnings.append(f"sink {T_sink:.0f} °C above {s['sink_warn_C']:.0f} °C: limited commercial availability")
    if unit.has_source:
        lift = T_sink - min(unit.T_source_in_C, unit.T_source_out_C)
        if lift > s["lift_max_K"]:
            warnings.append(f"lift {lift:.0f} K above {s['lift_max_K']:.0f} K: beyond reported COP data")
    if unit.COP < 1:
        warnings.append(f"COP {unit.COP:.2f} < 1: direct electric heating would use less electricity")
    return warnings


def source_warnings(design: HeatPumpDesign, ambient_T_C: float | None) -> dict[str, list[str]]:
    """Flag external source heat that ambient air cannot physically supply.

    A unit's source shortfall is assigned to an external source (ambient). That
    is only possible if the source temperature is at or below ambient. Above
    ambient, the unit's duty and COP are not achievable as designed.
    """
    flags: dict[str, list[str]] = {}
    if ambient_T_C is None:
        return flags
    for u in design.units:
        ext = design.integration.Q_source_external.get(u.name, 0.0)
        T_src = max(u.T_source_in_C, u.T_source_out_C) if u.has_source else None
        if ext > 0 and T_src is not None and T_src > ambient_T_C:
            flags.setdefault(u.name, []).append(
                f"external source {ext:.4g} at {T_src:.0f} °C above ambient {ambient_T_C:.0f} °C: "
                "not physically available; lower the source temperature or use a process source")
    return flags
