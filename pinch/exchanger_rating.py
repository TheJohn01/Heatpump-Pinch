"""Shell-and-tube rating of designed exchangers with the ht library (workflow step 5).

``pinch.hen_design`` sizes every exchanger in pure counter-current flow (A = Q / (U ΔT_LM)). A real
shell-and-tube unit with one shell pass and an even number of tube passes needs more area, by the factor
1/F, and when F is too low it needs several shells in series. This module adds that step, and a tube-side
rating (film coefficient and pressure drop) for a given bundle, using

    ht (Caleb Bell and contributors, MIT licence), github.com/CalebBell/ht, version pinned in
    requirements.txt: ``ht.hx.F_LMTD_Fakheri`` (Fakheri 2003, J. Heat Transfer 125, 527-530) for F with
    N shells, ``ht.conv_internal.turbulent_Colburn`` / ``turbulent_Gnielinski`` for the tube-side Nusselt
    number;
    fluids (same authors and licence), ``fluids.friction.friction_factor`` (Clamond solution of
    Colebrook) for the Darcy friction factor.

Rules
-----
* Number of shells: the smallest N with F(N) >= ``F_min``. Default 0.8: every value from 0.75 to 0.855
  reproduces the shell counts of all eleven exchangers designed by Polley and Panjeh Shahi (1991, Tables
  4-5); 0.8 is the middle of that range (assumption, docs/ASSUMPTIONS.md).
* Rated area A = Q / (U F ΔT_LM); cost per unit = N_shells × cost(A / N_shells).
* Tube side: velocity from the mass flow over (tubes / passes) bores; h_i from the Colburn form of
  Dittus-Boelter (0.023 Re^0.8 Pr^1/3, the relation behind Polley et al.'s ΔP = K A h^3.5) or Gnielinski;
  h_io = h_i d_i / d_o, then fouling and the tube wall in series; ΔP = f_D (L N_passes / d_i) ρ u² / 2 per
  shell, straight tubes only.

Validation (tests/test_exchanger_rating.py, scripts/benchmarks/benchmark_exchanger_rating.py) against the
detailed designs of Polley and Panjeh Shahi (1991): shell counts 11 of 11; with their Table 3 properties,
fouling 0.00018 m²K/W and a carbon-steel wall (k 45 W/mK, assumed), tube-side h_io within 0.3 % and ΔP_t
within 3.7 % for the six process exchangers; their published U with our F gives their actual areas within
1.2 %.
Not modelled: shell-side Bell-Delaware (baffle and clearance data are not published), return losses in
the tube headers (their ΔP_t values match straight tubes only), and multiple shell passes in one shell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import fluids.friction
import ht.conv_internal
import ht.hx

from pinch.hen_design import CostLaw, Exchanger, overall_U
from pinch.pressure_drop import Fluid

F_MIN_DEFAULT = 0.8          # assumption; 0.75-0.855 all reproduce Polley and Panjeh Shahi (1991)
K_WALL_STEEL = 45.0          # W/mK, carbon steel (assumption; not published by the benchmark)


def lmtd_correction(e: Exchanger, shells: int = 1) -> float:
    """F for one shell pass and an even number of tube passes per shell, ``shells`` in series (nan if none).

    Isothermal sides (condensing steam, boiling) give F = 1. A temperature cross that no number of shells
    can resolve gives nan.
    """
    if e.T_hot_in_C == e.T_hot_out_C or e.T_cold_in_C == e.T_cold_out_C:
        return 1.0
    try:
        F = ht.hx.F_LMTD_Fakheri(Thi=e.T_hot_in_C, Tho=e.T_hot_out_C,  # type: ignore[arg-type]  # ht types
                                 Tci=e.T_cold_in_C, Tco=e.T_cold_out_C, shells=shells)  # type: ignore[arg-type]
    except (ValueError, ZeroDivisionError):
        return math.nan
    F = complex(F).real if isinstance(F, complex) else float(F)
    return F if math.isfinite(F) and 0.0 < F <= 1.0 + 1e-9 else math.nan


def shells_required(e: Exchanger, F_min: float = F_MIN_DEFAULT, max_shells: int = 12) -> tuple[int, float]:
    """Smallest number of shells in series with F >= ``F_min``, and that F. Raises ValueError if none."""
    for n in range(1, max_shells + 1):
        F = lmtd_correction(e, n)
        if math.isfinite(F) and F >= F_min:
            return n, F
    raise ValueError(f"{e.hot}-{e.cold}: F stays below {F_min} up to {max_shells} shells")


@dataclass(frozen=True)
class RatedExchanger:
    hot: str
    cold: str
    Q: float
    U: float
    LMTD_K: float
    shells: int
    F: float
    area_counter_current_m2: float
    area_m2: float
    cost: float


def rate_exchangers(exchangers: tuple[Exchanger, ...], h: dict[str, float], cost_law: CostLaw | None = None,
                    Rf: dict[str, float] | None = None, F_min: float = F_MIN_DEFAULT) -> list[RatedExchanger]:
    """Shells, F, rated area and cost of each exchanger (units as in ``hen_design.evaluate_exchangers``)."""
    Rf = Rf or {}
    out = []
    for e in exchangers:
        U = overall_U(h[e.hot], h[e.cold], Rf.get(e.hot, 0.0), Rf.get(e.cold, 0.0))
        A_cc = e.Q / (U * e.lmtd_K)
        n, F = shells_required(e, F_min)
        A = A_cc / F
        cost = n * cost_law.cost(A / n) if cost_law else math.nan
        out.append(RatedExchanger(e.hot, e.cold, e.Q, U, e.lmtd_K, n, F, A_cc, A, cost))
    return out


@dataclass(frozen=True)
class TubeBundle:
    """Tubes of one shell; ``shells`` identical shells in series."""

    tubes: int
    passes: int
    d_i_m: float
    d_o_m: float
    length_m: float
    shells: int = 1
    k_wall_W_mK: float = K_WALL_STEEL
    roughness_m: float = 0.0


@dataclass(frozen=True)
class TubeSide:
    velocity_m_s: float
    Re: float
    h_i_W_m2K: float       # clean, inside area
    h_io_W_m2K: float      # referred to the outside area, with fouling and wall in series
    dP_Pa: float           # straight tubes, all shells


def tube_side(f: Fluid, m_kg_s: float, b: TubeBundle, Rf_m2K_W: float = 0.0,
              correlation: str = "colburn") -> TubeSide:
    """Tube-side film coefficient and pressure drop (turbulent flow; ht and fluids correlations)."""
    flow_area = math.pi * b.d_i_m ** 2 / 4 * b.tubes / b.passes
    u = m_kg_s / (f.rho * flow_area)
    Re = f.rho * u * b.d_i_m / f.mu
    if Re < 1e4:
        raise ValueError(f"Re = {Re:.0f}: the turbulent correlations need Re >= 1e4")
    fd = fluids.friction.friction_factor(Re, eD=b.roughness_m / b.d_i_m)
    if correlation == "colburn":
        Nu = ht.conv_internal.turbulent_Colburn(Re, f.Pr)
    elif correlation == "gnielinski":
        Nu = ht.conv_internal.turbulent_Gnielinski(Re, f.Pr, fd)
    else:
        raise ValueError(f"unknown correlation {correlation!r}")
    h_i = Nu * f.k / b.d_i_m
    R_wall = b.d_o_m * math.log(b.d_o_m / b.d_i_m) / (2 * b.k_wall_W_mK)
    h_io = 1.0 / (b.d_o_m / (h_i * b.d_i_m) + Rf_m2K_W + R_wall)
    dP = fd * (b.length_m * b.passes / b.d_i_m) * f.rho * u ** 2 / 2 * b.shells
    return TubeSide(u, Re, h_i, h_io, dP)
