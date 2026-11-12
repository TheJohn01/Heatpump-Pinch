"""Data input (step 1): units (pinch.units), guided extraction (pinch.extraction), Aspen Plus export
(pinch.aspen_import) and project files (pinch.project), against known answers."""

import io
import math
import zipfile

import pandas as pd
import pytest

pytest.importorskip("pint")

from pinch import aspen_import, extraction  # noqa: E402
from pinch import project as prj  # noqa: E402
from pinch.problem_table_algorithm import problem_table  # noqa: E402
from pinch.streams import load_streams, streams_from_frame  # noqa: E402
from pinch.units import convert, standardise_table  # noqa: E402
from pinch.validation import ROOT  # noqa: E402

EXPORT = ROOT / "tests" / "fixtures" / "aspen_export"


# ------------------------------------------------------------------ units
def test_conversions_known_answers():
    assert convert(212, "degF", "degC") == pytest.approx(100.0)
    assert convert(1, "Btu/h", "W") == pytest.approx(0.29307107, rel=1e-6)          # IT Btu
    assert convert(1, "kcal/h", "W") == pytest.approx(1.16222, rel=1e-5)             # thermochemical kcal
    assert convert(239005.736, "cal/s", "kW") == pytest.approx(1000.0, rel=1e-9)
    assert convert(18, "delta_degF", "kelvin") == pytest.approx(10.0)


def test_four_stream_example_in_imperial_units_gives_the_same_targets():
    """Kemp's four-stream example (MW, °C) rewritten in °F and Btu/h per °F: same Q̇h,min and Q̇c,min after conversion."""
    base = pd.read_csv(ROOT / "data" / "four_stream_process_streams.csv")
    imp = pd.DataFrame({"stream": base["stream"], "type": base["type"],
                        "T_in_F": base["T_in_C"] * 9 / 5 + 32, "T_out_F": base["T_out_C"] * 9 / 5 + 32,
                        "dT_shift_F": base["dT_shift_K"] * 9 / 5,
                        "CP_Btu_per_hr_per_F": base["CP_MW_per_K"] * 1e6 / 0.29307107 / 1.8})
    df, notes = standardise_table(imp)
    assert "CP_kW_per_K" in df.columns and len(notes) == 4
    t_conv = problem_table(streams_from_frame(df))
    t_ref = problem_table(load_streams(ROOT / "data" / "four_stream_process_streams.csv"))
    assert t_conv.Qh_min == pytest.approx(1000 * t_ref.Qh_min, rel=1e-6)            # MW -> kW
    assert t_conv.Qc_min == pytest.approx(1000 * t_ref.Qc_min, rel=1e-6)


def test_model_units_are_left_alone():
    df = pd.read_csv(ROOT / "data" / "brewery_streams.csv")
    out, notes = standardise_table(df)
    assert notes == [] and "Q_kWh_per_hl" in out.columns


def test_unit_errors():
    with pytest.raises(ValueError, match="temperature unit"):
        standardise_table(pd.DataFrame({"stream": ["a"], "type": ["hot"], "T_in_X": [1], "T_out_C": [0],
                                        "dT_shift_K": [5], "Q_kW": [1]}))
    with pytest.raises(ValueError, match="unknown unit"):
        standardise_table(pd.DataFrame({"stream": ["a"], "type": ["hot"], "T_in_C": [1], "T_out_C": [0],
                                        "dT_shift_K": [5], "Q_zorks": [1]}))
    with pytest.raises(ValueError, match="not an energy or a power"):
        standardise_table(pd.DataFrame({"stream": ["a"], "type": ["hot"], "T_in_C": [1], "T_out_C": [0],
                                        "dT_shift_K": [5], "Q_furlong": [1]}))


# ------------------------------------------------------------------ guided extraction
def _rec(**kw):
    base = {c: math.nan for c in extraction.COLUMNS} | {"include": True, "reasoning": "needed", "soft_target": False}
    return base | kw


def test_extraction_known_answers():
    rec = pd.DataFrame([
        _rec(stream="Feed", flowsheet_id="S1 → S2", T_supply_C=20, T_target_C=80, mass_flow_kg_s=2, cp_kJ_kgK=4.18),
        _rec(stream="Product", flowsheet_id="S5 → S6", T_supply_C=120, T_target_C=40, duty=-500, dT_shift_K=10),
        _rec(stream="Reboiler", flowsheet_id="S7", T_supply_C=110, T_target_C=110, duty=300),
        _rec(stream="Condenser", T_supply_C=60, T_target_C=60, duty=-200),
        _rec(include=False, stream="H2 off-gas", reasoning="kept separate for safety"),
    ])
    streams, excluded, warnings = extraction.extract(rec)
    s = streams.set_index("stream")
    assert s.loc["Feed", "Q_kW"] == pytest.approx(2 * 4.18 * 60) and s.loc["Feed", "type"] == "cold"
    assert s.loc["Product", "type"] == "hot" and s.loc["Product", "dT_shift_K"] == 10
    assert (s.loc["Reboiler", "T_in_C"], s.loc["Reboiler", "T_out_C"]) == (110, 111)       # heat added: cold
    assert (s.loc["Condenser", "T_in_C"], s.loc["Condenser", "T_out_C"]) == (60, 59)       # heat removed: hot, 1 K lower
    assert list(excluded["stream"]) == ["H2 off-gas"]
    assert any("over 1 K" in w for w in warnings)
    streams_from_frame(streams)                                                             # a valid stream table


