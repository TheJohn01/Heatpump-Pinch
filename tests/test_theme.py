"""Theme: config.toml matches pinch/theme.py, colours meet WCAG contrast, fonts are present,
and every chart follows the palette it is given (light and dark)."""

import tomllib

import pandas as pd
import pytest

from pinch import charts, problem_table
from pinch.streams import load_streams
from pinch.theme import (
    DARK,
    GRAPHIC_MIN_CONTRAST,
    LIGHT,
    PALETTES,
    TEXT_MIN_CONTRAST,
    contrast_ratio,
    palette_for,
    ramp,
    relative_luminance,
)
from pinch.validation import ROOT

CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
MODES = [LIGHT, DARK]


def _flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def test_contrast_reference_values():
    """WCAG anchors: black on white is 21:1, a colour against itself 1:1."""
    assert relative_luminance("#FFFFFF") == pytest.approx(1.0)
    assert relative_luminance("#000000") == pytest.approx(0.0)
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
    assert contrast_ratio("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)   # the usual AA grey


def test_ramp_ends_and_length():
    r = ramp("#000000", "#FFFFFF", 3)
    assert r == ["#000000", "#808080", "#FFFFFF"]
    with pytest.raises(ValueError):
        ramp("#000000", "#FFFFFF", 1)


def test_every_config_key_is_a_streamlit_option():
    config = pytest.importorskip("streamlit.config")
    known = set(config._config_options_template)
    keys = [k for k, _ in _flatten(CONFIG)]
    assert not [k for k in keys if k not in known], "unknown keys in .streamlit/config.toml"


@pytest.mark.parametrize("p", MODES, ids=lambda p: p.mode)
def test_config_matches_palette(p):
    t = CONFIG["theme"][p.mode]
    expected = {"backgroundColor": p.background, "secondaryBackgroundColor": p.secondary_background,
                "textColor": p.text, "borderColor": p.border, "dataframeBorderColor": p.border,
                "primaryColor": p.primary, "linkColor": p.link, "redColor": p.hot, "blueColor": p.cold,
                "redTextColor": p.hot, "blueTextColor": p.cold, "chartCategoricalColors": p.categorical(),
                "chartSequentialColors": p.sequential(), "chartDivergingColors": p.diverging()}
    assert {k: t.get(k) for k in expected} == expected
    assert len(p.sequential()) == len(p.diverging()) == 10      # Streamlit ignores any other length
    assert t["sidebar"]["backgroundColor"] == p.secondary_background


@pytest.mark.parametrize("p", MODES, ids=lambda p: p.mode)
def test_text_contrast(p):
    """Body text, links and the hot/cold label colours are readable on both backgrounds (4.5:1)."""
    for bg in (p.background, p.secondary_background):
        for name in ("text", "link", "hot", "cold"):
            assert contrast_ratio(getattr(p, name), bg) >= TEXT_MIN_CONTRAST, (p.mode, name, bg)


def _tint(colour: str, bg: str, alpha: float = 0.1) -> str:
    """``colour`` laid over ``bg`` at ``alpha``: Streamlit's fill behind a selected pill or segment."""
    c, g = (int(colour[i:i + 2], 16) for i in (1, 3, 5)), (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round((1 - alpha) * y + alpha * x):02X}" for x, y in zip(c, g))


@pytest.mark.parametrize("p", MODES, ids=lambda p: p.mode)
def test_primary_colour_compromise(p):
    """Streamlit uses primaryColor twice: as the fill behind white button text and as the text of a selected
    pill on a 10 % tint. On a near-black background no colour gives 4.5:1 for both (white text needs
    luminance <= 0.18, text on the background needs >= 0.21), so the dark primary balances the two at 4.0:1;
    the light primary meets 4.5:1 for both."""
    on_button = contrast_ratio("#FFFFFF", p.primary)
    on_pill = contrast_ratio(p.primary, _tint(p.primary, p.background))
    floor = TEXT_MIN_CONTRAST if p.mode == "light" else 4.0
    assert min(on_button, on_pill) >= floor, (p.mode, on_button, on_pill)


@pytest.mark.parametrize("p", MODES, ids=lambda p: p.mode)
def test_graphic_contrast(p):
    """Chart marks and the primary widget fill stand out from the background (3:1)."""
    for c in p.categorical() + [p.primary]:
        assert contrast_ratio(c, p.background) >= GRAPHIC_MIN_CONTRAST, (p.mode, c)


@pytest.mark.parametrize("p", MODES, ids=lambda p: p.mode)
def test_hot_and_cold_differ_in_lightness_too(p):
    """Hot and cold must stay distinct, and the physics colours must not double as the accents."""
    assert p.hot != p.cold
    assert {p.hot, p.cold}.isdisjoint({p.accent, p.accent2, p.primary, p.link})


def test_palette_for_defaults_to_light():
    assert palette_for(None) is LIGHT and palette_for("dark") is DARK and palette_for("other") is LIGHT
    assert set(PALETTES) == {"light", "dark"}


def test_fonts_are_served_and_licensed():
    assert CONFIG["server"]["enableStaticServing"] is True
    faces = CONFIG["theme"]["fontFaces"]
    families = {f["family"] for f in faces}
    assert families == {"IBM Plex Sans", "IBM Plex Mono"}
    for f in faces:
        assert f["url"].startswith("app/static/")
        path = ROOT / "static" / f["url"].removeprefix("app/static/")
        assert path.is_file() and path.read_bytes()[:4] == b"wOF2", path
    assert "SIL Open Font License" in (ROOT / "static" / "fonts" / "OFL.txt").read_text(encoding="utf-8")
    assert CONFIG["theme"]["font"].startswith("IBM Plex Sans") and CONFIG["theme"]["codeFont"].startswith("IBM Plex Mono")


def _colours(spec) -> set[str]:
    """Every '#RRGGBB' string anywhere in a Vega-Lite spec."""
    found: set[str] = set()
    if isinstance(spec, dict):
        for v in spec.values():
            found |= _colours(v)
    elif isinstance(spec, list):
        for v in spec:
            found |= _colours(v)
    elif isinstance(spec, str) and spec.startswith("#") and len(spec) == 7:
        found.add(spec.upper())
    return found


@pytest.fixture(scope="module")
def four_stream():
    streams = load_streams(ROOT / "data" / "four_stream_process_streams.csv")
    return streams, problem_table(streams)


def _all_charts(four_stream, p):
    streams, table = four_stream
    curve = pd.DataFrame({"fraction_of_Qh_min": [0.0, 0.5], "payback_years": [2.0, 6.0], "npv_EUR": [1e5, -1e4]})
    ratio = pd.DataFrame({"ratio": [1.5, 3.0], "payback_years": [2.0, 9.0], "npv_EUR": [2e5, -5e4]})
    st = pd.DataFrame({"dTmin_K": [5.0, 10.0], "TAC_EUR": [1e5, 9e4], "cost_law": ["law", "law"],
                       "area_m2": [100.0, 60.0], "Qh_min": [1.0, 2.0]})
    options = pd.DataFrame({"option": ["a", "b"], "gas_reduction_vs_baseline": [0.2, 0.4],
                            "payback_years": [3.0, 6.0], "npv_EUR": [1e5, 2e5], "capex_EUR": [1e5, 3e5]})
    rq = pd.DataFrame({"sensitivity": ["base", "up", "down"], "RQ3_ratio_HP1": [2.5, 2.9, 2.1],
                       "HP1_name": ["HP1"] * 3, "price_ratio": [2.4] * 3, "RQ1_HP_gas_share": [0.3] * 3,
                       "basis": ["x"] * 3})
    return {"composite": charts.composite_curves_chart(streams, table, palette=p),
            "gcc": charts.gcc_chart(table, palette=p),
            "supertargeting": charts.supertargeting_chart(st, palette=p),
            "electrification": charts.electrification_chart(curve, 5.0, palette=p),
            "price_ratio": charts.price_ratio_chart(ratio, 2.4, 5.0, palette=p),
            "retrofit": charts.retrofit_charts(options, palette=p)[1],
            "tornado": charts.tornado_chart(rq, palette=p)}


@pytest.mark.parametrize("p", MODES, ids=lambda p: p.mode)
def test_charts_use_only_their_palette(four_stream, p):
    allowed = {c.upper() for c in p.categorical()}
    for name, ch in _all_charts(four_stream, p).items():
        used = _colours(ch.to_dict())
        assert used, name
        assert used <= allowed, (name, used - allowed)


@pytest.mark.parametrize("p", MODES, ids=lambda p: p.mode)
def test_red_and_blue_only_on_thermal_charts(four_stream, p):
    """Economics charts use the accents: red and blue would read as hot and cold."""
    physics = {p.hot.upper(), p.cold.upper()}
    built = _all_charts(four_stream, p)
    assert physics <= _colours(built["composite"].to_dict())
    for name in ("supertargeting", "electrification", "price_ratio", "retrofit", "tornado"):
        assert not (_colours(built[name].to_dict()) & physics), name
