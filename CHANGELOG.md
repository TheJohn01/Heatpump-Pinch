# Changelog

Versions follow semantic versioning. Each release is a git tag `vX.Y.Z` whose version equals
`pinch.__version__`, `pyproject.toml` and `CITATION.cff` (checked by `tests/test_quality.py`). Numbers in
committed outputs change only where an entry says so.

## Unreleased

### Added
- Techno-economic assessment report of the current run, as PDF and Word: two buttons on the Dashboard
  (`pinch.report` builds the content once, `pinch.report_render` writes both files; written on click).
  Structure of ISO/TS 14076:2025 (goal and scope, technical, economic, environmental screening,
  sensitivity, interpretation, documentation), labelled "not critically reviewed" on every page. It includes
  every chart and diagram of the run (flowsheet and T* diagram rasterised with resvg, a self-contained wheel on every platform) plus a discounted
  cash-flow chart, a ±20 % NPV tornado and the RQ3 tornado. Tables and figures are numbered separately; table
  captions above, figure captions below; in Word the captions use the Caption style and SEQ fields.
- `Outputs.snapshot_pngs`: PNG copies of a run's figures that survive `write` (the zip download releases the
  figures, so the report could otherwise lose them).
- Dependencies: reportlab, python-docx, resvg-py (`requirements.txt`; extras `app` and `report`).
- Browser smoke test: both report downloads return a valid file (check 0b).

No committed output changes.

## 0.10.0 (2026-11-12)

### Added
- Sources for the limitations (design review groups B and C), each with a check or a sensitivity row:
  - Frost and defrost of the ambient-air source: sensitivity kind `frost` and rows −2.5 % (Danish Energy Agency,
    el & DH catalogue, ch. 40) and −13 % (NREL review, upper bound) on the ambient share of each unit's source.
  - Retrofit piping: `pinch.retrofit.piping_cost_EUR` (Lal et al. 2018, CET 70, Eq. 2), 50 m assumed in the base
    case and a 200 m row (sensitivity kind `piping`).
  - `scripts/checks/vendor_data_check.py`: Lorenz efficiency achieved by IEA HPT Annex 58 demonstration cases and
    supplier cost ranges (`data/sources/annex58_*.csv`). Finding: closed-cycle median η_L 0.37 < basis 0.50; new
    row "Lorenz efficiency 0.37" gives HP1 payback 6.78 y and RQ1 0 %.
  - `scripts/checks/benchmark_check.py`: the brewery stream table against the EU FDM BREF 2019 and the TNO process
    and waste heat dataset (`data/sources/brewery_benchmarks.csv`).
  - ERSE network access-tariff changes (`data/sources/erse_access_tariff_changes.csv`), `pinch.tariffs.
    access_tariff_change` and `with_network_change`, `tariff_check.py --erse`.
  - Grid factor row for a new 60 % CCGT (0.337 kg/kWh); the 55 % marginal plant and the 103 °C wort-boiling sink
    are now sourced (DEA; JRC best practice and FDM BREF); boil window 0.5–1.5 h from the FDM BREF.

- Flowsheet layouts for the other three cases (`data/milk_evaporator_flowsheet.json`,
  `spray_dryer_flowsheet.json`, `four_stream_process_flowsheet.json`), built from the stream names and roles
  in the source tables; step 1 no longer shows the T* diagram for them. Uploaded tables get a generic
  flowsheet (`pinch.process_diagram.generic_flowsheet`: one box per stream, no material connections).
- Flowsheet drawing: per-flow feed and product labels, products leaving to the right, a "+ process" stub
  for heat pump process sources when the layout has no source steps, duties with thousands separators
  instead of scientific notation (kW cases), and runs of stream identifiers collapsed (H2+H7–11).

### Fixed
- CI: `outputs-reproducible` failed on every figure after 0.9.0. GitHub's runner renders text with a
  different FreeType build, which moves plot areas beyond any useful pixel tolerance. `--check` now
  reports figure changes and fails only on CSV/JSON/Markdown/README changes (all data outputs reproduced
  on the runner); the tolerance still restores rasterisation-only differences locally.

