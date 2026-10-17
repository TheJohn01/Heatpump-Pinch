"""Verdicts of the paper-verification scripts (redundancy audit, item 6).

The scripts compute the comparisons once (``checks()``) and only write the tables; these tests pin
every verdict, so a change in the code that alters a conclusion stated in the dissertation fails here.
"""



def _verdicts(module) -> dict[tuple[str, str], str]:
    df = module.checks()
    return {(r["check"], r["quantity"]): r["verdict"] for _, r in df.iterrows()}


def test_walmsley2024_verdicts():
    import verify_walmsley2024 as v
    got = _verdicts(v)
    expected = {
        ("W1", "Qh_min / Qc_min [MW]"): "reproduced",
        ("W2", "pinch boundaries T* [°C], Table 2 shifts"): "lower bound differs",
        ("W2", "pinch boundaries T* [°C], chiller dT_cont = 2.5 K"): "matches text; targets unchanged",
        ("W3", "simple-design COP"): "reproduced",
        ("W5", "Qc - Qh from Table 1 (first law) [MW]"): "INCONSISTENT: published targets cannot come from Table 1",
        ("W5", "Qh_min / Qc_min from Table 1 [MW]"): "differs",
    }
    for key, verdict in expected.items():
        assert got[key] == verdict, key
    assert got[("W6", "Qh_min / Qc_min, inferred variant [MW]")].startswith("matches to 3 s.f.")
    assert got[("W4", "simple design W = Qh_min / COP [MW]")].startswith("-16 %")


def test_padulles2026_assumption_verdicts():
    import verify_padulles2026_assumptions as v
    got = _verdicts(v)
    expected = {
        ("A1", "CO2 HP COP, source -1 °C (our assumption)"): "matches",
        ("A1", "CO2 HP COP, temperatures drawn in Fig. 12"): "does not match: Fig. 12 is schematic",
        ("A3", "HTHP COP / W at sink 103.0 °C"): "matches",
        ("A4", "Fig. 11 with HR: deviation range over 100-180 °C [%]"): "reproduced",
        ("A4", "Fig. 11 no HR: deviation range over 100-180 °C [%]"): "not reproduced",
        ("A5", "Re-absorbed surplus vs unused sink heat [kWh/hl]"): "equal",
        ("A5", "Cold utility replaced [kWh/hl]"): "equal",
    }
    for key, verdict in expected.items():
        assert got[key] == verdict, key
    # A2: the isothermal width does not change the design up to 1 K, and does at 2 K
    widths = {q: verdict for (c, q), verdict in got.items() if c == "A2"}
    assert len({v for q, v in widths.items() if "2.0 K" not in q}) == 1
    assert widths["min-energy design W_total, width 2.0 K [kWh/hl]"] != widths["min-energy design W_total, width 1.0 K [kWh/hl]"]
