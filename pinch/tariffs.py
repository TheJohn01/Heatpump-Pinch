"""Hourly electricity prices and the effective price a heat pump pays (workflow step 6, RQ3).

The economics use one flat electricity price. A heat pump that runs only part of the day, or that can
shift its operation with storage, pays a different average: the price weighted by its own operating
hours. This module computes that effective price from an hourly price series and an operating pattern,
plus optional per-period network adders and a demand (capacity) charge, so RQ3 (break-even
electricity-to-gas price ratio) can be compared with the ratio the plant would actually see.

Data: hourly day-ahead prices in data/prices/ (Portugal, Spain, Germany 2025, Ember's CC BY 4.0 copy of the
ENTSO-E series, ``scripts/data/fetch_ember_prices.py``; other zones and years with an ENTSO-E key through
``scripts/data/fetch_entsoe_prices.py``). Published network tariffs with their time-of-use calendars in
data/sources/network_tariffs/ (``PeriodTariff``: ERSE 2026 MT, CNMC 2026 6.1TD, one German operator's 2026
medium-voltage charges); a simple per-hour adder and demand charge (``NetworkTariff``) for user inputs.
``delivered_price`` turns a case's flat band price into the price for a given operating pattern, with Eurostat's
shares of energy and supply, network and other components (``scripts/data/fetch_eurostat_prices.py``).

Operating patterns:
* ``fixed``: the heat pump runs in the given hours of the day (and days of the week), at constant load;
* ``cheapest``: the heat pump runs the N cheapest hours of each day (needs storage that covers the
  shift; the storage itself is sized in ``pinch.time_slices``).

effective price [€/kWh] = Σ_t (p_t + adder_t) / N_hours / 1000  (prices in €/MWh)
                        + demand charge [€/kW/year] / operating hours per year  (constant load)
"""

from __future__ import annotations

import functools
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
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

    def adders_EUR_per_MWh(self, index: pd.DatetimeIndex, timezone: str) -> np.ndarray:
        return self.adder(index.tz_convert(timezone).hour).to_numpy()

    def capacity_EUR(self, load_kW: pd.Series) -> float:
        return self.demand_charge_EUR_per_kW_year * float(load_kW.max()) * len(load_kW) / 8760.0


#: Published network tariffs (pinch.tariffs.PeriodTariff), one JSON file each, sources inside
TARIFF_DIR = Path(__file__).resolve().parents[1] / "data" / "sources" / "network_tariffs"


