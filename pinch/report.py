"""Techno-economic assessment (TEA) report of one case: content (step 6; Dashboard downloads).

The report follows the structure of ISO/TS 14076:2025 (environmental techno-economic assessment):
goal and scope (6.2), technical analysis (6.3), economic analysis (6.4), environmental assessment
(6.5), sensitivity analysis (6.6), interpretation (6.7) and documentation (7). It is not critically
reviewed, and says so on every page.

This module builds the content as a list of blocks (headings, paragraphs, tables, figures) from one
run of ``scripts/analysis/analyse.compute``; ``pinch.report_render`` writes the same blocks as PDF
(ReportLab) and Word (python-docx), so both files have the same text, tables, figures and numbering.

Caption rules (the same in both formats)
----------------------------------------
* Tables and figures are numbered separately, in order of appearance, from 1 ("Table 1.", "Figure 1.").
* A table caption stands above its table, a figure caption below its figure.
* A caption is the bold label followed by one or more full sentences ending in a full stop: what is
  shown, then, where useful, how to read it.

Numbers come from the run (summary and tables), from the case file with its stated sources, or are
derived here with stated formulas (cash flows, ±20 % swings, cost and CO2 per MWh of heat; each
tested in tests/test_report.py). Nothing is added that the run does not contain.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from pinch import __version__, with_extra_shift
from pinch import process_diagram as pdg
from pinch.case import Case
from pinch.economics import EconomicParameters, Option, evaluate
from pinch.investment import cash_flows, discounted_payback_years, irr
from pinch.streams import StreamSet
from pinch.theme import LIGHT

STANDARD = "A techno-economic assessment following the framework of ISO/TS 14076:2025, not critically reviewed."
FOOTER = STANDARD.rstrip(".")
PROGRAM = "Heatpump-Pinch"
#: Source of the default cost functions (pinch.economics.DEFAULT_COST_FUNCTIONS, module comment)
DEFAULT_COST_SOURCE = ("Padullés et al. (2026), Table 3, from the Danish Energy Agency Technology Catalogue; O&M from "
                       "the Danish Energy Agency, Technology Data - Industrial Process Heat (2025)")
MISSING_DIAGRAM = ("The {} could not be drawn here: the package resvg-py is not installed "
                   "(pip install -r requirements.txt). It is shown in the app.")
SWING = 0.20   # one-at-a-time change of each input in the sensitivity table (as in the reference layout)


# ================================================================== document model
@dataclass(frozen=True)
class Heading:
    """Section heading; level 1 starts a new page."""
    text: str
    level: int = 1


@dataclass(frozen=True)
class Para:
    """Paragraph. Markup: ``**bold**`` and ``_{subscript}``."""
    text: str


@dataclass(frozen=True)
class Box:
    """Highlighted statement on the title page (the standard and review status)."""
    text: str


@dataclass(frozen=True)
class Table:
    """Table with a caption (above). ``widths`` are fractions of the text width."""
    caption: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    widths: tuple[float, ...] = ()


@dataclass(frozen=True)
class Figure:
    """PNG image with a caption (below). ``width`` is a fraction of the text width."""
    caption: str
    png: bytes
    width: float = 0.9


Block = Heading | Para | Box | Table | Figure


@dataclass
class Report:
    title: tuple[str, ...]              # title lines
    short_title: str                    # document properties
    blocks: list[Block] = field(default_factory=list)

    def numbered(self):
        """(block, number) in document order; tables and figures numbered separately from 1, others None."""
        n = {Table: 0, Figure: 0}
        for b in self.blocks:
            if type(b) in n:
                n[type(b)] += 1
                yield b, n[type(b)]
            else:
                yield b, None

    def captions(self) -> list[str]:
        """'Table 1. ...' / 'Figure 1. ...' in document order (for tests and lists of figures)."""
        return [f"{type(b).__name__} {k}. {b.caption}" for b, k in self.numbered() if k is not None]


# ================================================================== formatting
def eur(x: float, decimals: int = 0) -> str:
    """€1,234 / -€1,234 (as in the reference layout); 'n/a' for a missing value."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    if math.isinf(x):
        return "unbounded"
    s = f"€{abs(x):,.{decimals}f}"
    return f"-{s}" if x < 0 and round(abs(x), decimals) > 0 else s


def pct(x: float | None, decimals: int = 1) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{100 * x:.{decimals}f} %"


def num(x, decimals: int = 2, unit: str = "") -> str:
    """Number with thousands separators; 'n/a' for missing, 'never' for an infinite payback."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(x):
        return "n/a"
    if math.isinf(x):
        return "never" if x > 0 else "none"
    s = f"{x:,.{decimals}f}"
    return f"{s} {unit}".rstrip()


def years(x) -> str:
    s = num(x, 1)
    return s if s in ("n/a", "never", "none") else f"{s} years"


def ratio(x) -> str:
    """Break-even price ratio: '+inf' pays off at any ratio, <= 0 or -inf never."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(x):
        return "n/a"
    if x == math.inf:
        return "any ratio"
    return "none" if x <= 0 else f"{x:.2f}"


