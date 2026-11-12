"""Guided stream data extraction (step 1): from process data to the stream table, with the reasoning kept.

Data extraction decides which heating and cooling duties enter the pinch analysis and at which
temperatures. Varbanov, Yong, Klemeš and Chin (2019), "Data Extraction for Heat Integration and Total
Site Analysis: A Review", CET 76, 67-72, DOI 10.3303/CET1976012, summarise the rules of Linnhoff et
al.'s User Guide (1994) and the Handbook of Process Integration (Klemeš 2013): extract genuine
heating and cooling requirements, recognise "soft" target temperatures, avoid non-isothermal mixing,
strive for accurate data near the pinch, and leave out parts that must stay separate for safety.
They also propose keeping, for every stream, its flowsheet identifiers and the reasoning for its
selection (their Table 1), plus a table of the streams left out with a note each, so that the
choices can be traced and changed. Automated extraction from a simulator captures the streams but
not that reasoning, which stays the engineer's job.

This module implements that record (``COLUMNS``) and turns it into the model's stream table:

* type from the temperatures (hot if T_supply > T_target);
* heat load from the duty, or from mass flow × specific heat × ΔT plus mass flow × latent heat;
  if both are given they must agree within ``DUTY_TOLERANCE``;
* a duty at one temperature (boiling, condensation) over a 1 K interval, as in the brewery case:
  cold T → T + 1, hot T → T − 1 (on the safe side: the hot stream gives its heat 1 K lower); the duty
  must then be signed (+ heat added, − heat removed, the simulator convention);
* checks, as warnings: missing reasoning, a flowsheet stream that is the inlet (or the outlet) of two
  records (extracted twice); a stream that is one record's outlet and the next one's inlet is a chain of
  heaters or coolers on one stream and is fine. Flowsheet identifiers are written "in → out (block)".

``near_pinch`` lists the streams whose shifted range comes within a margin of the pinch: where the
User Guide (via Varbanov et al. 2019) says data accuracy matters most, and where Bergamini et al.
(2019, Front. Energy Res. 7:108) found the temperatures that drive the target uncertainty.
"""

from __future__ import annotations

import math
import re

import pandas as pd

from pinch.streams import StreamSet

#: Columns of an extraction record (one row per candidate stream). Units: °C, K, kg/s, kJ/(kg K), kJ/kg;
#: duty in the unit chosen for the table (``extract(..., energy_unit=...)``).
COLUMNS = ("include", "stream", "flowsheet_id", "T_supply_C", "T_target_C", "duty", "mass_flow_kg_s",
           "cp_kJ_kgK", "latent_kJ_kg", "dT_shift_K", "soft_target", "reasoning")
DUTY_TOLERANCE = 0.05
LATENT_INTERVAL_K = 1.0
#: kW per (kg/s × kJ/kg); other units of the duty column are converted with pinch.units
_KW = 1.0


def empty_record() -> pd.DataFrame:
    """An empty extraction table with the right columns and types (for editors and templates)."""
    return normalise(pd.DataFrame(columns=list(COLUMNS)))


def normalise(records: pd.DataFrame) -> pd.DataFrame:
    """Records with exactly ``COLUMNS`` and fixed types (text, true/false, numbers), e.g. for an editable table."""
    out = records.reindex(columns=list(COLUMNS)).copy()
    for c in ("stream", "flowsheet_id", "reasoning"):
        out[c] = out[c].map(lambda x: "" if x is None or (isinstance(x, float) and math.isnan(x)) else str(x))
    for c in ("include", "soft_target"):
        out[c] = out[c].map(_truthy).astype(bool)
    for c in COLUMNS:
        if c not in ("stream", "flowsheet_id", "reasoning", "include", "soft_target"):
            out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
    return out.reset_index(drop=True)


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v


def _truthy(x) -> bool:
    if isinstance(x, str):
        return x.strip().lower() in ("1", "true", "yes", "y", "x")
    return bool(x) and not (isinstance(x, float) and math.isnan(x))


