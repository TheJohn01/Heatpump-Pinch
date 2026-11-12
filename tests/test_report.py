"""TEA report (pinch.report, pinch.report_render): derived numbers against known answers, structure and
caption rules, and both files (PDF and Word) written and read back."""

import io
import json
import math
import re
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

pytest.importorskip("reportlab")
docx = pytest.importorskip("docx")

from pinch import process_diagram as pdg  # noqa: E402
from pinch import report as rp  # noqa: E402
from pinch.case import load_case  # noqa: E402
from pinch.cycle_analysis import load_selected  # noqa: E402
from pinch.economics import evaluate  # noqa: E402
from pinch.investment import npv  # noqa: E402
from pinch.report_render import to_docx, to_pdf  # noqa: E402
from pinch.streams import load_streams  # noqa: E402
from pinch.validation import ROOT  # noqa: E402
from scripts.analysis.analyse import compute  # noqa: E402

SECTIONS = ["Abstract", "1. Goal and scope definition", "2. Technical analysis", "3. Economic analysis",
            "4. Environmental assessment", "5. Sensitivity analysis", "6. Interpretation", "7. Documentation"]


def _run(name):
    case = load_case(ROOT / "cases" / f"{name}.json")
    streams = load_streams(case.stream_file)
    res = compute(case, streams, cycle_selected=load_selected(ROOT / "outputs" / name / "cycle_screening.json"))
    res.snapshot_pngs()
    rq_path = ROOT / "outputs" / name / "rq_consolidated.csv"
    rq = pd.read_csv(rq_path) if rq_path.exists() else None
    path = pdg.flowsheet_path(ROOT, name)
    layout = pdg.load_flowsheet(path) if path.exists() else None
    rep = rp.build_report(case, streams, res.summary, res.tables, res.pngs, rq, layout, generated=date(2026, 11, 12))
    return case, streams, res, rep


@pytest.fixture(scope="module")
def brewery():
    return _run("brewery")


@pytest.fixture(scope="module")
def brewery_files(brewery):
    rep = brewery[3]
    return to_pdf(rep), to_docx(rep)


# ------------------------------------------------------------------ derived numbers (known answers)
def test_economics_reproduce_the_saved_full_design(brewery):
    """The report's re-evaluation equals the committed economics output (outputs/brewery/economics.json)."""
    case, streams, *_ = brewery
    e = rp.economics_of(case, streams)
    saved = json.loads((ROOT / "outputs" / "brewery" / "economics.json").read_text())
    full = saved["results"]["full design (heat recovery installed)"]
    assert e.capex_EUR == pytest.approx(full["capex_EUR"], abs=1)
    assert e.savings_EUR == pytest.approx(full["savings_EUR"], abs=1)
    assert e.npv_EUR == pytest.approx(full["npv_EUR"], abs=1)
    assert e.rerun(e.params) == pytest.approx(e.npv_EUR, abs=1e-6)


def test_cash_flow_table_ends_at_the_npv():
    """Last cumulative discounted value = -I + S x annuity factor (Towler and Sinnott, Sec. 9.6)."""
    cf = rp.cash_flow_table(1000.0, 150.0, 0.05, 10)
    af = (1 - 1.05 ** -10) / 0.05
    assert cf["cumulative_discounted_EUR"].iloc[-1] == pytest.approx(-1000 + 150 * af, rel=1e-12)
    assert cf["discounted_EUR"].iloc[1] == pytest.approx(150 / 1.05)
    assert len(cf) == 11 and cf["cash_flow_EUR"].iloc[0] == -1000


