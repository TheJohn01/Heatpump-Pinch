"""Vapour-compression heat pump cycles with real working fluids (workflow step 4b).

Replaces the Lorenz-efficiency COP of step 4a by a thermodynamic cycle model
(CoolProp, Helmholtz equations of state), to check the assumed η_L and to
select a working fluid.

Model (assumptions follow Andersen et al., 2024, Applied Energy 376, 124312,
Table 3, so that their published cycle COPs serve as the test case):

* Heat source and heat sink are secondary streams with linear temperature
  profiles (constant heat capacity), given by inlet and outlet temperatures.
  Isothermal profiles (T_in = T_out) are allowed.
* Pinch-point temperature difference 3 K in the evaporator and in the
  condenser/gas cooler, checked along the whole profile (counter-current).
* Suction superheat 3 K; condenser outlet at sink inlet + pinch ("maximum
  subcooling"), or saturated liquid if that is colder.
* Compressor: isentropic efficiency 70 %, heat loss 5 % of the shaft work
  (h_2 = h_1 + w (1 - f_q)), motor efficiency 95 % (W_el = w / η_motor).
* Optional suction-line heat exchanger (SLHX, pinch 5 K) and optional
  expansion machine (isentropic efficiency 50 %; its work offsets the
  compressor, w_el = w / η_motor - w_exp η_motor, our assumption: the paper
  does not state how expander work is credited).
* Cascade: two single-stage cycles coupled by a shared exchanger (pinch 3 K,
  checked between the two refrigerant profiles); the intermediate
  temperature is optimised.
* Pressures are optimised for maximum COP subject to the pinch constraints;
  wet compression (two-phase discharge) is infeasible.

Not modelled: two-stage cycles with separator (Andersen's "Two-stg"),
pressure drops, compressor maps and part load. Pressure ratio and discharge
temperature are reported, not screened: no sourced limits are applied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

import CoolProp.CoolProp as CP
from scipy.optimize import minimize_scalar

from pinch.heat_pump import KELVIN, thermodynamic_mean_temperature_K

ANDERSEN2024_TABLE3 = "Andersen et al. (2024), Applied Energy 376, 124312, Table 3"
EXPANDER_CREDIT = lambda a: a.eta_motor  # noqa: E731


@dataclass(frozen=True)
class CycleAssumptions:
    """Component assumptions; defaults from Andersen et al. (2024), Table 3."""

    dT_pinch_source_K: float = 3.0
    dT_pinch_sink_K: float = 3.0
    dT_superheat_K: float = 3.0
    dT_pinch_slhx_K: float = 5.0
    dT_pinch_cascade_K: float = 3.0
    eta_is_compressor: float = 0.70
    heat_loss_factor: float = 0.05
    eta_motor: float = 0.95
    eta_is_expander: float = 0.50
    n_points: int = 25            # points per exchanger profile for the pinch check
    source: str = ANDERSEN2024_TABLE3


@dataclass(frozen=True)
class SecondaryStream:
    """A heat source or sink outside the cycle, linear in enthalpy [°C]."""

    T_in_C: float
    T_out_C: float

    @property
    def T_hot_C(self) -> float:
        return max(self.T_in_C, self.T_out_C)

    @property
    def T_cold_C(self) -> float:
        return min(self.T_in_C, self.T_out_C)

    def T_from_hot_end(self, x: float) -> float:
        """Temperature at fraction x of the duty counted from the hot end."""
        return self.T_hot_C - x * (self.T_hot_C - self.T_cold_C)


@dataclass
class CycleResult:
    """Result for one cycle (or cascade) at its optimum.

    Specific quantities are per kg of refrigerant of the (top) cycle [kJ/kg].
    """

    fluid: str
    layout: str
    feasible: bool
    COP: float = math.nan
    COP_lorenz: float = math.nan
    eta_lorenz: float = math.nan
    T_evap_C: float = math.nan
    T_cond_C: float = math.nan          # saturation T at high pressure; nan if transcritical
    P_low_bar: float = math.nan
    P_high_bar: float = math.nan
    pressure_ratio: float = math.nan
    T_discharge_C: float = math.nan
    transcritical: bool = False
    q_sink_kJ_kg: float = math.nan
    q_source_kJ_kg: float = math.nan
    w_el_kJ_kg: float = math.nan
    note: str = ""
    stages: list["CycleResult"] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {k: (round(v, 4) if isinstance(v, float) and math.isfinite(v) else v)
               for k, v in self.__dict__.items() if k != "stages"}
        if self.stages:
            out["stages"] = [s.as_dict() for s in self.stages]
        return out


# ------------------------------------------------------------------ fluid helper
class _Fluid:
    """Thin CoolProp AbstractState wrapper, SI units internally (Pa, J/kg, K)."""

    def __init__(self, name: str):
        self.name = name
        self.AS = CP.AbstractState("HEOS", name)
        self.T_crit = self.AS.T_critical()
        self.P_crit = self.AS.p_critical()
        self.T_min = max(self.AS.Ttriple(), self.AS.Tmin()) + 0.5
        self.P_max = self.AS.pmax()

    def T_ph(self, P: float, h: float) -> float:
        self.AS.update(CP.HmassP_INPUTS, h, P)
        return self.AS.T()

    def h_pt(self, P: float, T: float) -> float:
        self.AS.update(CP.PT_INPUTS, P, T)
        return self.AS.hmass()

    def s_pt(self, P: float, T: float) -> float:
        self.AS.update(CP.PT_INPUTS, P, T)
        return self.AS.smass()

    def h_ps(self, P: float, s: float) -> float:
        self.AS.update(CP.PSmass_INPUTS, P, s)
        return self.AS.hmass()

    def s_ph(self, P: float, h: float) -> float:
        self.AS.update(CP.HmassP_INPUTS, h, P)
        return self.AS.smass()

    def P_sat(self, T: float) -> float:
        self.AS.update(CP.QT_INPUTS, 1.0, T)
        return self.AS.p()

    def T_sat(self, P: float) -> float:
        self.AS.update(CP.PQ_INPUTS, P, 1.0)
        return self.AS.T()

    def h_sat(self, P: float, Q: float) -> float:
        self.AS.update(CP.PQ_INPUTS, P, Q)
        return self.AS.hmass()


def _min_dT(T_hot: Callable[[float], float], T_cold: Callable[[float], float], n: int) -> float:
    """Minimum T_hot(x) - T_cold(x) over x in [0, 1] (both counted from the hot end)."""
    return min(T_hot(i / n) - T_cold(i / n) for i in range(n + 1))


# ------------------------------------------------------------------ single stage
@dataclass
class _State:
    feasible: bool
    COP: float = -math.inf
    T_e: float = math.nan
    P_lo: float = math.nan
    P_hi: float = math.nan
    h1: float = math.nan       # evaporator outlet
    h4: float = math.nan       # evaporator inlet
    h2: float = math.nan       # discharge
    h3: float = math.nan       # condenser outlet
    q_sink: float = math.nan
    q_src: float = math.nan
    w_el: float = math.nan
    T2: float = math.nan
    pr_stage: float = math.nan   # largest pressure ratio of one compression stage (two-stage cycles)


def _evaluate(f: _Fluid, T_e: float, P_hi: float, sink_T: Callable[[float], float], T_sink_in: float,
              a: CycleAssumptions, slhx: bool, expander: bool) -> _State:
    """Cycle states for given evaporation temperature [K] and high pressure [Pa]; condenser checked.

    A state outside the equation of state's range (CoolProp error) is infeasible.
    """
    try:
        if isinstance(expander, tuple):          # ("two-stg" | "two-stg2", intermediate-pressure factor)
            return _evaluate_two_stage_raw(f, T_e, P_hi, sink_T, T_sink_in, a, *expander)
        return _evaluate_raw(f, T_e, P_hi, sink_T, T_sink_in, a, slhx, expander)
    except ValueError:
        return _State(False)


def _evaluate_two_stage_raw(f: _Fluid, T_e: float, P_hi: float, sink_T, T_sink_in: float, a: CycleAssumptions,
                            variant: str, mid_factor: float) -> _State:
    """Two-stage cycle with a liquid separator at P_mid = mid_factor * sqrt(P_lo P_hi).

    Andersen et al. (2024), Fig. 1 B: "two-stg" injects the separator vapour into
    the low-stage discharge; "two-stg2" (open intercooler) sends the low-stage
    discharge into the separator, so the high stage draws saturated vapour.
    Specific quantities per kg of high-stage flow.
    """
    if T_e >= f.T_crit - 0.5 or T_e < f.T_min:
        return _State(False)
    P_lo = f.P_sat(T_e)
    P_mid = mid_factor * math.sqrt(P_lo * P_hi)
    if not (P_lo * 1.0001 < P_mid < P_hi / 1.0001) or P_mid >= f.P_crit * 0.98:
        return _State(False)
    h1 = f.h_pt(P_lo, T_e + a.dT_superheat_K)
    subcritical = P_hi < f.P_crit
    T7 = T_sink_in + a.dT_pinch_sink_K
    if subcritical:
        h7 = f.h_sat(P_hi, 0.0) if T7 >= f.T_sat(P_hi) - 1e-6 else f.h_pt(P_hi, T7)
    else:
        h7 = f.h_pt(P_hi, T7)
    h_l, h_v = f.h_sat(P_mid, 0.0), f.h_sat(P_mid, 1.0)
    dh1 = (f.h_ps(P_mid, f.s_ph(P_lo, h1)) - h1) / a.eta_is_compressor
    h2 = h1 + dh1
    if h2 <= h_v:
        return _State(False)                      # wet low-stage discharge
    if variant == "two-stg":
        x8 = (h7 - h_l) / (h_v - h_l)
        if not 0.0 <= x8 < 1.0:
            return _State(False)
        m_lp = 1.0 - x8
        h3 = m_lp * h2 + x8 * h_v
    elif variant == "two-stg2":
        m_lp = (h_v - h7) / (h2 - h_l)
        if m_lp <= 0:
            return _State(False)
        h3 = h_v
    else:
        raise ValueError(f"unknown two-stage variant {variant}")
    dh2 = (f.h_ps(P_hi, f.s_ph(P_mid, h3)) - h3) / a.eta_is_compressor
    h4 = h3 + dh2
    if subcritical and h4 <= f.h_sat(P_hi, 1.0):
        return _State(False)                      # wet high-stage discharge
    w_el = (m_lp * dh1 + dh2) / (1 - a.heat_loss_factor) / a.eta_motor
    q_sink, q_src = h4 - h7, m_lp * (h1 - h_l)
    if q_sink <= 0 or q_src <= 0:
        return _State(False)
    if _min_dT(lambda x: f.T_ph(P_hi, h4 - x * (h4 - h7)), sink_T, a.n_points) < a.dT_pinch_sink_K - 1e-6:
        return _State(False)
    st = _State(True, q_sink / w_el, T_e, P_lo, P_hi, h1, h_l, h4, h7, q_sink, q_src, w_el, f.T_ph(P_hi, h4))
    st.pr_stage = max(P_mid / P_lo, P_hi / P_mid)
    return st


def _evaluate_raw(f: _Fluid, T_e: float, P_hi: float, sink_T: Callable[[float], float], T_sink_in: float,
                  a: CycleAssumptions, slhx: bool, expander: bool) -> _State:
    if T_e >= f.T_crit - 0.5 or T_e < f.T_min:
        return _State(False)
    P_lo = f.P_sat(T_e)
    if P_hi <= P_lo * 1.0001:
        return _State(False)
    h1 = f.h_pt(P_lo, T_e + a.dT_superheat_K)
    subcritical = P_hi < f.P_crit
    T3 = T_sink_in + a.dT_pinch_sink_K
    if subcritical:
        T_cond = f.T_sat(P_hi)
        h3 = f.h_sat(P_hi, 0.0) if T3 >= T_cond - 1e-6 else f.h_pt(P_hi, T3)
    else:
        h3 = f.h_pt(P_hi, T3)
    T3_actual = f.T_ph(P_hi, h3)

    # suction-line heat exchanger: largest duty with pinch >= dT_pinch_slhx
    h1c, h3c = h1, h3
    if slhx:
        T1 = T_e + a.dT_superheat_K
        if T3_actual - T1 > a.dT_pinch_slhx_K:
            Q = min(f.h_pt(P_lo, T3_actual - a.dT_pinch_slhx_K) - h1, h3 - f.h_pt(P_hi, T1 + a.dT_pinch_slhx_K))
            Q = max(Q, 0.0)
            for _ in range(30):  # shrink until the internal profile respects the pinch
                if Q <= 0:
                    break
                dT = _min_dT(lambda x: f.T_ph(P_hi, h3 - x * Q), lambda x: f.T_ph(P_lo, h1 + Q - x * Q), 10)
                if dT >= a.dT_pinch_slhx_K - 1e-6:
                    break
                Q *= 0.95
            h1c, h3c = h1 + Q, h3 - Q

    s1 = f.s_ph(P_lo, h1c)
    dh = (f.h_ps(P_hi, s1) - h1c) / a.eta_is_compressor   # enthalpy rise of the refrigerant
    h2 = h1c + dh
    w = dh / (1 - a.heat_loss_factor)                      # shaft work: f_q of it is lost to ambient
    if subcritical and h2 <= f.h_sat(P_hi, 1.0):
        return _State(False)  # wet compression
    if expander:
        w_exp = a.eta_is_expander * (h3c - f.h_ps(P_lo, f.s_ph(P_hi, h3c)))
        h4 = h3c - w_exp
        w_el = w / a.eta_motor - w_exp * EXPANDER_CREDIT(a)
    else:
        h4 = h3c
        w_el = w / a.eta_motor
    q_sink, q_src = h2 - h3, h1 - h4
    if q_sink <= 0 or q_src <= 0 or w_el <= 0:
        return _State(False)
    # condenser / gas cooler pinch along the profile (x from the hot end)
    if _min_dT(lambda x: f.T_ph(P_hi, h2 - x * (h2 - h3)), sink_T, a.n_points) < a.dT_pinch_sink_K - 1e-6:
        return _State(False)
    return _State(True, q_sink / w_el, T_e, P_lo, P_hi, h1, h4, h2, h3, q_sink, q_src, w_el, f.T_ph(P_hi, h2))


def _evaporator_ok(f: _Fluid, s: _State, source_T: Callable[[float], float], a: CycleAssumptions) -> bool:
    try:
        return _evaporator_ok_raw(f, s, source_T, a)
    except ValueError:
        return False


def _evaporator_ok_raw(f: _Fluid, s: _State, source_T: Callable[[float], float], a: CycleAssumptions) -> bool:
    return _min_dT(source_T, lambda x: f.T_ph(s.P_lo, s.h1 - x * (s.h1 - s.h4)), a.n_points) >= a.dT_pinch_source_K - 1e-6


def _best_T_evap(f: _Fluid, P_hi: float, source_T, T_source_hot_K: float, sink_T, T_sink_in: float,
                 a: CycleAssumptions, slhx: bool, expander: bool, T_e_fixed: float | None) -> _State:
    """Highest evaporation temperature feasible for the evaporator at this high pressure."""
    def state(T_e):
        return _evaluate(f, T_e, P_hi, sink_T, T_sink_in, a, slhx, expander)

    if T_e_fixed is not None:
        return state(T_e_fixed)
    hi = min(T_source_hot_K - a.dT_pinch_source_K - a.dT_superheat_K, f.T_crit - 1.0)
    lo = f.T_min
    s_hi = state(hi)
    if s_hi.feasible and _evaporator_ok(f, s_hi, source_T, a):
        return s_hi
    best = _State(False)
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        s = state(mid)
        if s.feasible and _evaporator_ok(f, s, source_T, a):
            best, lo = s, mid
        else:
            # infeasible either at the evaporator (go colder) or at the condenser/discharge
            # (going colder only lowers the discharge entropy for most fluids): go colder
            hi = mid
        if hi - lo < 0.01:
            break
    return best


def _solve_single(fluid: str, source: SecondaryStream | None, sink_T: Callable[[float], float], T_sink_hot: float,
                  T_sink_in: float, a: CycleAssumptions, slhx: bool, expander: bool,
                  T_e_fixed: float | None = None) -> _State:
    """Optimise the high pressure (and evaporation temperature) for maximum COP."""
    f = _Fluid(fluid)
    if source is not None:
        source_T = lambda x: source.T_from_hot_end(x) + KELVIN  # noqa: E731
        T_source_hot_K = source.T_hot_C + KELVIN
    else:  # cascade top cycle: evaporation temperature imposed, no source check
        source_T, T_source_hot_K = None, None

    def at(P_hi: float) -> _State:
        if source_T is None:
            return _evaluate(f, T_e_fixed, P_hi, sink_T, T_sink_in, a, slhx, expander)
        return _best_T_evap(f, P_hi, source_T, T_source_hot_K, sink_T, T_sink_in, a, slhx, expander, None)

    # lowest high pressure at which the condenser respects the pinch
    T_needed = T_sink_hot + a.dT_pinch_sink_K
    if T_needed < f.T_crit - 0.5:
        P_lo_b = f.P_sat(max(T_needed - 40.0, f.T_min + 1.0))
    else:
        P_lo_b = 0.5 * f.P_crit
    P_hi_b = min(f.P_max * 0.95, 3.0 * max(f.P_crit, P_lo_b))
    if not at(P_hi_b).feasible:
        # COP may still be feasible at lower pressure (wet compression at high P is rare); scan
        grid = [P_lo_b * (P_hi_b / P_lo_b) ** (i / 30) for i in range(31)]
        ok = [P for P in grid if at(P).feasible]
        if not ok:
            return _State(False)
        P_hi_b = max(ok)
    lo, hi = P_lo_b, P_hi_b
    if at(lo).feasible:
        P_min = lo
    else:
        for _ in range(50):
            mid = math.sqrt(lo * hi)
            if at(mid).feasible:
                hi = mid
            else:
                lo = mid
            if hi / lo < 1.0005:
                break
        P_min = hi
    # COP over [P_min, P_max]: decreasing for subcritical condensation, may peak for transcritical
    P_top = min(P_hi_b, P_min * 2.5)
    res = minimize_scalar(lambda lnP: -at(math.exp(lnP)).COP, bounds=(math.log(P_min), math.log(P_top)),
                          method="bounded", options={"xatol": 1e-4})
    s_opt = at(math.exp(res.x))
    s_min = at(P_min)
    return s_opt if s_opt.feasible and s_opt.COP >= s_min.COP else s_min


def _lorenz(source: SecondaryStream, sink: SecondaryStream) -> float:
    T_si = thermodynamic_mean_temperature_K(sink.T_in_C, sink.T_out_C)
    T_so = thermodynamic_mean_temperature_K(source.T_in_C, source.T_out_C)
    return T_si / (T_si - T_so) if T_si > T_so else math.inf


def _result(fluid: str, layout: str, s: _State, source: SecondaryStream, sink: SecondaryStream) -> CycleResult:
    if not s.feasible:
        return CycleResult(fluid, layout, False, note="no feasible operating point")
    f = _Fluid(fluid)
    cop_L = _lorenz(source, sink)
    trans = s.P_hi >= f.P_crit
    return CycleResult(
        fluid, layout, True, COP=s.COP, COP_lorenz=cop_L, eta_lorenz=s.COP / cop_L,
        T_evap_C=s.T_e - KELVIN, T_cond_C=math.nan if trans else f.T_sat(s.P_hi) - KELVIN,
        P_low_bar=s.P_lo / 1e5, P_high_bar=s.P_hi / 1e5,
        pressure_ratio=s.pr_stage if math.isfinite(s.pr_stage) else s.P_hi / s.P_lo,
        T_discharge_C=s.T2 - KELVIN, transcritical=trans,
        q_sink_kJ_kg=s.q_sink / 1e3, q_source_kJ_kg=s.q_src / 1e3, w_el_kJ_kg=s.w_el / 1e3)


# ------------------------------------------------------------------ public API
def single_stage(fluid: str, source: SecondaryStream, sink: SecondaryStream,
                 assumptions: CycleAssumptions = CycleAssumptions(),
                 slhx: bool = False, expander: bool = False) -> CycleResult:
    """Optimised single-stage cycle between a source and a sink stream.

    Parameters
    ----------
    fluid : str
        CoolProp fluid name (e.g. "n-Butane", "CarbonDioxide", "R1233zd(E)").
    source, sink : SecondaryStream
        Source cools from T_in to T_out; sink heats from T_in to T_out [°C].
    slhx, expander : bool
        Suction-line heat exchanger; expansion machine instead of a valve.
    """
    sink_T = lambda x: sink.T_from_hot_end(x) + KELVIN  # noqa: E731
    s = _solve_single(fluid, source, sink_T, sink.T_hot_C + KELVIN, sink.T_cold_C + KELVIN,
                      assumptions, slhx, expander)
    layout = "single stage" + (", SLHX" if slhx else "") + (", expander" if expander else "")
    r = _result(fluid, layout, s, source, sink)
    if r.feasible and r.COP >= r.COP_lorenz:
        raise AssertionError("second-law violation: cycle COP above the Lorenz COP")
    return r


def two_stage(fluid: str, source: SecondaryStream, sink: SecondaryStream,
              assumptions: CycleAssumptions = CycleAssumptions(), variant: str = "two-stg2") -> CycleResult:
    """Optimised two-stage cycle with a liquid separator (Andersen et al., 2024, Fig. 1 B).

    The intermediate pressure is optimised as a factor on the geometric mean of
    the evaporation and condensation pressures. ``pressure_ratio`` in the result
    is the largest ratio of a single stage.
    """
    sink_T = lambda x: sink.T_from_hot_end(x) + KELVIN  # noqa: E731

    def solve(ln_factor: float) -> _State:
        return _solve_single(fluid, source, sink_T, sink.T_hot_C + KELVIN, sink.T_cold_C + KELVIN, assumptions,
                             False, (variant, math.exp(ln_factor)))

    grid = [math.log(x) for x in (0.6, 0.8, 1.0, 1.25, 1.6)]
    states = [(st.COP if st.feasible else -math.inf, g, st) for g in grid for st in [solve(g)]]
    best_cop, best_g, best = max(states, key=lambda t: t[0])
    if math.isfinite(best_cop):
        res = minimize_scalar(lambda g: -(lambda st: st.COP if st.feasible else -1e9)(solve(g)),
                              bounds=(best_g - 0.25, best_g + 0.25), method="bounded", options={"xatol": 0.01})
        st = solve(res.x)
        if st.feasible and st.COP > best.COP:
            best = st
    r = _result(fluid, f"two stage ({variant})", best, source, sink)
    if r.feasible and r.COP >= r.COP_lorenz:
        raise AssertionError("second-law violation: cycle COP above the Lorenz COP")
    return r


def cascade(fluid_low: str, fluid_high: str, source: SecondaryStream, sink: SecondaryStream,
            assumptions: CycleAssumptions = CycleAssumptions(),
            slhx_low: bool = False, slhx_high: bool = False) -> CycleResult:
    """Two single-stage cycles in cascade; the intermediate temperature is optimised.

    The top cycle evaporates at T_e,top; the bottom cycle condenses against the
    top cycle's evaporating profile with the cascade pinch checked point by point.
    """
    a = assumptions
    f_hi = _Fluid(fluid_high)

    def solve(T_e_top_C: float) -> tuple[float, _State | None, _State | None]:
        T_e = T_e_top_C + KELVIN
        if T_e >= f_hi.T_crit - 1 or T_e < f_hi.T_min:
            return -math.inf, None, None
        sink_T = lambda x: sink.T_from_hot_end(x) + KELVIN  # noqa: E731
        top = _solve_single(fluid_high, None, sink_T, sink.T_hot_C + KELVIN, sink.T_cold_C + KELVIN, a,
                            slhx_high, False, T_e_fixed=T_e)
        if not top.feasible:
            return -math.inf, None, None
        P_e = top.P_lo
        top_evap_T = lambda x: f_hi.T_ph(P_e, top.h1 - x * (top.h1 - top.h4))  # noqa: E731
        # bottom-cycle sink = top evaporator profile shifted by the cascade pinch (and the sink pinch removed)
        shift = a.dT_pinch_cascade_K - a.dT_pinch_sink_K
        bottom_sink_T = lambda x: top_evap_T(x) + shift  # noqa: E731
        bottom = _solve_single(fluid_low, source, bottom_sink_T, top_evap_T(0.0) + shift,
                               top_evap_T(1.0) + shift, a, slhx_low, False)
        if not bottom.feasible:
            return -math.inf, None, None
        # per kg of top-cycle refrigerant: bottom condenser duty = top evaporator duty
        m_ratio = top.q_src / bottom.q_sink
        cop = top.q_sink / (top.w_el + m_ratio * bottom.w_el)
        return cop, top, bottom

    # intermediate (top evaporation) temperature between the source and the sink; infeasible points score -inf
    lo = source.T_cold_C
    hi = sink.T_hot_C - 2 * a.dT_pinch_sink_K
    grid = [lo + (hi - lo) * i / 16 for i in range(17)]
    vals = [(solve(T)[0], T) for T in grid]
    best_cop, best_T = max(vals)
    if not math.isfinite(best_cop):
        return CycleResult(f"{fluid_low} / {fluid_high}", "cascade", False, note="no feasible intermediate temperature")
    step = (hi - lo) / 16
    res = minimize_scalar(lambda T: -solve(T)[0], bounds=(max(lo, best_T - step), min(hi, best_T + step)),
                          method="bounded", options={"xatol": 0.05})
    cop, top, bottom = solve(res.x)
    if cop < best_cop:
        cop, top, bottom = solve(best_T)
    cop_L = _lorenz(source, sink)
    if cop >= cop_L:
        raise AssertionError("second-law violation: cascade COP above the Lorenz COP")
    f_lo = _Fluid(fluid_low)
    stages = [
        CycleResult(fluid_low, "bottom", True, COP=bottom.COP, T_evap_C=bottom.T_e - KELVIN,
                    T_cond_C=math.nan if bottom.P_hi >= f_lo.P_crit else f_lo.T_sat(bottom.P_hi) - KELVIN,
                    P_low_bar=bottom.P_lo / 1e5, P_high_bar=bottom.P_hi / 1e5,
                    pressure_ratio=bottom.P_hi / bottom.P_lo, T_discharge_C=bottom.T2 - KELVIN,
                    transcritical=bottom.P_hi >= f_lo.P_crit),
        CycleResult(fluid_high, "top", True, COP=top.COP, T_evap_C=top.T_e - KELVIN,
                    T_cond_C=math.nan if top.P_hi >= f_hi.P_crit else f_hi.T_sat(top.P_hi) - KELVIN,
                    P_low_bar=top.P_lo / 1e5, P_high_bar=top.P_hi / 1e5, pressure_ratio=top.P_hi / top.P_lo,
                    T_discharge_C=top.T2 - KELVIN, transcritical=top.P_hi >= f_hi.P_crit),
    ]
    layout = "cascade" + (" (SLHX bottom)" if slhx_low else "") + (" (SLHX top)" if slhx_high else "")
    return CycleResult(f"{fluid_low} / {fluid_high}", layout, True, COP=cop, COP_lorenz=cop_L,
                       eta_lorenz=cop / cop_L, pressure_ratio=max(s.pressure_ratio for s in stages),
                       T_discharge_C=max(s.T_discharge_C for s in stages), stages=stages,
                       note=f"intermediate (top evaporation) {top.T_e - KELVIN:.1f} °C")


def screen_fluids(fluids: list[str], source: SecondaryStream, sink: SecondaryStream,
                  assumptions: CycleAssumptions = CycleAssumptions(),
                  layouts: tuple[str, ...] = ("std", "slhx")) -> list[CycleResult]:
    """Best single-stage cycle per fluid and layout, sorted by COP (feasible first)."""
    out = []
    for fl in fluids:
        for lay in layouts:
            try:
                out.append(single_stage(fl, source, sink, assumptions, slhx="slhx" in lay, expander="exp" in lay))
            except ValueError as exc:  # CoolProp out of range
                out.append(CycleResult(fl, lay, False, note=f"CoolProp: {exc}"[:120]))
    return sorted(out, key=lambda r: (not r.feasible, -(r.COP if r.feasible else 0)))
