"""Sizing read from the GCC (``gcc_duty_limit``) against a brute-force oracle (audit, item 3).

The oracle is the definition itself, checked on the full Problem Table by bisection: the largest sink
duty that lowers Q̇h,min by the same amount, and the largest source duty that leaves Q̇h,min unchanged.
It lives only here, as an independent check; the tool reads the curve.
"""

from dataclasses import replace

import pytest

from pinch import load_streams, problem_table, with_extra_shift
from pinch.case import load_case
from pinch.heat_pump import HeatPump, _max_process_source, _source_stream, add_units, max_useful_sink_duty
from pinch.validation import ROOT


def _bisect(ok, hi: float) -> float:
    if ok(hi):
        return hi
    lo = 0.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def _oracle_sink(streams, unit) -> float:
    Qh = problem_table(streams).Qh_min
    tol = 1e-12 * max(1.0, Qh)
    return _bisect(lambda Q: Q == 0 or problem_table(add_units(streams, [unit.with_sink_duty(Q)], {})).Qh_min
                   <= Qh - Q + tol, Qh)


def _oracle_source(streams, unit, cap) -> float:
    Qh = problem_table(streams).Qh_min
    tol = 1e-12 * max(1.0, Qh)
    return _bisect(lambda Q: Q == 0 or problem_table(replace(streams, streams=streams.streams + (_source_stream(unit, Q),))
                                                     ).Qh_min <= Qh + tol, cap)


def _cases():
    out = []
    for name in ("brewery_padulles2026", "walmsley2024_milk_evaporator", "fourstream_example"):
        c = load_case(ROOT / "cases" / f"{name}.json")
        out.append((name, with_extra_shift(load_streams(c.stream_file), c.extra_shift_K)))
    return out


CASES = _cases()


@pytest.mark.parametrize("name, streams", CASES, ids=[c[0] for c in CASES])
def test_sink_duty_matches_definition(name, streams):
    t = problem_table(streams)
    top, bottom = float(t.T_star_C[0]), float(t.T_star_C[-1])
    for T_out in [bottom + f * (top + 10 - bottom) for f in (0.2, 0.4, 0.6, 0.8, 0.95, 1.0)]:
        for glide in (0.0, 0.3 * (T_out - bottom)):
            u = HeatPump("u", 1.0, T_out - glide, T_out, bottom - 5, bottom - 5, eta_lorenz=0.5)
            assert max_useful_sink_duty(streams, u) == pytest.approx(_oracle_sink(streams, u), rel=1e-9, abs=1e-9 * t.Qh_min)


@pytest.mark.parametrize("name, streams", CASES, ids=[c[0] for c in CASES])
def test_source_duty_matches_definition(name, streams):
    t = problem_table(streams)
    top, bottom = float(t.T_star_C[0]), float(t.T_star_C[-1])
    for T_in in [bottom - 2 + f * (top - bottom) for f in (0.0, 0.1, 0.3, 0.5, 0.8)]:
        for glide in (0.0, 0.2 * (top - bottom)):
            u = HeatPump("u", 1e6, 200.0 + top, 200.0 + top, T_in, T_in - glide, eta_lorenz=0.5)
            cap = 2 * t.Qc_min + 1.0
            expected = _oracle_source(streams, u, cap)
            got = _max_process_source(streams, u, cap)
            assert got == pytest.approx(expected, rel=1e-9, abs=1e-6 * max(cap, t.Qh_min))
