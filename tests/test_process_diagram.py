"""Process diagrams (pinch.process_diagram): layout checks, stream identifiers, duties and SVG content.

Known answers are the brewery stream table (Padullés et al. 2026, data/brewery_streams.csv) and the
committed heat pump design (outputs/brewery/heat_pump_design.csv): the tags must carry the table's
duties and the heat pump boxes the design's COP and work.
"""

import json
import re
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from pinch import process_diagram as pdg
from pinch.case import load_case
from pinch.streams import load_streams
from pinch.theme import DARK, LIGHT
from pinch.validation import ROOT

LAYOUT = ROOT / "data" / "brewery_flowsheet.json"
TARGETS = {"Qh_min": 10.0424, "Qc_min": 3.4424, "heat_recovery": 11.3576, "pinch_T_star_C": [17.0]}


@pytest.fixture(scope="module")
def brewery():
    case = load_case(ROOT / "cases" / "brewery.json")
    return load_streams(case.stream_file)


@pytest.fixture(scope="module")
def hp():
    return pd.read_csv(ROOT / "outputs" / "brewery" / "heat_pump_design.csv")


@pytest.fixture(scope="module")
def fs():
    return pdg.load_flowsheet(LAYOUT)


def _text(svg: str) -> str:
    return " ".join(t for t in ET.fromstring(svg).itertext())


def test_stream_ids_follow_table_order(brewery):
    ids = pdg.stream_ids(brewery)
    assert ids["Wortcooling"] == "H1" and ids["Filtration/centrifugation"] == "H6"
    assert ids["Pre-mashing"] == "C1" and ids["CIP"] == "C6"
    assert sorted(ids.values()) == sorted([f"H{i}" for i in range(1, 7)] + [f"C{i}" for i in range(1, 7)])


def test_brewery_layout_owns_every_stream_once(fs, brewery):
    assert pdg.unassigned_streams(fs, brewery) == []
    assert {h.unit for h in fs.heat_pumps} == {"Warm-water HP", "HTHP (wort boiling)"}


def test_tags_carry_the_stream_table_duties(fs, brewery):
    """Wort kettle = C4 + C5 = 3.0 + 2.4; condenser = H2 + H3 = 2.4 + 0.9 (kWh/hl)."""
    txt = _text(pdg.flowsheet_svg(fs, brewery, view="energy"))
    for tag in ("C1 +4.4", "C3 +6", "C4+C5 +5.4", "C6 +2.1", "H1 −8.5", "H2+H3 −3.3", "H6 −0.4"):
        assert tag in txt
    demand = sum(s.Q for s in brewery.cold)
    release = sum(s.Q for s in brewery.hot)
    assert demand == pytest.approx(21.4) and release == pytest.approx(14.8)


def test_tags_follow_edits(fs, brewery):
    from dataclasses import replace
    edited = replace(brewery, streams=tuple(replace(s, Q=5.0) if s.name == "Mashing" else s
                                            for s in brewery.streams))
    assert "C2 +5" in _text(pdg.flowsheet_svg(fs, edited, view="energy"))


@pytest.mark.parametrize("view", pdg.VIEWS)
@pytest.mark.parametrize("palette", [LIGHT, DARK])
def test_every_view_is_well_formed_svg(fs, brewery, hp, view, palette):
    for svg in (pdg.flowsheet_svg(fs, brewery, hp, view, palette),
                pdg.stream_diagram_svg(brewery, TARGETS, hp, view, palette)):
        root = ET.fromstring(svg)
        assert root.get("viewBox").startswith("0 0 680 ")
        assert root.get("role") == "img"
        height = float(root.get("viewBox").split()[3])
        for x in re.findall(r"x='([-\d.]+)'|x=\"([-\d.]+)\"", svg):
            v = float(x[0] or x[1])
            assert 0 <= v <= 680
        for y in re.findall(r" y='([-\d.]+)'", svg):
            assert 0 <= float(y) <= height


def test_layers_by_view(fs, brewery, hp):
    process = _text(pdg.flowsheet_svg(fs, brewery, hp, "process"))
    assert "Wort kettle" in process and "C1 +4.4" not in process and "HP1" not in process
    hps = _text(pdg.flowsheet_svg(fs, brewery, hp, "heat_pumps"))
    assert "HP1 · water" in hps and "HP2 · HTHP" in hps
    assert "COP 3.23 · W 2.26" in hps and "COP 1.81 · W 1.53" in hps   # outputs/brewery/heat_pump_design.csv
    everything = _text(pdg.flowsheet_svg(fs, brewery, hp, "all"))
    assert "C1 +4.4" in everything and "HP2 · HTHP" in everything


def test_heat_pump_sources_split_process_and_ambient(fs, brewery, hp):
    """HP1 draws 3.44 from the process and 1.58 from ambient; HP2 1.23 from ambient only."""
    svg = pdg.flowsheet_svg(fs, brewery, hp, "heat_pumps")
    assert "3.44 kWh/hl to the heat pump sources" in svg
    assert svg.count("+ ambient") == 2
    assert "External (ambient) source 1.58" in svg and "External (ambient) source 1.23" in svg


def test_tstar_diagram_targets_and_pinch(brewery, hp):
    txt = _text(pdg.stream_diagram_svg(brewery, TARGETS, hp, "all"))
    for s in ("Pinch T* 17 °C", "10.04", "3.442", "11.36", "HP1", "HP2", "H1", "C6"):
        assert s in txt


def test_tstar_diagram_without_heat_pumps_or_pinch(brewery):
    svg = pdg.stream_diagram_svg(brewery, {**TARGETS, "pinch_T_star_C": []}, None, "heat_pumps")
    ET.fromstring(svg)
    assert "HP1" not in _text(svg)


@pytest.mark.parametrize("change, message", [
    (lambda d: d["steps"].append(dict(d["steps"][0])), "duplicate"),
    (lambda d: d["steps"][1].update(row=0, col=0), "grid cell"),
    (lambda d: d["steps"][0].update(col=4), "off the grid"),
    (lambda d: d["flows"].append(["Mashing", "Brewhouse"]), "unknown step"),
    (lambda d: d["heat_pumps"][0]["serves"].append("Bottling"), "unknown step"),
    (lambda d: d["steps"][1]["streams"].append("Pre-mashing"), "two steps"),
])
def test_layout_errors_are_reported(tmp_path, change, message):
    d = json.loads(LAYOUT.read_text(encoding="utf-8"))
    change(d)
    p = tmp_path / "bad_flowsheet.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        pdg.load_flowsheet(p)


def test_unknown_view_is_rejected(fs, brewery):
    with pytest.raises(ValueError):
        pdg.flowsheet_svg(fs, brewery, view="sideways")