@dataclass(frozen=True)
class PeriodTariff:
    """A published network tariff with time-of-use periods and capacity charges (``TARIFF_DIR/<key>.json``).

    ``calendar``: rules {"days": weekday|saturday|sunday|all, optional "months", optional "dst" (legal summer
    time)}, each with [start, end, period] clock-time intervals (quarter-hour boundaries allowed); holidays count
    as Sundays. ``capacity`` items, per kW of load and year (or day):
    * "max": the year's peak load (contracted power, Jahreshöchstleistung);
    * "period_mean": the mean load over the hours of one period (ERSE: power in peak hours);
    * "period_max_nondecreasing": the peak load within each period, made non-decreasing from P1 to P6
      (CNMC: contracted power P(n+1) >= P(n)).
    ``variants`` (instead of top-level prices): price sets chosen by the annual utilisation hours
    (energy / peak load), as German network charges below and above 2,500 h/a.
    """

    key: str
    data: dict

    @classmethod
    def load(cls, key: str) -> PeriodTariff:
        path = TARIFF_DIR / f"{key}.json"
        if not path.exists():
            raise ValueError(f"no network tariff '{key}' in {TARIFF_DIR.name}: "
                             + ", ".join(p.stem for p in sorted(TARIFF_DIR.glob('*.json'))))
        return cls(key, json.loads(path.read_text(encoding="utf-8")))

    @property
    def timezone(self) -> str:
        return self.data["timezone"]

    def period_fractions(self, index: pd.DatetimeIndex) -> pd.DataFrame:
        """Share of each hour of ``index`` (UTC, hourly) in each period, from the quarter hours."""
        quarters = pd.DatetimeIndex([t + pd.Timedelta(minutes=15 * q) for t in index for q in range(4)])
        local = quarters.tz_convert(self.timezone)
        holidays = {d for ds in self.data.get("holidays", {}).values() for d in ds}
        day = np.where(local.strftime("%Y-%m-%d").isin(holidays) | (local.weekday == 6), "sunday",
                       np.where(local.weekday == 5, "saturday", "weekday"))
        dst = np.array([bool(t.dst()) for t in local])
        minute = local.hour * 60 + local.minute
        period = np.full(len(local), "", dtype=object)
        for rule in self.data["calendar"]:
            sel = (day == rule["days"]) | (rule["days"] == "all")
            if "months" in rule:
                sel &= np.isin(local.month, rule["months"])
            if "dst" in rule:
                sel &= dst == rule["dst"]
            for start, end, name in rule["periods"]:
                a, b = (int(x[:2]) * 60 + int(x[3:]) for x in (start, end))
                period[sel & (minute >= a) & (minute < b) & (period == "")] = name
        if (period == "").any():
            raise ValueError(f"{self.key}: calendar leaves {int((period == '').sum())} quarter hours without a period")
        q = pd.get_dummies(pd.Series(period)).astype(float)
        return q.groupby(np.repeat(np.arange(len(index)), 4)).mean().set_axis(index)

    def _prices(self, load_kW: pd.Series) -> dict:
        if "variants" not in self.data:
            return self.data
        hours = float(load_kW.sum()) / float(load_kW.max()) * 8760.0 / len(load_kW)
        return next(v for v in self.data["variants"] if v["utilization_h"][0] <= hours < v["utilization_h"][1])

    def adders_EUR_per_MWh(self, index: pd.DatetimeIndex, load_kW: pd.Series) -> np.ndarray:
        f = self.period_fractions(index)
        prices = self._prices(load_kW)["energy_EUR_per_kWh"]
        return (f * pd.Series({p: prices[p] for p in f.columns})).sum(axis=1).to_numpy() * 1000.0

    def capacity_EUR(self, load_kW: pd.Series) -> float:
        """Capacity charges of the load profile over the length of the series [EUR]."""
        years = len(load_kW) / 8760.0
        f = self.period_fractions(load_kW.index)
        total, running_max = 0.0, 0.0
        for c in self._prices(load_kW)["capacity"]:
            rate = c["EUR_per_kW_year"] if "EUR_per_kW_year" in c else c["EUR_per_kW_day"] * 365.0
            if c["basis"] == "max":
                kw = float(load_kW.max())
            elif c["basis"] == "period_mean":
                w = f[c["period"]] if c["period"] in f else pd.Series(0.0, index=f.index)
                kw = float((load_kW * w).sum() / w.sum()) if w.sum() else 0.0
            elif c["basis"] == "period_max_nondecreasing":
                in_p = f[c["period"]] > 0 if c["period"] in f else pd.Series(False, index=f.index)
                running_max = max(running_max, float(load_kW[in_p].max()) if in_p.any() else 0.0)
                kw = running_max
            else:
                raise ValueError(f"{self.key}: unknown capacity basis {c['basis']!r}")
            total += rate * kw * years
        return total


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
                    tariff: NetworkTariff | PeriodTariff | None = None) -> EffectivePrice:
    """Price a constant-load heat pump pays over its operating hours (prices in €/MWh, hourly).

    Capacity (demand) charges are those of the heat pump's own load profile (1 kW when running), spread over
    its energy, so a partial year gives the same per-kWh share.
    """
    if (pd.Series(prices.index).diff().dropna() != pd.Timedelta(hours=1)).any():
        raise ValueError("prices must be hourly and gap-free (use to_hourly first)")
    if len(prices) < 24:
        raise ValueError("need at least one day of prices")
    tariff = tariff or NetworkTariff()
    mask = operating_mask(prices, pattern)
    if not mask.any():
        raise ValueError("the operating pattern selects no hours")
    load = mask.astype(float).set_axis(prices.index)
    adders = (tariff.adders_EUR_per_MWh(prices.index, pattern.timezone) if isinstance(tariff, NetworkTariff)
              else tariff.adders_EUR_per_MWh(prices.index, load))
    on = mask.to_numpy()
    energy = float((prices.to_numpy()[on] + adders[on]).mean()) / 1000.0
    hours_per_year = float(on.sum()) / (len(prices) / 8760.0)
    demand = tariff.capacity_EUR(load) / float(on.sum())
    return EffectivePrice(energy, demand, hours_per_year, float(prices.mean()) / 1000.0)


def access_tariff_change(year: int, voltage: str, path: Path | None = None) -> tuple[float, str]:
    """(change as a fraction, status) of the ERSE network access tariffs for a year and voltage code
    (MAT, AT, MT, BTE, BTN), from data/sources/erse_access_tariff_changes.csv."""
    path = path or Path(__file__).resolve().parents[1] / "data" / "sources" / "erse_access_tariff_changes.csv"
    df = pd.read_csv(path, comment="#")
    row = df[(df["year"] == year) & (df["code"] == voltage)]
    if row.empty:
        raise ValueError(f"no ERSE access tariff change for {year} {voltage} in {path.name}")
    return float(row["change_pct"].iloc[0]) / 100, str(row["status"].iloc[0])


