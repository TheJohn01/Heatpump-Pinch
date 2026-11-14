"""Heat pump COP from manufacturer and demonstration data, as ranges (step 4; RQ1-RQ3 sensitivity rows).

The design (``pinch.design``) gives each heat pump a COP from the Lorenz model with one efficiency
η_L. Jesper et al. (2021) show on manufacturer data that the second-law efficiency is not constant:
its median over lift classes ranges from 0.25 to 0.49, and a constant value can give a COP up to
twice the real one. This module puts published COP-lift correlations next to the Lorenz basis, per
unit, so that each result can be reported as a range.

Correlations (``FITS``; lift ΔT = sink outlet − source inlet, of the heat carriers, in K):

* ``jesper2021_hthp``: standard and high-temperature heat pumps, HFC/HFO, sink outlet 25-100 °C,
  source inlet −10-60 °C, lift 10-78 K. 425 manufacturer operating points of 29 heat pumps plus 8
  from Arpagaus et al. (2018). Jesper et al. (2021), Renew. Sustain. Energy Rev. 137, 110646,
  Table 6, Eq. 4-6.2 (recommended): COP = a (ΔT + 2b)^c, a = 1.4480e12, b = 88.730, c = −4.9460;
  σ = 0.28, R² = 0.96.
* ``jesper2021_vhthp``: very-high-temperature heat pumps, HCFO/HFC/HFO, sink outlet 80-160 °C, source
  inlet 25-110 °C, lift 25-95 K. Same paper, Table 7, Eq. 4-6.1 (recommended): COP = a (ΔT +
  2 T_dr)^b (T_sink,out + T_dr)^c with T in K, a = 1.9118, b = −0.89094, c = 0.67895,
  T_dr = 0.044189; σ = 0.19, R² = 0.95.
* ``jesper2021_r717``: ammonia heat pumps, sink outlet 70-85 °C, source inlet 0-40 °C, lift 30-75 K.
  Same paper, Table 8, Eq. 4-6.2: a = 40.789, b = 1.0305, c = −1.0489, d = 0.29998; σ = 0.42.
  Only 18 points from five heat pumps; used only when asked for (``fit="jesper2021_r717"``).
* ``arpagaus2026_sghp``: steam-generating heat pumps, COP = 52.94 ΔT^−0.716, R² = 0.8826, from 32
  supplier offers with lifts of about 38-95 K (read from the figure). Arpagaus (2026), Clean Technol.
  Environ. Policy 28:148, Fig. 2; also Bever et al. (2024), Chem. Ing. Tech. 96, 1071-1084, Eq. (2).
  No standard deviation published. Shown as an alternative for sinks above 100 °C.

Which fit: ``jesper2021_hthp`` for a sink outlet up to 100 °C, ``jesper2021_vhthp`` above. The
manufacturer data behind both are for small temperature glides (sink spreads of 5-10 K, as in the
test standard EN 14511), so for a unit that heats a stream through a large glide the fit is a
pessimistic bound: a heat pump built for the glide (several condensers, transcritical CO₂, a
zeotropic blend) does better. Brendel et al. (2024), Int. J. Refrig. 165, 84-96, measured +16 %
for the best blend over the best pure fluid at 35 K glides on source and sink (2.96 against 2.55).
The Lorenz model with the efficiencies achieved by IEA HPT Annex 58 demonstration plants
(``scripts/checks/vendor_data_check.py``) covers glides natively and is the other side of the range.

Temperatures: the model's design temperatures (T*, plus the unit's loop contribution dT_cont_K on
each side, as in ``HeatPump.COP``), the same basis as the Lorenz COP. The resulting COP is used in
the design through an equivalent Lorenz efficiency, η_eq = COP_fit / COP_Lorenz(η = 1), so the
sizing, source allocation and economics are unchanged code paths.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from pinch.heat_pump import lorenz_cop

KELVIN = 273.15
#: Measured COP gain of the best high-glide blend over the best pure fluid (Brendel et al. 2024, abstract and
#: Sec. 4.2: 2.96 vs 2.55 at 35 K glides, sink outlet 100 °C) and the glide from which it applies (their abstract:
#: applications with temperature differences of 25 K or more).
GLIDE_BLEND_GAIN = 0.16
GLIDE_MIN_K = 25.0


@dataclass(frozen=True)
class CopFit:
    """A published COP-lift correlation.

    Attributes
    ----------
    key, label, source : identification.
    formula : callable (lift_K, T_sink_out_C) -> COP [-].
    sigma : standard deviation of the residuals [-] (None if not published).
    lift_K, T_sink_out_C, T_source_in_C : range of the data behind the fit (None = not stated).
    """

    key: str
    label: str
    source: str
    formula: Callable[[float, float], float]
    sigma: float | None
    lift_K: tuple[float, float]
    T_sink_out_C: tuple[float, float] | None
    T_source_in_C: tuple[float, float] | None

    def cop(self, lift_K: float, T_sink_out_C: float) -> float:
        if lift_K <= 0:
            raise ValueError(f"{self.key}: lift must be positive, got {lift_K} K")
        return float(self.formula(lift_K, T_sink_out_C))

    def cop_at(self, p: UnitPoint) -> float:
        return self.cop(p.lift_K, p.T_sink_out_C)

    def in_range(self, lift_K: float, T_sink_out_C: float, T_source_in_C: float) -> bool:
        """True if the operating point lies inside the data range of the fit."""
        def inside(x: float, r: tuple[float, float] | None) -> bool:
            return r is None or r[0] - 1e-9 <= x <= r[1] + 1e-9
        return inside(lift_K, self.lift_K) and inside(T_sink_out_C, self.T_sink_out_C) \
            and inside(T_source_in_C, self.T_source_in_C)


_JESPER = "Jesper et al. (2021), Renew. Sustain. Energy Rev. 137, 110646"
FITS: dict[str, CopFit] = {
    "jesper2021_hthp": CopFit(
        "jesper2021_hthp", "Manufacturer data, HFC/HFO heat pumps (sink ≤ 100 °C)", f"{_JESPER}, Table 6, Eq. 4-6.2",
        lambda L, T: 1.4480e12 * (L + 2 * 88.730) ** -4.9460, 0.28, (10.0, 78.0), (25.0, 100.0), (-10.0, 60.0)),
    "jesper2021_vhthp": CopFit(
        "jesper2021_vhthp", "Manufacturer data, very-high-temperature heat pumps (sink 80-160 °C)",
        f"{_JESPER}, Table 7, Eq. 4-6.1",
        lambda L, T: 1.9118 * (L + 2 * 0.044189) ** -0.89094 * (T + KELVIN + 0.044189) ** 0.67895,
        0.19, (25.0, 95.0), (80.0, 160.0), (25.0, 110.0)),
    "jesper2021_r717": CopFit(
        "jesper2021_r717", "Manufacturer data, ammonia heat pumps (sink 70-85 °C)", f"{_JESPER}, Table 8, Eq. 4-6.2",
        lambda L, T: 40.789 * (L + 2 * 1.0305) ** -1.0489 * (T + KELVIN + 1.0305) ** 0.29998,
        0.42, (30.0, 75.0), (70.0, 85.0), (0.0, 40.0)),
    "arpagaus2026_sghp": CopFit(
        "arpagaus2026_sghp", "Supplier offers, steam-generating heat pumps",
        "Arpagaus (2026), Clean Technol. Environ. Policy 28:148, Fig. 2 (32 offers)",
        lambda L, T: 52.94 * L ** -0.716, None, (38.0, 95.0), None, None),
}


def default_fit(T_sink_out_C: float) -> CopFit:
    """Fit for a closed-cycle heat pump by its sink outlet temperature (module docstring)."""
    return FITS["jesper2021_hthp"] if T_sink_out_C <= 100.0 else FITS["jesper2021_vhthp"]


@dataclass(frozen=True)
class UnitPoint:
    """Design temperatures of one heat pump on the COP basis of ``HeatPump.COP`` [°C]."""
    name: str
    T_sink_in_C: float
    T_sink_out_C: float
    T_source_in_C: float
    T_source_out_C: float

    @property
    def lift_K(self) -> float:
        return self.T_sink_out_C - self.T_source_in_C

    @property
    def sink_glide_K(self) -> float:
        return self.T_sink_out_C - self.T_sink_in_C

    def cop_lorenz(self, eta: float) -> float:
        return lorenz_cop(self.T_sink_in_C, self.T_sink_out_C, self.T_source_in_C, self.T_source_out_C, eta)


def level_points(case, streams) -> list[UnitPoint]:
    """Design temperatures of every sink level of ``case`` (``streams``: the shifted stream set of the design)."""
    from pinch.design import resolve_level
    from pinch.problem_table_algorithm import problem_table
    table = problem_table(streams)
    out = []
    for spec in case.sink_levels:
        T_in, T_out = resolve_level(spec, table)
        T_src = case.source_T_C if spec.T_source_C is None else float(spec.T_source_C)
        d = spec.dT_cont_K
        out.append(UnitPoint(spec.name, T_in + d, T_out + d, T_src - d, T_src - d))
    return out


#: Operating points from the supplier sheets of IEA HPT Annex 58 / Project 68 (transcription notes in the file)
SUPPLIER_FILE = Path(__file__).resolve().parent.parent / "data" / "sources" / "annex58_supplier_operating_points.csv"


@functools.lru_cache(maxsize=4)
def supplier_points(path: Path = SUPPLIER_FILE) -> pd.DataFrame:
    """Closed-cycle operating points of the supplier sheets, with their Lorenz efficiency and mean-temperature
    lift. Rows whose source warms up (published inconsistently) are dropped. COP = middle of a published range.
    Cached: do not modify the returned frame."""
    from pinch.heat_pump import thermodynamic_mean_temperature_K as tm
    d = pd.read_csv(path, comment="#").query("cycle == 'closed' and T_source_out_C <= T_source_in_C").copy()
    d["COP"] = (d["COP_min"] + d["COP_max"]) / 2
    d["lift_K"] = d["T_sink_out_C"] - d["T_source_in_C"]
    T_sink = [steam_mean_temperature_K(r.T_sink_in_C, r.T_sink_out_C) if r.sink == "steam"
              else tm(r.T_sink_in_C, r.T_sink_out_C) for r in d.itertuples()]
    T_source = [tm(r.T_source_in_C, r.T_source_out_C) for r in d.itertuples()]
    d["mean_lift_K"] = [a - b for a, b in zip(T_sink, T_source)]
    d["eta_lorenz"] = [r.COP / (a / (a - b)) for r, a, b in zip(d.itertuples(), T_sink, T_source)]
    return d.reset_index(drop=True)


def steam_mean_temperature_K(T_feed_C: float, T_sat_C: float) -> float:
    """Entropic mean temperature [K] of water heated from ``T_feed_C`` and evaporated to saturated steam at
    ``T_sat_C``: Δh / Δs at the saturation pressure (CoolProp, IAPWS-95)."""
    from CoolProp.CoolProp import PropsSI
    T = T_sat_C + KELVIN
    p = PropsSI("P", "T", T, "Q", 1, "Water")
    h1, s1 = PropsSI("H", "T", T, "Q", 1, "Water"), PropsSI("S", "T", T, "Q", 1, "Water")
    if T_feed_C >= T_sat_C - 1e-9:      # latent only
        h0, s0 = PropsSI("H", "T", T, "Q", 0, "Water"), PropsSI("S", "T", T, "Q", 0, "Water")
    else:
        h0, s0 = PropsSI("H", "T", T_feed_C + KELVIN, "P", p, "Water"), PropsSI("S", "T", T_feed_C + KELVIN, "P", p, "Water")
    return (h1 - h0) / (s1 - s0)


def mean_lift_K(T_sink_in_C: float, T_sink_out_C: float, T_source_in_C: float, T_source_out_C: float) -> float:
    """Lift between the entropic mean temperatures of a liquid sink and the source [K] (Annex 58 Task 1, Sec. 1.1)."""
    from pinch.heat_pump import thermodynamic_mean_temperature_K as tm
    return tm(T_sink_in_C, T_sink_out_C) - tm(T_source_in_C, T_source_out_C)


@dataclass(frozen=True)
class SupplierMap:
    """COP of a unit from the published operating points of market products (Annex 58 / Project 68 sheets).

    Per product, its points' Lorenz efficiencies are interpolated linearly in the mean-temperature lift; a
    product counts for a unit only inside the lift and sink-outlet range of its own points (no extrapolation).
    The COP is the median over the products that count. Products with fewer than two distinct lifts never
    count (one point gives no trend)."""

    points: pd.DataFrame
    key: str = "annex58_suppliers"
    label: str = "Market products, supplier operating points (IEA HPT Annex 58 / Project 68)"
    source: str = "IEA HPT Annex 58 / Project 68 supplier technology sheets (data/sources/annex58_supplier_operating_points.csv)"
    sigma: float | None = None

    def product_cops(self, p: UnitPoint) -> dict[str, float]:
        """COP of the unit for every product whose published points cover it."""
        x = mean_lift_K(p.T_sink_in_C, p.T_sink_out_C, p.T_source_in_C, p.T_source_out_C)
        out = {}
        for name, g in self.points.groupby(["supplier", "product"]):
            by_x = g.groupby("mean_lift_K")["eta_lorenz"].mean().sort_index()
            if len(by_x) < 2:
                continue
            if not (by_x.index[0] - 1e-9 <= x <= by_x.index[-1] + 1e-9
                    and g["T_sink_out_C"].min() - 1e-9 <= p.T_sink_out_C <= g["T_sink_out_C"].max() + 1e-9):
                continue
            out[" ".join(name)] = float(np.interp(x, by_x.index, by_x.values)) * p.cop_lorenz(1.0)
        return out

    def cop_at(self, p: UnitPoint) -> float:
        cops = self.product_cops(p)
        if not cops:
            raise ValueError(f"{p.name}: no supplier product has published points covering this unit")
        return float(np.median(list(cops.values())))

    def covered(self, p: UnitPoint) -> list[str]:
        """Products with a published point at least as hot (sink outlet) and at least as large a lift as the unit."""
        hit = self.points[(self.points["T_sink_out_C"] >= p.T_sink_out_C - 1e-9) & (self.points["lift_K"] >= p.lift_K - 1e-9)]
        return sorted({f"{s} {q}" for s, q in zip(hit["supplier"], hit["product"])})


def unit_point(u) -> UnitPoint | None:
    """Design point of a ``HeatPump`` on the basis of ``level_points`` (None for a unit without a source)."""
    if u.T_source_in_C is None or u.T_source_out_C is None:
        return None
    d = u.dT_cont_K
    return UnitPoint(u.name, u.T_sink_in_C + d, u.T_sink_out_C + d, u.T_source_in_C - d, u.T_source_out_C - d)


def market_products(u) -> list[str] | None:
    """Supplier products with a published point reaching the unit's sink outlet at its lift (None: no source)."""
    p = unit_point(u)
    return None if p is None else SupplierMap(supplier_points()).covered(p)


