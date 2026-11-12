"""Investment-grade view of the research-question results, for any case with an annual basis.

Usage:
    python -m scripts.checks.investment_check cases/brewery.json

For the heat-recovery step, each heat pump increment (HP1 over the heat-recovery step, HP2 over HP1, ...)
and the full design against today's site (``pinch.research_questions``), this script adds what
``pinch.economics`` does not report (``pinch.investment``):

* internal rate of return and discounted payback (Towler and Sinnott 2013, Sec. 9.6);
* the NPV at the low and high ends of the capital estimate's accuracy range. The cost functions are
  parametric, so the estimate is taken as AACE Class 5 (RP 18R-97, Table 1: -20 to -50 % low, +30 to
  +100 % high). The classification is ours; both ends of the band are reported;
* grant scenarios under Portaria n.º 325-A/2021, Annex I (energy efficiency, 30 % of eligible cost;
  +15 points in Norte, Centro, Alentejo and the islands). The firm is taken as large (no size bonus) and
  the whole investment as eligible: an upper bound, since eligible cost is defined against a
  counterfactual investment. Scenarios, not a statement that the site qualifies;
* a Monte Carlo simulation (Sec. 9.8.3; 5000 samples, seed 0) with triangular distributions:
  investment over the Class 5 widest band; gas price over -50 % to +100 % (Table 9.4, fuel cost);
  electricity-to-gas ratio over the lowest and highest half-yearly values of the Eurostat series for the
  case's country data file (bands ID and I3), most likely = the case's ratio. Electricity = ratio x gas,
  because the two prices are correlated.

No tax or depreciation is applied: Portuguese rules for this equipment were not found in the sources read
(``pinch.investment.cash_flows`` accepts them as inputs).

Writes outputs/<case>/investment_check.csv and .md.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from pinch import investment as inv
from pinch import load_streams, with_extra_shift
from pinch import research_questions as rq
from pinch.case import load_case, to_MWh_per_year
from pinch.economic_analysis import _params_and_converter
from pinch.economics import evaluate

ROOT = Path(__file__).resolve().parents[2]   # repository root
ESTIMATE_CLASS = 5
GRANTS = (("no grant", 0.0),
          ("grant 30 % (energy efficiency, large firm)", inv.prr_aid_intensity("energy_efficiency", "large", "none")),
          ("grant 45 % (same, 'a' region)", inv.prr_aid_intensity("energy_efficiency", "large", "a")))
N_SAMPLES, SEED = 5000, 0
PRICE_FILE = ROOT / "data" / "sources" / "eurostat_portugal_prices.csv"
EL_BAND, GAS_BAND = "band ID", "band I3"
TAXES = "Excluding VAT and other recoverable taxes and levies"


def eurostat_ratio_range(path: Path = PRICE_FILE) -> tuple[float, float]:
    """Lowest and highest half-yearly electricity-to-gas price ratio in the Eurostat series (EUR/kWh)."""
    d = pd.read_csv(path)
    d = d[(d["taxes"] == TAXES) & (d["currency"] == "Euro") & (d["unit"] == "Kilowatt-hour")]
    el = d[(d["carrier"] == "electricity") & d["band"].str.endswith(EL_BAND)].set_index("period")["value"]
    gas = d[(d["carrier"] == "gas") & d["band"].str.endswith(GAS_BAND)].set_index("period")["value"]
    ratio = (el / gas).dropna()
    if ratio.empty:
        raise ValueError(f"{path.name}: no periods with both an electricity and a gas price")
    return float(ratio.min()), float(ratio.max())


def check(case_file: Path) -> pd.DataFrame:
    case = load_case(case_file)
    streams = with_extra_shift(load_streams(case.stream_file), case.extra_shift_K)
    params = _params_and_converter(case, streams.energy_unit)[1]
    to_MWh = lambda x: to_MWh_per_year(x, streams.energy_unit, case.basis)  # noqa: E731
    site = rq.build_site(case, streams, params)
    options = [site.reference] + [rq._option(site, site.units[:k], params, to_MWh)
                                  for k in range(1, len(site.units) + 1)]
    pairs = []
    if site.has_hr_step:
        pairs.append(("Heat-recovery step over today's site", site.reference, site.baseline))
    for k, u in enumerate(site.units, start=1):
        pairs.append((f"HP{k} ({u.name}) over the previous step", options[k], options[k - 1]))
    if site.units:
        pairs.append(("Full design over today's site", options[-1], site.baseline))

    lo, hi = inv.capex_factors(ESTIMATE_CLASS, "widest")
    lo_n, hi_n = inv.capex_factors(ESTIMATE_CLASS, "narrowest")
    r_lo, r_hi = eurostat_ratio_range()
    r_now = params.price_ratio
    ratio = inv.Range(min(r_lo, r_now), r_now, max(r_hi, r_now))
    fuel = inv.TOWLER_TABLE_9_4["fuel_cost"]
    p_gas = params.gas_price_EUR_per_kWh
    gas = inv.Range(fuel[0] * p_gas, p_gas, fuel[1] * p_gas)
    N, i = params.horizon_years, params.discount_rate

    rows = []
    for label, option, over in pairs:
        ev = evaluate(option, over, params)
        if ev.capex_EUR <= 0:
            continue
        for g_label, g in GRANTS:
            grant = inv.grant_EUR(ev.capex_EUR, g)
            flows = inv.cash_flows(ev.capex_EUR, ev.savings_EUR, N, grant_EUR=grant)
            mc = inv.summarise(inv.monte_carlo(option, over, params, capex_factor=inv.Range(lo, 1.0, hi),
                                               gas_price_EUR_per_kWh=gas, price_ratio=ratio,
                                               grant_fraction=grant / ev.capex_EUR, n=N_SAMPLES, seed=SEED),
                               params.payback_threshold_years)
            net = ev.capex_EUR - grant
            ann = ev.savings_EUR * params.annuity_factor
            rows.append({
                "increment": label, "scenario": g_label,
                "investment_MEUR": round(ev.capex_EUR / 1e6, 3), "grant_MEUR": round(grant / 1e6, 3),
                "savings_kEUR_per_y": round(ev.savings_EUR / 1e3, 1),
                "payback_y": round(net / ev.savings_EUR, 2) if ev.savings_EUR > 0 else math.inf,
                "discounted_payback_y": round(inv.discounted_payback_years(flows, i), 2),
                "IRR": round(inv.irr(flows), 4),
                "NPV_MEUR": round(inv.npv(flows, i) / 1e6, 3),
                "NPV_capex_low_narrow_MEUR": round((-net * lo_n + ann) / 1e6, 3),
                "NPV_capex_high_narrow_MEUR": round((-net * hi_n + ann) / 1e6, 3),
                "NPV_capex_low_wide_MEUR": round((-net * lo + ann) / 1e6, 3),
                "NPV_capex_high_wide_MEUR": round((-net * hi + ann) / 1e6, 3),
                "MC_NPV_p5_MEUR": round(mc["npv_p5_EUR"] / 1e6, 3),
                "MC_NPV_p50_MEUR": round(mc["npv_p50_EUR"] / 1e6, 3),
                "MC_NPV_p95_MEUR": round(mc["npv_p95_EUR"] / 1e6, 3),
                "MC_prob_NPV_positive": round(mc["prob_npv_positive"], 3),
                "MC_prob_payback_within_threshold": round(mc["prob_payback_within_threshold"], 3),
            })
    df = pd.DataFrame(rows)
    df.attrs.update(ratio=ratio, gas=gas, capex=(lo, hi), horizon=N, rate=i, threshold=params.payback_threshold_years)
    return df


def markdown(df: pd.DataFrame) -> str:
    a = df.attrs
    num = lambda x, f: "never" if not math.isfinite(x) else format(x, f)  # noqa: E731
    lines = [f"Horizon {a['horizon']} y, discount rate {100 * a['rate']:g} %, payback threshold {a['threshold']:g} y. "
             f"Monte Carlo ({N_SAMPLES} samples, seed {SEED}), triangular: investment x {a['capex'][0]:g}-{a['capex'][1]:g} "
             f"(AACE Class {ESTIMATE_CLASS}, widest band); gas {a['gas'].low:.4f}-{a['gas'].high:.4f} EUR/kWh "
             f"(most likely {a['gas'].most_likely:.4f}); electricity/gas ratio {a['ratio'].low:.2f}-{a['ratio'].high:.2f} "
             f"(most likely {a['ratio'].most_likely:.2f}). Grants assume a large firm and the whole investment "
             "eligible (upper bound).", "",
             "| Increment | Scenario | Investment [M€] | Payback [y] | Discounted payback [y] | IRR | NPV [M€] | "
             "NPV, Class 5 investment range [M€] | Monte Carlo NPV P5 / P50 / P95 [M€] | P(NPV > 0) | P(payback ≤ threshold) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        irr = "n/a" if not math.isfinite(r["IRR"]) else f"{100 * r['IRR']:.1f} %"
        lines.append(
            f"| {r['increment']} | {r['scenario']} | {r['investment_MEUR']:.2f} | {num(r['payback_y'], '.1f')} | "
            f"{num(r['discounted_payback_y'], '.1f')} | {irr} | {r['NPV_MEUR']:+.2f} | "
            f"{r['NPV_capex_high_wide_MEUR']:+.2f} to {r['NPV_capex_low_wide_MEUR']:+.2f} | "
            f"{r['MC_NPV_p5_MEUR']:+.2f} / {r['MC_NPV_p50_MEUR']:+.2f} / {r['MC_NPV_p95_MEUR']:+.2f} | "
            f"{100 * r['MC_prob_NPV_positive']:.0f} % | {100 * r['MC_prob_payback_within_threshold']:.0f} % |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()
    case = load_case(args.case_file)
    df = check(args.case_file)
    out = ROOT / "outputs" / case.name
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "investment_check.csv", index=False)
    text = markdown(df)
    (out / "investment_check.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
