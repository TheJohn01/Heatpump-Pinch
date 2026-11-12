"""Unit handling for stream data in any unit (step 1), with Pint.

The calculation keeps one energy unit per case (``pinch.streams``: kW, MW, kWh/hl, ...) and
temperatures in °C. Plant data and simulator exports come in other units (°F, K, Btu/h, kcal/h,
cal/s, t/h of steam...). ``standardise_table`` converts a stream table to the model's columns
before validation, so the rest of the code is unchanged.

Accepted columns (case-insensitive unit suffixes, underscores as in the CSV format of
``pinch.streams``: ``_per_`` for "/"):

* temperatures ``T_in_<u>``, ``T_out_<u>``, u in C, F, K, R (absolute temperatures);
* shift ``dT_shift_<u>``, u in K, C (a difference of 1 °C = 1 K), F, R (differences);
* one heat column ``Q_<unit>`` or ``CP_<unit>_per_<temperature difference>``, any unit Pint parses
  (e.g. ``Q_Btu_per_hr``, ``Q_kcal_per_h``, ``CP_kW_per_K``, ``CP_Btu_per_hr_per_F``).

Heat loads that are a power are converted to kW unless they are already in W, kW or MW (the units
of ``pinch.case.POWER_TO_MW``, which the annual conversion needs); loads per unit of product (e.g.
kWh/hl) are kept as given. A CP per °F is converted per K (× 9/5).

Pint: Grecco et al., https://github.com/hgrecco/pint (BSD licence). Its "cal" is the thermochemical
calorie, 4.184 J; the international-table calorie (4.1868 J) is "cal_it". Differences between
offset units (°F, °C) are handled as differences, never as absolute temperatures.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

from pinch.case import POWER_TO_MW

_ABS_T = {"c": "degC", "f": "degF", "k": "kelvin", "r": "degR"}
_DELTA_T = {"c": "kelvin", "k": "kelvin", "f": "delta_degF", "r": "delta_degR"}


@lru_cache(maxsize=1)
def registry():
    """Shared Pint unit registry, with the industrial units Pint lacks."""
    import pint
    ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=False)
    ureg.define("MMBtu = 1e6 * Btu")
    ureg.define("t = tonne")
    return ureg


def parse_unit(text: str):
    """Pint unit from a column suffix: 'Btu_per_hr' -> Btu/hr, 'kWh_per_hl' -> kWh/hl."""
    expr = text.replace("_per_", "/")
    try:
        return registry().parse_units(expr)
    except Exception as exc:                      # pint raises several error types
        raise ValueError(f"unknown unit '{expr}' (column suffix '{text}')") from exc


def convert(values, from_unit: str, to_unit: str):
    """Convert numbers (scalar, list, array or Series) between two units Pint knows."""
    ureg = registry()
    q = ureg.Quantity(pd.to_numeric(pd.Series(values), errors="raise").to_numpy(dtype=float), from_unit)
    out = q.to(to_unit).magnitude
    return out if not isinstance(values, (int, float)) else float(out[0])


def _column(df: pd.DataFrame, prefix: str) -> tuple[str, str] | None:
    """(column name, unit suffix) of the first column named prefix_<suffix>, else None."""
    pat = re.compile(rf"^{prefix}_(.+)$", re.IGNORECASE)
    for c in df.columns:
        m = pat.match(str(c))
        if m:
            return str(c), m.group(1)
    return None


def _energy_label(unit) -> str:
    """Column-suffix form of a Pint unit: 'kilowatt' -> 'kW', 'kilowatt_hour / hectoliter' -> 'kWh_per_hl'."""
    return f"{unit:~P}".replace("·", "").replace(" ", "").replace("/", "_per_")


def needs_conversion(df: pd.DataFrame) -> bool:
    """True if the table has temperatures or heat in units other than the model's (°C, K shifts, W/kW/MW or a
    load per product)."""
    cols = [str(c) for c in df.columns]
    if any(re.match(r"^(T_in|T_out)_(F|K|R)$", c, re.IGNORECASE) for c in cols):
        return True
    if any(re.match(r"^dT_shift_(F|R|C)$", c, re.IGNORECASE) for c in cols):
        return True
    for c in cols:
        m = re.match(r"^(Q|CP)_(.+)$", c)
        if m:
            text = m.group(2)
            if m.group(1) == "CP":
                if not text.endswith("_per_K"):
                    return True
                text = text[: -len("_per_K")]
            try:
                unit = parse_unit(text)
            except ValueError:
                return False                          # unknown: the stream reader reports it
            if unit.dimensionality == registry().watt.dimensionality and _energy_label(unit) not in POWER_TO_MW:
                return True
    return False


def standardise_table(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Stream table in the model's columns: T_in_C, T_out_C, dT_shift_K and Q_<unit> or CP_<unit>_per_K.

    Returns the converted table and a list of the conversions made (empty if none). Raises ValueError for a
    missing or ambiguous column or a unit Pint does not know.
    """
    df = df.copy()
    notes: list[str] = []
    for name in ("T_in", "T_out"):
        col = _column(df, name)
        if col is None:
            raise ValueError(f"missing column {name}_<unit> (e.g. {name}_C)")
        c, u = col
        key = u.lower()
        if key not in _ABS_T:
            raise ValueError(f"{c}: temperature unit must be C, F, K or R")
        if key != "c":
            df[f"{name}_C"] = convert(df[c], _ABS_T[key], "degC").round(9)   # 212 °F -> 100.0, not 100.00000000000006
            df = df.drop(columns=[c])
            notes.append(f"{c} converted to °C")
        elif c != f"{name}_C":
            df = df.rename(columns={c: f"{name}_C"})
    col = _column(df, "dT_shift")
    if col is None:
        raise ValueError("missing column dT_shift_<unit> (e.g. dT_shift_K)")
    c, u = col
    if u.lower() not in _DELTA_T:
        raise ValueError(f"{c}: temperature-difference unit must be K, C, F or R")
    if u.lower() in ("f", "r"):
        df["dT_shift_K"] = convert(df[c], _DELTA_T[u.lower()], "kelvin").round(9)
        df = df.drop(columns=[c])
        notes.append(f"{c} converted to K")
    elif c != "dT_shift_K":
        df = df.rename(columns={c: "dT_shift_K"})

    heat = [x for x in (_column(df, "Q"), _column(df, "CP")) if x is not None]
    if len(heat) != 1:
        raise ValueError("give exactly one Q_<unit> or CP_<unit> column")
    c, u = heat[0]
    if c.upper().startswith("CP_"):
        m = re.match(r"^(.+)_per_(K|C|F|R|delta_degF|delta_degC|kelvin)$", u, re.IGNORECASE)
        if not m:
            raise ValueError(f"{c}: CP unit must end in _per_K, _per_C or _per_F")
        energy, dT = m.group(1), m.group(2).lower()
        e_unit = parse_unit(energy)
        _check_heat(energy, c)
        per_K = {"k": 1.0, "c": 1.0, "kelvin": 1.0, "delta_degc": 1.0, "f": 9 / 5, "delta_degf": 9 / 5, "r": 9 / 5}[dT]
        values = pd.to_numeric(df[c]) * per_K
        target = _target(e_unit)
        if target != e_unit or per_K != 1.0:
            values = convert(values, str(e_unit), str(target))
            notes.append(f"{c} converted to CP_{_energy_label(target)}_per_K")
        df = df.drop(columns=[c])
        df[f"CP_{_energy_label(target)}_per_K"] = values
    else:
        e_unit = parse_unit(u)
        _check_heat(u, c)
        target = _target(e_unit)
        values = pd.to_numeric(df[c])
        if target != e_unit:
            values = convert(values, str(e_unit), str(target))
            notes.append(f"{c} converted to Q_{_energy_label(target)}")
        df = df.drop(columns=[c])
        df[f"Q_{_energy_label(target)}"] = values
    first = [c for c in ("stream", "type", "T_in_C", "T_out_C") if c in df.columns]
    heat_col = [c for c in df.columns if c.startswith(("Q_", "CP_"))]
    order = first + heat_col + ["dT_shift_K"]
    return df[order + [c for c in df.columns if c not in order]], notes


def _check_heat(suffix: str, column: str) -> None:
    """The heat column's unit must be an energy or a power, possibly per something (e.g. kWh per hl)."""
    ureg = registry()
    head = parse_unit(suffix.split("_per_")[0])
    if head.dimensionality not in (ureg.joule.dimensionality, ureg.watt.dimensionality):
        raise ValueError(f"{column}: '{head}' is not an energy or a power")


def _target(unit):
    """Model unit for a heat-load unit: powers outside W, kW, MW -> kW; everything else kept."""
    ureg = registry()
    if unit.dimensionality == ureg.watt.dimensionality and _energy_label(unit) not in POWER_TO_MW:
        return ureg.kilowatt
    return unit