def extract(records: pd.DataFrame, energy_unit: str = "kW", default_dT_shift_K: float = 5.0
            ) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Stream table, excluded-streams table and warnings from extraction records.

    Parameters
    ----------
    records : table with ``COLUMNS`` (missing optional columns are treated as empty).
    energy_unit : unit of the ``duty`` column and of the stream table (kW, MW, or any power unit Pint knows;
        powers other than W, kW, MW are converted to kW). Mass-flow based loads are computed in kW first.
    default_dT_shift_K : shift for rows that leave ``dT_shift_K`` empty.

    Returns
    -------
    streams : columns stream, type, T_in_C, T_out_C, Q_<unit>, dT_shift_K, note (ready for
        ``pinch.streams.streams_from_frame``).
    excluded : columns stream, flowsheet_id, reasoning.
    warnings : list of messages (the table is still built).

    Raises
    ------
    ValueError for a row that cannot become a stream (no temperatures, no load, a load that disagrees,
    an excluded row without a reason).
    """
    from pinch.units import _energy_label, _target, convert, registry
    rec = records.copy()
    for c in COLUMNS:
        if c not in rec.columns:
            rec[c] = math.nan
    unit = registry().parse_units(energy_unit.replace("_per_", "/"))
    target = _target(unit)
    label = _energy_label(target)
    kw_to_target = float(convert(1.0, "kW", str(target))) if target.dimensionality == registry().watt.dimensionality \
        else None
    duty_factor = float(convert(1.0, str(unit), str(target)))

    rows, excluded, warnings = [], [], []
    seen_ids: dict[tuple[str, str], str] = {}
    for i, r in rec.reset_index(drop=True).iterrows():
        name = str(r["stream"]).strip() if isinstance(r["stream"], str) and r["stream"].strip() else f"row {i + 1}"
        reason = str(r["reasoning"]).strip() if isinstance(r["reasoning"], str) else ""
        fid = str(r["flowsheet_id"]).strip() if isinstance(r["flowsheet_id"], str) else ""
        if not _truthy(r["include"]):
            if not reason:
                raise ValueError(f"{name}: excluded without a reason (record why it is left out)")
            excluded.append({"stream": name, "flowsheet_id": fid, "reasoning": reason})
            continue
        Ts, Tt = _num(r["T_supply_C"]), _num(r["T_target_C"])
        if not (math.isfinite(Ts) and math.isfinite(Tt)):
            raise ValueError(f"{name}: give the supply and target temperatures")
        m, cp, lat = _num(r["mass_flow_kg_s"]), _num(r["cp_kJ_kgK"]), _num(r["latent_kJ_kg"])
        q_flow = None
        if math.isfinite(m):
            sensible = m * cp * abs(Tt - Ts) if math.isfinite(cp) else 0.0
            latent = m * lat if math.isfinite(lat) else 0.0
            if sensible + latent > 0:
                if kw_to_target is None:
                    raise ValueError(f"{name}: a mass-flow based load needs a power unit, not {energy_unit}")
                q_flow = (sensible + latent) * _KW * kw_to_target
        duty = _num(r["duty"])
        q_duty = abs(duty) * duty_factor if math.isfinite(duty) and duty != 0 else None
        if q_duty is None and q_flow is None:
            raise ValueError(f"{name}: give the duty, or the mass flow with cp (and latent heat)")
        if q_duty is not None and q_flow is not None and abs(q_duty - q_flow) > DUTY_TOLERANCE * max(q_duty, q_flow):
            raise ValueError(f"{name}: duty {q_duty:.4g} and mass flow x cp {q_flow:.4g} {label} differ by more "
                             f"than {100 * DUTY_TOLERANCE:.0f} %")
        Q = q_duty if q_duty is not None else q_flow
        assert Q is not None
        if Ts == Tt:
            if not math.isfinite(duty) or duty == 0:
                raise ValueError(f"{name}: at one temperature, give a signed duty (+ heat added, − heat removed)")
            kind = "cold" if duty > 0 else "hot"
            T_in, T_out = (Ts, Ts + LATENT_INTERVAL_K) if kind == "cold" else (Ts, Ts - LATENT_INTERVAL_K)
            warnings.append(f"{name}: duty at one temperature modelled over {LATENT_INTERVAL_K:g} K ({T_in:g} → {T_out:g} °C)")
        else:
            kind = "hot" if Ts > Tt else "cold"
            T_in, T_out = Ts, Tt
            if math.isfinite(lat) and lat > 0:
                warnings.append(f"{name}: latent heat spread over {Ts:g}-{Tt:g} °C at constant CP; split it into "
                                "segments (segment_of) if the phase change sits at one temperature")
        dT = _num(r["dT_shift_K"])
        note = "; ".join(x for x in (f"flowsheet: {fid}" if fid else "", reason,
                                     "soft target" if _truthy(r["soft_target"]) else "") if x)
        if not reason:
            warnings.append(f"{name}: no reasoning recorded (why is this a genuine heating or cooling requirement?)")
        if fid:
            ends = re.sub(r"\(.*?\)", "", fid).split("→")
            for side, text in zip(("in", "out"), ends):
                for part in (p.strip() for p in re.split(r"[,;]", text)):
                    if not part:
                        continue
                    if (side, part) in seen_ids:
                        warnings.append(f"{name}: flowsheet stream '{part}' is also the {side}let of "
                                        f"{seen_ids[(side, part)]} (extracted twice?)")
                    else:
                        seen_ids[(side, part)] = name
        rows.append({"stream": name, "type": kind, "T_in_C": T_in, "T_out_C": T_out, f"Q_{label}": Q,
                     "dT_shift_K": dT if math.isfinite(dT) else default_dT_shift_K, "note": note})
    if not rows:
        raise ValueError("no stream included")
    names = [str(r["stream"]) for r in rows]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"duplicate stream names: {dup}")
    return (pd.DataFrame(rows), pd.DataFrame(excluded, columns=["stream", "flowsheet_id", "reasoning"]), warnings)


def near_pinch(streams: StreamSet, pinch_T_star_C: list[float] | tuple[float, ...], margin_K: float = 10.0) -> list[str]:
    """Streams whose shifted temperature range comes within ``margin_K`` of a pinch: measure these carefully."""
    out = []
    for s in streams.streams:
        lo, hi = sorted((s.T_star_in_C, s.T_star_out_C))
        if any(lo - margin_K <= p <= hi + margin_K for p in pinch_T_star_C):
            out.append(s.name)
    return out
