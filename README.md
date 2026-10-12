# heatpump-pinch: pinch analysis and heat pump integration for industrial sites

MSc dissertation, Project 1: electrification of process heat with high-temperature heat pumps.

The toolkit works for any process described by a stream table: it computes energy
targets, composite curves and the Grand Composite Curve (GCC), sizes heat pumps from
the GCC at the sink levels you choose, and flags designs outside reported heat pump
technology ranges. Site-specific data live only in a **case file** and a **stream CSV**.

## Quick start

```bash
pip install pandas numpy matplotlib pytest CoolProp
python -m pytest                                  # 75 tests
python analyse.py --all                           # every case in cases/
python analyse.py cases/brewery_padulles2026.json # one case
```

Outputs go to `outputs/<case name>/`: `problem_table.csv`, `composite_curves.png`,
`gcc.png`, `gcc_heat_pumps.png`, `heat_pump_design.csv`, `summary.json`, `summary.md`, and, when the
case has an annual basis and an `economics` block, `economics.json`, `electrification_curve.*`
and `price_ratio_sweep.*`.

## Analysing a new site

1. Write the stream table as CSV: `stream, type, T_in_C, T_out_C, dT_shift_K` and one of
   `Q_<unit>` (e.g. `Q_kW`, `Q_kWh_per_t`) or `CP_<unit>` (e.g. `CP_kW_per_K`).
   Latent loads: use a 1 K temperature interval.
2. Copy `cases/TEMPLATE.json`, point it to the CSV, and set the heat pump sink levels,
   source temperature, Lorenz efficiency and (optionally) the annual basis.
3. Fill in `provenance`: for every value, say whether it is published or assumed, and
   where it comes from.
4. Run `python analyse.py cases/<your file>.json`.

## Status

| Workflow step | Status |
|---|---|
| 1. Stream data, checks, energy-balance closure | Done, tested |
| 2. Problem table, composite curves, GCC | Done, validated (four-stream example; Padullés et al. 2026) |
| 3. ΔTmin / cost trade-off | Done: Bath area target, units target, supertargeting; validated on the OU area example (published error found and corrected). Brewery RQ2 as a sweep of area cost (no sourced cost law yet) |
| 4. Heat pump placement | 4a done: Lorenz COP, placement rules, GCC sizing, screening, general design. 4b (working fluid, cycle COP with CoolProp) pending |
| 5. HEN retrofit | Not started |
| 6. Economics | Done: CAPEX (Padullés Table 3), OPEX, payback, NPV, CO2, primary energy; RQ1 electrification curve; RQ3 break-even ratio; paper Sec. 5.2 statements reproduced |

## Layout

```
analyse.py                   General entry point: one or more case files -> outputs/<case>/
cases/
  TEMPLATE.json              Documented template for a new site
  brewery_padulles2026.json  Main case (Padullés et al., 2026)
  fourstream_example.json    Four-stream chemical process (non-food demonstration)
  walmsley2024_milk_evaporator.json  Dairy: MVR milk evaporator, kW (Walmsley et al., 2024)
  walmsley2024_spray_dryer.json      Dairy: milk powder spray dryer, kW (Table 1 as published; see warning)
data/
  brewery_streams.csv        Padullés et al. (2026), Table 2; 'Amb.' = 15 °C (inferred)
  fourstream_example.csv     Univ. Oklahoma ChE notes, Example 1.1
  fourstream_balanced_ou.csv Same example with the utilities of the OU area-targeting notes
  northwestern_4stream.csv   Northwestern Univ. design wiki example (second algorithm check)
  walmsley2024_*.csv         Walmsley et al. (2024), Tables 1 and 2
  reference_targets.json     Published/textbook targets used by the validation tests
  brewery_configurations.json  Paper's three configurations; values tagged published/figure/assumed
pinch/
  streams.py                 Load, validate, shift, energy balance
  problem_table.py           Problem Table Algorithm (cascade, targets, pinch)
  curves.py                  Composite curves and GCC data
  heat_pump.py               Lorenz COP, heat pump units, integration, GCC sizing
  design.py                  Automatic multi-level design and plausibility screening
  case.py                    Case files and annual (MWh/year) conversion
  plotting.py                Figures saved to file
  validation.py              Reference vs computed comparison
  economics.py               Cost functions, evaluation, break-even ratio (defaults with sources)
  economic_analysis.py       Per-case economics: RQ1 electrification curve, RQ3 break-even, sensitivities
  area.py                    Area target (Bath formula), units target, ΔTmin supertargeting
  area_analysis.py           Per-case supertargeting (RQ2) from the case's area_targeting block
tests/                       75 tests (validation cases first, then general behaviour)

Paper-specific scripts (brewery):
validate_targets.py                 Steps 1-2 validation report
reproduce_padulles2026.py           Reproduces the paper's three configurations (Sec. 4.3)
reproduce_padulles2026_economics.py Reproduces the paper's economic statements (Sec. 5.2) and option maps
verify_padulles2026_assumptions.py  Checks each modelling assumption against the paper

Paper-specific script (dairy):
verify_walmsley2024.py              Targets, COP, inconsistencies and inferred variant (Walmsley et al., 2024)
```

