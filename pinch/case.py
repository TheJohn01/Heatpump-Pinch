"""Case definition: everything that describes one industrial site, in one file.

A case file (JSON) points to a stream CSV and holds the site-specific
parameters, each with its provenance. The analysis code is the same for every
site; only the case file changes. See ``cases/TEMPLATE.json``.

Annual basis
------------
Stream loads may be given per unit of product (e.g. kWh/hl, kWh/t) or as power
(kW, MW). Conversion to MWh/year is done only when the case file gives an
explicit basis:

* ``{"type": "per_product", "production_per_year": ..., "production_unit": "hl"}``
  for loads such as kWh/hl (the denominator must match ``production_unit``);
* ``{"type": "power", "operating_hours_per_year": ...}`` for loads in kW or MW.

Without a basis, results stay in the stream-data unit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ENERGY_TO_MWH = {"Wh": 1e-6, "kWh": 1e-3, "MWh": 1.0, "GWh": 1e3, "kJ": 1 / 3.6e6, "MJ": 1 / 3600, "GJ": 1 / 3.6}
POWER_TO_MW = {"W": 1e-6, "kW": 1e-3, "MW": 1.0}


@dataclass(frozen=True)
class SinkLevelSpec:
    """A heat pump sink level as written in the case file.

    ``T_sink_out_C`` may be the string "gcc_max": an isothermal sink at the
    maximum shifted temperature of the GCC (covers all remaining demand).
    """

    name: str
    T_sink_in_C: float | str
    T_sink_out_C: float | str
    T_source_C: float | None = None
    eta_lorenz: float | None = None   # overrides the case-wide value for this level


@dataclass(frozen=True)
class Case:
    """One industrial site.

    Attributes
    ----------
    name : str
        Short identifier, used for the output folder.
    description, reference : str
        What the case is and where its data come from.
    stream_file : Path
        Stream CSV (see ``pinch.streams``).
    extra_shift_K : float
        Extra shift added to every stream (e.g. indirect transfer), default 0.
    eta_lorenz : float
        Lorenz efficiency for heat pump COPs [-].
    cycle_screening : dict or None
        Working fluids and layouts to screen (``pinch.cycle_analysis``).
    eta_lorenz_sensitivity : tuple of float
        Optional further Lorenz efficiencies; the design is re-sized and
        re-costed for each (``pinch.economic_analysis.eta_lorenz_sensitivity``).
    source_T_C : float
        Default heat pump source temperature, on the T* axis [°C].
    sink_levels : list of SinkLevelSpec
        Candidate heat pump sink levels; sized automatically from the GCC.
    basis : dict or None
        Annual basis (see module docstring).
    screening : dict
        Overrides for the plausibility thresholds in ``pinch.design``.
    ambient_T_C : float or None
        Ambient temperature [°C]. External (non-process) heat pump sources are
        only physically available at or below it; None disables the check.
    economics : dict or None
        Economic parameters (see ``pinch.economics.load_economics``).
    area_targeting : dict or None
        Film coefficients and cost law for ΔTmin supertargeting
        (see ``pinch.area_analysis``).
    provenance : dict
        Free-form notes stating which values are published or assumed.
    """

    name: str
    description: str
    reference: str
    stream_file: Path
    eta_lorenz: float
    source_T_C: float
    sink_levels: tuple[SinkLevelSpec, ...]
    extra_shift_K: float = 0.0
    basis: dict | None = None
    screening: dict = field(default_factory=dict)
    ambient_T_C: float | None = None
    economics: dict | None = None
    area_targeting: dict | None = None
    provenance: dict = field(default_factory=dict)
    eta_lorenz_sensitivity: tuple[float, ...] = ()
    cycle_screening: dict | None = None


def load_case(path: str | Path) -> Case:
    """Load and validate a case file. Relative paths resolve from the file's folder."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("name", "stream_file", "heat_pumps"):
        if key not in raw:
            raise ValueError(f"{path.name}: missing '{key}'")
    hp = raw["heat_pumps"]
    for key in ("eta_lorenz", "source_T_C"):
        if key not in hp:
            raise ValueError(f"{path.name}: heat_pumps needs '{key}'")
    eta = float(hp["eta_lorenz"])
    if not 0 < eta <= 1:
        raise ValueError(f"{path.name}: eta_lorenz must be in (0, 1]")
    eta_sens = tuple(float(x) for x in hp.get("eta_lorenz_sensitivity", []))
    if any(not 0 < x <= 1 for x in eta_sens):
        raise ValueError(f"{path.name}: eta_lorenz_sensitivity values must be in (0, 1]")

    levels = tuple(
        SinkLevelSpec(
            name=lv["name"],
            T_sink_in_C=lv.get("T_sink_in_C", lv.get("T_sink_C")),
            T_sink_out_C=lv.get("T_sink_out_C", lv.get("T_sink_C")),
            T_source_C=lv.get("T_source_C"),
            eta_lorenz=None if lv.get("eta_lorenz") is None else float(lv["eta_lorenz"]),
        )
        for lv in hp.get("sink_levels", [{"name": "HTHP", "T_sink_C": "gcc_max"}])
    )
    for lv in levels:
        if lv.T_sink_in_C is None or lv.T_sink_out_C is None:
            raise ValueError(f"{path.name}: sink level '{lv.name}' needs T_sink_C or T_sink_in_C/T_sink_out_C")

    basis = raw.get("basis")
    if basis is not None:
        _check_basis(basis, path.name)

    stream_file = Path(raw["stream_file"])
    if not stream_file.is_absolute():
        stream_file = (path.parent / stream_file).resolve()

    return Case(
        name=raw["name"],
        description=raw.get("description", ""),
        reference=raw.get("reference", ""),
        stream_file=stream_file,
        eta_lorenz=eta,
        source_T_C=float(hp["source_T_C"]),
        sink_levels=levels,
        extra_shift_K=float(raw.get("extra_shift_K", 0.0)),
        basis=basis,
        screening=raw.get("screening", {}),
        ambient_T_C=None if raw.get("ambient_T_C") is None else float(raw["ambient_T_C"]),
        economics=raw.get("economics"),
        area_targeting=raw.get("area_targeting"),
        provenance=raw.get("provenance", {}),
        eta_lorenz_sensitivity=eta_sens,
        cycle_screening=hp.get("cycle_screening"),
    )


