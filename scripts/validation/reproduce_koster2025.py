"""Measured data of a Norwegian dairy (Köster, Bengsch, Widell 2025): the published figures reproduced from the raw
data, and the average production day as a time-sliced stream table (step 1 on measured data).

Usage:
    python -m scripts.validation.reproduce_koster2025

Data: data/measured/koster2025_dairy_2024_hourly.csv and koster2025_figure2_monthly.csv
(scripts/data/fetch_sintef_dairy.py; CC BY 4.0). Paper: Int. J. Refrig. 180 (2025) 564-571, open access.

What this checks (a check of how the measured data are read, not of the pinch or heat pump models: the data hold
no compressor power per unit and no evaporating temperatures):
* monthly specific consumption [Wh per litre of milk] of every metered consumer against the authors' Figure 2
  data. Two published series include values that are not metered (Sec. 3): glycol process cooling includes the
  yoghurt cooling the authors computed from production until October ("yoghurt" column), and direct process
  water cooling includes CO2 unit 1, taken as 35 kW from 07:00 to 15:00 on production days (280 kWh/day);
* the production-day averages of Sec. 4.2-4.4 (August and December) and the boiler baseload of Sec. 4.1.
  The paper does not define a production day; here it is a weekday on which the boiler used more than
  1,500 kWh (stated as found, the rule that reproduces August).

Writes outputs/koster2025_checks.csv and data/measured/koster2025_production_day_streams.csv: the year's mean
production day, hour by hour, as streams with start and end times (pinch.time_slices format), at the published
temperatures (Sec. 2): cooling loads isothermal at the secondary-fluid supply temperature (glycol -3.5 °C,
process water 1 °C; a lower bound, since return temperatures are not published), hot water from city water
6.5 °C to 65 °C, and steam demand over the published 65-100 °C range (electric boiler, efficiency about 1).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]   # repository root
HOURLY = ROOT / "data" / "measured" / "koster2025_dairy_2024_hourly.csv"
FIGURE2 = ROOT / "data" / "measured" / "koster2025_figure2_monthly.csv"
STREAMS = ROOT / "data" / "measured" / "koster2025_production_day_streams.csv"
BOILER = "El. Boiler consumption [kW]"
COOL_GLYCOL = ("Glycol Process Cooling [kW]", "Cold Storage & AC Cooling [kW]")
COOL_WATER = "Direct Water Process Cooling: CO2 unit 4 [kW]"
HOT_WATER = ("Hot Water CIP [kW]", "Hot Water truck hall [kW]", "Hot Water production [kW]")
UNIT1_KW, UNIT1_HOURS = 35.0, range(7, 15)          # Sec. 3: CO2 unit 1, not metered
PRODUCTION_DAY_MIN_BOILER_KWH = 1500.0
#: Sec. 4.2-4.4: production-day averages [kWh/day] and maxima; Sec. 4.1: baseload (00:00-03:00)
PUBLISHED_DAYS = {
    ("August", 8): {"cooling": 2898.0, "steam": 2979.0, "steam_max": 3929.0, "hot_water": 2506.0, "cold_rooms": 1098.9},
    ("December", 12): {"cooling": 2302.0, "steam": 3318.0, "steam_max": 3983.0, "hot_water": 2753.0, "cold_rooms": 519.0},
}
PUBLISHED_BASELOAD = {"mean": 35.8, "median": 31.0, "q1": 29.0, "q3": 33.5}


def load() -> pd.DataFrame:
    return pd.read_csv(HOURLY, comment="#", parse_dates=["timestamp"]).set_index("timestamp")


def production_days(h: pd.DataFrame) -> pd.DatetimeIndex:
    day = h[BOILER].resample("D").sum(min_count=1)
    return day.index[(day.index.weekday < 5) & (day > PRODUCTION_DAY_MIN_BOILER_KWH)]


def checks(h: pd.DataFrame) -> pd.DataFrame:
    f = pd.read_csv(FIGURE2).set_index("year_month")
    m = h.resample("MS").sum(min_count=1)
    m.index = m.index.strftime("%Y-%m")
    milk = f["Processed milk [m^3]"]                 # kWh / m3 = Wh / l
    rows = []

    def row(check: str, published: float, reproduced: float, note: str = "") -> None:
        rows.append({"check": check, "published": published, "reproduced": round(reproduced, 2),
                     "deviation": round(reproduced - published, 2), "note": note})
    days = production_days(h)
    n_days = pd.Series(1, index=days).resample("MS").sum().reindex(pd.to_datetime(m.index), fill_value=0)
    n_days.index = m.index
    for month in f.index:
        per = lambda col, month=month: float(m.loc[month, col] / milk[month])   # noqa: E731
        row(f"{month} cold storage & AC [Wh/l]", f.loc[month, "Cold Storage & AC Cooling [Wh/l]"], per(COOL_GLYCOL[1]))
        for c in HOT_WATER + ("Hot Water overproduction / preCIP [kW]",):
            row(f"{month} {c.replace(' [kW]', '')} [Wh/l]", f.loc[month, c.replace("[kW]", "[Wh/l]")], per(c))
        row(f"{month} glycol process cooling [Wh/l]", f.loc[month, "Glycol Process Cooling [Wh/l]"],
            per(COOL_GLYCOL[0]) + f.loc[month, "yoghurt"], "metered + the authors' yoghurt cooling (not metered)")
        row(f"{month} direct process water cooling [Wh/l]", f.loc[month, "Direct Water Process Cooling [Wh/l]"],
            per(COOL_WATER) + n_days[month] * UNIT1_KW * len(UNIT1_HOURS) / milk[month],
            "metered + CO2 unit 1 at 35 kW, 07:00-15:00 on production days (Sec. 3)")
        row(f"{month} electric boiler [Wh/l]", f.loc[month, "steam"], per(BOILER),
            "hourly supplier data; not explained: the authors' monthly values differ by up to 4.3 Wh/l")
    day = h.resample("D").sum(min_count=1)
    for (name, month), pub in PUBLISHED_DAYS.items():
        d = day.loc[days[days.month == month]]
        row(f"{name}: cooling per production day [kWh]", pub["cooling"],
            d[[*COOL_GLYCOL, COOL_WATER]].sum(axis=1).mean() + UNIT1_KW * len(UNIT1_HOURS), "incl. CO2 unit 1, 280 kWh")
        row(f"{name}: steam per production day [kWh]", pub["steam"], d[BOILER].mean())
        row(f"{name}: steam, largest production day [kWh]", pub["steam_max"], d[BOILER].max())
        row(f"{name}: hot water consumers per production day [kWh]", pub["hot_water"], d[list(HOT_WATER)].sum(axis=1).mean())
        row(f"{name}: cold rooms & AC per production day [kWh]", pub["cold_rooms"], d[COOL_GLYCOL[1]].mean())
    night = h.loc[h.index.hour <= 3, BOILER]
    for k, v in {"mean": night.mean(), "median": night.median(), "q1": night.quantile(0.25),
                 "q3": night.quantile(0.75)}.items():
        row(f"boiler baseload 00:00-03:00, {k} [kW]", PUBLISHED_BASELOAD[k], float(v))
    return pd.DataFrame(rows)


def production_day_streams(h: pd.DataFrame) -> pd.DataFrame:
    """Mean production day, one row per load and clock hour (kW), at the published temperatures."""
    days = production_days(h)
    sel = h[h.index.normalize().isin(days)]
    prof = sel.groupby(sel.index.hour).mean()
    unit1 = pd.Series([UNIT1_KW if hr in UNIT1_HOURS else 0.0 for hr in range(24)])
    loads = {"Glycol cooling (process, cold rooms, AC)": ("hot", -3.5, -3.5, prof[list(COOL_GLYCOL)].sum(axis=1)),
             "Process water cooling (CO2 units 1 and 4)": ("hot", 1.0, 1.0, prof[COOL_WATER] + unit1.to_numpy()),
             "Hot water (CIP, truck hall, production)": ("cold", 6.5, 65.0, prof[list(HOT_WATER)].sum(axis=1)),
             "Steam demand (pasteurisation, sterilisation, CIP)": ("cold", 65.0, 100.0, prof[BOILER])}
    rows = []
    for name, (kind, T_in, T_out, q) in loads.items():
        for hr, v in enumerate(q.to_numpy()):
            if v <= 1e-6:
                continue
            if T_in == T_out:      # isothermal: a 1 K interval, as latent loads elsewhere in this tool
                T_in, T_out = (T_in + 1.0, T_out) if kind == "hot" else (T_in, T_out + 1.0)
            rows.append({"stream": f"{name} {hr:02d}h", "type": kind, "T_in_C": T_in, "T_out_C": T_out,
                         "Q_kW": round(float(v), 3), "dT_shift_K": 2.5, "t_start_h": hr, "t_end_h": hr + 1})
            T_in, T_out = loads[name][1], loads[name][2]
    return pd.DataFrame(rows)


def main() -> None:
    h = load()
    c = checks(h)
    c.to_csv(ROOT / "outputs" / "koster2025_checks.csv", index=False)
    s = production_day_streams(h)
    # no comment line: stream tables are read without one (provenance: this docstring and the case file)
    STREAMS.write_text(s.to_csv(index=False, lineterminator="\n"), encoding="utf-8")
    print(c.to_string(index=False))


if __name__ == "__main__":
    main()
