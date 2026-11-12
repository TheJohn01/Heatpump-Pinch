"""Project files: save and reopen everything entered in the app (step 1), as one JSON file.

A project holds the case it started from (a published case, or an uploaded table), the stream table,
the heat pump sink levels, the scalar inputs (Lorenz efficiency, temperatures, annual basis, prices...)
and, if used, the guided-extraction table with its reasoning (``pinch.extraction``). It does not hold
results: they are recomputed from the inputs, so a project opened by a later version of the tool gives
that version's results.

The file is validated before anything is loaded, so a damaged or hand-edited file gives a message
instead of a wrong run: format name and version, the expected keys and types, a stream table that
``pinch.streams.streams_from_frame`` accepts, and sink levels with the expected columns. The idea
follows OpenPinch (Walmsley 2026, Process Integr. Optim. Sustain. 10, 3947-3963), which validates its
JSON-like input against a schema (Pydantic) before any calculation; here the checks are written out,
without a new dependency.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import pandas as pd

FORMAT = "heatpump-pinch project"
VERSION = 1
LEVEL_COLUMNS = ("name", "T_sink_in_C", "T_sink_out_C", "T_source_C")


@dataclass
class Project:
    """Inputs of one app session.

    Attributes
    ----------
    choice : published case name, or "" for an uploaded / extracted stream table.
    name : project name (file stem for an uploaded table).
    inputs : scalar inputs by key (e.g. "eta", "source_T", "econ_gas_price_EUR_per_kWh", "basis_on").
    streams : stream table (columns of ``pinch.streams``, plus the optional film-coefficient column).
    levels : heat pump sink levels (``LEVEL_COLUMNS``).
    extraction : guided-extraction table (``pinch.extraction.COLUMNS``), or None.
    """

    choice: str
    name: str
    inputs: dict
    streams: pd.DataFrame
    levels: pd.DataFrame
    extraction: pd.DataFrame | None = None
    tool_version: str = field(default="")


def _records(df: pd.DataFrame | None) -> list[dict] | None:
    if df is None:
        return None
    return json.loads(df.to_json(orient="records", force_ascii=False))     # NaN -> null


def dumps(p: Project) -> str:
    """The project as JSON text (UTF-8, indented, keys in a fixed order)."""
    from pinch import __version__
    return json.dumps({"format": FORMAT, "format_version": VERSION, "tool_version": __version__,
                       "choice": p.choice, "name": p.name, "inputs": p.inputs,
                       "streams": _records(p.streams), "levels": _records(p.levels),
                       "extraction": _records(p.extraction)}, ensure_ascii=False, indent=1)


def loads(text: str | bytes, known_cases: tuple[str, ...] = ()) -> Project:
    """Read and validate a project file (raises ValueError with a readable message)."""
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"not a JSON file: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ValueError(f"not a {FORMAT} file")
    if raw.get("format_version") != VERSION:
        raise ValueError(f"project format version {raw.get('format_version')} is not supported (this tool reads {VERSION})")
    for key, kind in (("choice", str), ("name", str), ("inputs", dict), ("streams", list), ("levels", list)):
        if not isinstance(raw.get(key), kind):
            raise ValueError(f"'{key}' missing or not a {kind.__name__}")
    if raw["choice"] and known_cases and raw["choice"] not in known_cases:
        raise ValueError(f"case '{raw['choice']}' is not available in this version (cases: {', '.join(known_cases)})")
    for k, v in raw["inputs"].items():
        if not isinstance(k, str) or not (v is None or isinstance(v, (bool, int, float, str))):
            raise ValueError(f"input '{k}': not a number, text or true/false")
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"input '{k}': not a finite number")
    streams = pd.DataFrame(raw["streams"])
    levels = pd.DataFrame(raw["levels"])
    from pinch.streams import streams_from_frame
    try:
        streams_from_frame(streams.drop(columns=["h_kW_per_m2K"], errors="ignore"), source="project stream table")
    except ValueError as exc:
        raise ValueError(f"stream table: {exc}") from exc
    missing = [c for c in LEVEL_COLUMNS if c not in levels.columns]
    if missing or levels.empty:
        raise ValueError(f"sink levels: missing columns {missing}" if missing else "sink levels: none")
    extraction = raw.get("extraction")
    if extraction is not None and not isinstance(extraction, list):
        raise ValueError("'extraction' must be a list of rows")
    return Project(raw["choice"], raw["name"], raw["inputs"], streams, levels,
                   pd.DataFrame(extraction) if extraction is not None else None, str(raw.get("tool_version", "")))