def _short(text: str, limit: int = 260) -> str:
    """Source strings are kept whole up to ``limit`` characters (cut at a word, marked '…')."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


# ================================================================== derived quantities (tested)
@dataclass(frozen=True)
class Economics:
    """The grass-roots full design evaluated again, with what the summary does not keep."""
    params: EconomicParameters
    to_MWh: Callable[[float], float]
    baseline: Option
    full: Option
    Qh_MWh: float                       # gas heat of the baseline [MWh/year]
    Q_hp_MWh: float                     # heat from the heat pumps [MWh/year]
    capex_EUR: float
    savings_EUR: float
    npv_EUR: float
    baseline_annual: tuple[float, float, float, float]   # (gas fuel MWh, OPEX EUR, CO2 t, primary energy MWh)
    option_annual: tuple[float, float, float, float]
    rerun: Callable[[EconomicParameters], float]          # full design NPV with other parameters (options rebuilt)


def economics_of(case: Case, streams: StreamSet) -> Economics | None:
    """Recompute the full grass-roots design of ``pinch.economic_analysis`` (same functions, same inputs),
    keeping the options and the yearly quantities. None when the case has no annual basis."""
    if case.basis is None:
        return None
    from pinch.design import design_from_gcc
    from pinch.economic_analysis import _core, _params_and_converter
    from pinch.economics import _annual
    shifted = with_extra_shift(streams, case.extra_shift_K)
    design = design_from_gcc(shifted, case.sink_levels, case.eta_lorenz, case.source_T_C)
    _, params, to_MWh = _params_and_converter(case, shifted.energy_unit)
    Qh = to_MWh(design.Qh_before)
    core = _core(design, Qh, to_MWh, params, shifted, case.ambient_T_C)
    full = core["full"]

    def rerun(p: EconomicParameters) -> float:
        return _core(design, Qh, to_MWh, p, shifted, case.ambient_T_C)["full"].npv_EUR
    return Economics(params, to_MWh, core["baseline"], core["full_option"], Qh, to_MWh(design.Q_sink_total),
                     full.capex_EUR, full.savings_EUR, full.npv_EUR,
                     _annual(core["baseline"], params), _annual(core["full_option"], params), rerun)


def cash_flow_table(capex_EUR: float, savings_EUR: float, rate: float, n_years: int) -> pd.DataFrame:
    """Yearly cash flow (year 0 = investment, then constant savings), discounted and cumulative [EUR].

    The last cumulative value equals the NPV of ``pinch.economics.evaluate`` (annuity factor form).
    """
    flows = cash_flows(capex_EUR, savings_EUR, n_years)
    disc = flows / (1.0 + rate) ** np.arange(n_years + 1)
    return pd.DataFrame({"year": np.arange(n_years + 1), "cash_flow_EUR": flows, "discounted_EUR": disc,
                         "cumulative_discounted_EUR": np.cumsum(disc)})


def npv_swings(e: Economics, swing: float = SWING) -> pd.DataFrame:
    """Change in the full design's NPV when one input moves by -swing and +swing, the others at the base case.

    Inputs: CAPEX (NPV changes by ∓swing x CAPEX), gas price, electricity price, boiler efficiency, discount
    rate and, when they are set, the CO2 price and the chiller COP. The boiler efficiency is on the gross
    calorific value, so its upper value is capped at 1.0 (stated in the row label). Prices, efficiencies
    and the discount rate are re-evaluated on the same options; the chiller COP changes the baseline and
    the options themselves, so the economics are rebuilt for it (``Economics.rerun``). Rows are sorted
    by the larger absolute change.
    """
    p = e.params
    rows = [{"input": "CAPEX", "minus": swing * e.capex_EUR, "plus": -swing * e.capex_EUR}]
    fields = [("Gas price", "gas_price_EUR_per_kWh"), ("Electricity price", "electricity_price_EUR_per_kWh"),
              ("Boiler efficiency", "boiler_efficiency"), ("Discount rate", "discount_rate"),
              ("CO2 price", "co2_price_EUR_per_t"), ("Chiller COP", "chiller_cop")]
    for label, key in fields:
        base = getattr(p, key)
        if not base:
            continue
        lo, hi = base * (1 - swing), base * (1 + swing)
        if key == "boiler_efficiency" and hi > 1.0:
            hi = 1.0
            label = "Boiler efficiency (upper value capped at 1.0, GCV)"
        values = []
        for v in (lo, hi):
            q = replace(p, **{key: v})
            new = e.rerun(q) if key == "chiller_cop" else evaluate(e.full, e.baseline, q).npv_EUR
            values.append(new - e.npv_EUR)
        rows.append({"input": label, "minus": values[0], "plus": values[1]})
    df = pd.DataFrame(rows)
    order = df[["minus", "plus"]].abs().max(axis=1).sort_values(ascending=False).index
    return df.loc[order].reset_index(drop=True)


def per_MWh_heat(e: Economics) -> dict[str, float]:
    """Indicators per MWh of heat from the heat pumps (the functional unit).

    * net cost [EUR/MWh] = (CAPEX / annuity factor - yearly saving) / heat; negative = the heat pumps
      save money over the horizon (it is -NPV / (annuity factor x heat));
    * CO2 avoided [kg/MWh] and primary energy saved [MWh/MWh] = yearly change / heat.
    """
    af = e.params.annuity_factor
    q = e.Q_hp_MWh
    if q <= 0:
        return {"net_cost_EUR_per_MWh": math.nan, "co2_avoided_kg_per_MWh": math.nan, "pe_saved_per_MWh": math.nan}
    return {"net_cost_EUR_per_MWh": (e.capex_EUR / af - e.savings_EUR) / q,
            "co2_avoided_kg_per_MWh": (e.baseline_annual[2] - e.option_annual[2]) * 1000 / q,
            "pe_saved_per_MWh": (e.baseline_annual[3] - e.option_annual[3]) / q}


# ================================================================== figures
def figure_png(fig, dpi: int = 200) -> bytes:
    """PNG bytes of a matplotlib figure (the figure is left open)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    return buf.getvalue()


def svg_png(svg: str, width_px: int = 2000) -> bytes | None:
    """PNG of an SVG diagram with resvg (``resvg-py``); None if that package is not installed.

    resvg ships as a self-contained wheel for Windows, macOS and Linux (no system library, unlike CairoSVG,
    which needs Cairo and fails on a plain Windows install). Text is set in DejaVu Sans from matplotlib's
    data folder and system fonts are skipped, so the image is the same on every machine.
    """
    try:
        import resvg_py  # dependency of the report (requirements.txt)
    except ImportError:
        return None
    from pathlib import Path

    import matplotlib
    fonts = str(Path(matplotlib.get_data_path()) / "fonts" / "ttf")
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width_px, background="white", skip_system_fonts=True,
                                       font_dirs=[fonts], font_family="DejaVu Sans",
                                       sans_serif_family="DejaVu Sans"))


def cash_flow_figure(cf: pd.DataFrame, rate: float):
    """Discounted cash flow of each year (bars) and its running total (line), as in the reference layout."""
    import matplotlib.pyplot as plt

    from pinch.plotting import COLD_COLOUR, GCC_COLOUR, HOT_COLOUR
    fig, ax = plt.subplots(figsize=(8, 4.2))
    colours = [COLD_COLOUR if v >= 0 else HOT_COLOUR for v in cf["discounted_EUR"]]
    ax.bar(cf["year"], cf["discounted_EUR"] / 1e3, color=colours, label="discounted cash flow of the year")
    ax.plot(cf["year"], cf["cumulative_discounted_EUR"] / 1e3, marker="o", ms=3, color=GCC_COLOUR,
            label="cumulative (the NPV in the last year)")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Year (0 = investment)")
    ax.set_ylabel(f"Discounted at {100 * rate:.1f} % [k€]")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    return fig


