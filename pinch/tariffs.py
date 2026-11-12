"""Hourly electricity prices and the effective price a heat pump pays (workflow step 6, RQ3).

The economics use one flat electricity price. A heat pump that runs only part of the day, or that can
shift its operation with storage, pays a different average: the price weighted by its own operating
hours. This module computes that effective price from an hourly price series and an operating pattern,
plus optional per-period network adders and a demand (capacity) charge, so RQ3 (break-even
electricity-to-gas price ratio) can be compared with the ratio the plant would actually see.

Data: hourly day-ahead prices from the ENTSO-E Transparency Platform, fetched with entsoe-py
(EnergieID, MIT licence, github.com/EnergieID/entsoe-py) by ``scripts/data/fetch_entsoe_prices.py``
(needs a free ENTSO-E API key). No price data are committed: the series depends on the year and bidding
zone the user chooses. Network access tariffs (in Portugal set by ERSE per time-of-use period) are an
input, not a default: their values are not in the project sources.

Operating patterns:
* ``fixed``: the heat pump runs in the given hours of the day (and days of the week), at constant load;
* ``cheapest``: the heat pump runs the N cheapest hours of each day (needs storage that covers the
  shift; the storage itself is sized in ``pinch.time_slices``).

effective price [€/kWh] = Σ_t (p_t + adder_t) / N_hours / 1000  (prices in €/MWh)
                        + demand charge [€/kW/year] / operating hours per year  (constant load)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


def load_hourly_prices(path: Path) -> pd.Series:
    """Read a price CSV (columns ``timestamp`` with UTC offset, ``price_EUR_per_MWh``); returns a Series.

    Lines starting with '#' are provenance comments (written by the fetch script).
    """
    df = pd.read_csv(path, comment="#")
    if not {"timestamp", "price_EUR_per_MWh"} <= set(df.columns):
        raise ValueError(f"{path}: needs columns 'timestamp' and 'price_EUR_per_MWh'")
    ts = pd.to_datetime(df["timestamp"], utc=True)
    s = pd.Series(df["price_EUR_per_MWh"].to_numpy(dtype=float), index=ts, name="price_EUR_per_MWh")
    if s.index.has_duplicates:
        raise ValueError(f"{path}: duplicate timestamps")
    if s.isna().any():
        raise ValueError(f"{path}: missing prices")
    return to_hourly(s.sort_index())


def to_hourly(prices: pd.Series) -> pd.Series:
    """Hourly mean of a finer series (the European day-ahead market moved to 15-minute products in
    October 2025); an hourly series is returned unchanged. For a constant load the hourly mean is the
    energy-weighted price of that hour."""
    step = pd.Series(prices.index).diff().median()
    if pd.isna(step) or step == pd.Timedelta(hours=1):
        return prices
    if step > pd.Timedelta(hours=1):
        raise ValueError(f"price interval {step} is coarser than hourly")
    return prices.resample("1h").mean().dropna()


@dataclass(frozen=True)
class OperatingPattern:
    """When the heat pump runs. ``hours``: local clock hours 0-23 (fixed pattern); ``weekdays``: 0 = Monday."""

    kind: str = "fixed"                                  # "fixed" or "cheapest"
    hours: frozenset[int] = frozenset(range(24))
    weekdays: frozenset[int] = frozenset(range(7))
    hours_per_day: int = 24                              # for "cheapest"
    timezone: str = "Europe/Lisbon"

    def __post_init__(self) -> None:
        if self.kind not in ("fixed", "cheapest"):
            raise ValueError(f"unknown pattern {self.kind!r}")
        if not self.hours <= set(range(24)) or not self.weekdays <= set(range(7)):
            raise ValueError("hours must be within 0-23 and weekdays within 0-6")
        if not 1 <= self.hours_per_day <= 24:
            raise ValueError("hours_per_day must be within 1-24")


def operating_mask(prices: pd.Series, pattern: OperatingPattern) -> pd.Series:
    """True for every price interval in which the heat pump runs."""
    local = prices.index.tz_convert(pattern.timezone)
    on_day = pd.Series(local.weekday, index=prices.index).isin(pattern.weekdays)
    if pattern.kind == "fixed":
        return on_day & pd.Series(local.hour, index=prices.index).isin(pattern.hours)
    day = pd.Series(local.date, index=prices.index)
    rank = prices.groupby(day.to_numpy()).rank(method="first")
    return on_day & (rank <= pattern.hours_per_day)


@dataclass(frozen=True)
class NetworkTariff:
    """Per-period adders [€/MWh] by local clock hour, and a demand charge [€/kW/year]. All user inputs."""

    adder_EUR_per_MWh_by_hour: dict[int, float] = field(default_factory=dict)
    demand_charge_EUR_per_kW_year: float = 0.0
    source: str = "user input"

    def adder(self, hours: Iterable[int]) -> pd.Series:
        return pd.Series([self.adder_EUR_per_MWh_by_hour.get(h, 0.0) for h in hours], dtype=float)


@dataclass(frozen=True)
class EffectivePrice:
    energy_EUR_per_kWh: float          # weighted market price + adders over the operating hours
    demand_EUR_per_kWh: float          # demand charge spread over the annual consumption
    hours_per_year: float
    flat_average_EUR_per_kWh: float    # plain average over all hours, for comparison

    @property
    def total_EUR_per_kWh(self) -> float:
        return self.energy_EUR_per_kWh + self.demand_EUR_per_kWh


def effective_price(prices: pd.Series, pattern: OperatingPattern,
                    tariff: NetworkTariff | None = None) -> EffectivePrice:
    """Price a constant-load heat pump pays over its operating hours (prices in €/MWh, hourly).

    The demand charge is spread over the operating hours at constant load (peak = running load), and
    annualised to 8760 h from the length of the series, so a partial year gives the same per-kWh share.
    """
    if (pd.Series(prices.index).diff().dropna() != pd.Timedelta(hours=1)).any():
        raise ValueError("prices must be hourly and gap-free (use to_hourly first)")
    if len(prices) < 24:
        raise ValueError("need at least one day of prices")
    tariff = tariff or NetworkTariff()
    mask = operating_mask(prices, pattern)
    if not mask.any():
        raise ValueError("the operating pattern selects no hours")
    local_hours = prices.index.tz_convert(pattern.timezone).hour
    adders = tariff.adder(local_hours).to_numpy()
    on = mask.to_numpy()
    energy = float((prices.to_numpy()[on] + adders[on]).mean()) / 1000.0
    years = len(prices) / 8760.0
    hours_per_year = float(on.sum()) / years
    demand = tariff.demand_charge_EUR_per_kW_year / hours_per_year
    return EffectivePrice(energy, demand, hours_per_year, float(prices.mean()) / 1000.0)
