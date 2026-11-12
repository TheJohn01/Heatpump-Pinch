"""Command-line scripts, run from the repository root as modules, e.g. ``python -m scripts.analysis.analyse --all``.

analysis/    the general tool (any case file), cycle screening, RQ1-RQ3 consolidation
checks/      brewery checks that read the analysis outputs (batch, MVR, investment, plant data)
validation/  reproductions of published targets and results (Kemp, Padullés 2026, Walmsley 2024, Stampfli 2019)
benchmarks/  independent cross-checks (OpenPinch, published heat-exchanger networks)

``regenerate_outputs.py`` (repository root) runs all of them in dependency order.
"""
