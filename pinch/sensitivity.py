"""Sensitivity cases: one list per site, in the case file (redundancy audit, item 1.1).

Before 2026-10-17 the brewery had two lists that overlapped: ``economics.scenarios`` in the
case file (read by the grass-roots economics) and ``SENSITIVITIES`` in ``consolidate_rq.py``
(read by the RQ1-RQ3 table). The same label could then report two different "RQ1" values.
Now there is one list, ``sensitivities`` in the case file::

    "sensitivities": [
        {"label": "Boiler efficiency 0.929", "kind": "econ", "value": {"boiler_efficiency": 0.929},
         "basis": "implied by Padullés App. B (DK1)"},
        {"label": "Lorenz efficiency 0.45", "kind": "eta", "value": 0.45, "basis": "DEA HTHP data"},
        ...
    ]

Every row changes one thing in the base case (``apply``); ``basis`` says where the value comes
from. Which analysis uses which rows:

* ``consolidate_rq.py`` (the RQ1-RQ3 answers): every row;
* ``pinch.economic_analysis`` (grass-roots reference, step 6): the ``econ`` rows only, since the
  other kinds change the design, the network or the area targeting, which that table does not
  recompute.

Kinds
-----
econ          dict of economics overrides (prices, efficiencies, emission factors, cost functions...)
eta           case-wide Lorenz efficiency (per-level values are cleared)
cycle         per-unit Lorenz efficiency from the cycle screening (step 4b); value null
cycle_scaled  as ``cycle``, scaled by the value
hp_capex      heat pump cost function alpha and beta scaled by the value
hx_capex      plate exchanger cost function alpha and beta scaled by the value
no_om         operation and maintenance costs set to zero (as Padullés et al., 2026); value null
hthp_sink     isothermal sink temperature [°C] of every level whose name contains "HTHP"
area          dict of area_targeting overrides
film          film coefficients scaled by the value
scale         production [per year]; the retrofit storage is scaled with it
hp_hot_utility  RQ2 with heat-pump heat as the hot utility; the value is computed by consolidate_rq
combo         list of {"kind", "value"} applied in order
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any

KINDS = ("econ", "eta", "cycle", "cycle_scaled", "hp_capex", "hx_capex", "no_om", "hthp_sink", "area", "film",
         "scale", "hp_hot_utility", "combo")
_DICT_KINDS = ("econ", "area")
_NUMBER_KINDS = ("eta", "cycle_scaled", "hp_capex", "hx_capex", "hthp_sink", "film", "scale")
_NULL_KINDS = ("cycle", "no_om", "hp_hot_utility")


@dataclass(frozen=True)
class Sensitivity:
    """One row of the sensitivity list.

    Attributes
    ----------
    label : str
        Row label in every table.
    kind : str
        What the row changes (module docstring).
    value : Any
        The new value, in the form the kind expects.
    basis : str
        Where the value comes from.
    """

    label: str
    kind: str
    value: Any
    basis: str = ""

    @property
    def uses_cycle_screening(self) -> bool:
        """True if the row needs the step-4b cycle screening results."""
        if self.kind == "combo":
            return any(k.startswith("cycle") for k, _ in self.value)
        return self.kind.startswith("cycle")


def _check(kind: str, value: Any, where: str) -> Any:
    """Validate one (kind, value) pair; return the value in internal form."""
    if kind not in KINDS:
        raise ValueError(f"{where}: unknown kind '{kind}' (one of {', '.join(KINDS)})")
    if kind in _DICT_KINDS:
        if not isinstance(value, dict):
            raise ValueError(f"{where}: kind '{kind}' needs a dict of overrides")
        return {k: v for k, v in value.items() if not k.startswith("_")}
    if kind in _NUMBER_KINDS:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{where}: kind '{kind}' needs a number")
        return float(value)
    if kind in _NULL_KINDS:
        if value is not None:
            raise ValueError(f"{where}: kind '{kind}' takes no value (null)")
        return None
    # combo
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where}: kind 'combo' needs a list of {{kind, value}}")
    return tuple((p["kind"], _check(p["kind"], p.get("value"), f"{where} (combo)")) for p in value)


def parse_sensitivities(raw: list | None, file_name: str = "case file") -> tuple[Sensitivity, ...]:
    """Read the case file's ``sensitivities`` list; labels must be unique."""
    out, seen = [], set()
    for i, row in enumerate(raw or []):
        where = f"{file_name}: sensitivities[{i}]"
        if "label" not in row or "kind" not in row:
            raise ValueError(f"{where}: needs 'label' and 'kind'")
        if row["label"] in seen:
            raise ValueError(f"{where}: duplicate label '{row['label']}'")
        seen.add(row["label"])
        out.append(Sensitivity(row["label"], row["kind"], _check(row["kind"], row.get("value"), where),
                               row.get("basis", "")))
    return tuple(out)