### Changed
- Type checking covers the whole `pinch` package (101 errors fixed in 12 modules; `case.annual_converter`; one
  wrong annotation in `pinch.cycle`). `test_mypy_typed_modules` became `test_mypy_whole_package`.
- Heat-recovery retrofit N1 now includes piping: capex 56.0 → 76.1 k€, payback 1.11 → 1.51 y. RQ1-RQ3 unchanged
  (the heat pump increments share the N1 step).

## 0.9.0 (2026-11-12)

### Added
- `scripts/checks/design_consistency_check.py` → `outputs/brewery/design_consistency.csv/.md`: one table
  of every COP and CAPEX reported for the brewery heat pumps (basis, cycle model, idealised cycle in
  pinch.cycle and TESPy, paper's η_L, Andersen et al. 2024, reversible bound; case cost function and
  Kosmadakis component cost; case design against the paper's configuration 2) with verdicts V1-V5. Finding:
  the HTHP basis COP (η_L 0.50) is 7.6 % below our cascade-cycle model, i.e. conservative.
- Sensitivity row "Heat pump CAPEX −8 % (component cost, Kosmadakis 2020)" (HP1 payback 3.95 y; base 4.29 y).
- Process diagrams (`pinch/process_diagram.py`), each in four views (Process, Energy balance, With heat
  pumps, All at once). No computed result changes.
  - Workflow step 1 opens with a simplified flowsheet above the stream table: one box per process step,
    heat demand and release per step from the current stream table, the step 4 heat pumps with indicative
    sink and source connections. Layout file `data/brewery_flowsheet.json` (steps grouped from the
    stream table; wort kettle = preheating + boiling, condenser = boil-off condensation + condensate
    cooling).
  - T* stream diagram (streams on the shifted-temperature axis with pinch, energy targets and heat pumps)
    on the Dashboard, and in step 1 for cases without a layout file and for uploaded tables.
  - `tests/test_process_diagram.py`: duties against the brewery table, heat pump COP and work against
    `outputs/brewery/heat_pump_design.csv`, layout validation, well-formed SVG in every view and theme.
- Third-party integrations, each credited in `docs/THIRD_PARTY.md` (register items 66-71). No existing
  result changes; new outputs only.
  - `pinch/exchanger_rating.py` (ht, fluids): shells in series from the LMTD correction factor, rated area
    and cost, tube-side h and ΔP. `scripts/benchmarks/benchmark_exchanger_rating.py` against the detailed
    designs of Polley and Panjeh Shahi (1991): shells 11 of 11, h_io ≤ 0.3 %, ΔP_t ≤ 3.7 %, area from their U
    and our F ≤ 1.2 % (`data/benchmarks/polley1991_exchanger_designs.json`, transcribed from Tables 4-5).
  - `pinch/tariffs.py`: effective electricity price over the operating hours (fixed window or cheapest
    hours per day), network adders and demand charge; `scripts/data/fetch_entsoe_prices.py` (entsoe-py,
    needs an ENTSO-E API key) and `scripts/checks/tariff_check.py` against the RQ3 break-even ratios.
  - `pinch/tespy_heat_pump.py` (TESPy): rebuild of single-stage cycles, design COP equal to `pinch.cycle`
    (brewery warm-water unit 3.3546 both), part load 100-60 % with TESPy's default lines, component cost
    after Kosmadakis et al. (2020) as implemented in heatpumps (0.98 M€ against 1.07 M€ from Padullés'
    cost function). `scripts/analysis/heat_pump_partload.py` writes `outputs/brewery/heat_pump_partload.csv`
    and `heat_pump_cost_check.csv`.
  - `scripts/benchmarks/benchmark_min_matches.py`: the minimum-units MILP on 20 Furman and Sahinidis
    instances digitised by Letsios et al. (2018) (Apache 2.0, `data/benchmarks/letsios2018/`): 20 of 20
    equal to the published minimum.
- Dependencies pinned: ht 1.2.0, fluids 1.3.1, tespy 0.12.0.post1, entsoe-py 0.8.1, tabulate 0.10.0;
  optional extras `rating`, `tespy`, `prices` in `pyproject.toml`.

### Changed
- `heat_pump_design.csv`: the Andersen et al. (2024) value moves to `eta_lorenz_Andersen2024_extrapolated`
  when the unit is outside the fitted range (every committed case); `eta_lorenz_Andersen2024_check` is
  then empty. No other number changes.
- `regenerate_outputs.py` compares PNG figures with a rasterisation tolerance instead of skipping them,
  and restores figures that differ only by font rasterisation; Pillow pinned in `requirements.txt`.
- Wording only: the project no longer refers to an academic programme or institution; review notes
  are called "design review" (same item codes A1-C4). Committed outputs change only in these text
  fields and in the input hashes of `summary.json`; no number changes.
- README rewritten as a structured technical document: abstract with the RQ answers, introduction
  (motivation, objectives, scope, contributions), architecture diagrams, one section per workflow step
  with its equations, results for the brewery with sensitivities, validation and limitations, software
  and tests, conclusions and future work, credits, numbered references and nomenclature. The economic
  defaults block, the module list and the data-sources table keep their tested formats.
- Repository layout: the 18 scripts that sat in the root move into folders; only `app.py` (Streamlit Cloud
  entry point) and `regenerate_outputs.py` stay in the root. Scripts now run from the root as modules.
  No output changes (all committed outputs regenerate byte for byte).

  | Before | After |
  |---|---|
  | `analyse.py`, `screen_cycles.py`, `consolidate_rq.py` | `scripts/analysis/` |
  | `batch_check.py`, `mvr_check.py`, `investment_check.py`, `plant_data_check.py` | `scripts/checks/` |
  | `validate_targets.py`, `reproduce_*.py`, `verify_*.py` | `scripts/validation/` |
  | `benchmark_openpinch.py`, `benchmark_hen.py` | `scripts/benchmarks/` |
  | `app_pages.py` | `frontend/pages.py` |
  | `ui_smoke.py` | `tests/ui_smoke.py` |
  | `ASSUMPTIONS.md`, `QUALITY.md` | `docs/` |

  Commands: `python analyse.py --all` becomes `python -m scripts.analysis.analyse --all` (same pattern for
  every script). The `heatpump-pinch` console command points to `scripts.analysis.analyse:main`.

### Fixed
- Process diagrams did not show in the browser: `st.html` sanitises `<svg>` away. They are now
  drawn with `st.markdown` (markers and tooltips kept); `tests/ui_smoke.py` checks in Chromium that
  both diagrams are present, and its case selector uses the plant names shown since 0.8.0.
- CI: the `outputs-reproducible` job failed on every push since 11 November 2026 because GitHub moved the
  `ubuntu-latest` runner from Ubuntu 24.04 to 26.04. With identical package versions, the newer C library most likely
  changes the last digits of some CoolProp results, and `outputs/brewery/cycle_screening.csv` (written at
  4 decimals) no longer matched byte for byte. The committed outputs are unchanged; CI is pinned to
  `ubuntu-24.04`, the environment they were produced in. On failure the job now prints the diff of the
  stale outputs. `actions/checkout` and `actions/setup-python` move to v7 (Node 24; Node 20 is deprecated).

Front-end theme. No number in any output changes; the committed figures are untouched.

### Added
- Light and dark theme (`.streamlit/config.toml`, `pinch/theme.py`): a technical-document style with
  IBM Plex Sans and Mono served by the app (`static/fonts/`, SIL Open Font License 1.1). The viewer picks
  the mode in Settings > Theme; charts follow it (`st.context.theme`).
- `tests/test_theme.py`: config keys are valid Streamlit options and match `pinch/theme.py`; text contrast
  at least 4.5:1 and chart colours at least 3:1 against the background in both modes (WCAG 2.2, criteria
  1.4.3 and 1.4.11); font files present and licensed; every chart uses only its mode's palette.

### Changed
- Colour meaning: red only for hot (hot streams, Q̇h, heat pump sinks), blue only for cold. Payback, NPV,
  retrofit and tornado charts used red and blue for economic quantities; they now use teal and amber.
  The supertargeting chart's cost laws no longer start with red. Q̇h,min / Q̇c,min and hot/cold stream
  totals are labelled in their colour.
- `pinch.charts` functions take a `palette` argument (default light) and are now type-checked.

## 0.8.0 (2026-11-11)

Industrial-use review of 0.7.0 (commit bdc970a): eight gap groups addressed. No RQ1-RQ3 value of the brewery base case changes.

### Added
- `pinch/investment.py`, `investment_check.py`: IRR, discounted payback, tax and depreciation, AACE 18R-97
  accuracy ranges, Portuguese grant scenarios, Monte Carlo (Towler and Sinnott 2013, Ch. 9).
- `pinch/reconciliation.py`, `pinch/uncertainty.py`, `pinch/restricted_matches.py`, `plant_data_check.py`:
  data reconciliation (Yong et al. 2016), stream-data uncertainty with SRC ranking (Bergamini et al. 2019,
  2021), targets with forbidden or limited matches. Segmented (variable-CP) streams and `.xlsx` input.
- `pinch/time_slices.py`, `reproduce_stampfli2019.py`: Time Slice and Time Average targets, storage sizing,
  heat pump with storage loops; validated on Stampfli et al. (2019).
- `pinch/utilities.py`: targets for several utility levels against the GCC.
- `pinch/refrigerants.py`: GWP, safety group and EU F-gas prohibitions (Regulation (EU) 2024/573, as
  restated by the European Commission) for every screened fluid; new columns in `cycle_screening.csv`.
- Heat pump temperature contribution `dT_cont_K` (intermediate loops; Stampfli et al. 2019, Eq. 1) per
  sink level or case-wide; brewery sensitivity row "+2 K each side".
- `pinch/provenance.py`: tool version and input SHA-256 in every `summary.json`; volatile run metadata
  (commit, time, environment) in git-ignored `run_metadata.json`. `analyse.py --verbose` logging.
- `pinch/hen_design.py`: network synthesis by minimum units (transshipment MILP), series placement of the
  matches, exchanger sizing with film coefficients and fouling, per-unit cost law. `pinch/pressure_drop.py`:
  film coefficients from allowable pressure drop (Polley et al. 1990, 1991). `benchmark_hen.py`: the
  four-stream problem of Sagli et al. and the Aromatics Plant as published by Polley and Panjeh Shahi (1991).
- `benchmark_openpinch.py`: targets against OpenPinch 0.8.3 (Walmsley 2026) on 11 cases, both directions;
  results stored in `data/benchmarks/` (OpenPinch needs Python >= 3.14). `AreaTarget.contributions`.
- Quality gate: ruff rule set and mypy configuration in `pyproject.toml`; `tests/test_quality.py`;
  `QUALITY.md`; release workflow `.github/workflows/release.yml`.

### Changed
- An unknown key in a case's `economics` block is an error (was silently ignored).
- Stream tables reject non-finite values, temperatures below absolute zero and T_in = T_out.
- Payback-threshold provenance cites the primary source (Cooremans 2012, p. 511).
- Outputs: `summary.json` gains a `run` block; `cycle_screening.*` gains GWP100, safety group and F-gas
  columns; `rq_consolidated.*` gains the "+2 K" row; new files for the scripts above.

## 0.7.0 (2026-10-17)

Redundancy audit and RQ1-RQ3 for every case (commits up to bdc970a). Earlier history is in the git log.
