"""Process diagrams of a case as SVG: a simplified flowsheet and a shifted-temperature stream diagram.

Two pictures of the same stream table, both drawn in four views:

* ``process``: the material flow (flowsheet) or the streams on the T* axis;
* ``energy``: the heat each step needs or releases (flowsheet) or the energy
  targets Q̇h,min, Q̇c,min and recovery against the streams (T* diagram);
* ``heat_pumps``: the heat pump units of step 4, where they deliver heat and
  where their source heat comes from;
* ``all``: every layer at once.

The flowsheet needs a layout file, ``data/<case>_flowsheet.json``, because a
stream table has no material connections. The file lists the process steps
(grid position, the stream rows each step owns), the material flows and, for
each heat pump unit of the case, the steps it serves and draws its source heat
from. Those heat pump connections are **indicative**: which unit serves which
step is fixed only by the network design (step 5). Heat duties are always
taken from the current stream table, so the tags follow the user's edits.

The T* diagram needs no layout file and is drawn for any case.

Colour meaning follows ``pinch.theme``: red for hot streams and heat release,
blue for cold streams and heat demand, the accent colour (teal) for heat pumps,
grey for material flow and reference lines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path
from typing import Literal

import pandas as pd

from pinch.streams import Stream, StreamSet
from pinch.theme import LIGHT, Palette

View = Literal["process", "energy", "heat_pumps", "all"]
VIEWS: tuple[View, ...] = ("process", "energy", "heat_pumps", "all")
VIEW_LABELS: dict[View, str] = {"process": "Process", "energy": "Energy balance",
                                "heat_pumps": "With heat pumps", "all": "All at once"}

# Opacity of (base layer, energy layer, heat pump layer) per view; 0 = not drawn.
_OPACITY: dict[View, tuple[float, float, float]] = {
    "process": (1.0, 0.0, 0.0), "energy": (1.0, 1.0, 0.0),
    "heat_pumps": (0.45, 0.25, 1.0), "all": (1.0, 1.0, 1.0)}

WIDTH = 680                  # SVG user units (1:1 with CSS px at full width)
_BOX_W, _BOX_H = 112, 44     # process step box
_COL_DX, _ROW_DY = 142, 110  # grid pitch
_X0, _Y0 = 84, 60            # top-left box (room for feed and product labels on the left)


# ------------------------------------------------------------------ stream identifiers
def stream_ids(stream_set: StreamSet) -> dict[str, str]:
    """Short identifiers H1, H2, ... and C1, C2, ... in the order of the stream table.

    The same identifiers label both diagrams, so a tag on the flowsheet can be
    found on the T* diagram and in the stream table.
    """
    ids: dict[str, str] = {}
    for prefix, group in (("H", stream_set.hot), ("C", stream_set.cold)):
        for i, s in enumerate(group, start=1):
            ids[s.name] = f"{prefix}{i}"
    return ids


# ------------------------------------------------------------------ layout file
@dataclass(frozen=True)
class Step:
    """One process step of the flowsheet."""

    name: str
    row: int
    col: int
    streams: tuple[str, ...] = ()        # stream-table rows (column ``stream``) owned by this step
    subtitle: str = ""                   # e.g. "Sparge 15→75 °C"; computed from the streams if empty
    width: int = _BOX_W

    @property
    def x(self) -> float:
        return _X0 + _COL_DX * self.col

    @property
    def y(self) -> float:
        return _Y0 + _ROW_DY * self.row

    @property
    def cx(self) -> float:
        return self.x + self.width / 2


@dataclass(frozen=True)
class HeatPumpLink:
    """Where one heat pump unit (a row of ``heat_pump_design``) is drawn and what it connects to."""

    unit: str
    label: str
    row: int
    col: int
    serves: tuple[str, ...]              # step names receiving the sink heat (indicative)


@dataclass(frozen=True)
class Flowsheet:
    """Simplified flowsheet layout of one case (see the module docstring)."""

    case: str
    steps: tuple[Step, ...]
    flows: tuple[tuple[str, str, str], ...]   # (from step, to step, label); "" = feed or product
    feed_label: str = ""
    product_label: str = ""
    heat_pumps: tuple[HeatPumpLink, ...] = ()
    process_sources: tuple[str, ...] = ()  # steps whose sub-ambient release feeds the heat pump sources
    source_label: str = "Process heat below the pinch"
    note: str = ""
    extra: dict = field(default_factory=dict)

    def step(self, name: str) -> Step:
        for s in self.steps:
            if s.name == name:
                return s
        raise KeyError(f"flowsheet of '{self.case}' has no step '{name}'")

    @property
    def rows(self) -> int:
        cells = [(s.row) for s in self.steps] + [h.row for h in self.heat_pumps]
        return max(cells) + 1


def flowsheet_path(root: Path, case_name: str) -> Path:
    """Conventional location of a case's layout file."""
    return root / "data" / f"{case_name}_flowsheet.json"


