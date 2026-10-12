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
out of the calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("stream", "type", "T_in_C", "T_out_C", "dT_shift_K")


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
        CSV file following the format described in the module docstring.

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
    df = pd.read_csv(path)

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

        streams.append(
            Stream(
                name=str(row["stream"]),
                kind=kind,
                T_in_C=row["T_in_C"],
                T_out_C=row["T_out_C"],
                Q=Q,
                dT_shift_K=row["dT_shift_K"],
            )
        )

    return StreamSet(streams=tuple(streams), energy_unit=energy_unit, source=str(path))


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
