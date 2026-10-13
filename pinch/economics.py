"""Techno-economic evaluation of heat recovery and heat pump options (workflow step 6).

Model
-----
For each option, compared with a baseline that supplies heat from a gas boiler:

* Gas fuel        F = Q_gas / eta_boiler                         [MWh/year]
* Electricity     E = W (heat pumps, MVR, electric boilers)      [MWh/year]
* Operating cost  OPEX = F p_gas + E p_el + F EF_gas p_CO2       [EUR/year]
  (the CO2 price is applied to gas combustion only; electricity prices
  already include the power sector's carbon cost)
* Savings         S = OPEX_baseline - OPEX_option                [EUR/year]
* Investment      CAPEX = sum of C = beta + alpha X^gamma  (Padullés et al., 2026, Eq. 2)
* Simple payback  PBP = CAPEX / S                                [years]
* Net present value NPV_N = -CAPEX + S (1 - (1 + i)^-N) / i
* CO2             F EF_gas + E EF_grid                           [t/year]
* Primary energy  F PEF_gas + E PEF_el                           [MWh/year]

Equipment capacity in kW is the delivered heat divided by the operating hours,
as in Padullés et al. (2026, Sec. 5.1: constant operation, 8000 h/year).

Default parameters and their sources are in ``DEFAULTS``; a case file can
override any of them in its "economics" block.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

#: Cost functions C = beta + alpha * X**gamma [EUR]. Source: Padullés et al. (2026),
#: Table 3, taken from the Danish Energy Agency Technology Catalogue.
DEFAULT_COST_FUNCTIONS = {
    "hr_tank": {"alpha": 7450.0, "beta": 0.0, "gamma": 0.65, "size_unit": "m3"},
    "heat_pump": {"alpha": 600.0, "beta": 520_000.0, "gamma": 1.0, "size_unit": "kW"},
    "mvr": {"alpha": 350.0, "beta": 280_000.0, "gamma": 1.0, "size_unit": "kW"},
    "electric_boiler": {"alpha": 210.0, "beta": 110_000.0, "gamma": 1.0, "size_unit": "kW"},
    # an item whose size is its cost (e.g. the cost difference of an enlarged tank, computed elsewhere)
    "lump_sum_EUR": {"alpha": 1.0, "beta": 0.0, "gamma": 1.0, "size_unit": "EUR"},
}

#: Default economic parameters with provenance. "published" = stated in a cited
#: source; "bound" = a deliberate limiting value, not an estimate.
DEFAULTS = {
    "gas_price_EUR_per_kWh": (0.06, "published: Padullés et al. (2026), Sec. 5.1 base price"),
    "electricity_to_gas_ratio": (2.0, "published: Padullés et al. (2026), Sec. 5.2, 'current European ratios of around 2'"),
    "boiler_efficiency": (0.845, "Danish Energy Agency, Technology Data - Industrial Process Heat, sheet 6.1 'Boiler, gas and oil' (2025): total efficiency, net, annual average 93.9 % (range 91.9-94.9 %), steam boiler with economiser; converted to the gross (GCV) basis of Eurostat gas prices with NCV/GCV = 0.90: 0.939 x 0.90 = 0.845. Earlier default 0.817 (US DOE Steam Tip Sheet #15, HHV) kept as sensitivity"),
    "operating_hours_per_year": (8000.0, "published: Padullés et al. (2026), Sec. 5.1"),
    "discount_rate": (0.05, "published: Padullés et al. (2026), Sec. 5.2"),
    "horizon_years": (10, "published: Padullés et al. (2026), Sec. 5.2 (NPV10)"),
    "payback_threshold_years": (5.0, "research question 1 (industry practice 3-5 years: Cooremans, cited in Padullés et al. 2026)"),
    "gas_EF_kg_per_kWh": (0.182, "IPCC 2006 Guidelines, Vol. 2, Ch. 2, Table 2.2: natural gas, stationary combustion, 56,100 kg CO2/TJ (NCV) = 0.202 kg/kWh NCV = 0.182 kg/kWh GCV (NCV/GCV = 0.90), direct combustion only, matching the scope of production-based grid factors. Padullés et al. (2026, Sec. 5.3) use 0.219 (scope not stated); report it as a sensitivity"),
    "grid_EF_kg_per_kWh": (0.107, "APA, 'Fator de Emissão da Eletricidade - 2025', Table T1: Portugal 2023, 0.107 t CO2eq/MWh (annual, production-based, direct emissions). Sensitivities: mainland 2023 0.092; 5-year moving average 0.167 (Table T2); Electricity Maps 2025 flow-traced 0.1172"),
    "co2_price_EUR_per_t": (0.0, "0 by default (site may be outside the EU ETS); sensitivity uses the EUA price"),
    "pef_electricity": (1.9, "published: Commission Delegated Regulation (EU) 2023/807 (EED default)"),
    "pef_gas": (1.0, "convention: primary energy of a fuel = its final energy"),
    "refrigeration_credit_fraction": (1.0, "share of the refrigeration that the heat pump sources can take over that is actually credited (1 = all, continuous operation as in Padullés et al. 2026 Sec. 5.1; lower values represent batch mismatch between heat pump and cooling loads)"),
    "chiller_cop": (None, "no refrigeration credit unless set (Padullés et al. 2026 do not count it). Sinnott and Towler (2020), Sec. 6.4.4: real COP about 0.6 x Carnot for a simple cycle (up to 0.9 for complex cycles)"),
}


@dataclass(frozen=True)
class CostFunction:
    """C = beta + alpha * X**gamma, zero when X = 0."""

    alpha: float
    beta: float
    gamma: float
    size_unit: str = ""

    def cost(self, size: float) -> float:
        if size < 0:
            raise ValueError("equipment size must be >= 0")
        return 0.0 if size == 0 else self.beta + self.alpha * size ** self.gamma


@dataclass(frozen=True)
class EconomicParameters:
    """Prices, efficiencies and financial parameters (see ``DEFAULTS``)."""

    gas_price_EUR_per_kWh: float
    electricity_price_EUR_per_kWh: float
    boiler_efficiency: float
    operating_hours_per_year: float
    discount_rate: float
    horizon_years: int
    payback_threshold_years: float
    gas_EF_kg_per_kWh: float
    grid_EF_kg_per_kWh: float
    co2_price_EUR_per_t: float
    pef_electricity: float
    pef_gas: float
    cost_functions: dict[str, CostFunction] = field(default_factory=dict)
    chiller_cop: float | None = None   # refrigeration COP; None = no credit for avoided chiller electricity
    refrigeration_credit_fraction: float = 1.0

    def __post_init__(self) -> None:
        if not 0 < self.boiler_efficiency <= 1.1:
            raise ValueError("boiler_efficiency must be in (0, 1.1] (LHV basis allows condensing > 1)")
        if self.discount_rate < 0 or self.horizon_years < 1:
            raise ValueError("discount_rate >= 0 and horizon_years >= 1 required")
        if self.gas_price_EUR_per_kWh <= 0 or self.electricity_price_EUR_per_kWh <= 0:
            raise ValueError("energy prices must be positive")
        if not 0.0 <= self.refrigeration_credit_fraction <= 1.0:
            raise ValueError("refrigeration_credit_fraction must be in [0, 1]")
        if self.chiller_cop is not None and self.chiller_cop <= 0:
            raise ValueError("chiller_cop must be positive (or None)")

    @property
    def price_ratio(self) -> float:
        """Electricity-to-gas price ratio [-]."""
        return self.electricity_price_EUR_per_kWh / self.gas_price_EUR_per_kWh

    def with_ratio(self, ratio: float) -> "EconomicParameters":
        """Copy with the electricity price set to ratio * gas price."""
        return replace(self, electricity_price_EUR_per_kWh=ratio * self.gas_price_EUR_per_kWh)

    @property
    def annuity_factor(self) -> float:
        i, n = self.discount_rate, self.horizon_years
        return float(n) if i == 0 else (1 - (1 + i) ** -n) / i


def load_economics(block: dict | None) -> EconomicParameters:
    """Build parameters from a case-file "economics" block, filling in ``DEFAULTS``.

    The electricity price is either given directly (``electricity_price_EUR_per_kWh``)
    or through ``electricity_to_gas_ratio``.
    """
    block = dict(block or {})
    values = {k: block.get(k, v[0]) for k, v in DEFAULTS.items()}
    if "electricity_price_EUR_per_kWh" in block:
        p_el = float(block["electricity_price_EUR_per_kWh"])
    else:
        p_el = float(values["electricity_to_gas_ratio"]) * float(values["gas_price_EUR_per_kWh"])
    given = block.get("cost_functions", {})
    costs = {k: CostFunction(**{**DEFAULT_COST_FUNCTIONS.get(k, {}), **{x: y for x, y in given.get(k, {}).items()
                                                                     if not x.startswith("_") and x != "source"}})
             for k in {**DEFAULT_COST_FUNCTIONS, **given}}
    return EconomicParameters(
        gas_price_EUR_per_kWh=float(values["gas_price_EUR_per_kWh"]),
        electricity_price_EUR_per_kWh=p_el,
        boiler_efficiency=float(values["boiler_efficiency"]),
        operating_hours_per_year=float(values["operating_hours_per_year"]),
        discount_rate=float(values["discount_rate"]),
        horizon_years=int(values["horizon_years"]),
        payback_threshold_years=float(values["payback_threshold_years"]),
        gas_EF_kg_per_kWh=float(values["gas_EF_kg_per_kWh"]),
        grid_EF_kg_per_kWh=float(values["grid_EF_kg_per_kWh"]),
        co2_price_EUR_per_t=float(values["co2_price_EUR_per_t"]),
        pef_electricity=float(values["pef_electricity"]),
        pef_gas=float(values["pef_gas"]),
        cost_functions=costs,
        chiller_cop=None if values["chiller_cop"] is None else float(values["chiller_cop"]),
        refrigeration_credit_fraction=float(values["refrigeration_credit_fraction"]),
    )


@dataclass(frozen=True)
class Option:
    """An energy-supply option, with annual quantities in MWh/year.

    Attributes
    ----------
    name : str
    gas_heat_MWh : float
        Heat still supplied by the gas boiler (before boiler efficiency).
    electricity_MWh : float
        Electricity for heat pumps, MVR and electric boilers.
    equipment : tuple of (kind, size)
        Investment items; kind is a key of the cost functions (e.g. "heat_pump"),
        size in the cost function's unit (kW, m3).
    """

    name: str
    gas_heat_MWh: float
    electricity_MWh: float
    equipment: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class Evaluation:
    """Economic and environmental results of an option against a baseline."""

    option: str
    capex_EUR: float
    opex_EUR: float
    savings_EUR: float
    payback_years: float
    npv_EUR: float
    gas_fuel_MWh: float
    electricity_MWh: float
    co2_t: float
    co2_avoided_t: float
    primary_energy_MWh: float
    primary_energy_reduction: float
    gas_reduction: float

    def as_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) and math.isfinite(v) else v)
                for k, v in self.__dict__.items()}


def capex(option: Option, params: EconomicParameters) -> float:
    """Total investment [EUR] from the cost functions."""
    total = 0.0
    for kind, size in option.equipment:
        if kind not in params.cost_functions:
            raise ValueError(f"no cost function for '{kind}'")
        total += params.cost_functions[kind].cost(size)
    return total


def _annual(option: Option, p: EconomicParameters) -> tuple[float, float, float, float]:
    """(gas fuel MWh, OPEX EUR, CO2 t, primary energy MWh) per year."""
    fuel = option.gas_heat_MWh / p.boiler_efficiency
    co2_gas_t = fuel * p.gas_EF_kg_per_kWh  # MWh x kg/kWh = t
    opex = (fuel * p.gas_price_EUR_per_kWh + option.electricity_MWh * p.electricity_price_EUR_per_kWh) * 1000 \
        + co2_gas_t * p.co2_price_EUR_per_t
    co2 = co2_gas_t + option.electricity_MWh * p.grid_EF_kg_per_kWh
    pe = fuel * p.pef_gas + option.electricity_MWh * p.pef_electricity
    return fuel, opex, co2, pe


def evaluate(option: Option, baseline: Option, params: EconomicParameters) -> Evaluation:
    """Compare an option with the baseline."""
    fuel_b, opex_b, co2_b, pe_b = _annual(baseline, params)
    fuel, opex, co2, pe = _annual(option, params)
    invest = capex(option, params) - capex(baseline, params)
    savings = opex_b - opex
    pbp = invest / savings if savings > 0 else math.inf
    if invest <= 0 and savings > 0:
        pbp = 0.0
    if invest == 0 and savings == 0:
        pbp = math.nan  # nothing invested, nothing saved: payback undefined
    return Evaluation(
        option=option.name,
        capex_EUR=invest,
        opex_EUR=opex,
        savings_EUR=savings,
        payback_years=pbp,
        npv_EUR=-invest + savings * params.annuity_factor,
        gas_fuel_MWh=fuel,
        electricity_MWh=option.electricity_MWh,
        co2_t=co2,
        co2_avoided_t=co2_b - co2,
        primary_energy_MWh=pe,
        primary_energy_reduction=1 - pe / pe_b if pe_b > 0 else math.nan,
        gas_reduction=1 - fuel / fuel_b if fuel_b > 0 else math.nan,
    )


def break_even_ratio(option: Option, baseline: Option, params: EconomicParameters,
                     criterion: str = "npv") -> float:
    """Electricity-to-gas price ratio at which the option just pays off.

    criterion "npv": NPV over the horizon = 0; "payback": payback = threshold.
    Savings are linear in the electricity price, so the ratio has a closed form.
    Returns -inf if the option never pays off, +inf if it pays off at any ratio.
    A negative finite value means the option does not pay off at any positive ratio.
    """
    invest = capex(option, params) - capex(baseline, params)
    required = invest / (params.annuity_factor if criterion == "npv" else params.payback_threshold_years)
    fuel_b, _, _, _ = _annual(baseline, params)
    fuel, _, _, _ = _annual(option, params)
    p_gas = params.gas_price_EUR_per_kWh
    # savings(r) = A - r * B: A from gas and CO2 terms, B from the electricity difference
    A = (fuel_b - fuel) * p_gas * 1000 + (fuel_b - fuel) * params.gas_EF_kg_per_kWh * params.co2_price_EUR_per_t
    B = (option.electricity_MWh - baseline.electricity_MWh) * p_gas * 1000
    if B <= 0:
        return math.inf if A - required >= 0 else -math.inf
    return (A - required) / B


def capacity_kW(heat_MWh_per_year: float, params: EconomicParameters) -> float:
    """Equipment capacity [kW] for constant operation over the operating hours."""
    return heat_MWh_per_year * 1000 / params.operating_hours_per_year