## Conventions

* Each stream has its own temperature shift (`dT_shift_K`): T* = T − shift (hot), T* = T + shift (cold).
* Heat pump sink and source temperatures are compared directly with T* (utility shift 0),
  as in Padullés et al. (2026, Sec. 4.1). Isothermal sinks and sources are modelled over 1 K;
  results are unchanged for widths ≤ 1 K (tested).
* COP: Lorenz-efficiency model, COP = η_L · T̄_sink / (T̄_sink − T̄_source), with entropic mean
  temperatures; η_L ≤ 1 enforced (second law).
* Annual figures are reported only when the case file gives an explicit production or
  operating-hours basis.

## Plausibility screening (defaults, overridable per case)

| Check | Threshold | Source |
|---|---|---|
| Sink temperature, warning | > 160 °C | IEA HPT Annex 58 Task 1 report (Sept. 2023): commercial availability projected up to 160 °C by 2025–26 |
| Sink temperature, outside range | > 200 °C | Annex 58 scope (100–200 °C); vendor claims up to 200 °C (e.g. ENERIN, 2024; not peer-reviewed) |
| Temperature lift | > 130 K | Arpagaus et al. (2018): commercial COP data up to 130 K lift (dated; no newer verified source) |
| COP | < 1 | Direct electric heating would use less electricity |

## Validation

| Case | Quantity | Reference | Computed | Deviation |
|---|---|---|---|---|
| Four-stream example | Qh,min / Qc,min / pinch T* | 7.5 MW / 10.0 MW / 145 °C | 7.5 / 10.0 / 145 | 0 |
| Second four-stream example (Northwestern) | Qh,min / Qc,min / pinch T* | 2900 kW / 600 kW / 90 °C | 2900 / 600 / 90 | 0 |
| Milk evaporator (Walmsley 2024) | Qh,min / Qc,min | 3.54 / 0.46 MW | 3.542 / 0.456 | within rounding |
| Milk evaporator | Simple-design COP (15 → 105 °C, 50 % Carnot) | 2.1 | 2.101 | +0.05 % |
| Brewery | Qh,min | 10.0 kWh/hl | 10.04 | +0.4 % |
| Brewery | Qc,min | 3.2 kWh/hl | 3.44 | +7.6 % (known Table 2 rounding gap) |
| Brewery | Heat recovery | 11.4 kWh/hl | 11.36 | −0.4 % |
| Brewery + 2 K | Qh,min / Qc,min / recovery | 10.5 / 3.8 / 10.9 | 10.48 / 3.88 / 10.92 | ≤ 2.2 % |
| Brewery, config. 2 | Electricity | 3.6 kWh/hl | 3.55 | −1.5 % |
| Brewery, config. 3 (HTHP) | Electricity | 3.6 kWh/hl | 3.56 | −1.1 % |
| Brewery, config. 1 | Electricity vs Fig. 11 (digitised), 100–180 °C | curve | curve | −4.5 to +0.7 % |

### Known inconsistencies in the source papers (reported, not corrected)

* Brewery (Padullés et al., 2026): Q̇c,min rounding gap (Table 2); MVR COP 15 vs stated η 0.55; config. 3 EB total 4.6 vs Fig. 17 sum 4.4; Fig. 11 'EB + Ref. with HR' 11.0 < 11.3 kWh/hl; Fig. 4 GCC about 0.4 kWh/hl below Table 2 at both ends (consistent with an ambient of about 11 °C, while Sec. 4.3.1 states 15 °C). Targets change by about 0.1 kWh/hl per K of ambient.
* Spray dryer (Walmsley et al., 2024): published targets 4.98 / 3.99 MW violate the first law for Table 1 (net surplus +0.84 MW vs −0.99 MW). They are reproduced (4.978 / 3.986 MW) if Exhaust 2 ends at 23 °C and the fluidised bed starts at 25 °C, values inferred from Fig. 5, not published.
* Milk evaporator (Walmsley et al., 2024): the text's pinch range (5.5–10.5 °C) needs a 2.5 K contribution for chiller water; Table 2 gives 0.5 K. Targets are unaffected.

### Economic defaults

Every default in `pinch/economics.py` (`DEFAULTS`) carries its source. Boiler efficiency
defaults to 0.817 (US DOE Steam Tip Sheet #15); 0.90 and the bound 1.0 are always reported as
sensitivities. CO2 price defaults to 0 (the site may be outside the EU ETS); a sensitivity price
can be set per case.

### Area-targeting validation

The University of Oklahoma "Units and Area Targeting" notes give a total area of 2716.3 m² for the
four-stream example with utilities (U = 0.001 MW/m²K). Intervals I–V are reproduced exactly. Interval
VI's printed ΔT_LM (81.9 K) uses the cold temperatures of interval V; with its own temperatures it is
56.6 K, and the corrected total (2757.3 m²) equals our composite-curve area (2757.0 m²).
