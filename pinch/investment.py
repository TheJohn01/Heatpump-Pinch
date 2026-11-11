"""Investment-grade additions to the economics (workflow step 6): cash flows, IRR, estimate accuracy,
investment grants and uncertainty.

``pinch.economics`` reports simple payback and NPV of constant savings. A firm deciding on the
investment also asks for the rate of return, the effect of tax and depreciation, how accurate the
capital estimate is, what a grant changes, and how likely the result is under uncertain prices.
This module adds those, each from a named source. It changes no existing result.

Sources
-------
* Towler and Sinnott (2013), *Chemical Engineering Design*, 2nd ed., Ch. 9 "Economic Evaluation of
  Projects" (DOI 10.1016/B978-0-08-096659-5.00009-2): Sec. 9.4 taxes and depreciation, Sec. 9.6 NPV and
  discounted cash-flow rate of return (DCFROR), Sec. 9.8 sensitivity analysis: Table 9.4 (ranges of
  variation), Eqs 9.30-9.31 (three-point mean and standard deviation, after Piekarski 1984), Sec. 9.8.3
  (Monte Carlo simulation; correlated parameters must not be varied independently).
* AACE International Recommended Practice 18R-97 (Rev. 7 August 2020), Table 1: expected accuracy
  ranges of estimate classes 5 to 1 (industry standard, not peer-reviewed).
* Portaria n.º 325-A/2021, Diário da República, 1.ª série, n.º 251, 29 December 2021, Annex I: aid
  intensities of the PRR incentive system "Descarbonização da Indústria".
* Aviso MPR-2026-01 (Portugal 2030, published 26 January 2026): minimum eligible expenditure and the
  exclusion of EU ETS activities.

What is NOT sourced here (inputs the user must supply, no defaults)
-------------------------------------------------------------------
* The corporate tax rate and the tax depreciation period: Portuguese rules for this equipment were not
  found in the sources read. ``cash_flows`` therefore takes them as explicit arguments, default no tax.
* The share of the investment that counts as eligible cost for a grant. State-aid rules define
  eligible cost against a counterfactual investment; ``grant_EUR`` takes the eligible cost as an input.
* The probability distributions of the Monte Carlo analysis. The sources give ranges (low, most likely,
  high), not distributions; a triangular distribution over the range is this module's choice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from pinch.economics import EconomicParameters, Option, evaluate

# ----------------------------------------------------------------------------- cash flows, NPV, IRR


def cash_flows(investment_EUR: float, annual_savings_EUR: float, years: int, *, grant_EUR: float = 0.0,
               tax_rate: float = 0.0, depreciation_years: int | None = None) -> np.ndarray:
    """Cash flow of each year, year 0 first [EUR].

    Year 0: -investment + grant. Years 1..N: savings minus tax, with
    tax = tax_rate x (savings - depreciation) and straight-line depreciation of the investment net of
    the grant over ``depreciation_years`` (Towler and Sinnott 2013, Sec. 9.4: taxable income is gross
    profit less the depreciation allowance).

    Conventions (stated, not from a source): constant savings in real terms; the investment is paid
    in year 0; a negative taxable income lowers the firm's tax elsewhere (the firm is profitable);
    the grant is received in year 0 and reduces the depreciable base.
    """
    if years < 1:
        raise ValueError("years must be >= 1")
    if not 0.0 <= tax_rate < 1.0:
        raise ValueError("tax_rate must be in [0, 1)")
    if grant_EUR < 0 or grant_EUR > investment_EUR:
        raise ValueError("grant must be between 0 and the investment")
    if tax_rate > 0 and (depreciation_years is None or depreciation_years < 1):
        raise ValueError("depreciation_years (>= 1) is required when tax_rate > 0")
    flows = np.full(years + 1, float(annual_savings_EUR))
    flows[0] = -investment_EUR + grant_EUR
    if tax_rate > 0:
        depreciation = np.zeros(years + 1)
        n = min(int(depreciation_years), years)
        depreciation[1:n + 1] = (investment_EUR - grant_EUR) / depreciation_years
        flows[1:] -= tax_rate * (annual_savings_EUR - depreciation[1:])
    return flows


def npv(flows, rate: float) -> float:
    """Net present value of yearly cash flows, year 0 first (Towler and Sinnott 2013, Sec. 9.6)."""
    flows = np.asarray(flows, dtype=float)
    return float(np.sum(flows / (1.0 + rate) ** np.arange(len(flows))))


def irr(flows) -> float:
    """Internal rate of return (DCFROR): the discount rate at which NPV = 0 (Sec. 9.6).

    Returns nan when the cash flows do not change sign (no investment, or savings never repay it
    within the horizon at any rate above -99 %).
    """
    flows = np.asarray(flows, dtype=float)
    if not (flows.min() < 0 < flows.max()):
        return math.nan
    lo, hi = -0.99, 10.0
    if npv(flows, lo) * npv(flows, hi) > 0:
        return math.nan
    return float(brentq(lambda r: npv(flows, r), lo, hi, xtol=1e-10))


def discounted_payback_years(flows, rate: float) -> float:
    """Years until the cumulative discounted cash flow turns positive (linear within the year); inf if never."""
    flows = np.asarray(flows, dtype=float)
    discounted = flows / (1.0 + rate) ** np.arange(len(flows))
    cumulative = np.cumsum(discounted)
    if cumulative[0] >= 0:
        return 0.0
    for t in range(1, len(flows)):
        if cumulative[t] >= 0:
            return t - 1 + (-cumulative[t - 1]) / discounted[t]
    return math.inf


# ----------------------------------------------------------------------------- estimate accuracy

#: AACE RP 18R-97 (Rev. 7 August 2020), Table 1: expected accuracy range of each estimate class, as
#: fractions of the estimate. "low" and "high" are each a band: (widest, narrowest). Ranges are stated
#: at an 80 % confidence interval, after contingency.
AACE_18R97_ACCURACY = {
    5: {"low": (-0.50, -0.20), "high": (1.00, 0.30)},
    4: {"low": (-0.30, -0.15), "high": (0.50, 0.20)},
    3: {"low": (-0.20, -0.10), "high": (0.30, 0.10)},
    2: {"low": (-0.15, -0.05), "high": (0.20, 0.05)},
    1: {"low": (-0.10, -0.03), "high": (0.15, 0.03)},
}


def capex_factors(estimate_class: int, band: str = "widest") -> tuple[float, float]:
    """(low, high) multipliers on a capital estimate of the given AACE class.

    ``band``: "widest" or "narrowest" end of the class's accuracy range (Table 1 gives both).
    Class 5 (concept screening: capacity-factored and parametric cost models) is the class of the cost
    functions in ``pinch.economics``; that classification is this project's, not a statement by AACE.
    """
    if estimate_class not in AACE_18R97_ACCURACY:
        raise ValueError("estimate_class must be 1 to 5")
    if band not in ("widest", "narrowest"):
        raise ValueError("band must be 'widest' or 'narrowest'")
    i = 0 if band == "widest" else 1
    row = AACE_18R97_ACCURACY[estimate_class]
    return 1.0 + row["low"][i], 1.0 + row["high"][i]


# ----------------------------------------------------------------------------- grants (Portugal)

#: Portaria n.º 325-A/2021, Annex I: base aid intensity by category (share of eligible cost).
PRR_BASE_INTENSITY = {"energy_efficiency": 0.30, "environmental_protection": 0.40}
#: Bonus for small and medium enterprises (percentage points as fractions).
PRR_SIZE_BONUS = {"large": 0.0, "medium": 0.10, "small": 0.20}
#: Regional bonus: "a" = Norte, Centro, Alentejo, Açores, Madeira; "c" = other assisted "c" regions.
PRR_REGION_BONUS = {"none": 0.0, "c": 0.05, "a": 0.15}
#: Ceiling per firm and per project [EUR].
PRR_CEILING_EUR = 15e6
#: Aviso MPR-2026-01: minimum eligible expenditure, general regime [EUR].
MPR_2026_01_MIN_ELIGIBLE_EUR = 400e3


def prr_aid_intensity(category: str = "energy_efficiency", firm_size: str = "large", region: str = "none") -> float:
    """Aid intensity (share of eligible cost) under Portaria n.º 325-A/2021, Annex I."""
    try:
        return PRR_BASE_INTENSITY[category] + PRR_SIZE_BONUS[firm_size] + PRR_REGION_BONUS[region]
    except KeyError as exc:
        raise ValueError(f"unknown category, firm size or region: {exc}") from None


def grant_EUR(eligible_cost_EUR: float, intensity: float, ceiling_EUR: float = PRR_CEILING_EUR) -> float:
    """Grant = intensity x eligible cost, limited by the ceiling.

    The eligible cost is an input: it is not the whole investment in general (VAT, fossil-fuel equipment
    and operation and maintenance are excluded; state-aid rules compare with a counterfactual investment).
    """
    if eligible_cost_EUR < 0 or not 0.0 <= intensity <= 1.0:
        raise ValueError("eligible cost must be >= 0 and intensity in [0, 1]")
    return min(intensity * eligible_cost_EUR, ceiling_EUR)


def mpr_2026_01_admissible(eligible_cost_EUR: float, in_eu_ets: bool) -> tuple[bool, str]:
    """Two admissibility conditions of Aviso MPR-2026-01 (general regime) that this tool can check.

    Not a full eligibility test: the notice has further conditions (region, energy audits, timing).
    """
    if in_eu_ets:
        return False, "activities in Annex I of the EU ETS Directive are excluded"
    if eligible_cost_EUR < MPR_2026_01_MIN_ELIGIBLE_EUR:
        return False, f"eligible expenditure below {MPR_2026_01_MIN_ELIGIBLE_EUR:,.0f} EUR"
    return True, "passes the two conditions checked (minimum expenditure, not in the EU ETS)"


# ----------------------------------------------------------------------------- uncertainty

#: Towler and Sinnott (2013), Table 9.4: range of variation usually assumed, as (low, high) multipliers.
TOWLER_TABLE_9_4 = {
    "fuel_cost": (0.50, 2.00),               # -50 % to +100 % of base
    "capital_investment": (0.80, 1.50),      # ISBL and OSBL: -20 % to +50 % of base
    "fixed_costs": (0.80, 2.00),             # -20 % to +100 % of base
    "production_rate": (0.80, 1.20),         # +/- 20 % of base
}


def three_point_mean(low: float, most_likely: float, high: float) -> float:
    """Mean of a three-point estimate: (H + 2 ML + L) / 4 (Towler and Sinnott 2013, Eq. 9.30)."""
    return (high + 2.0 * most_likely + low) / 4.0


def three_point_std(low: float, high: float) -> float:
    """Standard deviation of a three-point estimate: (H - L) / 2.65 (Towler and Sinnott 2013, Eq. 9.31)."""
    return (high - low) / 2.65


@dataclass(frozen=True)
class Range:
    """Low, most likely and high value of an uncertain input (absolute values, not multipliers)."""

    low: float
    most_likely: float
    high: float

    def __post_init__(self) -> None:
        if not self.low <= self.most_likely <= self.high:
            raise ValueError("Range needs low <= most_likely <= high")

    def sample(self, rng: np.random.Generator, n: int) -> np.ndarray:
        """Triangular samples; a zero-width range returns the constant."""
        if self.high == self.low:
            return np.full(n, self.most_likely)
        return rng.triangular(self.low, self.most_likely, self.high, n)


def monte_carlo(option: Option, baseline: Option, params: EconomicParameters, *, capex_factor: Range,
                gas_price_EUR_per_kWh: Range, price_ratio: Range, grant_fraction: float = 0.0,
                n: int = 5000, seed: int = 0) -> pd.DataFrame:
    """Monte Carlo simulation of one option against a baseline (Towler and Sinnott 2013, Sec. 9.8.3).

    Three inputs are sampled independently from triangular distributions:

    * ``capex_factor``: multiplier on the investment (e.g. from ``capex_factors`` or Table 9.4);
    * ``gas_price_EUR_per_kWh``: the gas price;
    * ``price_ratio``: electricity-to-gas price ratio. Electricity is set to ratio x gas, not sampled
      on its own: gas and electricity prices are correlated, and Sec. 9.8.3 warns against varying
      correlated parameters independently.

    Everything else (COP, loads, O&M, operating hours, discount rate) stays at its value in ``params``.
    ``grant_fraction`` is the share of the investment paid by a grant.

    Returns one row per sample: the three inputs, ``savings_EUR``, ``investment_EUR`` (net of grant),
    ``npv_EUR`` and ``payback_years``. Deterministic for a given seed.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if not 0.0 <= grant_fraction < 1.0:
        raise ValueError("grant_fraction must be in [0, 1)")
    rng = np.random.default_rng(seed)
    f = capex_factor.sample(rng, n)
    p_gas = gas_price_EUR_per_kWh.sample(rng, n)
    ratio = price_ratio.sample(rng, n)

    # Savings are linear in the two prices: savings = a + b p_gas + c p_el. Three evaluations fix a, b, c.
    def savings(pg: float, pe: float) -> float:
        return evaluate(option, baseline, replace(params, gas_price_EUR_per_kWh=pg,
                                                  electricity_price_EUR_per_kWh=pe)).savings_EUR
    s11, s21, s12 = savings(1.0, 1.0), savings(2.0, 1.0), savings(1.0, 2.0)
    b, c = s21 - s11, s12 - s11
    a = s11 - b - c
    base_investment = evaluate(option, baseline, params).capex_EUR

    out = pd.DataFrame({"capex_factor": f, "gas_price_EUR_per_kWh": p_gas, "price_ratio": ratio})
    out["savings_EUR"] = a + b * p_gas + c * ratio * p_gas
    out["investment_EUR"] = base_investment * f * (1.0 - grant_fraction)
    out["npv_EUR"] = -out["investment_EUR"] + out["savings_EUR"] * params.annuity_factor
    with np.errstate(divide="ignore", invalid="ignore"):
        payback = out["investment_EUR"] / out["savings_EUR"]
    out["payback_years"] = np.where(out["savings_EUR"] > 0, payback, np.inf)
    return out


def summarise(samples: pd.DataFrame, payback_threshold_years: float) -> dict:
    """Mean, standard deviation and percentiles of NPV, and the probabilities a decision needs."""
    v = samples["npv_EUR"].to_numpy()
    p5, p50, p95 = np.percentile(v, [5, 50, 95])
    return {
        "n": int(len(v)),
        "npv_mean_EUR": float(v.mean()),
        "npv_std_EUR": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
        "npv_p5_EUR": float(p5),
        "npv_p50_EUR": float(p50),
        "npv_p95_EUR": float(p95),
        "prob_npv_positive": float((v > 0).mean()),
        "prob_payback_within_threshold": float((samples["payback_years"] <= payback_threshold_years).mean()),
    }
