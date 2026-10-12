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
        Lorenz efficiency for all units [-].
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
        resolved.append((T_out, spec.name, T_in, T_src))
    resolved.sort()

    current = stream_set
    units: list[HeatPump] = []
    skipped: list[str] = []
    for T_out, name, T_in, T_src in resolved:
        template = HeatPump(name, 1.0, T_in, T_out, T_src, T_src, eta_lorenz=eta_lorenz)
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


# ------------------------------------------------------------ plausibility
#: Screening thresholds, overridable per case ("screening" in the case file).
#: Verified 2026-10-12; sources:
#:  sink_warn_C 160: IEA HPT Annex 58, Task 1 report (Sept. 2023) projects commercial
#:      availability up to 120 °C around 2024-25 and 160 °C around 2025-26; above
#:      160 °C, availability is limited. (Replaces the earlier 120 °C value from
#:      Arpagaus et al., 2018, which is out of date.)
#:  sink_max_C 200: upper end of the IEA HPT Annex 58 scope (100-200 °C); commercial
#:      units up to 200 °C have been announced (e.g. ENERIN, Hannover Messe news,
#:      20 April 2024; vendor claim, not peer-reviewed).
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
        warnings.append(f"sink {T_sink:.0f} °C above {s['sink_max_C']:.0f} °C: outside reported heat pump range")
    elif T_sink > s["sink_warn_C"]:
        warnings.append(f"sink {T_sink:.0f} °C above {s['sink_warn_C']:.0f} °C: limited commercial availability")
    if unit.has_source:
        lift = T_sink - min(unit.T_source_in_C, unit.T_source_out_C)
        if lift > s["lift_max_K"]:
            warnings.append(f"lift {lift:.0f} K above {s['lift_max_K']:.0f} K: beyond reported COP data")
    if unit.COP < 1:
        warnings.append(f"COP {unit.COP:.2f} < 1: direct electric heating would use less electricity")
    return warnings