def test_npv_swings(brewery):
    case, streams, *_ = brewery
    e = rp.economics_of(case, streams)
    sw = rp.npv_swings(e).set_index("input")
    assert sw.loc["CAPEX", "minus"] == pytest.approx(0.2 * e.capex_EUR)
    assert sw.loc["CAPEX", "plus"] == pytest.approx(-0.2 * e.capex_EUR)
    # NPV is linear in the gas price: symmetric change, sign of more expensive gas = more saving
    assert sw.loc["Gas price", "plus"] == pytest.approx(-sw.loc["Gas price", "minus"], rel=1e-9)
    assert sw.loc["Gas price", "plus"] > 0 > sw.loc["Electricity price", "plus"]
    # boiler efficiency 0.845 x 1.2 > 1 on GCV: capped and labelled
    capped = [i for i in sw.index if i.startswith("Boiler efficiency")]
    assert capped == ["Boiler efficiency (upper value capped at 1.0, GCV)"]
    expected = evaluate(e.full, e.baseline, replace(e.params, boiler_efficiency=1.0)).npv_EUR - e.npv_EUR
    assert sw.loc[capped[0], "plus"] == pytest.approx(expected)
    # the chiller COP changes the baseline itself: not zero (rebuilt), higher COP = smaller credit
    assert sw.loc["Chiller COP", "plus"] < 0 < sw.loc["Chiller COP", "minus"]
    order = sw[["minus", "plus"]].abs().max(axis=1).to_numpy()
    assert all(order[:-1] >= order[1:])


def test_per_mwh_indicators(brewery):
    case, streams, *_ = brewery
    e = rp.economics_of(case, streams)
    per = rp.per_MWh_heat(e)
    af = e.params.annuity_factor
    assert per["net_cost_EUR_per_MWh"] == pytest.approx(-e.npv_EUR / (af * e.Q_hp_MWh))
    saved = json.loads((ROOT / "outputs" / "brewery" / "economics.json").read_text())
    co2 = saved["results"]["full design (heat recovery installed)"]["co2_avoided_t"]
    assert per["co2_avoided_kg_per_MWh"] == pytest.approx(co2 * 1000 / e.Q_hp_MWh, rel=1e-6)


def test_irr_of_the_reported_cash_flows_gives_zero_npv(brewery):
    case, streams, *_ = brewery
    e = rp.economics_of(case, streams)
    flows = rp.cash_flow_table(e.capex_EUR, e.savings_EUR, 0.0, e.params.horizon_years)["cash_flow_EUR"]
    from pinch.investment import irr
    assert npv(flows, irr(flows)) == pytest.approx(0.0, abs=1e-3)


def test_formatting():
    assert rp.eur(-11581.4) == "-€11,581" and rp.eur(17886) == "€17,886" and rp.eur(-0.2) == "€0"
    assert rp.pct(0.6624) == "66.2 %" and rp.years(math.inf) == "never" and rp.ratio(-math.inf) == "none"
    assert rp.ratio(math.inf) == "any ratio" and rp.ratio(2.229) == "2.23"
    assert rp.runs("a **b** Q_{h,min} x^{2}") == [("a ", ""), ("b", "b"), (" Q", ""), ("h,min", "sub"),
                                                  (" x", ""), ("2", "sup")]


# ------------------------------------------------------------------ structure and caption rules
def test_sections_in_iso_order(brewery):
    rep = brewery[3]
    h1 = [b.text for b in rep.blocks if isinstance(b, rp.Heading) and b.level == 1]
    assert len(h1) == len(SECTIONS)
    assert all(h.startswith(s) for h, s in zip(h1, SECTIONS))
    assert isinstance(rep.blocks[0], rp.Box) and rp.STANDARD in rep.blocks[0].text


def test_caption_rules(brewery):
    rep = brewery[3]
    caps = rep.captions()
    for kind in ("Table", "Figure"):
        nums = [int(re.match(rf"{kind} (\d+)\.", c).group(1)) for c in caps if c.startswith(kind)]
        assert nums == list(range(1, len(nums) + 1))          # numbered from 1, in order
    assert all(b.caption.rstrip().endswith(".") and b.caption[0].isupper()
               for b in rep.blocks if isinstance(b, rp.Table | rp.Figure))
    assert all(b.png[:8] == b"\x89PNG\r\n\x1a\n" for b in rep.blocks if isinstance(b, rp.Figure))
    assert all(len(r) == len(b.header) for b in rep.blocks if isinstance(b, rp.Table) for r in b.rows)


