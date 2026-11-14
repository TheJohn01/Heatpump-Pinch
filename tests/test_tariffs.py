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
ROOT_DIR = __import__("pathlib").Path(__file__).resolve().parents[1]


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


# ---------------------------------------------------------------- published network tariffs (PeriodTariff)

def _period_at(key: str, local: str) -> dict:
    from pinch.tariffs import PeriodTariff
    t = PeriodTariff.load(key)
    idx = pd.DatetimeIndex([pd.Timestamp(local, tz=t.timezone).tz_convert(UTC)])
    return t.period_fractions(idx).iloc[0][lambda s: s > 0].to_dict()


@pytest.mark.parametrize("local, expected", [
    ("2025-01-13 10:00", {"ponta": 1.0}),                       # winter Monday (ERSE weekly cycle, p. 62)
    ("2025-07-14 09:00", {"cheias": 0.25, "ponta": 0.75}),      # summer: ponta from 09.15
    ("2025-01-18 10:00", {"cheias": 1.0}),                      # winter Saturday
    ("2025-12-25 10:00", {"vazio_normal": 1.0}),                # holiday (Thursday) = Sunday
    ("2025-03-02 03:00", {"super_vazio": 1.0}),
])
def test_erse_weekly_cycle(local, expected):
    assert _period_at("pt_erse_2026_mt", local) == pytest.approx(expected)


@pytest.mark.parametrize("local, expected", [
    ("2025-01-13 10:00", "P1"), ("2025-03-10 10:00", "P2"), ("2025-06-09 08:00", "P4"),
    ("2025-04-07 08:00", "P5"), ("2025-04-07 03:00", "P6"), ("2025-01-18 10:00", "P6"), ("2025-01-06 10:00", "P6"),
])
def test_cnmc_six_periods(local, expected):                     # Circular 3/2020, Península
    assert _period_at("es_cnmc_2026_61td", local) == {expected: 1.0}


def test_capacity_charges_of_a_constant_load():
    from pinch.tariffs import PeriodTariff
    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz=UTC, inclusive="left")
    one = pd.Series(1.0, index=idx)
    assert PeriodTariff.load("pt_erse_2026_mt").capacity_EUR(one) == pytest.approx((0.2271 + 0.0206) * 365)
    es = PeriodTariff.load("es_cnmc_2026_61td")
    assert es.capacity_EUR(one) == pytest.approx(23.946498 + 12.687713 + 4.747747 + 3.339695 + 0.070979 + 0.062703)
    p6 = es.period_fractions(idx)["P6"].eq(1.0).astype(float)          # load only in P6 hours: P6 term only
    assert es.capacity_EUR(p6) == pytest.approx(0.062703)
    de = PeriodTariff.load("de_swm_2026_ms")                            # 8760 h/a: the >= 2500 h price set
    assert de.capacity_EUR(one) == pytest.approx(132.13)
    assert de.adders_EUR_per_MWh(idx[:3], one).tolist() == pytest.approx([3.0] * 3)
    short = one.where(idx.month == 1, 0.0)                              # 744 h/a: the < 2500 h price set
    assert de.capacity_EUR(short) == pytest.approx(15.88)


def test_eurostat_shares_add_up_and_delivered_price():
    from pinch.tariffs import delivered_price, eurostat_shares
    s = eurostat_shares("PT", "band ID")
    assert s["energy_supply"] + s["network"] + s["other"] == pytest.approx(1.0)
    spec = {"prices": "data/prices/portugal_2025_day_ahead.csv", "network_tariff": "pt_erse_2026_mt", "band": "band ID"}
    p, d = delivered_price(0.1135, spec)
    assert d["shape"] == pytest.approx(1.0)                              # round the clock: the year's mean
    assert p == pytest.approx(0.1135 * (s["energy_supply"] + s["other"]) + d["network_EUR_per_kWh"])
    night = delivered_price(0.1135, {**spec, "pattern": {"hours": list(range(0, 6))}})[1]
    prices = load_hourly_prices(ROOT_DIR / spec["prices"])
    at_night = prices[prices.index.tz_convert("Europe/Lisbon").hour < 6]
    assert night["shape"] == pytest.approx(at_night.mean() / prices.mean())
    assert night["hours_per_year"] == pytest.approx(6 * 365)