def load_flowsheet(path: str | Path) -> Flowsheet:
    """Read and check a layout file (``data/<case>_flowsheet.json``)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    steps = tuple(Step(name=s["name"], row=int(s["row"]), col=int(s["col"]),
                       streams=tuple(s.get("streams", [])), subtitle=s.get("subtitle", ""),
                       width=int(s.get("width", _BOX_W))) for s in raw["steps"])
    hps = tuple(HeatPumpLink(unit=h["unit"], label=h["label"], row=int(h["row"]), col=int(h["col"]),
                             serves=tuple(h.get("serves", []))) for h in raw.get("heat_pumps", []))
    fs = Flowsheet(case=raw["case"], steps=steps, flows=tuple((f[0], f[1], f[2] if len(f) > 2 else "") for f in raw["flows"]),
                   feed_label=raw.get("feed_label", ""), product_label=raw.get("product_label", ""),
                   heat_pumps=hps, process_sources=tuple(raw.get("process_sources", [])),
                   source_label=raw.get("source_label", "Process heat below the pinch"),
                   note=raw.get("note", ""))
    check_flowsheet(fs)
    return fs


def check_flowsheet(fs: Flowsheet) -> None:
    """Raise ``ValueError`` on an inconsistent layout (unknown step, overlap, off-canvas, stream twice)."""
    names = [s.name for s in fs.steps]
    if len(set(names)) != len(names):
        raise ValueError("duplicate step names in the flowsheet")
    cells = [(s.row, s.col) for s in fs.steps] + [(h.row, h.col) for h in fs.heat_pumps]
    if len(set(cells)) != len(cells):
        raise ValueError("two boxes share one grid cell")
    for s in fs.steps:
        if not 0 <= s.col <= 3 or s.row < 0:
            raise ValueError(f"step '{s.name}' is off the grid (columns 0-3)")
    for h in fs.heat_pumps:
        if not 0 <= h.col <= 3 or h.row < 0:
            raise ValueError(f"heat pump '{h.unit}' is off the grid (columns 0-3)")
    known = set(names) | {""}
    for a, b, _ in fs.flows:
        if b and not a and fs.step(b).col != 0:
            raise ValueError(f"feed into '{b}': feeds enter from the left, so the step must be in column 0")
        if a not in known or b not in known or a == b == "":
            raise ValueError(f"flow {a!r} -> {b!r} names an unknown step")
    for h in fs.heat_pumps:
        for n in h.serves:
            if n not in names:
                raise ValueError(f"heat pump '{h.unit}' serves unknown step '{n}'")
    for n in fs.process_sources:
        if n not in names:
            raise ValueError(f"unknown source step '{n}'")
    owned = [r for s in fs.steps for r in s.streams]
    if len(set(owned)) != len(owned):
        raise ValueError("a stream row is assigned to two steps")


GENERIC_NOTE = ("Generic layout: one box per stream (cold streams above, hot streams below); the stream table has no "
                "material connections, so none are drawn. Heat pump links are indicative.")


def generic_flowsheet(stream_set: StreamSet, heat_pumps: pd.DataFrame | None = None,
                      case: str = "uploaded table") -> Flowsheet:
    """Flowsheet for a stream table without a layout file (uploads): one box per stream row.

    Cold streams fill the rows above the heat pump row, four per row, hot streams the rows below it.
    A heat pump is linked to the cold streams in the row just above it whose temperature range
    overlaps its sink range (indicative); its process source is shown as a labelled stub.
    """
    def rows_of(streams: list[Stream], first_row: int) -> list[Step]:
        return [Step(name=s.name if len(s.name) <= 16 else s.name[:15] + "…", row=first_row + i // 4, col=i % 4,
                     streams=(s.name,)) for i, s in enumerate(streams)]

    cold, hot = list(stream_set.cold), list(stream_set.hot)
    n_cold_rows = max(1, -(-len(cold) // 4))
    hp_row = n_cold_rows
    units = [] if heat_pumps is None else [r for _, r in heat_pumps.head(4).iterrows()]
    hot_first = hp_row + (1 if units else 0)
    cold_steps, hot_steps = rows_of(cold, 0), rows_of(hot, hot_first)
    names: set[str] = set()
    steps = []
    for st in cold_steps + hot_steps:           # truncated names must stay unique
        name, i = st.name, 2
        while name in names:
            name, i = f"{st.name[:13]} {i}", i + 1
        names.add(name)
        steps.append(replace(st, name=name))
    by_stream = {st.streams[0]: st for st in steps}
    links = []
    for k, r in enumerate(units):
        lo, hi = float(r["T_sink_in_C"]), float(r["T_sink_out_C"])
        serves = tuple(by_stream[s.name].name for s in cold
                       if by_stream[s.name].row == hp_row - 1 and s.T_in_C < hi and s.T_out_C > lo - 20)
        links.append(HeatPumpLink(unit=str(r["unit"]), label=f"HP{k + 1}", row=hp_row, col=k, serves=serves))
    return Flowsheet(case=case, steps=tuple(steps), flows=(), heat_pumps=tuple(links), note=GENERIC_NOTE)


def unassigned_streams(fs: Flowsheet, stream_set: StreamSet) -> list[str]:
    """Stream rows of the table that no step owns (e.g. rows added by the user)."""
    owned = {r for s in fs.steps for r in s.streams}
    return [s.name for s in stream_set.streams if s.name not in owned]


# ------------------------------------------------------------------ SVG helpers
def _fmt(x: float) -> str:
    """Three significant figures, without scientific notation (kW cases reach 10^4)."""
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    return f"{x:.3g}"


def _id_list(ids: list[str]) -> str:
    """'H2+H7–11' for H2, H7, H8, H9, H10, H11: consecutive identifiers collapse into a range."""
    nums = sorted((i[0], int(i[1:])) for i in ids)
    parts, run = [], [nums[0]]
    for prev, cur in zip(nums, nums[1:]):
        if cur[0] == prev[0] and cur[1] == prev[1] + 1:
            run.append(cur)
            continue
        parts.append(run)
        run = [cur]
    parts.append(run)
    return "+".join("+".join(f"{k}{n}" for k, n in r) if len(r) < 3 else f"{r[0][0]}{r[0][1]}–{r[-1][1]}"
                    for r in parts)


def _txt(x: float, y: float, s: str, fill: str, size: int = 12, anchor: str = "middle",
         weight: int = 400) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" dominant-baseline="central">{escape(s)}</text>')


def _defs(p: Palette) -> str:
    def m(mid: str, colour: str) -> str:
        return (f'<marker id="{mid}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
                f'orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="{colour}" '
                f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker>')
    return ("<defs>" + m("a-flow", p.grey) + m("a-hot", p.hot) + m("a-cold", p.cold)
            + m("a-hp", p.accent) + m("a-ink", p.ink) + "</defs>")


def _box(x: float, y: float, w: float, title: str, sub: str, p: Palette, stroke: str | None = None,
         tip: str = "") -> str:
    t = f"<title>{escape(tip)}</title>" if tip else ""
    return (f"<g>{t}<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{_BOX_H}' rx='4' "
            f"fill='{p.secondary_background}' stroke='{stroke or p.border}' stroke-width='{1 if stroke else 0.5}'/>"
            + _txt(x + w / 2, y + 15, title, p.text, 14, weight=500)
            + _txt(x + w / 2, y + 32, sub, p.text if stroke else p.grey, 12) + "</g>")


def _path(d: str, colour: str, marker: str = "", dash: str = "", width: float = 1.5, tip: str = "") -> str:
    m = f' marker-end="url(#{marker})"' if marker else ""
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    t = f"<title>{escape(tip)}</title>" if tip else ""
    return f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}"{ds}{m}>{t}</path>'


def _layer(body: list[str], opacity: float) -> str:
    return f'<g opacity="{opacity:g}">' + "".join(body) + "</g>" if opacity else ""


def _svg(height: float, title: str, desc: str, p: Palette, body: str, uid: str) -> str:
    """Whole SVG document; marker ids get the prefix ``uid`` so two diagrams can share a page."""
    defs = _defs(p).replace('id="a-', f'id="{uid}-')
    body = body.replace("url(#a-", f"url(#{uid}-")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {WIDTH} {height:.0f}" '
            f'role="img" style="font-family: inherit; max-width: {WIDTH * 1.4:.0f}px">'
            f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>{defs}{body}</svg>")


def _temperatures(streams: list[Stream]) -> str:
    if not streams:
        return ""
    a = streams[0].T_in_C
    b = streams[-1].T_out_C
    return f"{a:g}→{b:g} °C"


# ------------------------------------------------------------------ flowsheet
def _flow_path(a: Step, b: Step) -> str:
    """Material-flow path between two step boxes: straight when adjacent, else via the gap on the right."""
    if a.row == b.row:
        if b.col > a.col:
            return f"M{a.x + a.width:.1f} {a.y + _BOX_H / 2:.1f} L{b.x - 2:.1f} {b.y + _BOX_H / 2:.1f}"
        return f"M{a.x:.1f} {a.y + _BOX_H / 2:.1f} L{b.x + b.width + 2:.1f} {b.y + _BOX_H / 2:.1f}"
    if a.col == b.col and abs(a.row - b.row) == 1:
        y1, y2 = (a.y + _BOX_H, b.y - 2) if b.row > a.row else (a.y, b.y + _BOX_H + 2)
        return f"M{a.cx:.1f} {y1:.1f} L{a.cx:.1f} {y2:.1f}"
    gx = max(a.x + a.width, b.x + b.width) + 12          # side route through the right-hand gap
    return (f"M{a.x + a.width:.1f} {a.y + _BOX_H / 2:.1f} L{gx:.1f} {a.y + _BOX_H / 2:.1f} "
            f"L{gx:.1f} {b.y + _BOX_H / 2:.1f} L{b.x + b.width + 2:.1f} {b.y + _BOX_H / 2:.1f}")


def flowsheet_svg(fs: Flowsheet, stream_set: StreamSet, heat_pumps: pd.DataFrame | None = None,
                  view: View = "all", palette: Palette = LIGHT) -> str:
    """Simplified flowsheet of the case as an SVG string.

    Parameters
    ----------
    fs : layout from ``load_flowsheet``.
    stream_set : the current stream table (heat duties of the tags come from here).
    heat_pumps : the ``heat_pump_design`` table of ``analyse.compute`` (columns ``unit``, ``COP``,
        ``Q_sink_<unit>``, ``W_<unit>``, ``source_from_process_<unit>``, ``source_external_<unit>``);
        units without a layout entry are not drawn.
    view : one of ``VIEWS``.
    palette : ``pinch.theme.LIGHT`` or ``DARK``.
    """
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")
    p, u = palette, stream_set.energy_unit
    ids = stream_ids(stream_set)
    by_name = {s.name: s for s in stream_set.streams}
    op_base, op_energy, op_hp = _OPACITY[view]
    base: list[str] = []
    energy: list[str] = []
    hp: list[str] = []

    for s in fs.steps:
        own = [by_name[n] for n in s.streams if n in by_name]
        sub = s.subtitle or _temperatures(own)
        tip = "; ".join(f"{ids[x.name]} {x.name}: {x.T_in_C:g}→{x.T_out_C:g} °C, {_fmt(x.Q)} {u}" for x in own)
        base.append(_box(s.x, s.y, s.width, s.name, sub, p, tip=tip or s.name))
        for kind, colour, sign in (("cold", p.cold, "+"), ("hot", p.hot, "−")):
            rows = [x for x in own if x.kind == kind]
            if not rows:
                continue
            label = _id_list([ids[x.name] for x in rows]) + f" {sign}{_fmt(sum(x.Q for x in rows))}"
            tw = max(96.0, min(float(s.width), 7.0 * len(label) + 10))
            ty = s.y - 24 if s.row == 0 else s.y + _BOX_H + 8
            tx = s.x
            if any(x.kind == "cold" for x in own) and kind == "hot":
                ty += -20 if s.row == 0 else 20
            energy.append(f"<g><title>{escape(('Heat demand' if kind == 'cold' else 'Heat release') + f' [{u}]')}"
                          f"</title><rect x='{tx:.1f}' y='{ty:.1f}' width='{tw:.0f}' height='18' rx='4' "
                          f"fill='{p.background}' stroke='{colour}' stroke-width='1'/>"
                          + _txt(tx + tw / 2, ty + 9, label, colour, 12) + "</g>")

    for a, b, label in fs.flows:
        if a and b:
            base.append(_path(_flow_path(fs.step(a), fs.step(b)), p.grey, "a-flow"))
        elif b:                                         # feed, from the left margin
            t = fs.step(b)
            base.append(_path(f"M12 {t.y + _BOX_H / 2:.1f} L{t.x - 2:.1f} {t.y + _BOX_H / 2:.1f}", p.grey, "a-flow"))
            base.append(_txt(10, t.y + _BOX_H / 2 - 12, label or fs.feed_label, p.grey, 12, "start"))
        elif fs.step(a).col == 0:                       # product, to the left margin
            f = fs.step(a)
            base.append(_path(f"M{f.x:.1f} {f.y + _BOX_H / 2:.1f} L14 {f.y + _BOX_H / 2:.1f}", p.grey, "a-flow"))
            base.append(_txt(10, f.y + _BOX_H / 2 + 14, label or fs.product_label, p.grey, 12, "start"))
        else:                                           # product, to the right of the step
            f = fs.step(a)
            x0 = f.x + f.width
            base.append(_path(f"M{x0:.1f} {f.y + _BOX_H / 2:.1f} L{x0 + 26:.1f} {f.y + _BOX_H / 2:.1f}", p.grey,
                              "a-flow"))
            base.append(_txt(x0 + 4, f.y + _BOX_H / 2 - 12, label or fs.product_label, p.grey, 12, "start"))

    rows_hp = {} if heat_pumps is None else {r["unit"]: r for _, r in heat_pumps.iterrows()}
    links = [h for h in fs.heat_pumps if h.unit in rows_hp]
    src_y = None
    if fs.process_sources:
        src_steps = [fs.step(n) for n in fs.process_sources]
        src_y = _Y0 + _ROW_DY * max(s.row for s in src_steps) - 30   # header above the lowest source row
    for k, h in enumerate(links):
        r = rows_hp[h.unit]
        hx = _X0 + _COL_DX * h.col
        hy = _Y0 + _ROW_DY * h.row
        hcx = hx + _BOX_W / 2
        hy_head = _Y0 + _ROW_DY * h.row - 40 + 15 * k          # this unit's distribution header
        drops = []
        for n in h.serves:
            s = fs.step(n)
            dx = s.cx - 30 * k
            y_end = s.y + _BOX_H + 2 if s.y < hy_head else s.y - 2
            hp.append(_path(f"M{dx:.1f} {hy_head:.1f} L{dx:.1f} {y_end:.1f}", p.accent, "a-hp"))
            drops.append(dx)
        rx = hcx - 30 * k
        hp.append(_path(f"M{rx:.1f} {hy:.1f} L{rx:.1f} {hy_head:.1f}", p.accent))
        xs = drops + [rx]
        sink = f"{r['T_sink_in_C']:g}→{r['T_sink_out_C']:g} °C" if r["T_sink_in_C"] != r["T_sink_out_C"] \
            else f"{r['T_sink_out_C']:g} °C"
        hp.append(_path(f"M{min(xs):.1f} {hy_head:.1f} L{max(xs):.1f} {hy_head:.1f}", p.accent, width=2,
                        tip=f"{h.label} sink {_fmt(r[f'Q_sink_{u}'])} {u} at {sink} (indicative connections)"))
        tip = (f"{h.unit}: Q_sink {_fmt(r[f'Q_sink_{u}'])} {u} at {sink}, COP {r['COP']:.3g}, "
               f"W {_fmt(r[f'W_{u}'])}, source {_fmt(r[f'Q_source_{u}'])} at {r['T_source_C']:g} °C "
               f"({_fmt(r[f'source_from_process_{u}'])} process + {_fmt(r[f'source_external_{u}'])} external)")
        hp.append(_box(hx, hy, _BOX_W, h.label, f"COP {r['COP']:.3g} · W {_fmt(r[f'W_{u}'])}", p,
                       stroke=p.accent, tip=tip))
        if src_y is not None and r[f"source_from_process_{u}"] > 1e-9:
            sx = hcx + 30
            hp.append(_path(f"M{sx:.1f} {src_y:.1f} L{sx:.1f} {hy + _BOX_H + 2:.1f}", p.accent, "a-hp", "4 3"))
        elif r[f"source_from_process_{u}"] > 1e-9:      # no source steps in the layout: a labelled stub
            sx = hcx + 30
            hp.append(_path(f"M{sx:.1f} {hy + _BOX_H + 28:.1f} L{sx:.1f} {hy + _BOX_H + 2:.1f}", p.accent, "a-hp",
                            "4 3", tip=f"Process source {_fmt(r[f'source_from_process_{u}'])} {u}"))
            hp.append(_txt(sx + 6, hy + _BOX_H + 20, "+ process", p.accent, 12, "start"))
        if r[f"source_external_{u}"] > 1e-9:
            ex = hcx + (-40 if r[f"source_from_process_{u}"] > 1e-9 else -20)
            hp.append(_path(f"M{ex:.1f} {hy + _BOX_H + 28:.1f} L{ex:.1f} {hy + _BOX_H + 2:.1f}", p.accent, "a-hp",
                            "4 3", tip=f"External (ambient) source {_fmt(r[f'source_external_{u}'])} {u}"))
            hp.append(_txt(ex + 6, hy + _BOX_H + 20, "+ ambient", p.accent, 12, "start"))
    if src_y is not None and links and any(rows_hp[h.unit][f"source_from_process_{u}"] > 1e-9 for h in links):
        xs = []
        for n in fs.process_sources:
            s = fs.step(n)
            # below the header: riser from the box top; above it: from the bottom right, clear of the tag
            sx = s.cx + 20 if s.y > src_y else s.x + s.width - 8   # clear of a vertical material flow at cx
            y_to = s.y if s.y > src_y else s.y + _BOX_H
            hp.append(_path(f"M{sx:.1f} {y_to:.1f} L{sx:.1f} {src_y:.1f}", p.accent, dash="4 3"))
            xs.append(sx)
        xs += [_X0 + _COL_DX * h.col + _BOX_W / 2 + 30 for h in links
               if rows_hp[h.unit][f"source_from_process_{u}"] > 1e-9]
        q = sum(rows_hp[h.unit][f"source_from_process_{u}"] for h in links)
        hp.append(_path(f"M{min(xs):.1f} {src_y:.1f} L{max(xs):.1f} {src_y:.1f}", p.accent, dash="4 3", width=2,
                        tip=f"{fs.source_label}: {_fmt(q)} {u} to the heat pump sources (indicative connections)"))

    height = _Y0 + _ROW_DY * (fs.rows - 1) + _BOX_H + 50
    body = _layer(base, op_base) + _layer(energy, op_energy) + _layer(hp, op_hp)
    return _svg(height, f"Simplified flowsheet: {fs.case}",
                f"Process steps with material flow; view: {VIEW_LABELS[view]}.", p, body, "fs")


# ------------------------------------------------------------------ T* stream diagram
def stream_diagram_svg(stream_set: StreamSet, targets: dict, heat_pumps: pd.DataFrame | None = None,
                       view: View = "all", palette: Palette = LIGHT) -> str:
    """Streams as vertical arrows on the shifted-temperature axis T*, with the pinch, targets and heat pumps.

    ``targets`` is ``summary["targets"]`` of ``analyse.compute`` (keys ``Qh_min``, ``Qc_min``,
    ``heat_recovery``, ``pinch_T_star_C``). Streams shorter than 8 px on the axis (latent loads over
    1 K) are stretched to 8 px so they stay visible; their tooltips keep the true temperatures.
    """
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")
    p, u = palette, stream_set.energy_unit
    ids = stream_ids(stream_set)
    hot, cold = list(stream_set.hot), list(stream_set.cold)
    ts = [x for s in stream_set.streams for x in (s.T_star_in_C, s.T_star_out_C)]
    t_hi, t_lo = max(ts), min(ts)
    pad = max(2.0, 0.04 * (t_hi - t_lo))
    t_hi, t_lo = t_hi + pad, t_lo - pad
    top, bottom = 34.0, 380.0

    def y(T: float) -> float:
        return top + (t_hi - T) / (t_hi - t_lo) * (bottom - top)

    left, right = 80.0, 435.0
    n_hot, n_cold = max(1, len(hot)), max(1, len(cold))
    half = (right - left) / 2
    _, op_energy, op_hp = _OPACITY[view]
    op_streams = {"process": 1.0, "energy": 0.3, "heat_pumps": 0.3, "all": 1.0}[view]
    frame: list[str] = []
    streams: list[str] = []
    energy: list[str] = []
    hp: list[str] = []

    frame.append(f"<rect x='{left:.0f}' y='22' width='{right - left:.0f}' height='{bottom - 14:.0f}' rx='6' "
                 f"fill='none' stroke='{p.border}' stroke-width='0.5' stroke-dasharray='4 4'/>")
    frame.append(f"<line x1='60' y1='{top}' x2='60' y2='{bottom}' stroke='{p.grey}' stroke-width='0.5'/>")
    span = t_hi - t_lo
    step = next(s for s in (5, 10, 20, 25, 50, 100, 200, 500, 1000) if span / s <= 7)
    T = step * (int(t_lo // step) + 1)
    while T < t_hi:
        frame.append(f"<line x1='56' y1='{y(T):.1f}' x2='60' y2='{y(T):.1f}' stroke='{p.grey}' stroke-width='0.5'/>")
        frame.append(_txt(52, y(T), f"{T:g}", p.grey, 12, "end"))
        T += step
    frame.append(_txt(20, 14, "T* (°C)", p.grey, 12, "start"))
    frame.append(_txt(left + half / 2, 14, "Hot streams", p.hot, 12))
    frame.append(_txt(left + 1.5 * half, 14, "Cold streams", p.cold, 12))
    for pt in targets.get("pinch_T_star_C", []):
        frame.append(f"<line x1='60' y1='{y(pt):.1f}' x2='545' y2='{y(pt):.1f}' stroke='{p.grey}' "
                     f"stroke-width='1' stroke-dasharray='6 4'/>")
        frame.append(_txt(496, y(pt) - 12, f"Pinch T* {pt:g} °C", p.grey, 12))

    for group, x0, colour, mk in ((hot, left, p.hot, "a-hot"), (cold, left + half, p.cold, "a-cold")):
        n = n_hot if group is hot else n_cold
        pitch = (half - 30) / max(1, n - 1) if n > 1 else 0
        for i, s in enumerate(group):
            x = x0 + 15 + i * pitch if n > 1 else x0 + half / 2
            y1, y2 = y(s.T_star_in_C), y(s.T_star_out_C)
            if abs(y2 - y1) < 8:
                y2 = y1 + (8 if s.kind == "hot" else -8)
            tip = (f"{ids[s.name]} {s.name}: {s.T_in_C:g}→{s.T_out_C:g} °C (T* {s.T_star_in_C:g}→{s.T_star_out_C:g}), "
                   f"{_fmt(s.Q)} {u}, ΔT_shift {s.dT_shift_K:g} K")
            streams.append(f"<g><title>{escape(tip)}</title>"
                           f"<line x1='{x:.1f}' y1='{y1:.1f}' x2='{x:.1f}' y2='{y2:.1f}' stroke='{colour}' "
                           f"stroke-width='3' stroke-linecap='round' marker-end='url(#{mk})'/>"
                           f"<line x1='{x:.1f}' y1='{y1:.1f}' x2='{x:.1f}' y2='{y2:.1f}' stroke='transparent' "
                           f"stroke-width='14'/>" + _txt(x, max(y1, y2) + 14, ids[s.name], p.text, 12) + "</g>")

    pinch = targets.get("pinch_T_star_C") or [t_lo]
    y_p = y(min(pinch))
    hp_rows = [] if heat_pumps is None else [r for _, r in heat_pumps.head(3).iterrows()]
    hp_y = [min(max(y(r["T_sink_out_C"] + 1), 26.0), bottom - 60) for r in hp_rows]

    def free(prefer: float, lo: float, hi: float) -> float:
        """Centre of an energy box near ``prefer`` and at least 32 px from every heat pump arrow."""
        options = [c for c in range(int(lo), int(hi) + 1, 2) if all(abs(c - h) >= 32 for h in hp_y)]
        return min(options, key=lambda c: abs(c - prefer)) if options else prefer

    yh = free(max(top + 60, min(y_p - 130, top + 80)), top + 24, y_p - 100)
    energy.append(_box(448, yh - 22, 96, "Hot utility", f"{targets['Qh_min']:.4g}", p, stroke=p.hot,
                       tip=f"Q̇h,min = {_fmt(targets['Qh_min'])} {u}, supplied above the pinch"))
    energy.append(_path(f"M446 {yh:.1f} L438 {yh:.1f}", p.hot, "a-hot"))
    yr = free(y_p - 50, yh + 50, y_p - 30)
    energy.append(_box(448, yr - 22, 96, "Recovered", f"{targets['heat_recovery']:.4g}", p,
                       tip=f"Process-to-process heat recovery at the energy target: {_fmt(targets['heat_recovery'])} {u}"))
    yc = min(y_p + 30, bottom - 20)
    energy.append(_box(448, yc - 22, 96, "Cold utility", f"{targets['Qc_min']:.4g}", p, stroke=p.cold,
                       tip=f"Q̇c,min = {_fmt(targets['Qc_min'])} {u}, rejected below the pinch"))
    energy.append(_path(f"M437 {yc:.1f} L446 {yc:.1f}", p.cold, "a-cold"))

    if heat_pumps is not None and len(heat_pumps):
        for k, (r, ys) in enumerate(zip(hp_rows, hp_y)):
            hp.append(_box(556, ys - 22, 94, f"HP{k + 1}", f"{_fmt(r[f'Q_sink_{u}'])} {u}", p,
                           stroke=p.accent,
                           tip=(f"{r['unit']}: Q_sink {_fmt(r[f'Q_sink_{u}'])} {u} at {r['T_sink_in_C']:g}→"
                                f"{r['T_sink_out_C']:g} °C, COP {r['COP']:.3g}, W {_fmt(r[f'W_{u}'])}, source "
                                f"{_fmt(r[f'Q_source_{u}'])} at {r['T_source_C']:g} °C")))
            hp.append(_path(f"M554 {ys:.1f} L438 {ys:.1f}", p.accent, "a-hp"))
            y_src = min(y(r["T_source_C"] - 1), bottom - 4)
            if r[f"source_from_process_{u}"] > 1e-9:
                hp.append(_path(f"M437 {y_src:.1f} L{603 - 10 * k} {y_src:.1f} L{603 - 10 * k} {ys + 24:.1f}",
                                p.accent, "a-hp", "4 3", tip=f"Process source {_fmt(r[f'source_from_process_{u}'])} {u}"))
            if r[f"source_external_{u}"] > 1e-9:
                hp.append(_path(f"M664 {bottom:.1f} L664 {ys:.1f} L652 {ys:.1f}", p.accent, "a-hp", "4 3",
                                tip=f"External (ambient) source {_fmt(r[f'source_external_{u}'])} {u}"))
        hp.append(_txt(664, bottom + 14, "Ambient source", p.accent, 12, "end"))

    body = (_layer(frame, 1.0) + _layer(streams, op_streams)
            + _layer(energy, op_energy) + _layer(hp, op_hp))
    return _svg(bottom + 30, "Streams on the shifted-temperature axis",
                f"Hot and cold streams, pinch, energy targets and heat pumps; view: {VIEW_LABELS[view]}.", p, body, "ts")


def legend_rows(stream_set: StreamSet) -> pd.DataFrame:
    """Key of the stream identifiers (ID, stream, type, temperatures, duty) for display under a diagram."""
    ids = stream_ids(stream_set)
    u = stream_set.energy_unit
    return pd.DataFrame([{"ID": ids[s.name], "stream": s.name, "type": s.kind,
                          "T_in → T_out [°C]": f"{s.T_in_C:g} → {s.T_out_C:g}", f"Q [{u}]": s.Q}
                         for s in sorted(stream_set.streams, key=lambda s: (s.kind != "hot", int(ids[s.name][1:])))])