def _check_basis(basis: dict, file_name: str) -> None:
    kind = basis.get("type")
    if kind == "per_product":
        if basis.get("production_per_year", 0) <= 0 or not basis.get("production_unit"):
            raise ValueError(f"{file_name}: per_product basis needs production_per_year > 0 and production_unit")
    elif kind == "power":
        if not 0 < basis.get("operating_hours_per_year", 0) <= 8784:
            raise ValueError(f"{file_name}: power basis needs 0 < operating_hours_per_year <= 8784")
    else:
        raise ValueError(f"{file_name}: basis type must be 'per_product' or 'power'")


def to_MWh_per_year(value: float, energy_unit: str, basis: dict | None) -> float | None:
    """Convert a heat or work quantity to MWh/year, or None if no basis is given.

    Raises
    ------
    ValueError
        If the unit is not understood or does not match the basis.
    """
    if basis is None:
        return None
    if basis["type"] == "per_product":
        if "/" not in energy_unit:
            raise ValueError(f"unit '{energy_unit}' is not per product; use a 'power' basis")
        energy, product = energy_unit.split("/", 1)
        if product != basis["production_unit"]:
            raise ValueError(f"unit '{energy_unit}' does not match production unit '{basis['production_unit']}'")
        if energy not in ENERGY_TO_MWH:
            raise ValueError(f"unknown energy unit '{energy}'")
        return value * ENERGY_TO_MWH[energy] * basis["production_per_year"]
    if energy_unit not in POWER_TO_MW:
        raise ValueError(f"unit '{energy_unit}' is not a power unit; use a 'per_product' basis")
    return value * POWER_TO_MW[energy_unit] * basis["operating_hours_per_year"]