def test_tariff_in_the_economics_and_the_ratio_override():
    from pinch.economics import load_economics
    from pinch.sensitivity import _merge
    from pinch.tariffs import delivered_price
    spec = {"prices": "data/prices/spain_2025_day_ahead.csv", "network_tariff": "es_cnmc_2026_61td", "band": "band ID"}
    block = {"electricity_price_EUR_per_kWh": 0.1177, "gas_price_EUR_per_kWh": 0.0493, "tariff": spec}
    assert load_economics(block).electricity_price_EUR_per_kWh == pytest.approx(delivered_price(0.1177, spec)[0])
    from dataclasses import replace

    from pinch.case import load_case
    from pinch.sensitivity import apply
    from pinch.validation import ROOT
    case = replace(load_case(ROOT / "cases" / "brewery.json"), economics=_merge({}, block))
    assert "tariff" not in apply(case, "econ", {"electricity_to_gas_ratio": 2.0}).economics


def test_committed_prices_hold_the_case_prices():
    """data/sources/eurostat_prices.csv (fetched) holds the 2026-S1 prices the cases cite."""
    from pinch.tariffs import EUROSTAT_PRICES, X_VAT
    d = pd.read_csv(EUROSTAT_PRICES, comment="#")
    d = d[(d.taxes == X_VAT) & (d.period == "2026-S1") & (d.geo == "PT")]
    el = d[(d.carrier == "electricity") & d.band.str.endswith("band ID")]["value"].item()
    gas = d[(d.carrier == "gas") & d.band.str.endswith("band I3")]["value"].item()
    assert (el, gas) == (0.1135, 0.0512)


def test_eurostat_fetch_parsing():
    import io

    from scripts.data.fetch_eurostat_prices import prices
    head = ("STRUCTURE,STRUCTURE_ID,freq: Time frequency,siec: SIEC,nrg_cons: Energy consumption,unit: Unit of measure,"
            "tax: Taxes,currency: Currency,geo: Geopolitical entity (reporting),TIME_PERIOD: Time,"
            "OBS_VALUE: Observation value,OBS_FLAG: Flag,CONF_STATUS: Confidentiality\n")
    row = ('dataflow,X,"S: Half-yearly",E7000: Electricity,MWH2000-19999: Consumption from 2 000 MWh to 19 999 MWh '
           '- band ID,{u},X_VAT: Excluding VAT and other recoverable taxes and levies,EUR: Euro,PT: Portugal,{p},{v},,\n')
    body = head + row.format(u="KWH: Kilowatt-hour", p="2026-S1", v="0.1135") \
        + row.format(u="KWH: Kilowatt-hour", p="2020-S1", v="0.09") + row.format(u="GJ_GCV: GJ", p="2026-S1", v="31")

    class Fake(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    out = prices(["PT"], "2021-S2", opener=lambda url: Fake(body.encode()))
    el = out[out.carrier == "electricity"]
    assert el[["geo", "band", "taxes", "period", "value"]].values.tolist() == [
        ["PT", "Consumption from 2 000 MWh to 19 999 MWh - band ID", X_VAT_LABEL, "2026-S1", 0.1135]]


X_VAT_LABEL = "Excluding VAT and other recoverable taxes and levies"


def test_ember_extract_needs_a_complete_year(tmp_path):
    import io
    import zipfile

    from scripts.data.fetch_ember_prices import extract
    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz=UTC, inclusive="left")
    csv = pd.DataFrame({"Datetime (UTC)": idx.strftime("%Y-%m-%d %H:%M:%S"), "Price (EUR/MWhe)": 50.0}).to_csv(index=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Portugal.csv", csv)
        z.writestr("Spain.csv", pd.read_csv(io.StringIO(csv)).iloc[:-1].to_csv(index=False))
    assert len(extract(buf.getvalue(), "Portugal", 2025)) == 8760
    with pytest.raises(ValueError, match="complete year"):
        extract(buf.getvalue(), "Spain", 2025)