def swing_figure(sw: pd.DataFrame, swing: float = SWING):
    """Tornado of the NPV change for -swing and +swing of each input (longest bar on top)."""
    import matplotlib.pyplot as plt

    from pinch.plotting import COLD_COLOUR, HOT_COLOUR
    d = sw.iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(d) + 1.4))
    y = np.arange(len(d))
    ax.barh(y, d["minus"] / 1e3, color=HOT_COLOUR, label=f"input -{100 * swing:.0f} %")
    ax.barh(y, d["plus"] / 1e3, color=COLD_COLOUR, alpha=0.85, label=f"input +{100 * swing:.0f} %")
    ax.set_yticks(y, d["input"])
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("Change in the net present value [k€]")
    ax.grid(axis="x", alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    return fig


# ================================================================== content
def _n_streams(streams: StreamSet) -> int:
    """Number of process streams (segments of a variable-CP stream count once)."""
    return len({x.parent or x.name for x in streams.streams})


def _basis_text(case: Case, params: EconomicParameters | None) -> str:
    b = case.basis
    if b is None:
        return "none given (no annual figures)"
    hours = f", {params.operating_hours_per_year:,.0f} operating hours a year" if params else ""
    if b["type"] == "per_product":
        return f"{b['production_per_year']:,.0f} {b['production_unit']} a year{hours}"
    return f"average duties over {b['operating_hours_per_year']:,.0f} operating hours a year"


def _assumed(text: str) -> bool:
    t = str(text).lower()
    return any(w in t for w in ("assum", "approximation", "inference", "not a published"))


def _source_for(key: str, ec: dict) -> str:
    """Source string of an economic parameter: case file first, then the defaults."""
    aliases = {"gas_price_EUR_per_kWh": ("prices", "gas_price"), "electricity_price_EUR_per_kWh": ("prices",)}
    for k, v in ec.get("case_sources", {}).items():
        names = [x.strip() for x in k.split(",")]
        if key in names or any(a in names for a in aliases.get(key, ())):
            return v
    if key == "electricity_price_EUR_per_kWh" and "electricity_to_gas_ratio" in ec.get("default_sources", {}):
        return "ratio x gas price; " + ec["default_sources"]["electricity_to_gas_ratio"]
    return ec.get("default_sources", {}).get(key, "case file")


def _hp_rows(hp: pd.DataFrame, unit: str) -> tuple[tuple[str, ...], ...]:
    return tuple((r["unit"], f"{r['T_sink_in_C']:g} → {r['T_sink_out_C']:g}", f"{r['T_source_C']:g}",
                  num(r[f"Q_sink_{unit}"], 2), num(r["COP"], 2), num(r[f"W_{unit}"], 2), str(r["placement"]))
                 for _, r in hp.iterrows())


def _flowsheet(case: Case, streams: StreamSet, hp: pd.DataFrame | None, layout: pdg.Flowsheet | None) -> str:
    fs = layout if layout is not None else pdg.generic_flowsheet(streams, hp, case.name)
    return pdg.flowsheet_svg(fs, streams, hp, "all", LIGHT)


@dataclass
class _Builder:
    report: Report

    def h(self, text: str, level: int = 1) -> None:
        self.report.blocks.append(Heading(text, level))

    def p(self, text: str) -> None:
        self.report.blocks.append(Para(text))

    def table(self, caption: str, header, rows, widths=()) -> None:
        self.report.blocks.append(Table(caption, tuple(header), tuple(tuple(str(c) for c in r) for r in rows),
                                        tuple(widths)))

    def figure(self, caption: str, png: bytes | None, width: float = 0.9, missing: str = "") -> None:
        if png:
            self.report.blocks.append(Figure(caption, png, width))
        elif missing:
            self.p(missing)


def build_report(case: Case, streams: StreamSet, summary: dict, tables: dict[str, pd.DataFrame],
                 pngs: dict[str, bytes], rq: pd.DataFrame | None = None, layout: pdg.Flowsheet | None = None,
                 edited: bool = False, generated: date | None = None) -> Report:
    """Build the TEA report of one run.

    Parameters
    ----------
    case, streams : the inputs of the run (streams before the case's extra shift, as passed to ``compute``).
    summary, tables : ``Outputs.summary`` and ``Outputs.tables`` of ``scripts/analysis/analyse.compute``.
    pngs : figure stem -> PNG bytes (``Outputs.snapshot_pngs``).
    rq : consolidated research-question table (``scripts/analysis/consolidate_rq.consolidate_case``), optional.
    layout : flowsheet layout of the case (``pinch.process_diagram.load_flowsheet``); None = generic layout.
    edited : True when the inputs differ from the case file (stated on the title page).
    generated : report date (default today).
    """
    s, t, unit = summary, summary["targets"], summary["energy_unit"]
    hpd = summary["heat_pump_design"]
    ec = summary.get("economics") or {}
    has_econ = bool(ec) and "skipped" not in ec
    e = economics_of(case, streams) if has_econ else None
    hp = tables.get("heat_pump_design")
    if hp is not None and f"Q_sink_{unit}" not in hp.columns:
        hp = None
    n_hp = len(hpd["units"])
    rep = Report(title=("Techno-economic assessment of process-heat electrification with heat pumps:",
                        f"{case.plant} ({_n_streams(streams)} process streams, {n_hp} heat pump"
                        f"{'' if n_hp == 1 else 's'})"),
                 short_title=f"TEA - {case.plant}")
    b = _Builder(rep)
    today = (generated or date.today()).isoformat()
    swings = npv_swings(e) if e else None
    cf = cash_flow_table(e.capex_EUR, e.savings_EUR, e.params.discount_rate, e.params.horizon_years) if e else None
    per = per_MWh_heat(e) if e else None
    full: dict = ec["results"]["full design (heat recovery installed)"] if has_econ else {}
    gr = ec.get("grass_roots_reference", {}) if has_econ else {}
    has_rq = rq is not None and len(rq) > 0 and e is not None
    sec_rq = "3.6"
    sec_rf = "3.7" if has_rq else "3.6"

    # ---------------------------------------------------------------- title page
    rep.blocks.append(Box(STANDARD))
    b.p(f"Generated {today} by {PROGRAM} v{__version__} from one run of the case '{case.name}'"
        + (", with inputs edited in the app (they differ from the case file)" if edited else "")
        + ". Every number comes from the calculation, from the cited literature or from an assumption marked "
          "as such (section 7).")

    # ---------------------------------------------------------------- abstract
    b.h("Abstract")
    pinch_txt = ", ".join(f"{x:g}" for x in t["pinch_T_star_C"]) or "none (threshold problem)"
    names = ", ".join(hpd["units"]) or "none"
    lead = (f"The pinch analysis of the {case.plant.lower()} gives a minimum hot utility Q_{{h,min}} of "
            f"{num(t['Qh_min'], 2)} {unit} and a minimum cold utility Q_{{c,min}} of {num(t['Qc_min'], 2)} {unit}, "
            f"with the pinch at T* = {pinch_txt} °C. {n_hp} heat pump{'' if n_hp == 1 else 's'} sized from the grand "
            f"composite curve ({names}) supply {pct(hpd['fraction_of_Qh_min_electrified'])} of Q_{{h,min}} with a "
            f"system COP of {num(hpd['COP_system'], 2)} (Lorenz efficiency {hpd['eta_lorenz']:g}).")
    if e and full:
        cfl = cash_flows(e.capex_EUR, e.savings_EUR, e.params.horizon_years)
        lead += (f" On an annual basis of {_basis_text(case, e.params)}, the full design costs {eur(full['capex_EUR'])} "
                 f"and saves {eur(full['savings_EUR'])} a year against a gas boiler on a site already recovering heat "
                 f"at the target: simple payback {years(full['payback_years'])}, net present value "
                 f"**{eur(full['npv_EUR'])}** over {e.params.horizon_years} years at "
                 f"{pct(e.params.discount_rate)} and internal rate of return {pct(irr(cfl))}. It avoids "
                 f"{num(full['co2_avoided_t'], 0)} t CO2 a year and cuts primary energy by "
                 f"{pct(full['primary_energy_reduction'])}. It breaks even (NPV = 0) up to an electricity-to-gas "
                 f"price ratio of {ratio(gr.get('full_design_break_even_ratio_NPV'))}, against "
                 f"{num(ec['price_ratio'], 2)} today.")
    else:
        lead += (" The case has no annual basis, so the economic and environmental sections are not computed "
                 f"({ec.get('skipped', 'no economics block')}).")
    if has_rq:
        assert rq is not None and e is not None
        r0 = rq.iloc[0]
        lead += (f" Against today's site ({r0['todays_site']}), heat pumps can replace "
                 f"{pct(r0['RQ1_HP_gas_share'])} of the gas with an incremental payback within "
                 f"{e.params.payback_threshold_years:g} years (section {sec_rq}).")
    b.p(lead)
    if e:
        p = e.params
        cop = hpd["COP_system"]
        ratio_max = cop * p.boiler_efficiency
        ctx = (f"**Context: what decides whether the heat pumps pay off.** (1) The operating margin. Each MWh of heat "
               f"from a heat pump saves {1 / p.boiler_efficiency:.2f} MWh of gas (boiler efficiency "
               f"{p.boiler_efficiency:g}) and uses 1/COP MWh of electricity; at the system COP of {cop:.2f} the "
               f"energy bill falls only while the electricity-to-gas price ratio stays below COP × η_{{boiler}} = "
               f"{ratio_max:.2f} (before O&M and any refrigeration credit); today's ratio is {p.price_ratio:.2f}. "
               f"(2) The investment. The heat pumps cost {eur(e.capex_EUR)}, against a yearly saving of "
               f"{eur(e.savings_EUR)}. (3) Discounting. Over {p.horizon_years} years at {pct(p.discount_rate)}, a euro "
               f"saved every year is worth {p.annuity_factor:.2f} euro today, so the NPV is positive only if the simple "
               f"payback is below {p.annuity_factor:.1f} years.")
        if p.chiller_cop:
            ctx += (f" (4) The refrigeration credit. Where the heat pumps draw their heat from below ambient, they "
                    f"take over refrigeration, and the chiller electricity it would need (COP {p.chiller_cop:g}) is "
                    f"saved too.")
        b.p(ctx)
    b.p("Results depend strongly on energy prices and on the heat pump efficiency (section 5). Every input, its "
        "source and the remaining assumptions are listed in section 7.")

    # ---------------------------------------------------------------- 1 goal and scope
    b.h("1. Goal and scope definition (ISO/TS 14076, 6.2)")
    b.h("1.1 Goal", 2)
    b.p(f"Intended application: estimate how much of the process heat of the {case.plant.lower()} heat pumps can "
        "supply, at what investment, operating cost, CO2 emissions and primary energy, and show which inputs drive "
        "the result. Intended audience: the project team (internal). The study is not intended for investment "
        "decisions or public comparisons.")
    b.h("1.2 Basis of production, functional unit and reference flow", 2)
    ref = ""
    if e:
        ref = (f" Reference flow: {num(e.Qh_MWh, 0)} MWh a year of minimum hot utility, of which the heat pumps "
               f"supply {num(e.Q_hp_MWh, 0)} MWh, over {e.params.horizon_years} years.")
    b.p(f"Basis of production (ISO/TS 14076, 4.3): {_basis_text(case, e.params if e else None)}. The stream data are "
        f"given in {unit}{' and converted to MWh a year with this basis' if case.basis else ''}. Functional unit: "
        f"1 MWh of process heat supplied by the heat pumps to the cold process streams.{ref}")
    b.h("1.3 System boundary and time horizon", 2)
    rows = [("Heat pumps (compressor, exchangers, installation)", "Yes" if e else "No",
             "Cost functions of the case (section 3.2)" if e else "No annual basis")]
    if e:
        p = e.params
        om = any(cf.fixed_om_EUR_per_unit_year or cf.variable_om_EUR_per_MWh for cf in p.cost_functions.values())
        rows += [("Gas saved at the boiler", "Yes", f"Gas price and boiler efficiency {p.boiler_efficiency:g}"),
                 ("Electricity for the heat pumps", "Yes", "Electricity price"),
                 ("Chiller electricity avoided (refrigeration credit)", "Yes" if p.chiller_cop else "No",
                  f"Chiller COP {p.chiller_cop:g}" if p.chiller_cop else "No chiller COP given"),
                 ("Operation and maintenance", "Yes" if om else "No",
                  "Fixed and variable O&M of the cost functions" if om else "No O&M in the cost functions"),
                 ("CO2 emission cost", "Yes" if p.co2_price_EUR_per_t else "No",
                  f"{p.co2_price_EUR_per_t:g} €/t" if p.co2_price_EUR_per_t else "0 €/t in the base case; "
                  "sensitivity rows (section 5)")]
    if "retrofit" in s and "skipped" not in s["retrofit"]:
        rows.append(("Existing heat-exchanger network, retrofit and piping", "Yes", f"Retrofit options (section {sec_rf})"))
    elif "retrofit_bounds" in s and "skipped" not in s["retrofit_bounds"]:
        rows.append(("New heat-recovery network", "Yes", f"Retrofit bounds (section {sec_rf})"))
    else:
        rows.append(("Heat-exchanger network changes and piping", "No", "Site at the energy target (grass roots)"))
    rows += [("Electrical connection and grid reinforcement", "No", "Not modelled"),
             ("Taxes, grants and financing structure", "No", "One discount rate for the whole project"),
             ("Decommissioning and residual value", "No", "Not modelled")]
    b.table("System boundary: what the assessment includes and how.", ("Element", "Included?", "How"), rows,
            (0.42, 0.14, 0.44))
    if e:
        b.p(f"Time horizon: {e.params.horizon_years} years. Currency: euro at constant prices (the model holds "
            f"prices constant over the horizon); cash flows are discounted at {pct(e.params.discount_rate)}. "
            f"Heat pump capacities are average duties over {e.params.operating_hours_per_year:,.0f} operating hours "
            "a year.")

    # ---------------------------------------------------------------- 2 technical analysis
    b.h("2. Technical analysis (ISO/TS 14076, 6.3)")
    shift = f"plus {case.extra_shift_K:g} K for indirect transfer" if case.extra_shift_K else "no extra shift"
    prov = s.get("provenance", {})
    eta_src = "Case file (assumed; section 7)" if _assumed(prov.get("eta_lorenz", "")) else "Case file"
    trows = [("Process streams", f"{_n_streams(streams)} ({len({x.parent or x.name for x in streams.hot})} hot)",
              "Stream table (section 2.1)"),
             ("Temperature shifts", f"per stream, from the stream table; {shift}", "Stream table, case file"),
             ("Ambient temperature", "n/a" if case.ambient_T_C is None else f"{case.ambient_T_C:g} °C", "Case file"),
             ("Minimum hot utility Q_{h,min}", f"{num(t['Qh_min'], 2)} {unit}", "Problem table algorithm"),
             ("Minimum cold utility Q_{c,min}", f"{num(t['Qc_min'], 2)} {unit}", "Problem table algorithm"),
             ("Heat recovery at the target", f"{num(t['heat_recovery'], 2)} {unit}", "Problem table algorithm"),
             ("Pinch (shifted temperature)", f"T* = {pinch_txt} °C", "Problem table algorithm"),
             ("Lorenz efficiency η_{L}", f"{hpd['eta_lorenz']:g}", eta_src),
             ("Heat delivered by the heat pumps", f"{num(hpd['Q_sink_total'], 2)} {unit}", "Sized from the GCC"),
             ("Electricity of the heat pumps", f"{num(hpd['W_total'], 2)} {unit}", "Lorenz COP"),
             ("System COP", f"{num(hpd['COP_system'], 2)}", "Heat / electricity"),
             ("Share of Q_{h,min} electrified", pct(hpd["fraction_of_Qh_min_electrified"]), "Sized from the GCC")]
    if s.get("annual_MWh_per_year"):
        a = s["annual_MWh_per_year"]
        trows.append(("Q_{h,min} on the annual basis", f"{num(a['Qh_min'], 0)} MWh/year", "Basis (section 1.2)"))
    b.table("Technical inputs and calculated values of this run.", ("Quantity", "Value", "Source"), trows,
            (0.40, 0.30, 0.30))
    b.p("Method. The problem table algorithm cascades the heat of the shifted temperature intervals and gives the "
        "energy targets and the pinch (Kemp 2007). One heat pump is sized per sink level from the grand composite "
        "curve (GCC): its sink lies above the pinch and its source below it, and its COP is the Lorenz COP times the "
        "Lorenz efficiency.")
    b.h("2.1 Process and stream data", 2)
    hp_df = tables.get("heat_pump_design")
    hp_ok = hp_df if hp_df is not None and f"Q_sink_{unit}" in hp_df.columns else None
    generic = layout is None
    b.figure(f"Simplified flowsheet of the {case.plant.lower()}"
             + (" (generic layout: one box per stream, built from the stream table)" if generic else "")
             + f". Tags give each step's heat demand (+) or release (−) in {unit}; heat pumps and their "
               "connections are shown in teal, and the connections are indicative (fixed by the network design).",
             svg_png(_flowsheet(case, streams, hp_ok, layout)), 0.95,
             missing=MISSING_DIAGRAM.format("flowsheet"))
    leg = pdg.legend_rows(streams)
    b.table(f"Process streams: supply and target temperatures and heat loads ({unit}).",
            leg.columns, leg.astype(str).itertuples(index=False), (0.09, 0.39, 0.1, 0.24, 0.18))
    shifted = with_extra_shift(streams, case.extra_shift_K)
    b.figure("Streams, energy targets and heat pumps on the shifted-temperature axis T*: hot streams point down, "
             "cold streams up, and the dashed line is the pinch. Streams of 1 K (latent loads) are drawn at a minimum "
             "length.", svg_png(pdg.stream_diagram_svg(shifted, t, hp_ok, "all", LIGHT)), 0.95,
             missing=MISSING_DIAGRAM.format("T* diagram"))
    b.h("2.2 Energy targets", 2)
    b.figure("Shifted composite curves: the horizontal overlap is the heat recovered, the overhang at the top the "
             "minimum hot utility and at the bottom the minimum cold utility.", pngs.get("composite_curves"))
    b.figure("Grand composite curve: net heat flow against shifted temperature. It touches the axis at the pinch; "
             "its top is the minimum hot utility and its bottom the minimum cold utility.", pngs.get("gcc"))
    b.h("2.3 Heat pumps", 2)
    if hp is not None and len(hp):
        b.table(f"Heat pumps sized from the grand composite curve (heat and electricity in {unit}).",
                ("Unit", "Sink in → out [°C]", "Source [°C]", "Heat", "COP", "Electricity", "Placement"),
                _hp_rows(hp, unit), (0.2, 0.14, 0.1, 0.09, 0.08, 0.14, 0.25))
    else:
        b.p("No heat pump has a useful duty at the case's sink levels.")
    if hpd.get("levels_skipped_no_useful_duty"):
        b.p("Sink levels without a useful duty: " + ", ".join(hpd["levels_skipped_no_useful_duty"]) + ".")
    for u, w in (s.get("warnings") or {}).items():
        b.p(f"**Check, {u}:** " + "; ".join(w) + ".")
    b.figure("Heat pumps placed against the grand composite curve: each sink (above the pinch) and source (below "
             "it) is drawn at its temperature and duty.", pngs.get("gcc_heat_pumps"))
    cyc = s.get("cycle_based_design") or {}
    if cyc.get("units"):
        b.p("Working-fluid screening (cycle model): " + "; ".join(
            f"{u}: {d.get('fluid', 'n/a')}, {d.get('layout', '')}, COP {num(d.get('COP'), 2)} (η_{{L}} "
            f"{num(d.get('eta_lorenz'), 2)})" for u, d in cyc["units"].items())
            + f". System COP with the cycle model: {num(cyc.get('COP_system'), 2)}.")
    at = s.get("area_targeting") or {}
    if at.get("RQ2"):
        b.h("2.4 Minimum approach temperature (supertargeting)", 2)
        b.p("Total annual cost = energy cost + annualised exchanger cost, against ΔT_{min}, from the area and units "
            f"targets (capital recovery factor {num(at.get('crf_per_year'), 4)} per year). Film coefficients: "
            f"{_short(at.get('film_coefficients_source', 'case file'))}.")
        b.table("Supertargeting: ΔT_{min} with the lowest total annual cost for each exchanger cost law.",
                ("Cost law", "ΔT_{min,opt} [K]", "Within 1 % of the minimum [K]", "Total annual cost"),
                [(r["cost_law"], num(r["dTmin_opt_K"], 2),
                  "–".join(f"{x:g}" for x in r["dTmin_within_1pct_K"]) if r.get("dTmin_within_1pct_K") else "n/a",
                  eur(r["TAC_min_EUR"])) for r in at["RQ2"]], (0.43, 0.17, 0.22, 0.18))
        b.figure("Total annual cost against ΔT_{min}: the optimum is flat, so a practical ΔT_{min} within the 1 % band "
                 "costs little more than the minimum.", pngs.get("supertargeting"))

    # ---------------------------------------------------------------- 3 economic analysis
    b.h("3. Economic analysis (ISO/TS 14076, 6.4)")
    if not e:
        b.p(f"Not computed: {ec.get('skipped', 'no economics block')}. Give the case an annual basis (case file or "
            "Workflow, step 1) to run sections 3 to 6.")
    else:
        p = e.params
        b.h("3.1 Method", 2)
        b.p("Life-cycle costing with a cost breakdown into acquisition (CAPEX, year 0) and operation (gas, "
            "electricity, CO2 cost, O&M) (IEC 60300-3-3). The heat pumps are compared with a baseline: "
            f"{e.baseline.name}. Yearly saving = baseline operating cost − operating cost with heat pumps, constant "
            "over the horizon; net present value = −CAPEX + saving × annuity factor, with annuity factor "
            "= (1 − (1 + r)^{−N}) / r; simple payback = CAPEX / saving. The electrification curve sizes the heat pumps "
            "from zero to the full design; the break-even ratio is the electricity-to-gas price ratio at which the NPV "
            "is zero.")
        b.h("3.2 Inputs", 2)
        prm = ec["parameters"]
        labels = {"gas_price_EUR_per_kWh": "Gas price (€/kWh, GCV)",
                  "electricity_price_EUR_per_kWh": "Electricity price (€/kWh)",
                  "boiler_efficiency": "Boiler efficiency (GCV)", "operating_hours_per_year": "Operating hours (h/year)",
                  "discount_rate": "Discount rate", "horizon_years": "Horizon (years)",
                  "payback_threshold_years": "Payback threshold (years)",
                  "gas_EF_kg_per_kWh": "Gas emission factor (kg CO2/kWh)",
                  "grid_EF_kg_per_kWh": "Grid emission factor (kg CO2/kWh)", "co2_price_EUR_per_t": "CO2 price (€/t)",
                  "pef_electricity": "Primary energy factor, electricity", "pef_gas": "Primary energy factor, gas",
                  "chiller_cop": "Chiller COP"}
        irows = [(labels[k], "not set" if prm.get(k) is None else f"{prm[k]:g}", _short(_source_for(k, ec)))
                 for k in labels if k in prm]
        irows.append(("Electricity-to-gas price ratio", f"{ec['price_ratio']:.3f}", "Calculated"))
        case_cf = (case.economics or {}).get("cost_functions", {})
        for kind in sorted({k for k, _ in e.full.equipment}):
            cfn = p.cost_functions[kind]
            formula = (f"{cfn.beta:,.0f} + {cfn.alpha:,.1f} × X^{{{cfn.gamma:g}}} € (X in {cfn.size_unit})"
                       if cfn.size_unit != "EUR" else "lump sum")
            if cfn.fixed_om_EUR_per_unit_year or cfn.variable_om_EUR_per_MWh:
                formula += (f"; O&M {cfn.fixed_om_EUR_per_unit_year:g} €/{cfn.size_unit}/year + "
                            f"{cfn.variable_om_EUR_per_MWh:g} €/MWh")
            src = case_cf.get(kind, {}).get("source") if isinstance(case_cf.get(kind), dict) else None
            irows.append((f"Cost function '{kind}'", formula, _short(src or DEFAULT_COST_SOURCE)))
        b.table("Economic inputs, with their source or status.", ("Parameter", "Value", "Source or status"), irows,
                (0.3, 0.25, 0.45))
        b.h("3.3 Cash flows by year (constant €)", 2)
        assert cf is not None
        b.table("Cash flows of the full design by year (constant euro): the year's cash flow, its discounted value "
                "and the running total.", ("Year", "Cash flow", "Discounted", "Cumulative"),
                [("0 (CAPEX)" if int(r.year) == 0 else str(int(r.year)), eur(r.cash_flow_EUR), eur(r.discounted_EUR),
                  eur(r.cumulative_discounted_EUR)) for r in cf.itertuples()], (0.2, 0.26, 0.27, 0.27))
        fig = cash_flow_figure(cf, p.discount_rate)
        b.figure(f"Discounted cash flows of the full design at {pct(p.discount_rate)}: year 0 is the investment; the "
                 "line ends at the net present value. Where it crosses zero, the heat pumps have paid for themselves.",
                 figure_png(fig))
        _close(fig)
        b.h("3.4 Results", 2)
        flows = cf["cash_flow_EUR"].to_numpy()
        res_rows = [("Investment (CAPEX)", eur(full["capex_EUR"])),
                    ("Yearly saving", eur(full["savings_EUR"])),
                    (f"Net present value ({p.horizon_years} years)", eur(full["npv_EUR"])),
                    ("Internal rate of return", pct(irr(flows))),
                    ("Simple payback", years(full["payback_years"])),
                    ("Discounted payback", years(discounted_payback_years(flows, p.discount_rate))
                     if math.isfinite(discounted_payback_years(flows, p.discount_rate)) else "not within the horizon"),
                    ("Break-even price ratio (NPV = 0)", ratio(gr.get("full_design_break_even_ratio_NPV"))),
                    (f"Break-even price ratio (payback = {p.payback_threshold_years:g} years)",
                     ratio(gr.get("full_design_break_even_ratio_payback"))),
                    (f"Share of Q_{{h,min}} with payback ≤ {p.payback_threshold_years:g} years",
                     pct(gr.get("hp_share_of_Qh_min_payback_ok", math.nan))),
                    ("Electricity of the heat pumps", f"{num(full['electricity_MWh'], 0)} MWh/year")]
        b.table("Results of the techno-economic assessment (full design against the grass-roots baseline).",
                ("Indicator", "Value"), res_rows, (0.6, 0.4))
        others = [(k, v) for k, v in ec["results"].items() if k != "full design (heat recovery installed)"]
        if others:
            b.table("Other options evaluated by the economics block, each against its own baseline.",
                    ("Option", "CAPEX", "Saving per year", "Payback", "NPV"),
                    [(k, eur(v["capex_EUR"]), eur(v["savings_EUR"]), years(v["payback_years"]), eur(v["npv_EUR"]))
                     for k, v in others], (0.36, 0.16, 0.18, 0.14, 0.16))
        b.h("3.5 Electrification curve and price ratio", 2)
        b.figure(f"Electrification curve: payback and NPV as the heat pumps grow from zero to the full design (share of "
                 f"Q_{{h,min}}); the dashed line is the payback threshold of {p.payback_threshold_years:g} years.",
                 pngs.get("electrification_curve"))
        b.figure("Full design against the electricity-to-gas price ratio: payback and NPV; the full design pays off "
                 f"to the left of the break-even ratio. Today's ratio is {ec['price_ratio']:.2f}.",
                 pngs.get("price_ratio_sweep"))
        if has_rq:
            assert rq is not None
            b.h(f"{sec_rq} Against today's site (research questions)", 2)
            r0 = rq.iloc[0]
            from pinch.research_questions import unit_names
            unames = unit_names(r0)
            b.p(f"Today's site: {r0['todays_site']}. Heat pumps are added one at a time in order of decreasing COP, each "
                "evaluated over the previous ones (incremental payback); the first may run at partial duty. RQ1: share "
                f"of today's gas the heat pumps replace with an incremental payback within "
                f"{p.payback_threshold_years:g} years = **{pct(r0['RQ1_HP_gas_share'])}**. RQ3: break-even "
                "electricity-to-gas ratio of each increment.")
            hr_rows = []
            for i, nm in enumerate(unames, 1):
                h = f"HP{i}"
                hr_rows.append((f"{h}: {nm}", years(r0[f"{h}_incremental_payback_y"]),
                                eur(1e6 * float(r0[f"{h}_incremental_NPV_MEUR"])),
                                num(r0[f"{h}_CO2_avoided_t"], 0), ratio(r0[f"RQ3_ratio_{h}"])))
            b.table("Heat pumps added to today's site one at a time: incremental payback, NPV, CO2 avoided and "
                    "break-even price ratio (RQ3).", ("Unit", "Payback", "NPV", "CO2 avoided [t/year]", "RQ3 ratio"),
                    hr_rows, (0.36, 0.16, 0.18, 0.16, 0.14))
        rf = s.get("retrofit") if s.get("retrofit") and "skipped" not in s.get("retrofit", {}) else None
        bounds = s.get("retrofit_bounds") if s.get("retrofit_bounds") and "skipped" not in s["retrofit_bounds"] else None
        if rf or bounds:
            b.h(f"{sec_rf} Retrofit of the heat-exchanger network", 2)
            if rf:
                bl = rf["baseline"]
                b.p(f"Existing network ({bl['network']}): hot utility {num(bl['Qh'], 2)} {unit} against a target of "
                    f"{num(bl['Qh_min'], 2)} {unit}, so {num(bl['energy_gap'], 2)} {unit} is recoverable by a "
                    "network retrofit before any heat pump.")
                opts = rf["options"]
                b.table("Retrofit options against the existing network: investment, yearly saving, payback, NPV and "
                        "gas reduction.", ("Option", "CAPEX", "Saving", "Payback", "NPV", "Gas cut"),
                        [(o["option"], eur(o["capex_EUR"]), eur(o["savings_EUR"]), years(o["payback_years"]),
                          eur(o["npv_EUR"]), pct(o["gas_reduction_vs_baseline"])) for o in opts],
                        (0.34, 0.14, 0.13, 0.13, 0.14, 0.12))
                b.figure("Retrofit options: gas reduction and payback of each option against the existing network.",
                         pngs.get("retrofit_options"))
            else:
                assert bounds is not None
                b.p(f"{_short(bounds.get('baseline_meaning', ''), 400)}.")
                b.table("Retrofit bounds: heat pumps and a new heat-recovery network against the plant without heat "
                        "recovery, and the lower bound of a plant already at the target.",
                        ("Option", "Baseline", "CAPEX", "Saving", "Payback", "NPV"),
                        [(o["option"], o["baseline"], eur(o["capex_EUR"]), eur(o["savings_EUR"]),
                          years(o["payback_years"]), eur(o["npv_EUR"])) for o in bounds["options"]],
                        (0.3, 0.18, 0.13, 0.13, 0.12, 0.14))

    # ---------------------------------------------------------------- 4 environmental assessment
    b.h("4. Environmental assessment (ISO/TS 14076, 6.5)")
    if not e:
        b.p("Not computed: the case has no annual basis.")
    else:
        p = e.params
        b.p("The environmental part is a screening of the operational CO2 emissions and primary energy of the full "
            "design against the baseline, not a life cycle assessment: equipment manufacture, refrigerant leakage and "
            f"end of life are outside the boundary. Emission factors: gas {p.gas_EF_kg_per_kWh:g} kg CO2/kWh (GCV), "
            f"grid {p.grid_EF_kg_per_kWh:g} kg CO2/kWh; primary energy factors: electricity {p.pef_electricity:g}, "
            f"gas {p.pef_gas:g} (sources in Table "
            f"{_table_number(rep, 'Economic inputs')}).")
        (fb, _, cb, pb), (fo, _, co, po) = e.baseline_annual, e.option_annual
        b.table("Yearly energy use, CO2 emissions and primary energy of the baseline and of the full design.",
                ("Indicator per year", "Baseline", "Full design", "Change"),
                [("Gas (fuel, GCV) [MWh]", num(fb, 0), num(fo, 0), num(fo - fb, 0)),
                 ("Electricity [MWh]", num(e.baseline.electricity_MWh, 0), num(e.full.electricity_MWh, 0),
                  num(e.full.electricity_MWh - e.baseline.electricity_MWh, 0)),
                 ("CO2 [t]", num(cb, 0), num(co, 0), num(co - cb, 0)),
                 ("Primary energy [MWh]", num(pb, 0), num(po, 0), num(po - pb, 0))], (0.37, 0.21, 0.21, 0.21))

    # ---------------------------------------------------------------- 5 sensitivity analysis
    b.h("5. Sensitivity analysis (ISO/TS 14076, 6.6)")
    if not e:
        b.p("Not computed: the case has no annual basis.")
    else:
        assert swings is not None
        sw = int(100 * SWING)
        b.table(f"Change in the net present value of the full design when one input moves by {sw} %.",
                (f"Input changed by ±{sw} % (one at a time)", f"NPV change at −{sw} %", f"at +{sw} %"),
                [(r["input"], eur(r["minus"]), eur(r["plus"])) for _, r in swings.iterrows()], (0.46, 0.27, 0.27))
        fig = swing_figure(swings)
        b.figure(f"Change in the net present value when one input moves by {sw} % down or up, the others staying at "
                 "the base case: the longest bars matter most.", figure_png(fig), 0.85)
        _close(fig)
        sens = ec.get("grass_roots_sensitivities") or []
        if sens:
            b.p("Scenarios (one change at a time from the base case, rows of the case's sensitivity list):")
            b.table("Scenarios, one change at a time from the base case: full design payback, NPV and break-even "
                    "price ratio.", ("Scenario", "Payback", "NPV", "Break-even ratio"),
                    [("Base case", years(full["payback_years"]), eur(full["npv_EUR"]),
                      ratio(gr.get("full_design_break_even_ratio_NPV")))]
                    + [(r["sensitivity"], years(r["full_payback_years"]), eur(r["full_npv_EUR"]),
                        ratio(r["full_design_break_even_ratio_NPV"])) for r in sens], (0.5, 0.16, 0.18, 0.16))
        eta = s.get("eta_lorenz_sensitivity") or []
        if eta:
            b.table("Heat pumps re-sized for each Lorenz efficiency: system COP, payback and NPV of the full design.",
                    ("Lorenz efficiency", "System COP", "Payback", "NPV"),
                    [(f"{r['eta_lorenz']:g}", num(r["COP_system"], 2), years(r["full_payback_years"]),
                      eur(r["full_npv_EUR"])) for r in eta], (0.25, 0.25, 0.25, 0.25))
        if rq is not None and len(rq) > 1:
            b.table("Research questions for every row of the case's sensitivity list (against today's site).",
                    ("Sensitivity", "RQ1 gas share", "HP1 payback", "RQ3 ratio, HP1"),
                    [(r["sensitivity"], pct(r["RQ1_HP_gas_share"]), years(r["HP1_incremental_payback_y"]),
                      ratio(r["RQ3_ratio_HP1"])) for _, r in rq.iterrows()], (0.52, 0.16, 0.16, 0.16))
            if rq.iloc[1:]["RQ3_ratio_HP1"].notna().any():
                from pinch.plotting import tornado_figure
                fig = tornado_figure(rq, "RQ3_ratio_HP1", f"RQ3, {rq.iloc[0]['HP1_name']}: {case.plant}",
                                     "Break-even electricity-to-gas price ratio [-]")
                fig.set_size_inches(7.5, 0.17 * len(rq) + 1.6)   # one readable line per row at report width
                fig.axes[0].tick_params(axis="y", labelsize=7)
                fig.tight_layout()
                b.figure("Break-even price ratio of the first heat pump (RQ3) for each sensitivity row: bars start at "
                         "the base case; the dashed line is today's ratio, so a bar that crosses it changes the "
                         "answer.", figure_png(fig), 1.0)
                _close(fig)

    # ---------------------------------------------------------------- 6 interpretation
    b.h("6. Interpretation: technical, economic and environmental results combined (ISO/TS 14076, 6.7)")
    if e and per is not None and swings is not None:
        b.table("Cost, CO2 and primary energy per MWh of heat from the heat pumps (the functional unit).",
                ("Indicator per MWh of heat from the heat pumps", "Value"),
                [("Net cost over the horizon (negative = saving)", f"{eur(per['net_cost_EUR_per_MWh'], 1)}/MWh"),
                 ("CO2 avoided", f"{num(per['co2_avoided_kg_per_MWh'], 0)} kg/MWh"),
                 ("Primary energy saved", f"{num(per['pe_saved_per_MWh'], 2)} MWh/MWh")], (0.65, 0.35))
        top = ", ".join(swings["input"].head(3))
        b.p(f"**Significant issues.** The inputs that move the NPV most are: {top}. The result also depends on the "
            "heat pump efficiency (Lorenz efficiency, section 5), which is not measured at the site.")
        b.p("**Limitations.** Stream data are steady averages over the operating hours, so batch timing and storage "
            "are not captured unless the case models them; prices and efficiencies are constant over the horizon; "
            "capital costs come from generic cost functions (study-estimate accuracy); the electrical connection, "
            "taxes and grants are not valued; CO2 is operational only.")
        verdict = ("pays back within the threshold" if full["payback_years"] <= e.params.payback_threshold_years
                   else "does not pay back within the threshold")
        b.p(f"**Conclusion.** At today's prices the full heat pump design {verdict} of "
            f"{e.params.payback_threshold_years:g} years (simple payback {years(full['payback_years'])}, NPV "
            f"{eur(full['npv_EUR'])}); it avoids {num(full['co2_avoided_t'], 0)} t CO2 a year and stays profitable up "
            f"to a price ratio of {ratio(gr.get('full_design_break_even_ratio_NPV'))}.")
    else:
        b.p("Only the technical analysis is available for this case (no annual basis): the energy targets and the heat "
            "pump design of section 2 are its results.")

    # ---------------------------------------------------------------- 7 documentation
    b.h("7. Documentation (ISO/TS 14076, 7)")
    b.p(f"{STANDARD} Method: environmental techno-economic assessment following the framework of ISO/TS 14076:2025; "
        "life-cycle costing as in IEC 60300-3-3:2017 (constant prices, NPV); pinch analysis with the problem table "
        "algorithm (Kemp 2007). Not reviewed. Functional unit: 1 MWh of process heat supplied by the heat pumps.")
    assumed = [f"{k}: {_short(v, 400)}" for k, v in prov.items() if _assumed(v)]
    if assumed:
        b.p("**Assumptions (not sourced or inferred):** " + " ".join(f"({i}) {a}." for i, a in
                                                                     enumerate(assumed, 1)).replace("..", "."))
    b.p(f"Data source of the case: {prov.get('data source', case.data_source or 'not given')}.")
    run = s.get("run", {})
    hashes = run.get("inputs_sha256", {})
    if hashes:
        b.p("Input files (SHA-256, first 12 characters): "
            + "; ".join(f"{k} {v[:12]}" for k, v in hashes.items()) + ".")
    b.p(f"The tables (CSV), the summary (JSON) and every input with its source can be downloaded from the Sources page. "
        f"Program: {PROGRAM} v{run.get('tool_version', __version__)}.")
    b.h("References", 2)
    for ref_ in ("ISO/TS 14076:2025. Environmental management - Environmental techno-economic assessment - Principles, "
                 "requirements and guidance.",
                 "IEC 60300-3-3:2017. Dependability management - Part 3-3: Application guide - Life cycle costing.",
                 "Kemp I.C. (2007). Pinch Analysis and Process Integration: A User Guide on Process Integration for "
                 "the Efficient Use of Energy, 2nd ed. Butterworth-Heinemann.",
                 f"{prov.get('data source', case.data_source or '')}"):
        if ref_:
            b.p(f"- {ref_}")
    if has_econ:
        b.p("Sources of the economic inputs, as recorded in the run:")
        seen = set()
        for k, v in {**ec.get("default_sources", {}), **ec.get("case_sources", {})}.items():
            if v not in seen:
                seen.add(v)
                b.p(f"- {k}: {_short(v, 600)}")
    return rep


def _table_number(rep: Report, prefix: str) -> str:
    """Number of the first table whose caption starts with ``prefix`` (for cross-references)."""
    for blk, k in rep.numbered():
        if isinstance(blk, Table) and blk.caption.startswith(prefix):
            return str(k)
    return "?"


def _close(fig) -> None:
    from pinch.plotting import close_figure
    close_figure(fig)


# ================================================================== markup (shared by both renderers)
_TOKEN = re.compile(r"\*\*(.+?)\*\*|_\{(.+?)\}|\^\{(.+?)\}")


def runs(text: str) -> list[tuple[str, str]]:
    """Split markup into (text, style) runs; style is '' (plain), 'b' (bold), 'sub' or 'sup'.

    ``**x**`` bold, ``_{x}`` subscript, ``^{x}`` superscript; no nesting.
    """
    out: list[tuple[str, str]] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], ""))
        bold, sub, sup = m.groups()
        out.append((bold, "b") if bold is not None else (sub, "sub") if sub is not None else (sup, "sup"))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], ""))
    return out


def plain(text: str) -> str:
    """Text without markup (for tests and searches)."""
    return "".join(t for t, _ in runs(text))