def _merge(base: dict, override: dict) -> dict:
    """Override merged into base key by key, recursing into dicts, so that a row that changes one field of one
    cost function keeps the others (before 2026-10-17 a 'cost_functions' override replaced the whole block and
    dropped the heat pumps' O&M terms)."""
    out = dict(base)
    for k, v in override.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def apply(case, kind: str, value: Any, selected: dict | None = None):
    """Return a copy of ``case`` with one sensitivity applied.

    ``selected``: cycle screening per unit name (``pinch.cycle_analysis.load_selected``), needed by the
    ``cycle`` kinds.
    """
    if kind == "combo":
        for k, v in value:
            case = apply(case, k, v, selected)
        return case
    if kind == "econ":
        eco = _merge(case.economics or {}, value)
        if "electricity_to_gas_ratio" in value:            # the ratio replaces the electricity price
            eco.pop("electricity_price_EUR_per_kWh", None)
        return replace(case, economics=eco)
    if kind == "eta":
        return replace(case, eta_lorenz=float(value),
                       sink_levels=tuple(replace(lv, eta_lorenz=None) for lv in case.sink_levels))
    if kind in ("cycle", "cycle_scaled"):
        if not selected:
            raise ValueError("cycle-based sensitivities need the cycle screening (screen_cycles.py)")
        k = 1.0 if kind == "cycle" else float(value)
        return replace(case, sink_levels=tuple(replace(lv, eta_lorenz=k * selected[lv.name]["eta_lorenz_cycle"])
                                               if lv.name in selected else lv for lv in case.sink_levels))
    if kind in ("hp_capex", "hx_capex"):
        from pinch.economics import DEFAULT_COST_FUNCTIONS
        key = "heat_pump" if kind == "hp_capex" else "plate_hex"
        cf = copy.deepcopy(case.economics.get("cost_functions", {}))
        base = {**DEFAULT_COST_FUNCTIONS.get(key, {}), **cf.get(key, {})}
        cf[key] = {**base, "alpha": base["alpha"] * value, "beta": base["beta"] * value}
        return replace(case, economics={**case.economics, "cost_functions": cf})
    if kind == "no_om":
        from pinch.economics import NO_OM
        cf = copy.deepcopy(case.economics.get("cost_functions", {}))
        for k, v in NO_OM["cost_functions"].items():
            cf[k] = {**cf.get(k, {}), **v}
        return replace(case, economics={**case.economics, "cost_functions": cf, "boiler_variable_om_EUR_per_MWh": 0.0})
    if kind == "hthp_sink":
        return replace(case, sink_levels=tuple(replace(lv, T_sink_in_C=float(value), T_sink_out_C=float(value))
                                               if "HTHP" in lv.name else lv for lv in case.sink_levels))
    if kind == "area":
        return replace(case, area_targeting={**case.area_targeting, **value})
    if kind == "film":
        at = dict(case.area_targeting)
        at["film_coefficients_kW_per_m2K"] = {k: v * float(value) for k, v in at["film_coefficients_kW_per_m2K"].items()}
        return replace(case, area_targeting=at)
    if kind == "scale":
        f = value / case.basis["production_per_year"]
        retro = copy.deepcopy(case.retrofit)
        if retro and retro.get("storage"):
            retro["storage"]["size_baseline"] *= f          # tank scaled with production, as in Padullés Sec. 5.1
        return replace(case, basis={**case.basis, "production_per_year": value}, retrofit=retro)
    raise ValueError(f"kind '{kind}' cannot be applied directly")
