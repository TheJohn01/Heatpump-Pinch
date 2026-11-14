"""Measured thermal loads of a Norwegian dairy, 2024 (SINTEF / NTNU, ENOUGH project), as hourly means.

Usage:
    python -m scripts.data.fetch_sintef_dairy

Source: Köster, Bengsch, Widell, "Replication Data for: Improving thermal energy efficiency in a Norwegian dairy
utilising integrated CO2 refrigeration systems", Zenodo, doi:10.5281/zenodo.22877098 (v2; v1 15111145), CC BY 4.0.
Paper: Köster, Bengsch, Widell (2025), Int. J. Refrig. 180, 564-571, doi:10.1016/j.ijrefrig.2025.10.001 (open
access copy, CC BY 4.0: zenodo.org/records/17734000). One-minute heat loads (energy flow meters, Savitzky-Golay
filtered by the authors) and the hourly electricity of the electric steam boiler.

Writes data/measured/koster2025_dairy_2024_hourly.csv (hourly means in kW; timestamps as published, local time
without a zone) and copies the authors' Figure 2 data (monthly Wh per litre of milk) unchanged to
data/measured/koster2025_figure2_monthly.csv. Not part of regenerate_outputs.py (network, 50 MB download).
"""

from __future__ import annotations

import datetime as dt
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]   # repository root
RECORD = "https://zenodo.org/records/22877098/files/{}?download=1"
LOADS, BOILER, FIGURE2 = ("02_DATA_thermal_loads_in_kW.csv", "03_DATA_electric_boiler_consumption_in_kW.csv",
                          "01_DATA_Figure_2_specific_energy_consumption.csv")


def hourly(loads: pd.DataFrame, boiler: pd.DataFrame) -> pd.DataFrame:
    """Hourly means of the one-minute loads (over the minutes with a value), the number of minutes recorded, and the
    hourly boiler electricity [kW]. Gaps stay empty (2024-10-27 has no load data); the boiler's repeated hour at
    the October clock change is averaged."""
    loads = loads.assign(timestamp=pd.to_datetime(loads["timestamp"])).set_index("timestamp")
    h = loads.resample("1h").mean()
    h["minutes_recorded"] = loads.resample("1h").size()
    b = boiler.assign(timestamp=pd.to_datetime(boiler["timestamp"])).groupby("timestamp").mean()
    return h.join(b, how="outer")


def main() -> None:
    def get(name: str) -> bytes:
        with urlopen(RECORD.format(name)) as r:
            return r.read()
    out_dir = ROOT / "data" / "measured"
    out_dir.mkdir(parents=True, exist_ok=True)
    h = hourly(pd.read_csv(BytesIO(get(LOADS))), pd.read_csv(BytesIO(get(BOILER))))
    header = ("# Köster, Bengsch, Widell (2025), Zenodo doi:10.5281/zenodo.22877098, CC BY 4.0: measured 2024 heat loads of "
              "a Norwegian dairy (one-minute values averaged to hours by scripts/data/fetch_sintef_dairy.py) and the "
              f"hourly electricity of the electric steam boiler, kW. Local time as published. Fetched {dt.date.today()}.\n")
    (out_dir / "koster2025_dairy_2024_hourly.csv").write_text(
        header + h.round(4).to_csv(lineterminator="\n"), encoding="utf-8")
    (out_dir / "koster2025_figure2_monthly.csv").write_bytes(get(FIGURE2))
    print(f"wrote {len(h)} hours to {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
