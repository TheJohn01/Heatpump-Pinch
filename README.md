# Heat pump integration: pinch analysis toolkit

MSc dissertation, Project 1: electrification of process heat with high-temperature heat pumps.

## Status

| Workflow step | Status |
|---|---|
| 1. Stream data, checks, energy-balance closure | Done, tested |
| 2. Problem table, composite curves, GCC | Done, validated (Kemp; Padullés et al. 2026) |
| 3. ΔTmin / cost trade-off | Not started |
| 4. Heat pump placement | Not started |
| 5. HEN retrofit | Not started |
| 6. Economics | Not started |

## Layout

```
data/
  brewery_streams.csv        Padullés et al. (2026), Table 2; ambient = 15 °C
  kemp_4stream.csv           Kemp (2007), Ch. 2 four-stream example
  reference_targets.json     Published/textbook targets used by tests and report
pinch/
  streams.py                 Load, validate, shift, energy balance
  problem_table.py           Problem Table Algorithm (cascade, targets, pinch)
  curves.py                  Composite curves and GCC data
  plotting.py                Figures saved to file
  validation.py              Reference vs computed comparison
tests/test_problem_table.py  Kemp first, then brewery published targets
run_targets.py               Runs all cases; writes outputs/
```

## Usage

```bash
pip install pandas numpy matplotlib pytest
python -m pytest           # 14 tests
python run_targets.py      # tables, figures and outputs/validation_report.csv
```

## Conventions

* Each stream has its own temperature shift (`dT_shift_K`): T* = T − shift for hot streams, T* = T + shift for cold streams. No global ΔTmin unless a case asks for one.
* Heat loads are in the unit named by the CSV column (`Q_kWh_per_hl` → kWh/hl; `CP_kW_per_K` → kW).
* Composite curves are plotted in shifted temperature so that they touch at the pinch.

## Validation (outputs/validation_report.csv)

| Case | Quantity | Reference | Computed | Deviation |
|---|---|---|---|---|
| Kemp | Qh,min / Qc,min / pinch T* | 750 kW / 1000 kW / 145 °C | 750 / 1000 / 145 | 0 |
| Brewery | Qh,min | 10.0 kWh/hl | 10.04 | +0.4 % |
| Brewery | Qc,min | 3.2 kWh/hl | 3.44 | +7.6 % (known Table 2 rounding gap) |
| Brewery | T* range | 103 to −1 °C | 103 to −1 °C | 0 |
| Brewery | Heat recovery | 11.4 kWh/hl | 11.36 | −0.4 % |
| Brewery + 2 K | Qh,min / Qc,min / recovery | 10.5 / 3.8 / 10.9 | 10.48 / 3.88 / 10.92 | ≤ 2.2 % |

The Qc,min gap is not a code error: Table 2 sums to 21.4 kWh/hl cold and 14.8 kWh/hl hot, so Qc,min − Qh,min must be −6.6 kWh/hl, while the paper's rounded targets give −6.8.