#: Keys accepted by ``fit_by_key`` (and the ``fit`` of the vendor_cop sensitivity)
FIT_KEYS = (*FITS, "annex58_suppliers")


def fit_by_key(key: str) -> CopFit | SupplierMap:
    return SupplierMap(supplier_points()) if key == "annex58_suppliers" else FITS[key]


def vendor_cop(p: UnitPoint, sigma: float = 0.0, fit: CopFit | SupplierMap | None = None, glide_gain: float = 0.0) -> float:
    """COP of one unit from a correlation or the supplier map, shifted by ``sigma`` standard deviations and, for
    a sink glide of ``GLIDE_MIN_K`` or more, raised by ``glide_gain`` (e.g. ``GLIDE_BLEND_GAIN``). Raises if
    the result breaks the second law or drops to 1 or below."""
    fit = fit or default_fit(p.T_sink_out_C)
    if sigma and fit.sigma is None:
        raise ValueError(f"{fit.key}: no published standard deviation")
    cop = fit.cop_at(p) + sigma * (fit.sigma or 0.0)
    if glide_gain and p.sink_glide_K >= GLIDE_MIN_K:
        cop *= 1 + glide_gain
    if cop <= 1.0:
        raise ValueError(f"{p.name}: COP {cop:.2f} from {fit.key} at a {p.lift_K:.0f} K lift is not above 1")
    if cop > p.cop_lorenz(1.0):
        raise ValueError(f"{p.name}: COP {cop:.2f} from {fit.key} exceeds the reversible limit "
                         f"{p.cop_lorenz(1.0):.2f} (second law)")
    return cop


