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
#: O&M from the Danish Energy Agency, Technology Data - Industrial Process Heat (2025 values): heat pump
#: sheet 2.a (2,494 EUR/MW/y, 3.6 EUR/MWh; both brewery heat pumps deliver <= 125 °C), MVR sheet 4
#: (2,345 EUR/MW/y, 2.1 EUR/MWh), electric boiler sheet 5.1a (1,442 EUR/MW/y, 0.674 EUR/MWh).
#: Padullés et al. (2026) include no O&M: their reproduction scripts set it to zero.
DEFAULT_COST_FUNCTIONS = {
    "hr_tank": {"alpha": 7450.0, "beta": 0.0, "gamma": 0.65, "size_unit": "m3"},
    "heat_pump": {"alpha": 600.0, "beta": 520_000.0, "gamma": 1.0, "size_unit": "kW",
                  "fixed_om_EUR_per_unit_year": 2.494, "variable_om_EUR_per_MWh": 3.6},
    "mvr": {"alpha": 350.0, "beta": 280_000.0, "gamma": 1.0, "size_unit": "kW",
            "fixed_om_EUR_per_unit_year": 2.345, "variable_om_EUR_per_MWh": 2.1},
    "electric_boiler": {"alpha": 210.0, "beta": 110_000.0, "gamma": 1.0, "size_unit": "kW",
                        "fixed_om_EUR_per_unit_year": 1.442, "variable_om_EUR_per_MWh": 0.674},
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
    "boiler_variable_om_EUR_per_MWh": (1.23, "Danish Energy Agency, Technology Data - Industrial Process Heat, sheet 6.1 'Boiler, gas and oil' (2025): variable O&M 1.23 EUR/MWh of heat, avoided with the gas heat it no longer supplies. The fixed O&M (2,000 EUR/MW/y) is not credited: the boiler is kept as back-up"),
    "chiller_cop": (None, "no refrigeration credit unless set (Padullés et al. 2026 do not count it). Sinnott and Towler (2020), Sec. 6.4.4: real COP about 0.6 x Carnot for a simple cycle (up to 0.9 for complex cycles)"),
}


@dataclass(frozen=True)
class CostFunction:
    """C = beta + alpha * X**gamma, zero when X = 0."""

    alpha: float
    beta: float
    gamma: float
    size_unit: str = ""
    #: operation and maintenance: fixed per size unit and year; variable per MWh of heat delivered
    #: (only for sizes in kW, delivered over the operating hours)
    fixed_om_EUR_per_unit_year: float = 0.0
    variable_om_EUR_per_MWh: float = 0.0

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
    boiler_variable_om_EUR_per_MWh: float = 0.0
    #: {heat pump unit name: installed / average capacity}: > 1 for a unit that runs only part of the time
    #: without storage (e.g. a batch duty); the extra capacity is added as investment only
    capacity_factors: dict = field(default_factory=dict)
    #: ((max sink temperature [°C], cost-function kind), ...) in ascending order; empty = one
    #: "heat_pump" cost function for every unit (Padullés et al. 2026, Table 3)
    heat_pump_cost_classes: tuple = ()
    #: ((cost-function kind, base kinds it applies to, min lift [K] or None, isothermal sink only,
    #:   min sink temperature [°C] or None), ...):
    #: add-ons such as the DEA catalogue's "lift above 75 K" and "steam generation" equipment costs
    heat_pump_cost_adders: tuple = ()

    def heat_pump_cost_items(self, unit) -> tuple[tuple[str, ...], bool]:
        """Cost-function kinds for one heat pump unit (base class plus add-ons), and the extrapolation flag.

        ``unit`` needs ``T_sink_in_C``, ``T_sink_out_C`` and ``T_source_out_C``/``T_source_in_C``. Lift is
        sink outlet minus source outlet, the definition of the DEA catalogue (sheet 1.2: 80 °C, 75 K
        from a 15 -> 5 °C source). An isothermal sink (in = out) is taken as steam generation.
        """
        base, extrapolated = self.heat_pump_cost_class(unit.T_sink_out_C)
        T_src = unit.T_source_out_C if unit.T_source_out_C is not None else unit.T_source_in_C
        lift = None if T_src is None else unit.T_sink_out_C - T_src
        isothermal = abs(unit.T_sink_out_C - unit.T_sink_in_C) < 1e-9
        kinds = [base]
        for kind, applies_to, min_lift, iso_only, min_sink in self.heat_pump_cost_adders:
            if base not in applies_to:
                continue
            if min_sink is not None and unit.T_sink_out_C < min_sink:
                continue
            if min_lift is not None and (lift is None or lift <= min_lift):
                continue
            if iso_only and not isothermal:
                continue
            kinds.append(kind)
        return tuple(kinds), extrapolated

    def heat_pump_kind(self, T_sink_out_C: float) -> str:
        """Cost-function kind for a heat pump delivering heat up to ``T_sink_out_C``.

        Above the highest class the last class is used (an extrapolation, reported
        by ``heat_pump_cost_class``).
        """
        return self.heat_pump_cost_class(T_sink_out_C)[0]

    def heat_pump_cost_class(self, T_sink_out_C: float) -> tuple[str, bool]:
        """(cost-function kind, True if the sink is above every class)."""
        if not self.heat_pump_cost_classes:
            return "heat_pump", False
        for T_max, kind in self.heat_pump_cost_classes:
            if T_sink_out_C <= T_max + 1e-9:
                return kind, False
        return self.heat_pump_cost_classes[-1][1], True

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
    classes = tuple(sorted((float(c["max_sink_T_C"]), str(c["cost_function"]))
                           for c in block.get("heat_pump_cost_classes", [])))
    adders = tuple((str(a["cost_function"]), tuple(a["applies_to"]),
                    None if a.get("min_lift_K") is None else float(a["min_lift_K"]), bool(a.get("isothermal_sink")),
                    None if a.get("min_sink_T_C") is None else float(a["min_sink_T_C"]))
                   for a in block.get("heat_pump_cost_adders", []))
    for kind in [k for _, k in classes] + [a[0] for a in adders]:
        if kind not in costs:
            raise ValueError(f"heat pump cost: no cost function '{kind}' in economics.cost_functions")
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
        heat_pump_cost_classes=classes,
        boiler_variable_om_EUR_per_MWh=float(values["boiler_variable_om_EUR_per_MWh"]),
        capacity_factors={str(k): float(v) for k, v in (block.get("heat_pump_capacity_factors") or {}).items()},
        heat_pump_cost_adders=adders,
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


