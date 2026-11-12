"""Candidate streams from an Aspen Plus simulation, for the guided extraction (step 1).

Aspen Plus and Aspen HYSYS are reached from Python only through Windows COM automation, so on the
machine that runs the simulator with its licence (Velázquez et al. 2025, Syst. Control Trans. 4,
1409-1414, Table 1: ``win32com.client.Dispatch('Apwn.Document')``; Santos Bartolome and Van Gerven
2022, Comput. Chem. Eng. 162, 107785, for HYSYS). This app does not drive Aspen. It reads the CSV
export of the published Python-Aspen Plus interface of Maier, Weyand et al. (2025), ESCAPE 35, Syst.
Control Trans. 4, 1631-1636, DOI 10.69997/sct.184450 (code on Zenodo), which writes one folder per
simulation run::

    <run>/blocks/Heater.csv    Heater blocks: inlet F(IN), outlet P(OUT), ('qcalc', <unit>), ('temperature', <unit>)
    <run>/blocks/HeatX.csv     two-stream exchangers: C(IN), C(OUT), H(IN), H(OUT), ('duty', <unit>)
    <run>/streams/MATERIAL.csv material streams: name, ('temperature', <unit>), ('vfrac', '1'), ('mass_flow', <unit>)

Units are read from the column headers and converted with Pint (``pinch.units``). Each Heater
block becomes one candidate stream (supply = its inlet stream temperature, target = its outlet
temperature, duty = its calculated duty, signed as Aspen gives it: + heat added); each HeatX block
becomes two (its hot and its cold side), since an existing exchanger's duty is heat already
recovered. The candidates go into the extraction table for review (``pinch.extraction``): which
heaters are genuine process requirements and which belong to the utility system (steam raising,
cooling water) is the engineer's call, as Varbanov et al. (2019) stress for automated extraction.

Left out automatically, with the reason recorded: blocks with no duty, blocks with several inlets
(mixing at the inlet; extract the streams before they mix), and blocks whose inlet temperature is
not in the stream results. A change of vapour fraction across a block is flagged: constant CP over a
phase change is a simplification (segment it with ``pinch.streams.segments_from_TH``).

Aspen's "cal" is read as Pint's thermochemical calorie (4.184 J); if the simulation used the
international-table calorie (4.1868 J) the duties are 0.07 % low.
"""

from __future__ import annotations

import ast
import io
import math
import zipfile
from pathlib import Path, PurePosixPath

import pandas as pd

from pinch.extraction import COLUMNS

_FILES = ("blocks/Heater.csv", "blocks/HeatX.csv", "streams/MATERIAL.csv")


def _header(col: str) -> tuple[str, str] | None:
    """('qcalc', 'cal/sec') from the header text "('qcalc', 'cal/sec')"; None for plain headers."""
    if not col.startswith("("):
        return None
    try:
        v = ast.literal_eval(col)
    except (ValueError, SyntaxError):
        return None
    return (str(v[0]), str(v[1])) if isinstance(v, tuple) and len(v) == 2 else None


def _quantity(df: pd.DataFrame, name: str, kinds: tuple[str, ...]) -> tuple[str, str] | None:
    """(column, unit) of quantity ``name`` with a physical unit (not '1'); kinds = accepted unit families."""
    for c in df.columns:
        h = _header(str(c))
        if h and h[0] == name and h[1] != "1":
            return str(c), h[1]
    return None


def _unit(u: str) -> str:
    """Aspen unit text to Pint: 'cal/sec' -> 'cal/s', 'C' -> 'degC', 'K' -> 'kelvin', 'F' -> 'degF'."""
    return {"C": "degC", "K": "kelvin", "F": "degF", "R": "degR"}.get(u, u.replace("sec", "s").replace("hr", "h"))


def _ids(x) -> list[str]:
    if isinstance(x, str) and x.startswith("["):
        try:
            return [str(v) for v in ast.literal_eval(x)]
        except (ValueError, SyntaxError):
            return [x]
    return [] if x is None or (isinstance(x, float) and math.isnan(x)) else [str(x)]


def list_runs(source: str | Path | bytes) -> list[str]:
    """Run folders in an export (a folder, or a .zip given as path or bytes) that contain the three files."""
    names = _names(source)
    runs = sorted({str(PurePosixPath(n).parent.parent) for n in names if n.endswith(_FILES[2])})
    return [r for r in runs if all(f"{r}/{f}" in names or (r == "." and f in names) for f in _FILES)]


#: Largest uncompressed size of an uploaded archive [bytes] (a guard against zip bombs)
MAX_UNZIPPED_BYTES = 500_000_000


def _names(source) -> set[str]:
    if isinstance(source, (bytes, bytearray)) or str(source).lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED_BYTES:
                raise ValueError(f"archive larger than {MAX_UNZIPPED_BYTES / 1e6:.0f} MB once unpacked")
            return {n for n in z.namelist() if not n.endswith("/")}
    root = Path(source)
    return {p.relative_to(root).as_posix() for p in root.rglob("*.csv")}


def _read(source, run: str, rel: str) -> pd.DataFrame:
    name = rel if run in ("", ".") else f"{run}/{rel}"
    if isinstance(source, (bytes, bytearray)) or str(source).lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source) as z:
            with z.open(name) as f:
                return pd.read_csv(f)
    return pd.read_csv(Path(source) / name)


