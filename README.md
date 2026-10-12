# heatpump-pinch: pinch analysis and heat pump integration for industrial sites

MSc dissertation, Project 1: electrification of process heat with high-temperature heat pumps.

The toolkit works for any process described by a stream table: it computes energy
targets, composite curves and the Grand Composite Curve (GCC), sizes heat pumps from
the GCC at the sink levels you choose, and flags designs outside reported heat pump
technology ranges. Site-specific data live only in a **case file** and a **stream CSV**.

## Quick start

```bash
pip install pandas numpy matplotlib pytest CoolProp
python -m pytest                                  # 48 tests
python analyse.py --all                           # every case in cases/
python analyse.py cases/brewery_padulles2026.json # one case
```

Outputs go to `outputs/<case name>/`: `problem_table.csv`, `composite_curves.png`,
`gcc.png`, `gcc_heat_pumps.png`, `heat_pump_design.csv`, `summary.json`, `summary.md`.

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
| 3. ΔTmin / cost trade-off | Not started (needs film coefficients and exchanger costs) |
| 4. Heat pump placement | 4a done: Lorenz COP, placement rules, GCC sizing, screening, general design. 4b (working fluid, cycle COP with CoolProp) pending |
| 5. HEN retrofit | Not started |
| 6. Economics | Not started |

## Layout

```
analyse.py                   General entry point: one or more case files -> outputs/<case>/
cases/
  TEMPLATE.json              Documented template for a new site
  brewery_padulles2026.json  Main case (Padullés et al., 2026)
  fourstream_example.json    Four-stream chemical process (non-food demonstration)
data/
  brewery_streams.csv        Padullés et al. (2026), Table 2; 'Amb.' = 15 °C (inferred)
  fourstream_example.csv     Univ. Oklahoma ChE notes, Example 1.1
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
tests/                       48 tests (validation cases first, then general behaviour)

Paper-specific scripts (brewery):
validate_targets.py                 Steps 1-2 validation report
reproduce_padulles2026.py           Reproduces the paper's three configurations (Sec. 4.3)
verify_padulles2026_assumptions.py  Checks each modelling assumption against the paper
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
| Sink temperature, warning | > 120 °C | Arpagaus et al. (2018), Purdue Refrigeration Conf.: few commercial units above 120 °C |
| Sink temperature, outside range | > 200 °C | IEA HPT Annex 58 scope (100–200 °C) |
| Temperature lift | > 130 K | Arpagaus et al. (2018): commercial COP data up to 130 K lift |
| COP | < 1 | Direct electric heating would use less electricity |

## Validation

| Case | Quantity | Reference | Computed | Deviation |
|---|---|---|---|---|
| Four-stream example | Qh,min / Qc,min / pinch T* | 7.5 MW / 10.0 MW / 145 °C | 7.5 / 10.0 / 145 | 0 |
| Brewery | Qh,min | 10.0 kWh/hl | 10.04 | +0.4 % |
| Brewery | Qc,min | 3.2 kWh/hl | 3.44 | +7.6 % (known Table 2 rounding gap) |
| Brewery | Heat recovery | 11.4 kWh/hl | 11.36 | −0.4 % |
| Brewery + 2 K | Qh,min / Qc,min / recovery | 10.5 / 3.8 / 10.9 | 10.48 / 3.88 / 10.92 | ≤ 2.2 % |
| Brewery, config. 2 | Electricity | 3.6 kWh/hl | 3.55 | −1.5 % |
| Brewery, config. 3 (HTHP) | Electricity | 3.6 kWh/hl | 3.56 | −1.1 % |
| Brewery, config. 1 | Electricity vs Fig. 11 (digitised), 100–180 °C | curve | curve | −4.5 to +0.7 % |