def om(option: Option, p: EconomicParameters) -> float:
    """Operation and maintenance [EUR/year]: equipment (fixed + variable) and the boiler's variable O&M."""
    total = option.gas_heat_MWh * p.boiler_variable_om_EUR_per_MWh
    for kind, size in option.equipment:
        cf = p.cost_functions[kind]
        total += cf.fixed_om_EUR_per_unit_year * size
        if cf.variable_om_EUR_per_MWh:
            if cf.size_unit != "kW":
                raise ValueError(f"{kind}: variable O&M needs a size in kW")
            total += cf.variable_om_EUR_per_MWh * size * p.operating_hours_per_year / 1000
    return total


def _annual(option: Option, p: EconomicParameters) -> tuple[float, float, float, float]:
    """(gas fuel MWh, OPEX EUR, CO2 t, primary energy MWh) per year. OPEX includes O&M (``om``)."""
    fuel = option.gas_heat_MWh / p.boiler_efficiency
    co2_gas_t = fuel * p.gas_EF_kg_per_kWh  # MWh x kg/kWh = t
    opex = (fuel * p.gas_price_EUR_per_kWh + option.electricity_MWh * p.electricity_price_EUR_per_kWh) * 1000 \
        + co2_gas_t * p.co2_price_EUR_per_t + om(option, p)
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
    A = (fuel_b - fuel) * p_gas * 1000 + (fuel_b - fuel) * params.gas_EF_kg_per_kWh * params.co2_price_EUR_per_t \
        + om(baseline, params) - om(option, params)
    B = (option.electricity_MWh - baseline.electricity_MWh) * p_gas * 1000
    if B <= 0:
        return math.inf if A - required >= 0 else -math.inf
    return (A - required) / B


def capacity_kW(heat_MWh_per_year: float, params: EconomicParameters) -> float:
    """Equipment capacity [kW] for constant operation over the operating hours."""
    return heat_MWh_per_year * 1000 / params.operating_hours_per_year


#: Padullés et al. (2026) include no operation and maintenance costs: overrides that reproduce their convention
NO_OM = {"boiler_variable_om_EUR_per_MWh": 0.0,
         "cost_functions": {k: {"fixed_om_EUR_per_unit_year": 0.0, "variable_om_EUR_per_MWh": 0.0}
                            for k in ("heat_pump", "mvr", "electric_boiler")}}


def heat_pump_equipment(params: EconomicParameters, unit, capacity_kW_avg: float) -> list[tuple[str, float]]:
    """Investment items of one heat pump unit: its cost classes at the average capacity, plus, for a unit
    with a capacity factor F > 1 (batch duty without storage), the extra investment of the larger unit
    (cost at F x capacity minus cost at capacity) as a lump sum. O&M stays on the average capacity: the
    variable part follows the heat delivered; the fixed part of the extra capacity (about 2.5 EUR/kW/y)
    is neglected."""
    kinds = params.heat_pump_cost_items(unit)[0]
    items = [(k, capacity_kW_avg) for k in kinds]
    F = params.capacity_factors.get(unit.name, 1.0)
    if F < 1:
        raise ValueError(f"{unit.name}: capacity factor must be >= 1")
    if F > 1 and capacity_kW_avg > 0:
        extra = sum(params.cost_functions[k].cost(capacity_kW_avg * F) - params.cost_functions[k].cost(capacity_kW_avg)
                    for k in kinds)
        items.append(("lump_sum_EUR", extra))
    return items

