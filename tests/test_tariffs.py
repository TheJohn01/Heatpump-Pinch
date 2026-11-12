"""Effective electricity price over a heat pump's operating hours (pinch.tariffs): hand-calculated cases."""

import pandas as pd
import pytest

from pinch.tariffs import (
    NetworkTariff,
    OperatingPattern,
    effective_price,
    load_hourly_prices,
    operating_mask,
    to_hourly,
)

UTC = "UTC"


def _two_days() -> pd.Series:
    """48 h in UTC (= Lisbon time in January): price = clock hour (0..23 €/MWh), second day + 100."""
    idx = pd.date_range("2025-01-06", periods=48, freq="h", tz=UTC)       # Monday and Tuesday
    return pd.Series([h % 24 + (100 if h >= 24 else 0) for h in range(48)], index=idx, dtype=float)


def test_round_the_clock_equals_the_plain_average():
    p = _two_days()
    r = effective_price(p, OperatingPattern())
    assert r.energy_EUR_per_kWh == pytest.approx(p.mean() / 1000) == pytest.approx(r.flat_average_EUR_per_kWh)
    assert r.hours_per_year == pytest.approx(8760)


def test_fixed_daytime_window():
    """Hours 8-15 on both days: mean of 8..15 and 108..115 = 61.5 €/MWh."""
    r = effective_price(_two_days(), OperatingPattern(hours=frozenset(range(8, 16))))
    assert r.energy_EUR_per_kWh == pytest.approx(0.0615)
    assert r.hours_per_year == pytest.approx(8760 / 3)


def test_cheapest_hours_per_day():
    """4 cheapest hours each day: 0..3 and 100..103, mean 51.5 €/MWh."""
    r = effective_price(_two_days(), OperatingPattern(kind="cheapest", hours_per_day=4))
    assert r.energy_EUR_per_kWh == pytest.approx(0.0515)


def test_weekdays_filter():
    """Only Tuesday (weekday 1): mean 111.5 €/MWh."""
    r = effective_price(_two_days(), OperatingPattern(weekdays=frozenset({1})))
    assert r.energy_EUR_per_kWh == pytest.approx(0.1115)


def test_network_adders_and_demand_charge():
    """+10 €/MWh in hours 18-21 only; running 18-21 -> mean (18..21 + 118..121)/8 + 10 = 79.5 €/MWh.
    Demand charge 36.5 €/kW/year over 4 h/day x 365 = 1460 h -> 0.025 €/kWh."""
    t = NetworkTariff({h: 10.0 for h in (18, 19, 20, 21)}, demand_charge_EUR_per_kW_year=36.5)
    r = effective_price(_two_days(), OperatingPattern(hours=frozenset({18, 19, 20, 21})), t)
    assert r.energy_EUR_per_kWh == pytest.approx(0.0795)
    assert r.hours_per_year == pytest.approx(1460)
    assert r.demand_EUR_per_kWh == pytest.approx(0.025)
    assert r.total_EUR_per_kWh == pytest.approx(0.1045)


def test_local_time_is_used_for_clock_hours():
    """In July Lisbon is UTC+1: local hour 8 is 07:00 UTC."""
    idx = pd.date_range("2025-07-07", periods=24, freq="h", tz=UTC)
    p = pd.Series(range(24), index=idx, dtype=float)
    m = operating_mask(p, OperatingPattern(hours=frozenset({8})))
    assert list(p[m].index.hour) == [7]


def test_quarter_hour_prices_are_averaged_to_hours():
    idx = pd.date_range("2025-10-06", periods=96, freq="15min", tz=UTC)
    q = pd.Series([float(i % 4) for i in range(96)], index=idx)      # 0,1,2,3 within each hour
    h = to_hourly(q)
    assert len(h) == 24 and (h == 1.5).all()
    with pytest.raises(ValueError, match="hourly"):
        effective_price(q, OperatingPattern())


def test_csv_round_trip(tmp_path):
    p = _two_days()
    f = tmp_path / "prices.csv"
    f.write_text("# source: test\n" + pd.DataFrame({"timestamp": p.index.astype(str),
                                                     "price_EUR_per_MWh": p.values}).to_csv(index=False))
    assert load_hourly_prices(f).equals(p.rename("price_EUR_per_MWh"))


def test_invalid_patterns():
    with pytest.raises(ValueError):
        OperatingPattern(kind="sometimes")
    with pytest.raises(ValueError):
        OperatingPattern(hours=frozenset({24}))
    with pytest.raises(ValueError, match="no hours"):
        effective_price(_two_days(), OperatingPattern(weekdays=frozenset({6})))


def test_fetch_script_with_a_stand_in_client(tmp_path):
    """No network: a stand-in for EntsoePandasClient returns quarter-hour prices in Brussels time."""
    from scripts.data.fetch_entsoe_prices import fetch, write

    class Client:
        def query_day_ahead_prices(self, zone, start, end):
            idx = pd.date_range(start, end, freq="15min", inclusive="left")
            return pd.Series([float(i // 4) for i in range(len(idx))], index=idx)

    s = fetch("PT", "2025-10-06", "2025-10-07", client=Client())
    assert len(s) == 24 and list(s.iloc[:3]) == [0.0, 1.0, 2.0]
    back = load_hourly_prices(write(s, "PT", "2025-10-06", "2025-10-07", tmp_path))
    assert back.equals(s)


def test_tariff_check_on_the_brewery(tmp_path):
    """Flat 100 €/MWh all year round: effective price 0.1 €/kWh; ratio = 0.1 / case gas price."""
    from pinch.case import load_case
    from pinch.economics import load_economics
    from scripts.checks.tariff_check import report
    idx = pd.date_range("2025-01-01", periods=8760, freq="h", tz=UTC)
    f = tmp_path / "flat.csv"
    pd.DataFrame({"timestamp": idx.astype(str), "price_EUR_per_MWh": 100.0}).to_csv(f, index=False)
    df = report(__import__("pathlib").Path("cases/brewery.json"), f, OperatingPattern(), NetworkTariff())
    gas = load_economics(load_case("cases/brewery.json").economics).gas_price_EUR_per_kWh
    assert (df["effective_EUR_per_kWh"] == 0.1).all()
    assert df["effective_ratio"].iloc[0] == pytest.approx(round(0.1 / gas, 3))
    assert list(df["unit"]) == ["Warm-water HP", "HTHP (wort boiling)"]