def test_every_figure_of_the_run_is_in_the_report(brewery):
    """All matplotlib figures of the run, the cash flow and ±20 % figures, the RQ tornado and (with CairoSVG)
    the flowsheet and T* diagram."""
    *_, res, rep = brewery
    figs = [b.png for b in rep.blocks if isinstance(b, rp.Figure)]
    for stem, png in res.pngs.items():
        assert png in figs, stem
    svg = 2 if rp.svg_png("<svg xmlns='http://www.w3.org/2000/svg' width='2' height='2'/>") else 0
    assert len(figs) == len(res.pngs) + 3 + svg


def test_missing_cairo_gives_a_note(brewery, monkeypatch):
    case, streams, res, _ = brewery
    monkeypatch.setattr(rp, "svg_png", lambda svg, width_px=2000: None)
    rep = rp.build_report(case, streams, res.summary, res.tables, res.pngs)
    text = " ".join(b.text for b in rep.blocks if isinstance(b, rp.Para))
    assert "flowsheet could not be drawn" in text and "T* diagram could not be drawn" in text


def test_numbers_in_the_abstract_match_the_run(brewery):
    *_, res, rep = brewery
    full = res.summary["economics"]["results"]["full design (heat recovery installed)"]
    abstract = rp.plain(next(b.text for b in rep.blocks if isinstance(b, rp.Para) and "pinch analysis" in b.text))
    assert rp.eur(full["capex_EUR"]) in abstract and rp.eur(full["npv_EUR"]) in abstract
    assert "66.2 %" in abstract                                  # RQ1 of the saved consolidated table


def test_case_without_basis_builds_technical_part_only():
    case, streams, res, rep = _run("four_stream_process")
    text = " ".join(rp.plain(b.text) for b in rep.blocks if isinstance(b, rp.Para))
    assert "Not computed" in text
    assert not any(isinstance(b, rp.Table) and b.caption.startswith("Economic inputs") for b in rep.blocks)
    assert to_pdf(rep)[:5] == b"%PDF-" and to_docx(rep)[:2] == b"PK"


def test_spray_dryer_retrofit_bounds_numbered_after_rq():
    rep = _run("spray_dryer")[3]
    h2 = [b.text for b in rep.blocks if isinstance(b, rp.Heading) and b.level == 2]
    assert "3.6 Against today's site (research questions)" in h2
    assert "3.7 Retrofit of the heat-exchanger network" in h2


# ------------------------------------------------------------------ files
def test_pdf(brewery, brewery_files):
    pdf, _ = brewery_files
    assert pdf[:5] == b"%PDF-"
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
    rep = brewery[3]
    assert pages >= 1 + len(SECTIONS)                           # title page + a new page per section
    assert b"/Title (TEA - Brewery)" in pdf or b"TEA - Brewery" in pdf
    n_fig = sum(isinstance(b, rp.Figure) for b in rep.blocks)
    assert len(re.findall(rb"/Subtype\s*/Image", pdf)) >= n_fig


def test_docx_read_back(brewery, brewery_files):
    _, data = brewery_files
    rep = brewery[3]
    d = docx.Document(io.BytesIO(data))
    caps = [p.text for p in d.paragraphs if p.style.name == "Caption"]
    # the number is a SEQ field (python-docx's text skips fields): compare the rest, then the cached numbers
    assert [re.sub(r"^(Table|Figure) \d+\.", r"\1 .", rp.plain(c)) for c in rep.captions()] == caps
    cached = re.findall(r'SEQ (Table|Figure) \\\* ARABIC.*?<w:t>(\d+)</w:t>', d.element.xml, flags=re.S)
    assert [f"{k} {n}" for k, n in cached] == [c.split(".")[0] for c in rep.captions()]
    assert len(d.tables) == 1 + sum(isinstance(b, rp.Table) for b in rep.blocks)   # + the title-page box
    assert len(d.inline_shapes) == sum(isinstance(b, rp.Figure) for b in rep.blocks)
    assert rp.FOOTER in d.sections[0].footer.paragraphs[0].text
    assert "SEQ Table" in d.element.xml and "PAGE" in d.sections[0].footer._element.xml
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert all(h.startswith(s) for h, s in zip(h1, SECTIONS))
    assert d.styles["Heading 1"].paragraph_format.page_break_before
    assert d.core_properties.title == "TEA - Brewery"