def equivalent_eta(p: UnitPoint, cop: float) -> float:
    """Lorenz efficiency that gives ``cop`` at the unit's design temperatures [-]."""
    return cop / p.cop_lorenz(1.0)


def apply_vendor(case, streams, sigma: float = 0.0, glide_gain: float = 0.0, fit: str | None = None):
    """Copy of ``case`` whose sink levels use the correlation's COP (through η_eq), shifted by ``sigma``."""
    eta = {p.name: equivalent_eta(p, vendor_cop(p, sigma, fit_by_key(fit) if fit else None, glide_gain))
           for p in level_points(case, streams)}
    return replace(case, sink_levels=tuple(replace(lv, eta_lorenz=eta[lv.name]) for lv in case.sink_levels))


def cop_ranges(case, streams, demo_eta: tuple[float, float, float] | None = None) -> pd.DataFrame:
    """One row per sink level: COP of the case basis, of the manufacturer-data fit (±σ, extrapolation
    flag), of a glide-matched blend, of the steam-generating fit (sink above 100 °C) and, if
    ``demo_eta`` = (min, median, max) is given, of the Lorenz model with the demonstration efficiencies."""
    rows = []
    smap = SupplierMap(supplier_points())
    for spec, p in zip(case.sink_levels, level_points(case, streams)):
        sup = smap.product_cops(p)
        fit = default_fit(p.T_sink_out_C)
        eta_basis = case.eta_lorenz if spec.eta_lorenz is None else spec.eta_lorenz
        cop_fit = fit.cop(p.lift_K, p.T_sink_out_C)
        row = {"unit": p.name, "T_sink_in_C": round(p.T_sink_in_C, 2), "T_sink_out_C": round(p.T_sink_out_C, 2),
               "T_source_in_C": round(p.T_source_in_C, 2), "lift_K": round(p.lift_K, 2),
               "sink_glide_K": round(p.sink_glide_K, 2),
               "COP_basis": round(p.cop_lorenz(eta_basis), 3), "eta_lorenz_basis": eta_basis,
               "fit": fit.key, "COP_fit": round(cop_fit, 3),
               "COP_fit_minus_sigma": round(cop_fit - (fit.sigma or 0), 3),
               "COP_fit_plus_sigma": round(cop_fit + (fit.sigma or 0), 3),
               "fit_in_range": fit.in_range(p.lift_K, p.T_sink_out_C, p.T_source_in_C),
               "eta_equivalent_fit": round(equivalent_eta(p, cop_fit), 4),
               "COP_glide_blend": round(cop_fit * (1 + GLIDE_BLEND_GAIN), 3) if p.sink_glide_K >= GLIDE_MIN_K
               else math.nan,
               "COP_sghp_fit": round(FITS["arpagaus2026_sghp"].cop(p.lift_K, p.T_sink_out_C), 3)
               if p.T_sink_out_C > 100 else math.nan,
               "suppliers_interpolated": len(sup),
               "COP_suppliers_median": round(float(np.median(list(sup.values()))), 3) if sup else math.nan,
               "COP_suppliers_min": round(min(sup.values()), 3) if sup else math.nan,
               "COP_suppliers_max": round(max(sup.values()), 3) if sup else math.nan,
               "suppliers_reaching_point": len(smap.covered(p))}
        if demo_eta:
            lo, med, hi = demo_eta
            row |= {"COP_demo_eta_min": round(p.cop_lorenz(lo), 3), "COP_demo_eta_median": round(p.cop_lorenz(med), 3),
                    "COP_demo_eta_max": round(p.cop_lorenz(hi), 3)}
        rows.append(row)
    return pd.DataFrame(rows)


