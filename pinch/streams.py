"""Stream data: loading, validation and energy-balance checks.

Conventions
-----------
* A *hot* stream must be cooled (T_in > T_out); a *cold* stream must be heated
  (T_in < T_out).
* Each stream carries its own temperature shift ``dT_shift_K``. Shifted
  temperatures are T* = T - dT_shift for hot streams and T* = T + dT_shift for
  cold streams. With a single global minimum approach temperature, every
  stream would have dT_shift = dTmin / 2.
* Heat loads ``Q`` are positive and expressed in the case's energy unit
  (e.g. kWh/hl for the brewery, MW for the four-stream example). The unit is read
  from the CSV column name and carried through every result.

CSV format
----------
Required columns: ``stream, type, T_in_C, T_out_C, dT_shift_K`` and exactly one
of ``Q_<unit>`` (heat load) or ``CP_<unit>`` (heat capacity flow rate).
Underscored units are converted for display, e.g. ``Q_kWh_per_hl`` -> "kWh/hl"
and ``CP_MW_per_K`` -> heat loads in "MW". Extra columns (e.g. ``note``) are kept
out of the calculation. An Excel workbook (.xlsx) with the same columns is read
from its sheet "streams", or from the first sheet if there is none.

Other units
-----------
Temperatures in °F, K or R (``T_in_F``...), shifts in °F (``dT_shift_F``) and heat in any unit Pint knows
(``Q_Btu_per_hr``, ``CP_kcal_per_h_per_K``...) are converted first (``pinch.units.standardise_table``).

Segmented streams (variable heat capacity)
------------------------------------------
A stream whose CP changes with temperature is entered as several rows, one per
linear segment, each with its own name and the parent's name in the optional
column ``segment_of``. The segments must have the same type and join end to end
(one segment's T_out is the next one's T_in). Each segment is a stream of its own
in every calculation; ``Stream.parent`` keeps the link. Yong et al. (2016,
Chemical Engineering Transactions 52, 1045-1050) note that a stepwise CP forces
this segmentation. ``segments_from_TH`` builds the segments from a temperature-
enthalpy table, e.g. exported from a process simulator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("stream", "type", "T_in_C", "T_out_C", "dT_shift_K")
ABSOLUTE_ZERO_C = -273.15


@dataclass(frozen=True)
class Stream:
    """A single process stream with constant heat capacity flow rate.

    Attributes
    ----------
    name : str
        Stream label.
    kind : str
        "hot" (to be cooled) or "cold" (to be heated).
    T_in_C, T_out_C : float
        Supply and target temperatures [°C].
    Q : float
        Heat load, positive [case energy unit, e.g. kWh/hl or kW].
    dT_shift_K : float
        Individual temperature shift [K].
    """

    name: str
    kind: str
    T_in_C: float
    T_out_C: float
    Q: float
    dT_shift_K: float
    parent: str | None = None   # name of the stream this row is a segment of (variable CP); None = whole stream

    @property
    def CP(self) -> float:
        """Heat capacity flow rate [energy unit / K]."""
        return self.Q / abs(self.T_out_C - self.T_in_C)

    @property
    def T_star_in_C(self) -> float:
        """Shifted supply temperature T* [°C]."""
        return self._shift(self.T_in_C)

    @property
    def T_star_out_C(self) -> float:
        """Shifted target temperature T* [°C]."""
        return self._shift(self.T_out_C)

    def _shift(self, T_C: float) -> float:
        return T_C - self.dT_shift_K if self.kind == "hot" else T_C + self.dT_shift_K


@dataclass(frozen=True)
class StreamSet:
    """An ordered collection of streams sharing one energy unit."""

    streams: tuple[Stream, ...]
    energy_unit: str
    source: str = ""

    @property
    def hot(self) -> tuple[Stream, ...]:
        return tuple(s for s in self.streams if s.kind == "hot")

    @property
    def cold(self) -> tuple[Stream, ...]:
        return tuple(s for s in self.streams if s.kind == "cold")

    def to_frame(self) -> pd.DataFrame:
        """Return the streams as a DataFrame, including CP and shifted temperatures."""
        return pd.DataFrame(
            {
                "stream": [s.name for s in self.streams],
                "type": [s.kind for s in self.streams],
                "T_in_C": [s.T_in_C for s in self.streams],
                "T_out_C": [s.T_out_C for s in self.streams],
                "T_star_in_C": [s.T_star_in_C for s in self.streams],
                "T_star_out_C": [s.T_star_out_C for s in self.streams],
                f"Q_{self.energy_unit}": [s.Q for s in self.streams],
                f"CP_{self.energy_unit}/K": [s.CP for s in self.streams],
                "dT_shift_K": [s.dT_shift_K for s in self.streams],
            }
        )


def _unit_from_column(column: str) -> str:
    """Convert a column suffix such as 'kWh_per_hl' into 'kWh/hl'."""
    return column.split("_", 1)[1].replace("_per_", "/")


def load_streams(path: str | Path) -> StreamSet:
    """Load and validate stream data from a CSV file.

    Parameters
    ----------
    path : str or Path
        CSV file (or .xlsx workbook) following the format described in the module docstring.

    Returns
    -------
    StreamSet
        Validated streams with heat loads in the unit given by the CSV.

    Raises
    ------
    ValueError
        If a column is missing, a value is missing or invalid, a stream's
        direction does not match its type, or stream names are duplicated.
    """
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return streams_from_frame(read_excel_streams(path), source=str(path))
    return streams_from_frame(pd.read_csv(path), source=str(path))


def read_excel_streams(path: str | Path) -> pd.DataFrame:
    """Read the stream table of a workbook: sheet "streams" if present, else the first sheet.

    Needs the optional dependency openpyxl (``pip install openpyxl``).
    """
    path = Path(path)
    try:
        sheets = pd.ExcelFile(path).sheet_names
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("reading .xlsx needs openpyxl: pip install openpyxl") from exc
    return pd.read_excel(path, sheet_name="streams" if "streams" in sheets else sheets[0])


def streams_from_frame(df: pd.DataFrame, source: str = "table") -> StreamSet:
    """Validate a stream table already in memory (same columns as the CSV).

    Used by ``load_streams`` and by interactive front ends (uploaded or edited
    tables). Raises ValueError with a message naming the offending stream or column.
    """
    df = df.copy()
    path = Path(source)

    from pinch.units import needs_conversion, standardise_table
    if needs_conversion(df):                           # other units (°F, K, Btu/h, ...): converted first
        df, _ = standardise_table(df)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")

    q_cols = [c for c in df.columns if c.startswith("Q_")]
    cp_cols = [c for c in df.columns if c.startswith("CP_")]
    if len(q_cols) + len(cp_cols) != 1:
        raise ValueError(f"{path.name}: give exactly one Q_<unit> or CP_<unit> column")

    numeric = ["T_in_C", "T_out_C", "dT_shift_K"] + q_cols + cp_cols
    if df[list(REQUIRED_COLUMNS) + q_cols + cp_cols].isna().any().any():
        raise ValueError(f"{path.name}: missing values in required columns")
    df[numeric] = df[numeric].astype(float)

    if df["stream"].duplicated().any():
        raise ValueError(f"{path.name}: duplicated stream names")

    if q_cols:
        energy_unit = _unit_from_column(q_cols[0])
    else:
        cp_unit = _unit_from_column(cp_cols[0])  # e.g. "kW/K"
        if not cp_unit.endswith("/K"):
            raise ValueError(f"{path.name}: CP unit must end in '_per_K'")
        energy_unit = cp_unit[: -len("/K")]

    streams = []
    for row in df.itertuples(index=False):
        row = row._asdict()
        kind = str(row["type"]).strip().lower()
        if kind not in ("hot", "cold"):
            raise ValueError(f"{row['stream']}: type must be 'hot' or 'cold'")
        for column in numeric:
            if not math.isfinite(row[column]):
                raise ValueError(f"{row['stream']}: {column} must be a finite number")
        for column in ("T_in_C", "T_out_C"):
            if row[column] < ABSOLUTE_ZERO_C:
                raise ValueError(f"{row['stream']}: {column} is below absolute zero ({ABSOLUTE_ZERO_C} °C)")
        if row["T_in_C"] == row["T_out_C"]:
            raise ValueError(f"{row['stream']}: T_in equals T_out. Give a latent load (boiling, condensation) "
                             "over a 1 K interval, as in the brewery case")
        dT_K = row["T_out_C"] - row["T_in_C"]
        if kind == "hot" and dT_K >= 0:
            raise ValueError(f"{row['stream']}: hot stream needs T_in > T_out")
        if kind == "cold" and dT_K <= 0:
            raise ValueError(f"{row['stream']}: cold stream needs T_in < T_out")
        if row["dT_shift_K"] < 0:
            raise ValueError(f"{row['stream']}: dT_shift_K must be >= 0")

        Q = row[q_cols[0]] if q_cols else row[cp_cols[0]] * abs(dT_K)
        if Q <= 0:
            raise ValueError(f"{row['stream']}: heat load must be positive")

        parent = row.get("segment_of")
        parent = None if parent is None or (isinstance(parent, float) and math.isnan(parent)) \
            or str(parent).strip() == "" else str(parent).strip()
        streams.append(
            Stream(
                name=str(row["stream"]),
                kind=kind,
                T_in_C=row["T_in_C"],
                T_out_C=row["T_out_C"],
                Q=Q,
                dT_shift_K=row["dT_shift_K"],
                parent=parent,
            )
        )

    if not streams:
        raise ValueError(f"{path.name}: no streams")
    _check_segments(streams)
    return StreamSet(streams=tuple(streams), energy_unit=energy_unit, source=source)


def _check_segments(streams: list[Stream]) -> None:
    """Segments of one parent: same type, joined end to end, and the parent name is not also a stream."""
    names = {s.name for s in streams}
    groups: dict[str, list[Stream]] = {}
    for s in streams:
        if s.parent is not None:
            groups.setdefault(s.parent, []).append(s)
    for parent, segs in groups.items():
        if parent in names:
            raise ValueError(f"segment_of '{parent}': a stream row has the same name as the parent")
        if len({s.kind for s in segs}) > 1:
            raise ValueError(f"segments of '{parent}' mix hot and cold rows")
        hot = segs[0].kind == "hot"
        segs = sorted(segs, key=lambda s: -s.T_in_C if hot else s.T_in_C)
        for a, b in zip(segs[:-1], segs[1:]):
            if abs(a.T_out_C - b.T_in_C) > 1e-9:
                raise ValueError(f"segments of '{parent}' do not join: '{a.name}' ends at {a.T_out_C} °C, "
                                 f"'{b.name}' starts at {b.T_in_C} °C")


def segments_from_TH(name: str, kind: str, T_C, H, dT_shift_K: float, max_error_K: float = 1.0) -> list[Stream]:
    """Linear segments of a stream from a temperature-enthalpy table (variable CP).

    Parameters
    ----------
    name, kind : stream name and "hot" or "cold".
    T_C, H : temperatures [°C] and cumulative enthalpy change [case energy unit] at the same points,
        ordered along the stream's path (hot: decreasing T; cold: increasing T); H starts at 0.
    dT_shift_K : temperature shift of every segment [K].
    max_error_K : largest temperature deviation allowed between the table and the segments [K].

    Method: recursive splitting (Ramer-Douglas-Peucker) at the table point that deviates most in
    temperature from the chord, until every point is within ``max_error_K``. The end points of every
    segment are table points, so the total load is preserved exactly. This is a fitting choice of this
    tool, not taken from a source; it does not place the segments on the conservative side of a curved
    profile (an error of up to ``max_error_K`` either way is accepted), so choose ``max_error_K`` well
    below the stream's ΔT_shift.
    """
    T = [float(x) for x in T_C]
    Hs = [float(x) for x in H]
    if len(T) != len(Hs) or len(T) < 2:
        raise ValueError("T_C and H need the same length, at least 2")
    if kind not in ("hot", "cold"):
        raise ValueError("kind must be 'hot' or 'cold'")
    if max_error_K <= 0:
        raise ValueError("max_error_K must be positive")
    step = [b - a for a, b in zip(T[:-1], T[1:])]
    if any((d >= 0) if kind == "hot" else (d <= 0) for d in step):
        raise ValueError(f"{name}: temperatures must {'fall' if kind == 'hot' else 'rise'} strictly along the table")
    if any(b <= a for a, b in zip(Hs[:-1], Hs[1:])):
        raise ValueError(f"{name}: enthalpy must increase strictly along the table")

    def split(i: int, j: int) -> list[int]:
        worst, k_worst = 0.0, None
        for k in range(i + 1, j):
            T_chord = T[i] + (T[j] - T[i]) * (Hs[k] - Hs[i]) / (Hs[j] - Hs[i])
            if abs(T[k] - T_chord) > worst:
                worst, k_worst = abs(T[k] - T_chord), k
        if k_worst is None or worst <= max_error_K:
            return [i, j]
        return split(i, k_worst)[:-1] + split(k_worst, j)

    idx = split(0, len(T) - 1)
    many = len(idx) > 2
    return [Stream(name=f"{name} [{n}]" if many else name, kind=kind, T_in_C=T[a], T_out_C=T[b], Q=Hs[b] - Hs[a],
                   dT_shift_K=dT_shift_K, parent=name if many else None)
            for n, (a, b) in enumerate(zip(idx[:-1], idx[1:]), start=1)]


def with_extra_shift(stream_set: StreamSet, extra_K: float) -> StreamSet:
    """Return a copy with ``extra_K`` added to every stream's temperature shift.

    Used, for example, to represent indirect heat transfer through an
    intermediate medium (Padullés et al., 2026, Sec. 4.1: extra 2 K).
    """
    if extra_K < 0:
        raise ValueError("extra_K must be >= 0")
    shifted = tuple(replace(s, dT_shift_K=s.dT_shift_K + extra_K) for s in stream_set.streams)
    return replace(stream_set, streams=shifted)


def energy_balance(stream_set: StreamSet) -> dict[str, float]:
    """Total hot and cold loads and their difference.

    Any correct target must satisfy Qc_min - Qh_min = Q_hot_total - Q_cold_total.

    Returns
    -------
    dict
        ``Q_hot_total``, ``Q_cold_total`` and ``net_surplus`` (hot minus cold),
        all in the case energy unit.
    """
    Q_hot = sum(s.Q for s in stream_set.hot)
    Q_cold = sum(s.Q for s in stream_set.cold)
    return {"Q_hot_total": Q_hot, "Q_cold_total": Q_cold, "net_surplus": Q_hot - Q_cold}
