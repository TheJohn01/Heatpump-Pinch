# Changelog

Versions follow semantic versioning. Each release is a git tag `vX.Y.Z` whose version equals
`pinch.__version__`, `pyproject.toml` and `CITATION.cff` (checked by `tests/test_quality.py`). Numbers in
committed outputs change only where an entry says so.

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

Redundancy audit and RQ1-RQ3 for every case (commits up to bdc970a). See `claude/sources_case_studies.md`
in the dissertation project for the history before this file existed.
