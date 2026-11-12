"""Film coefficients from allowable pressure drop, and fouling (workflow steps 3 and 5).

Area targets and network costs use stream film coefficients h. Assumed values can be far from what a
detailed exchanger design achieves: Polley and Panjeh Shahi (1991) found the four-stream problem of
Sagli et al. designed at U = 50 W/m²K needed 163.6 k$ of exchangers instead of the predicted 716 k$, because
the stream pressure drops supported much higher coefficients. Basing h on the pressure drop each stream
can spend on heat transfer removes that guess. This module follows

    Polley, Panjeh Shahi, Jegede (1990), "Pressure drop considerations in the retrofit of heat exchanger
    networks", Trans IChemE 68 A, 211-220 (Eqs 2, 11-13; Appendices 1-2);
    Polley and Panjeh Shahi (1991), "Interfacing heat exchanger network synthesis and detailed heat
    exchanger design", Trans IChemE 69 A, 445-457 (Eqs 1, 4-5; Fig. 4).

Relations
---------
* Pressure drop, area and film coefficient: ΔP = K A h^n (1990, Eq. 11).
  - Tube side, turbulent (Dittus-Boelter, Nu = 0.023 Re^0.8 Pr^1/3; Fanning f = 0.046 Re^-0.2):
    n = 3.5, K = k2 k3 / k1^3.5 with k1 = 0.023 (λ/d)(ρd/μ)^0.8 Pr^1/3, k2 = 0.092 (ρ/d)(ρd/μ)^-0.2,
    k3 = d / (4 V) (1990, Eqs A1.1-A1.13).
  - Shell side (Kern, 25 % baffle cut: j = 0.36 Re^0.55, f = 1.79 Re^-0.19): n = 2.81/0.55 = 5.11
    (printed as 5.1), K = k2 k3 / k1^n with k1 = 0.36 (λ/d_e)(ρ d_e/μ)^0.55 Pr^1/3,
    k2 = 0.895 (ρ/d_e)(ρ d_e/μ)^-0.19, k3 = 4 P_t (P_t - d_o) / (π² d_o V) (1990, Eqs A2.1-A2.13).
  The 1991 paper replaces Kern by a Bell-Delaware fit whose constant is not published; it is not used.
* Area contribution of stream j (Bath formula split by stream, 1990 Eq. 2; 1991 Eq. 4), with its fouling
  resistance: A_j = Σ_k q_j,k (1/h_j + R_f,j) / ΔT_LM,k.
* Contact (wetted) area of stream j (1990 Eq. 13; 1991 Eq. 5): A_c,j = A_j + Σ_k (CP_k / Σ CP) A_k over the
  opposing streams k.
* Solve together: h_j = (ΔP_j / (K_j A_c,j))^(1/n_j), by fixed-point iteration.
* Usable pressure drop: 1991 (p. 448) advises keeping about 10 % of the allowable drop for nozzles and
  headers; ``usable_fraction`` (default 0.9).

Validation (tests/test_pressure_drop.py): the tube-side constant against a direct calculation from tube
geometry (velocity, Dittus-Boelter, Fanning); a fixed point built from known h is returned unchanged; the
area at the converged h equals the Bath area target with those h. The Sagli problem with Polley and
Panjeh Shahi's Table 3 properties is computed in ``scripts/benchmarks/benchmark_hen.py`` and compared with their detailed
designs (Tables 4-5), as a comparison, not a reproduction: their designs are Bell-Delaware shells.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from pinch.area import area_target
from pinch.streams import StreamSet

TUBE_EXPONENT = 3.5               # Polley et al. (1990), Eq. A1.13
SHELL_EXPONENT = 2.81 / 0.55      # Polley et al. (1990), Eq. A2.13 (printed 5.1)


@dataclass(frozen=True)
class Fluid:
    """Physical properties (SI): density [kg/m³], viscosity [Pa s], conductivity [W/m K], cp [J/kg K]."""

    rho: float
    mu: float
    k: float
    cp: float

    @property
    def Pr(self) -> float:
        return self.cp * self.mu / self.k


def tube_side_K(f: Fluid, d_i_m: float, V_m3_s: float) -> float:
    """K in ΔP [Pa] = K A [m²] h^3.5 [W/m²K], turbulent flow in tubes (Polley et al. 1990, App. 1)."""
    k1 = 0.023 * (f.k / d_i_m) * (f.rho * d_i_m / f.mu) ** 0.8 * f.Pr ** (1 / 3)
    k2 = 0.092 * (f.rho / d_i_m) * (f.rho * d_i_m / f.mu) ** -0.2
    k3 = d_i_m / (4 * V_m3_s)
    return k2 * k3 / k1 ** TUBE_EXPONENT


def shell_side_K(f: Fluid, d_e_m: float, d_o_m: float, pitch_m: float, V_m3_s: float) -> float:
    """K in ΔP = K A h^5.11, Kern correlations, 25 % baffle cut (Polley et al. 1990, App. 2)."""
    k1 = 0.36 * (f.k / d_e_m) * (f.rho * d_e_m / f.mu) ** 0.55 * f.Pr ** (1 / 3)
    k2 = 0.5 * 1.79 * (f.rho / d_e_m) * (f.rho * d_e_m / f.mu) ** -0.19
    k3 = 4 * pitch_m * (pitch_m - d_o_m) / (math.pi ** 2 * d_o_m * V_m3_s)
    return k2 * k3 / k1 ** SHELL_EXPONENT


@dataclass(frozen=True)
class PressureDropResult:
    h: dict[str, float]                  # film coefficients [W/m²K]
    contact_area_m2: dict[str, float]
    area_m2: float                       # network area target with these h (Bath formula, fouling included)
    iterations: int


def coefficients_from_pressure_drop(streams: StreamSet, dP_Pa: dict[str, float], K: dict[str, float],
                                    n: dict[str, float], Rf_m2K_W: dict[str, float] | None = None,
                                    usable_fraction: float = 0.9, h_start: float = 1000.0, tol: float = 1e-8,
                                    max_iter: int = 500, energy_to_W: float = 1000.0) -> PressureDropResult:
    """Film coefficients that spend each stream's usable pressure drop (Polley and Panjeh Shahi 1991, Fig. 4).

    ``streams`` are the streams of the area target (process streams for heat recovery; add utility streams
    and keep the set balanced to include utilities). Heat loads are converted to W with ``energy_to_W``
    (1000 for kW). ``K`` and ``n`` per stream from ``tube_side_K``/``shell_side_K`` and their exponents.
    """
    if not 0 < usable_fraction <= 1:
        raise ValueError("usable_fraction must be in (0, 1]")
    Rf = Rf_m2K_W or {}
    names = [s.name for s in streams.streams]
    for d, what in ((dP_Pa, "dP_Pa"), (K, "K"), (n, "n")):
        miss = [x for x in names if x not in d]
        if miss:
            raise ValueError(f"{what} missing for {miss}")
    kind = {s.name: s.kind for s in streams.streams}
    CP = {s.name: s.CP for s in streams.streams}
    h = {x: h_start for x in names}
    contact: dict[str, float] = {}
    it = 0
    for it in range(1, max_iter + 1):  # noqa: B007 (the count is returned)
        # effective coefficient including fouling: 1/h_eff = 1/h + Rf; area_target takes energy units / m²K
        h_eff = {x: 1.0 / (1.0 / h[x] + Rf.get(x, 0.0)) / energy_to_W for x in names}
        A = area_target(streams, h_eff).contributions or {}
        contact = {}
        for j in names:
            opp = [k for k in names if kind[k] != kind[j]]
            tot = sum(CP[k] for k in opp)
            contact[j] = A[j] + sum(CP[k] / tot * A[k] for k in opp) if tot > 0 else A[j]
        new = {j: (usable_fraction * dP_Pa[j] / (K[j] * contact[j])) ** (1.0 / n[j]) if contact[j] > 0 else h[j]
               for j in names}
        done = all(abs(new[j] - h[j]) <= tol * h[j] for j in names)
        h = new
        if done:
            break
    else:
        raise RuntimeError("pressure-drop iteration did not converge")
    h_eff = {x: 1.0 / (1.0 / h[x] + Rf.get(x, 0.0)) / energy_to_W for x in names}
    return PressureDropResult(h=h, contact_area_m2=contact, area_m2=area_target(streams, h_eff).area, iterations=it)


def with_dT(streams: StreamSet, dTmin_K: float) -> StreamSet:
    """Copy with every stream contributing dTmin/2 (helper for the benchmarks)."""
    return replace(streams, streams=tuple(replace(s, dT_shift_K=dTmin_K / 2) for s in streams.streams))