def with_network_change(price_EUR_per_kWh: float, network_share: float, change: float) -> float:
    """Delivered price after the network-cost part (``network_share`` of the price, 0-1) changes by ``change``
    (fraction, e.g. -0.135). Energy, supply and taxes are left as they are."""
    if not 0 <= network_share <= 1:
        raise ValueError("network_share must be between 0 and 1")
    return price_EUR_per_kWh * (1 + network_share * change)


# ----------------------------------------------------------------------------- delivered price for the economics

ROOT = Path(__file__).resolve().parents[1]
EUROSTAT_PRICES = ROOT / "data" / "sources" / "eurostat_prices.csv"
EUROSTAT_COMPONENTS = ROOT / "data" / "sources" / "eurostat_electricity_components.csv"
X_VAT = "Excluding VAT and other recoverable taxes and levies"


def eurostat_shares(geo: str, band: str, year: str | None = None) -> dict:
    """Shares of the price excluding VAT in one band: energy and supply, network, other (taxes and levies that
    are not recoverable), from nrg_pc_205_c (components, on the all-taxes basis) and nrg_pc_205 (prices, the
    year's mean of both half-years). ``band`` e.g. "band ID"; ``year`` defaults to the latest with components."""
    c = pd.read_csv(EUROSTAT_COMPONENTS, comment="#")
    c = c[(c["geo"] == geo) & c["band"].str.endswith(band)]
    year = year or str(c["year"].max())
    comp = c[c["year"].astype(str) == year].set_index("component")["value_EUR_per_kWh"]
    p = pd.read_csv(EUROSTAT_PRICES, comment="#")
    p = p[(p["geo"] == geo) & (p["carrier"] == "electricity") & p["band"].str.endswith(band) & (p["taxes"] == X_VAT)
          & p["period"].str.startswith(year)]
    if comp.empty or len(p) != 2:
        raise ValueError(f"Eurostat: no components and two half-year prices for {geo} {band} {year}")
    total = float(p["value"].mean())
    sup, net = float(comp["NRG_SUP"]), float(comp["NETC"])
    return {"year": year, "price_excl_VAT": total, "energy_supply": sup / total, "network": net / total,
            "other": (total - sup - net) / total}


@functools.lru_cache(maxsize=32)
def _tariff_terms(spec: str) -> dict:
    b = json.loads(spec)
    prices = load_hourly_prices(ROOT / b["prices"])
    tariff = PeriodTariff.load(b["network_tariff"])
    pat = b.get("pattern", {})
    pattern = OperatingPattern(kind=pat.get("kind", "fixed"), hours=frozenset(pat.get("hours", range(24))),
                               weekdays=frozenset(pat.get("weekdays", range(7))),
                               hours_per_day=int(pat.get("hours_per_day", 24)), timezone=tariff.timezone)
    with_tariff = effective_price(prices, pattern, tariff)
    market = effective_price(prices, pattern)
    shares = eurostat_shares(tariff.data["country"], b["band"])
    return {"shape": market.energy_EUR_per_kWh / market.flat_average_EUR_per_kWh,
            "network_EUR_per_kWh": with_tariff.total_EUR_per_kWh - market.energy_EUR_per_kWh,
            "hours_per_year": with_tariff.hours_per_year, **{f"share_{k}": v for k, v in shares.items()}}


def delivered_price(flat_EUR_per_kWh: float, spec: dict) -> tuple[float, dict]:
    """Electricity price a heat pump with the given operating pattern pays, from the case's flat band price.

    p = p_flat (s_supply x shape + s_other) + network, where s_* are Eurostat's shares of the band price
    (``eurostat_shares``), shape = market price weighted over the operating hours / the year's mean, and network =
    the published tariff's energy and capacity charges for the heat pump's own load (``PeriodTariff``), replacing
    Eurostat's average network share. ``spec``: {"prices": hourly CSV (repository-relative), "network_tariff":
    key in TARIFF_DIR, "band": e.g. "band ID", "pattern": {"kind", "hours", "weekdays", "hours_per_day"}}.
    """
    t = _tariff_terms(json.dumps(spec, sort_keys=True))
    price = flat_EUR_per_kWh * (t["share_energy_supply"] * t["shape"] + t["share_other"]) + t["network_EUR_per_kWh"]
    return price, {"flat_EUR_per_kWh": flat_EUR_per_kWh, "delivered_EUR_per_kWh": price, **t}