def candidates(source: str | Path | bytes, run: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Extraction records (``pinch.extraction.COLUMNS``, duty in kW) from one run of an export, and notes."""
    from pinch.units import convert
    runs = list_runs(source)
    if not runs:
        raise ValueError("no run folder with blocks/Heater.csv, blocks/HeatX.csv and streams/MATERIAL.csv")
    run = run or runs[0]
    if run not in runs:
        raise ValueError(f"run '{run}' not found (runs: {runs})")
    mat = _read(source, run, _FILES[2])
    t_col = _quantity(mat, "temperature", ())
    if t_col is None:
        raise ValueError("streams/MATERIAL.csv has no temperature column with a unit")
    temps = dict(zip(mat["name"].astype(str), convert(mat[t_col[0]], _unit(t_col[1]), "degC")))
    vf = _quantity_plain(mat, "vfrac")
    vfrac = dict(zip(mat["name"].astype(str), pd.to_numeric(mat[vf], errors="coerce"))) if vf else {}
    rows, notes = [], [f"run {run}: {len(mat)} material streams"]

    def record(include, name, fid, Ts, Tt, duty_kW, reason):
        rows.append({"include": include, "stream": name, "flowsheet_id": fid, "T_supply_C": Ts, "T_target_C": Tt,
                     "duty": duty_kW, "mass_flow_kg_s": math.nan, "cp_kJ_kgK": math.nan, "latent_kJ_kg": math.nan,
                     "dT_shift_K": math.nan, "soft_target": False, "reasoning": reason})

    heaters = _read(source, run, _FILES[0])
    q = _quantity(heaters, "qcalc", ())
    t_out = _quantity(heaters, "temperature", ())
    if q is None or t_out is None:
        raise ValueError("blocks/Heater.csv needs ('qcalc', unit) and ('temperature', unit) columns")
    duties = convert(heaters[q[0]].fillna(0.0), _unit(q[1]), "kW")
    outs = convert(heaters[t_out[0]], _unit(t_out[1]), "degC")
    for (_, h), duty, Tt in zip(heaters.iterrows(), duties, outs):
        name, ins, outs_ids = str(h["name"]), _ids(h.get("F(IN)")), _ids(h.get("P(OUT)"))
        fid = f"{', '.join(ins)} → {', '.join(outs_ids)} (Heater {name})"
        if not duty:
            record(False, name, fid, math.nan, Tt, 0.0, "no duty in the simulation")
            continue
        if len(ins) != 1:
            record(False, name, fid, math.nan, Tt, duty,
                   f"{len(ins)} inlets: mixing at the inlet; extract the streams before they mix (non-isothermal mixing)")
            continue
        Ts = temps.get(ins[0], math.nan)
        if not math.isfinite(Ts) or not math.isfinite(Tt):
            record(False, name, fid, Ts, Tt, duty, "inlet or outlet temperature missing in the stream results")
            continue
        reason = (f"Aspen Plus Heater block {h.get('path', name)}: duty and temperatures from the simulation. Review: "
                  "genuine process requirement or utility system? soft target?")
        v_in, v_out = vfrac.get(ins[0], math.nan), vfrac.get(outs_ids[0], math.nan) if outs_ids else math.nan
        if math.isfinite(v_in) and math.isfinite(v_out) and abs(v_in - v_out) > 1e-3:
            reason += f" Phase change (vapour fraction {v_in:.2f} → {v_out:.2f}): constant CP is a simplification."
        if Ts == Tt and duty == 0:
            continue
        record(True, name, fid, Ts, Tt, duty, reason)

    hx = _read(source, run, _FILES[1])
    qd = _quantity(hx, "duty", ())
    if len(hx) and qd is not None:
        for (_, x), duty in zip(hx.iterrows(), convert(hx[qd[0]].fillna(0.0), _unit(qd[1]), "kW")):
            name = str(x["name"])
            for side, sign in (("H", -1.0), ("C", 1.0)):
                i, o = _ids(x.get(f"{side}(IN)")), _ids(x.get(f"{side}(OUT)"))
                fid = f"{', '.join(i)} → {', '.join(o)} (HeatX {name}, {'hot' if side == 'H' else 'cold'} side)"
                Ts = temps.get(i[0], math.nan) if len(i) == 1 else math.nan
                Tt = temps.get(o[0], math.nan) if len(o) == 1 else math.nan
                ok = math.isfinite(Ts) and math.isfinite(Tt) and duty > 0
                record(ok, f"{name} {'hot' if side == 'H' else 'cold'}", fid, Ts, Tt, sign * abs(duty),
                       "existing exchanger: its duty is heat already recovered; keep both sides to target the whole "
                       "process" if ok else "temperatures or duty missing in the results")
    out = pd.DataFrame(rows, columns=list(COLUMNS))
    notes.append(f"{int(out['include'].sum())} candidate streams, {int((~out['include']).sum())} left out with a reason")
    return out, notes


def _quantity_plain(df: pd.DataFrame, name: str) -> str | None:
    for c in df.columns:
        h = _header(str(c))
        if h and h[0] == name:
            return str(c)
    return None