#: Data file of the demonstration plants (IEA HPT Annex 58 Task 1; transcription notes in the file)
DEMO_FILE = Path(__file__).resolve().parent.parent / "data" / "sources" / "annex58_demonstration_cases.csv"

COP_RANGES_NOTE = ("COP of each heat pump on four bases: the case's Lorenz efficiency; manufacturer-data fits "
                   "(Jesper et al. 2021) at lift = sink outlet - source inlet, with their standard deviation; a "
                   "glide-matched blend (+16 %, Brendel et al. 2024) for sink glides of 25 K or more; the Lorenz model "
                   "with the efficiencies achieved by IEA HPT Annex 58 closed-cycle demonstration plants "
                   "(min, median, max). The fits come from small-glide machines, so for a large sink glide they are "
                   "a pessimistic bound. fit_in_range = False: the point is outside the data behind the fit.")


def demonstration_eta(path: Path = DEMO_FILE) -> pd.DataFrame:
    """Demonstration plants with their Lorenz COP and achieved Lorenz efficiency (closed cycle = not MVR)."""
    d = pd.read_csv(path, comment="#")
    d["COP_Lorenz"] = [round(lorenz_cop(r.T_sink_in_C, r.T_sink_out_C, r.T_source_in_C, r.T_source_out_C, 1.0), 3)
                       for r in d.itertuples()]
    d["eta_lorenz"] = (d["COP_heating"] / d["COP_Lorenz"]).round(3)
    d["closed_cycle"] = ~d["hp_type"].str.startswith("MVR")
    return d