def test_extraction_unit_and_errors():
    s, _, _ = extraction.extract(pd.DataFrame([_rec(stream="a", T_supply_C=100, T_target_C=50, duty=3412142)]),
                                 energy_unit="Btu/h")
    assert s["Q_kW"].iloc[0] == pytest.approx(1000.0, rel=1e-6)
    with pytest.raises(ValueError, match="differ"):
        extraction.extract(pd.DataFrame([_rec(stream="a", T_supply_C=20, T_target_C=80, duty=100,
                                              mass_flow_kg_s=2, cp_kJ_kgK=4.18)]))
    with pytest.raises(ValueError, match="without a reason"):
        extraction.extract(pd.DataFrame([_rec(stream="a", include=False, reasoning=math.nan)]))
    with pytest.raises(ValueError, match="signed duty"):
        extraction.extract(pd.DataFrame([_rec(stream="a", T_supply_C=60, T_target_C=60, mass_flow_kg_s=1,
                                              latent_kJ_kg=2000)]))


def test_extraction_flags_a_stream_extracted_twice_but_not_a_chain():
    rec = pd.DataFrame([_rec(stream="c1", flowsheet_id="A → B", T_supply_C=200, T_target_C=150, duty=-10),
                        _rec(stream="c2", flowsheet_id="B → C", T_supply_C=150, T_target_C=100, duty=-10),
                        _rec(stream="c3", flowsheet_id="A → D", T_supply_C=200, T_target_C=120, duty=-10)])
    _, _, warnings = extraction.extract(rec)
    assert len(warnings) == 1 and "'A'" in warnings[0] and "c3" in warnings[0]


def test_near_pinch():
    s = load_streams(ROOT / "data" / "four_stream_process_streams.csv")
    t = problem_table(s)
    names = extraction.near_pinch(s, list(t.pinch_T_star_C), margin_K=0)
    assert names and all(n in [x.name for x in s.streams] for n in names)


# ------------------------------------------------------------------ Aspen Plus export
def test_aspen_candidates_known_answers():
    rec, notes = aspen_import.candidates(EXPORT)
    r = rec.set_index("stream")
    assert r.loc["COOLER", "duty"] == pytest.approx(-1000.0, rel=1e-6)
    assert (r.loc["COOLER", "T_supply_C"], r.loc["COOLER", "T_target_C"]) == (120.0, 40.0)
    assert "Phase change" in r.loc["COOLER", "reasoning"]
    assert r.loc["HEATER", "duty"] == pytest.approx(500.0, rel=1e-6)
    assert not r.loc["MIXHEAT", "include"] and "mixing" in r.loc["MIXHEAT", "reasoning"]
    assert r.loc["HX1 hot", "duty"] == pytest.approx(-250.0, rel=1e-6)
    assert (r.loc["HX1 cold", "T_supply_C"], r.loc["HX1 cold", "T_target_C"]) == (60.0, 90.0)
    streams, excluded, _ = extraction.extract(rec)
    assert len(streams) == 4 and list(excluded["stream"]) == ["MIXHEAT"]
    st = streams_from_frame(streams)
    assert sum(x.Q for x in st.hot) == pytest.approx(1250.0, rel=1e-6)


def test_aspen_zip_and_runs():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in EXPORT.rglob("*.csv"):
            z.write(p, f"export/{p.relative_to(EXPORT).as_posix()}")
    data = buf.getvalue()
    assert aspen_import.list_runs(data) == ["export/run1"]
    rec, _ = aspen_import.candidates(data)
    assert len(rec) == 5
    with pytest.raises(ValueError, match="no run folder"):
        aspen_import.candidates(b"PK\x05\x06" + b"\x00" * 18)          # empty zip


# ------------------------------------------------------------------ project files
def test_project_round_trip():
    streams = pd.read_csv(ROOT / "data" / "brewery_streams.csv")
    levels = pd.DataFrame({"name": ["HP1"], "T_sink_in_C": ["18"], "T_sink_out_C": ["82"], "T_source_C": [None]})
    rec = pd.DataFrame([_rec(stream="Feed", T_supply_C=20, T_target_C=80, duty=10)])
    p = prj.Project("brewery", "brewery", {"eta": 0.45, "basis_on": True, "econ_gas_price_EUR_per_kWh": 0.06},
                    streams, levels, rec)
    q = prj.loads(prj.dumps(p), ("brewery",))
    assert q.inputs == p.inputs and q.choice == "brewery"
    pd.testing.assert_frame_equal(q.streams, streams, check_dtype=False)
    assert q.levels.loc[0, "T_sink_out_C"] == "82" and q.extraction is not None
    assert q.extraction.loc[0, "stream"] == "Feed"


@pytest.mark.parametrize("text, match", [
    ("not json", "not a JSON"),
    ('{"format": "other"}', "not a heatpump-pinch"),
    ('{"format": "heatpump-pinch project", "format_version": 99}', "not supported"),
    ('{"format": "heatpump-pinch project", "format_version": 1, "choice": "x", "name": "n", "inputs": {}, '
     '"streams": [], "levels": []}', "not available"),
])
def test_project_validation(text, match):
    with pytest.raises(ValueError, match=match):
        prj.loads(text, ("brewery",))


def test_project_rejects_a_bad_stream_table():
    p = prj.Project("", "x", {}, pd.DataFrame({"stream": ["a"], "type": ["hot"], "T_in_C": [10], "T_out_C": [50],
                                               "dT_shift_K": [5], "Q_kW": [1]}),
                    pd.DataFrame({"name": ["HP"], "T_sink_in_C": ["1"], "T_sink_out_C": ["2"], "T_source_C": [0]}))
    with pytest.raises(ValueError, match="stream table"):
        prj.loads(prj.dumps(p))
