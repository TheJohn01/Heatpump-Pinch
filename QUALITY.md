# Software quality: what is enforced, what is not yet

Practices follow Wilson et al. (2017), "Good enough practices in scientific computing", PLOS Comput. Biol.
13, e1005510; Wilson et al. (2014), "Best practices for scientific computing", PLoS Biol. 12, e1001745;
and the FAIR principles for research software (Barker et al. 2022, Sci. Data 9, 622).

## Enforced on every push (GitHub Actions, `tests.yml`)

| Check | How | Fails when |
|---|---|---|
| Known-answer tests | `pytest` (all of `tests/`) | any published or hand-calculated value is not reproduced |
| Reproducible outputs | `regenerate_outputs.py --check` | a committed CSV/JSON/MD output no longer follows from code and inputs |
| Lint | `tests/test_quality.py::test_ruff_clean`, rule set in `pyproject.toml` | any finding in the repository |
| Types | `tests/test_quality.py::test_mypy_typed_modules` | a type error in a module of `TYPED_MODULES` |
| One version | `tests/test_quality.py::test_one_version_everywhere` | `pinch.__version__`, `pyproject.toml`, `CITATION.cff` or `CHANGELOG.md` disagree |
| Provenance | `tests/test_quality.py` | `summary.json` hashes do not match the input files |
| Independent tool | `tests/test_hen_design.py` (`benchmark_openpinch.py`) | a target differs from OpenPinch 0.8.3 by more than 1e-6 (11 cases) |

Tool versions are pinned in `requirements.txt` and `requirements-dev.txt`.

## Recorded debt

- **Types.** 13 modules are outside `TYPED_MODULES`, with 104 mypy errors at 0.8.0: `area_analysis`,
  `charts`, `cycle`, `cycle_analysis`, `design`, `economic_analysis`, `economics`, `heat_pump`, `network`,
  `refrigeration`, `research_questions`, `retrofit`, `sensitivity`. Most are `float | None` arguments
  passed on without a check and untyped dicts. Rule: a module joins the list when it is clean and never
  leaves it.
- **Units.** Units live in names (`T_C`, `Q_kWh_per_hl`, `dT_K`) and in docstrings, and conversions are
  centralised in `pinch.case.to_MWh_per_year`; there is no unit library. A library such as pint would
  catch mixed units at run time but makes formulas harder for examiners to read; not adopted.
- **Logging.** `analyse.py --verbose` logs progress; other scripts print their results tables. Warnings
  about input plausibility are part of the outputs (`summary.json` "warnings").
- **Coverage.** Line coverage was 91 % at 0.7.0 (lowest: `cycle_analysis` 39 %, `validation` 65 %); not
  gated.

## Provenance of results

Every `summary.json` holds `run.tool_version` and `run.inputs_sha256` (case file, stream file, network
file; line endings normalised). `run_metadata.json` next to it adds the time, git commit, whether the
working tree was clean, and library versions; it changes on every run and is git-ignored. A result is
traceable when its `summary.json` hashes match the files at the tagged version.

## Releasing

1. Update the version in `pinch/__init__.py`, `pyproject.toml`, `CITATION.cff` (and `date-released`) and
   add a `CHANGELOG.md` section.
2. `python regenerate_outputs.py`, commit, `python -m pytest`.
3. `git tag vX.Y.Z && git push --tags`. The release workflow checks the tag against `pinch.__version__`,
   runs the tests, builds the sdist and wheel, and attaches them to a GitHub release.
4. For a citable persistent identifier, connect the repository to Zenodo (one-time, on zenodo.org); each
   GitHub release then gets a DOI to add to `CITATION.cff`. Not done: it needs the author's accounts.