def demonstration_eta_range(path: Path = DEMO_FILE) -> tuple[float, float, float]:
    """(min, median, max) Lorenz efficiency of the closed-cycle demonstration plants [-]."""
    e = demonstration_eta(path).query("closed_cycle")["eta_lorenz"]
    return float(e.min()), float(e.median()), float(e.max())


def check_against_demonstrations(demo: pd.DataFrame) -> pd.DataFrame:
    """Fit COP against reported COPs of demonstration plants (closed cycles inside a fit's sink range).

    ``demo``: columns T_source_in_C, T_sink_in_C, T_sink_out_C, COP_heating, hp_type (as
    ``data/sources/annex58_demonstration_cases.csv``). Deviation = (reported − fit) / fit.
    """
    rows = []
    for r in demo.itertuples():
        if not str(r.hp_type).startswith("CCHP"):
            continue
        fit = default_fit(r.T_sink_out_C)
        lift = r.T_sink_out_C - r.T_source_in_C
        cop_fit = fit.cop(lift, r.T_sink_out_C)
        rows.append({"no": r.no, "refrigerant": r.refrigerant, "lift_K": lift,
                     "sink_glide_K": r.T_sink_out_C - r.T_sink_in_C, "fit": fit.key,
                     "fit_in_range": fit.in_range(lift, r.T_sink_out_C, r.T_source_in_C),
                     "COP_reported": r.COP_heating, "COP_fit": round(cop_fit, 3),
                     "deviation": round((r.COP_heating - cop_fit) / cop_fit, 3)})
    return pd.DataFrame(rows)
