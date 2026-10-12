"""Heat pump models and integration with the Problem Table (workflow step 4).

COP model
---------
Lorenz-efficiency model, as used by Padullés et al. (2026), Eq. (1):

    COP = eta_L * T_sink_mean / (T_sink_mean - T_source_mean)

with thermodynamic (entropic) mean temperatures in kelvin,

    T_mean = (T_in - T_out) / ln(T_in / T_out)      (T_mean = T if isothermal).

For an isothermal sink and source this is eta_L times the Carnot COP. The
paper takes eta_L = 0.55 from Andersen et al. (its ref. [41]). eta_L is a
lumped empirical factor: it is only meaningful for vapour-compression cycles
of the type and lift it was fitted to, and it must satisfy 0 < eta_L <= 1
(second law). A cycle-based COP with real working fluids (CoolProp) is a
later refinement.

Temperature convention
----------------------
Heat pump sink and source temperatures are compared directly with the
shifted temperatures T* of the Grand Composite Curve, i.e. utility streams get
dT_shift = 0. This follows Padullés et al. (2026, Sec. 4.1), who read utility
temperatures directly off the GCC ("the maximum temperature of the GCC, and
therefore the minimum temperature of the heating utility, is 103 °C"). An
isothermal sink at T is modelled as a hot stream from T to T - w, and an
isothermal source at T as a cold stream from T to T + w, with
w = ``isothermal_width_K`` (default 1 K, the convention used for latent loads
in the stream data). Results are insensitive to w for w <= 1 K (see
``tests/test_heat_pump.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from pinch.problem_table import problem_table
from pinch.streams import Stream, StreamSet

KELVIN = 273.15
#: Duties below this fraction of Qh,min are treated as zero (solver noise).
MIN_DUTY_FRACTION = 1e-6


def thermodynamic_mean_temperature_K(T_a_C: float, T_b_C: float) -> float:
    """Entropic mean temperature [K] of a stream changing between T_a and T_b [°C]."""
    T_a_K, T_b_K = T_a_C + KELVIN, T_b_C + KELVIN
    if T_a_K <= 0 or T_b_K <= 0:
        raise ValueError("temperatures must be above absolute zero")
    if math.isclose(T_a_K, T_b_K):
        return T_a_K
    return (T_a_K - T_b_K) / math.log(T_a_K / T_b_K)


#: Validity of the Andersen et al. (2024) polynomial (their Sec. 2.5).
ANDERSEN2024_RANGE = {"T_source_in_C": (0.0, 100.0), "lift_K": (20.0, 150.0),
                      "source_glide_K": (-50.0, -10.0), "sink_glide_K": (0.0, 80.0)}


def andersen2024_eta_lorenz(T_source_in_C: float, T_sink_out_C: float,
                            source_glide_K: float, sink_glide_K: float) -> tuple[float, list[str]]:
    """Lorenz efficiency of the best-performing cycle/fluid, Andersen et al. (2024).

    Andersen, M.P. et al., Applied Energy 376 (2024) 124312, Sec. 3.2:
        eta_Lor = 0.486 + 1e-4 (27.1 dT_lift - 0.0737 dT_lift^2 - 2.0 T_so,in
                                - 13.0 dT_so - 5.15 dT_si)
    with absolute temperatures, dT_lift = T_si,out - T_so,in, dT_so = source glide
    (outlet - inlet, negative) and dT_si = sink glide (outlet - inlet). R² = 0.866.
    It fits the best of 1056 cycle/fluid combinations (an upper envelope) with
    3 K pinch, 70 % isentropic compressor efficiency and 5 % heat loss.

    Returns
    -------
    (eta, warnings) : the Lorenz efficiency and a list of validity-range violations.
    """
    lift_K = T_sink_out_C - T_source_in_C
    T_so_in_K = T_source_in_C + KELVIN
    eta = 0.486 + 1e-4 * (27.1 * lift_K - 0.0737 * lift_K ** 2 - 2.0 * T_so_in_K
                          - 13.0 * source_glide_K - 5.15 * sink_glide_K)
    values = {"T_source_in_C": T_source_in_C, "lift_K": lift_K,
              "source_glide_K": source_glide_K, "sink_glide_K": sink_glide_K}
    warnings = [f"{k} = {v:g} outside fitted range {ANDERSEN2024_RANGE[k]}"
                for k, v in values.items() if not ANDERSEN2024_RANGE[k][0] <= v <= ANDERSEN2024_RANGE[k][1]]
    return eta, warnings


def lorenz_cop(
    T_sink_in_C: float,
    T_sink_out_C: float,
    T_source_in_C: float,
    T_source_out_C: float,
    eta_lorenz: float,
) -> float:
    """Heating COP from the Lorenz-efficiency model.

    Parameters
    ----------
    T_sink_in_C, T_sink_out_C : float
        Temperatures of the heat sink (fluid being heated) [°C].
    T_source_in_C, T_source_out_C : float
        Temperatures of the heat source (fluid being cooled) [°C].
    eta_lorenz : float
        Lorenz efficiency [-], 0 < eta_lorenz <= 1. eta_lorenz = 1 gives the
        reversible (Lorenz) COP, the second-law upper bound.

    Returns
    -------
    float
        Heating COP [-].
    """
    if not 0 < eta_lorenz <= 1:
        raise ValueError("eta_lorenz must be in (0, 1]")
    T_sink_K = thermodynamic_mean_temperature_K(T_sink_in_C, T_sink_out_C)
    T_source_K = thermodynamic_mean_temperature_K(T_source_in_C, T_source_out_C)
    if T_sink_K <= T_source_K:
        raise ValueError("mean sink temperature must exceed mean source temperature")
    return eta_lorenz * T_sink_K / (T_sink_K - T_source_K)


@dataclass(frozen=True)
class HeatPump:
    """An electrically driven heat supply unit (heat pump, MVR or electric heater).

    Give either ``eta_lorenz`` (COP from the Lorenz model) or ``cop_fixed``
    (a published COP, e.g. MVR COP = 15, electric boiler COP = 1). A unit with
    ``cop_fixed == 1`` and no source temperatures is a direct electric heater.

    Attributes
    ----------
    name : str
        Unit label.
    Q_sink : float
        Heat delivered to the process [case energy unit].
    T_sink_in_C, T_sink_out_C : float
        Sink temperatures [°C]; equal values mean an isothermal sink.
    T_source_in_C, T_source_out_C : float or None
        Source temperatures [°C]; None only for a direct electric heater.
    eta_lorenz : float or None
        Lorenz efficiency [-].
    cop_fixed : float or None
        Fixed heating COP [-].
    isothermal_width_K : float
        Temperature interval used to represent an isothermal sink or source
        in the cascade [K].
    """

    name: str
    Q_sink: float
    T_sink_in_C: float
    T_sink_out_C: float
    T_source_in_C: float | None = None
    T_source_out_C: float | None = None
    eta_lorenz: float | None = None
    cop_fixed: float | None = None
    isothermal_width_K: float = 1.0

    def __post_init__(self) -> None:
        if self.isothermal_width_K <= 0:
            raise ValueError(f"{self.name}: isothermal_width_K must be positive")
        if self.Q_sink <= 0:
            raise ValueError(f"{self.name}: Q_sink must be positive")
        if self.T_sink_out_C < self.T_sink_in_C:
            raise ValueError(f"{self.name}: sink must be heated (T_sink_out >= T_sink_in)")
        if (self.eta_lorenz is None) == (self.cop_fixed is None):
            raise ValueError(f"{self.name}: give exactly one of eta_lorenz or cop_fixed")
        has_source = self.T_source_in_C is not None and self.T_source_out_C is not None
        if not has_source and self.cop_fixed != 1:
            raise ValueError(f"{self.name}: source temperatures required unless cop_fixed == 1")
        if has_source and self.T_source_out_C > self.T_source_in_C:
            raise ValueError(f"{self.name}: source must be cooled (T_source_out <= T_source_in)")
        if self.cop_fixed is not None and has_source and self.cop_fixed > self.cop_reversible:
            raise ValueError(
                f"{self.name}: COP {self.cop_fixed} exceeds the reversible limit "
                f"{self.cop_reversible:.2f} (second law)"
            )

    @property
    def has_source(self) -> bool:
        return self.T_source_in_C is not None

    @property
    def cop_reversible(self) -> float:
        """Second-law upper bound (Lorenz COP with eta = 1) [-]."""
        if not self.has_source:
            return float("inf")
        return lorenz_cop(self.T_sink_in_C, self.T_sink_out_C,
                          self.T_source_in_C, self.T_source_out_C, 1.0)

    @property
    def COP(self) -> float:
        """Heating COP [-]."""
        if self.cop_fixed is not None:
            return self.cop_fixed
        return lorenz_cop(self.T_sink_in_C, self.T_sink_out_C,
                          self.T_source_in_C, self.T_source_out_C, self.eta_lorenz)

    @property
    def W(self) -> float:
        """Electricity input [case energy unit]."""
        return self.Q_sink / self.COP

    @property
    def Q_source(self) -> float:
        """Heat absorbed from the source [case energy unit] (first law)."""
        return self.Q_sink - self.W if self.has_source else 0.0

    def with_sink_duty(self, Q_sink: float) -> "HeatPump":
        """Copy with a different sink duty."""
        return replace(self, Q_sink=Q_sink)


# ----------------------------------------------------------------- streams
def _sink_stream(unit: HeatPump) -> Stream:
    """Condenser / gas cooler as a hot stream (dT_shift = 0)."""
    T_hi = unit.T_sink_out_C
    T_lo = unit.T_sink_in_C if unit.T_sink_in_C < T_hi else T_hi - unit.isothermal_width_K
    return Stream(f"{unit.name} sink", "hot", T_hi, T_lo, unit.Q_sink, 0.0)


def _source_stream(unit: HeatPump, Q_from_process: float) -> Stream:
    """Evaporator as a cold stream (dT_shift = 0) taking Q_from_process."""
    T_lo = unit.T_source_out_C
    T_hi = unit.T_source_in_C if unit.T_source_in_C > T_lo else T_lo + unit.isothermal_width_K
    return Stream(f"{unit.name} source", "cold", T_lo, T_hi, Q_from_process, 0.0)


def add_units(
    stream_set: StreamSet, units: list[HeatPump], Q_source_from_process: dict[str, float]
) -> StreamSet:
    """Return the stream set extended with the units' sink and source streams.

    ``Q_source_from_process`` gives, per unit name, the part of the source duty
    taken from the process; the rest is assumed to come from outside the
    process (e.g. ambient air) and is not added to the cascade.
    """
    extra: list[Stream] = []
    for unit in units:
        extra.append(_sink_stream(unit))
        Q_proc = Q_source_from_process.get(unit.name, 0.0)
        if Q_proc > 0:
            if Q_proc > unit.Q_source * (1 + 1e-9):
                raise ValueError(f"{unit.name}: process source exceeds total source duty")
            extra.append(_source_stream(unit, Q_proc))
    return replace(stream_set, streams=stream_set.streams + tuple(extra))


def classify_placement(unit: HeatPump, pinch_T_star_C: float) -> str:
    """Placement relative to the pinch (heat pump integration rule).

    Returns "across pinch" (sink above, source below: correct), "above pinch",
    "below pinch", "straddles pinch", or "no source" for an electric heater.
    """
    sink_lo = min(unit.T_sink_in_C, unit.T_sink_out_C)
    if not unit.has_source:
        return "no source"
    source_hi = max(unit.T_source_in_C, unit.T_source_out_C)
    source_lo = min(unit.T_source_in_C, unit.T_source_out_C)
    sink_hi = max(unit.T_sink_in_C, unit.T_sink_out_C)
    if sink_lo >= pinch_T_star_C and source_hi <= pinch_T_star_C:
        return "across pinch"
    if source_lo >= pinch_T_star_C:
        return "above pinch"
    if sink_hi <= pinch_T_star_C:
        return "below pinch"
    return "straddles pinch"


def _placement_label(unit: HeatPump, pinch_T_star_C: float, Q_source_process: float) -> str:
    """Placement label that accounts for sources outside the process (e.g. ambient).

    A unit whose whole source is external only interacts with the process
    through its sink, so only the sink position relative to the pinch matters.
    """
    if unit.has_source and Q_source_process <= 0.0:
        sink_lo = min(unit.T_sink_in_C, unit.T_sink_out_C)
        side = "above" if sink_lo >= pinch_T_star_C else "below"
        return f"sink {side} pinch; external source"
    return classify_placement(unit, pinch_T_star_C)


@dataclass(frozen=True)
class IntegrationResult:
    """Effect of a set of units on the process energy targets.

    All heat quantities are in the case energy unit.
    """

    Qh_before: float
    Qc_before: float
    Qh_after: float
    Qc_after: float
    W_total: float
    Q_sink_total: float
    Q_sink_useful: float
    Q_source_process: dict[str, float]
    Q_source_external: dict[str, float]
    placement: dict[str, str]
    pinch_T_star_C: float

    @property
    def Q_sink_excess(self) -> float:
        """Sink heat the process cannot use at the sink temperatures."""
        return self.Q_sink_total - self.Q_sink_useful

    @property
    def Q_cold_utility_replaced(self) -> float:
        """Process cooling taken over by heat pump sources (Qc_before - Qc_after)."""
        return self.Qc_before - self.Qc_after

    @property
    def Q_source_recirculated(self) -> float:
        """Source heat that is the units' own surplus sink heat, re-absorbed.

        The evaporators take more heat from the cascade than the original
        cooling demand only when unused sink heat has been rejected into it;
        that part does no useful work for the process.
        """
        return sum(self.Q_source_process.values()) - self.Q_cold_utility_replaced


def _max_process_source(base: StreamSet, sinks: StreamSet, unit: HeatPump, Q_cap: float) -> float:
    """Largest source duty the process can give a unit without raising Qh.

    Found by bisection on the cascade, so it works for gliding sources too.
    """
    Qh_ref = problem_table(sinks).Qh_min
    tol = 1e-9 * max(1.0, Qh_ref)

    def feasible(Q: float) -> bool:
        trial = replace(sinks, streams=sinks.streams + (_source_stream(unit, Q),))
        return problem_table(trial).Qh_min <= Qh_ref + tol

    if Q_cap <= 0:
        return 0.0
    if feasible(Q_cap):
        return Q_cap
    lo, hi = 0.0, Q_cap
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if feasible(mid) else (lo, mid)
    # Duties within the solver tolerance are numerical noise, not process heat.
    return lo if lo > MIN_DUTY_FRACTION * max(Q_cap, Qh_ref) else 0.0


def integrate(stream_set: StreamSet, units: list[HeatPump]) -> IntegrationResult:
    """Integrate heat supply units into the process cascade.

    Sinks are added first. Each unit's source duty is then taken from the
    process up to the amount the cascade can give at the source temperature
    without increasing the hot utility; any remainder is external (ambient).

    Parameters
    ----------
    stream_set : StreamSet
        Process streams (before integration).
    units : list of HeatPump
        Units to integrate, processed in the given order for source allocation.

    Returns
    -------
    IntegrationResult
    """
    before = problem_table(stream_set)
    pinch = before.pinch_T_star_C[0] if before.pinch_T_star_C else float("nan")

    current = add_units(stream_set, units, {})
    after_sinks = problem_table(current)

    Q_proc: dict[str, float] = {}
    for unit in units:
        if not unit.has_source:
            continue
        Q = _max_process_source(stream_set, current, unit, unit.Q_source)
        Q_proc[unit.name] = Q
        if Q > 0:
            current = replace(current, streams=current.streams + (_source_stream(unit, Q),))

    after = problem_table(current)
    return IntegrationResult(
        Qh_before=before.Qh_min,
        Qc_before=before.Qc_min,
        Qh_after=after.Qh_min,
        Qc_after=after.Qc_min,
        W_total=sum(u.W for u in units),
        Q_sink_total=sum(u.Q_sink for u in units),
        Q_sink_useful=before.Qh_min - after_sinks.Qh_min,
        Q_source_process=Q_proc,
        Q_source_external={u.name: u.Q_source - Q_proc.get(u.name, 0.0) for u in units if u.has_source},
        placement={u.name: _placement_label(u, pinch, Q_proc.get(u.name, 0.0)) for u in units},
        pinch_T_star_C=pinch,
    )


def max_useful_sink_duty(stream_set: StreamSet, unit: HeatPump) -> float:
    """Size a unit from the GCC: largest sink duty the process can fully use.

    A sink duty is fully used when it lowers the hot utility by the same
    amount. Found by bisection on the cascade, so it works for gliding sinks.
    The upper bound is the process's current minimum hot utility.
    """
    Qh_ref = problem_table(stream_set).Qh_min
    tol = 1e-9 * max(1.0, Qh_ref)

    def fully_used(Q: float) -> bool:
        trial = add_units(stream_set, [unit.with_sink_duty(Q)], {})
        return problem_table(trial).Qh_min <= Qh_ref - Q + tol

    if Qh_ref <= tol:
        return 0.0
    if fully_used(Qh_ref):
        return Qh_ref
    lo, hi = 0.0, Qh_ref
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if fully_used(mid) else (lo, mid)
    # Duties within the solver tolerance are numerical noise, not a design.
    return lo if lo > MIN_DUTY_FRACTION * Qh_ref else 0.0
