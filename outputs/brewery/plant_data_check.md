## Stream-data uncertainty (5000 Latin hypercube samples, seed 0)

Heat loads σ 10 %, temperatures σ 3 K (Bergamini et al. 2019, Table 1: rough estimates, dairy case). Temperature shifts not varied.

| Output | Nominal | Mean | Std | Std / mean | MC error | 2.5 % | 97.5 % | R² of linear model |
|---|---|---|---|---|---|---|---|---|
| Qh_min [kWh/hl] | 10 | 9.84 | 1.31 | 13 % | 0.0186 | 7.19 | 12.3 | 0.99 |
| Qc_min [kWh/hl] | 3.44 | 3.24 | 0.402 | 12 % | 0.00568 | 2.47 | 4.03 | 0.87 |
| pinch_T_star_C [°C] | 17 | 17 | 2.21 | n/a | 0.0312 | 12.6 | 21.2 | 0.54 |

Inputs with β² ≥ 0.01 for an output whose linear model has R² > 0.7 (16 of 33; ranked by largest β²):

| Input | β² Qh_min | β² Qc_min |
|---|---|---|
| Wortcooling: Q | 0.379 | 0.011 |
| Wortcooling: T_out | 0.032 | 0.338 |
| Lautering/Filtering: Q | 0.202 | 0.001 |
| Pre-mashing: T_in | 0.013 | 0.141 |
| Fermentation: Q | 0.000 | 0.140 |
| Lautering/Filtering: T_in | 0.011 | 0.122 |
| Pre-mashing: Q | 0.107 | 0.001 |
| Beer cooling: Q | 0.000 | 0.074 |
| Mashing: Q | 0.072 | 0.000 |
| Wortboiling (preheating): Q | 0.052 | 0.000 |
| Wortboiling (boiling): Q | 0.034 | 0.000 |
| Boiloff condensation: Q | 0.033 | 0.000 |
| CIP: Q | 0.025 | 0.000 |
| Fermentation: T | 0.002 | 0.022 |
| CIP: T_in | 0.001 | 0.013 |
| Filtration/centrifugation: Q | 0.000 | 0.010 |

## Match restrictions

No restrictions declared in the case file.

Screening, one pair forbidden at a time (not a claim that any pair is forbidden): pairs with a penalty.

| Hot | Cold | Qh,min [kWh/hl] | Penalty [kWh/hl] |
|---|---|---|---|
| (none) | | | |

36 of 36 pairs can be forbidden alone without penalty.

Screening, each stream barred from every process partner (it exchanges with utilities only):

| Stream | Type | Load [kWh/hl] | Qh,min [kWh/hl] | Penalty [kWh/hl] |
|---|---|---|---|---|
| Wortcooling | hot | 8.5 | 18.142 | +8.100 |
| Boiloff condensation | hot | 2.4 | 12.442 | +2.400 |
| Condensate cooling | hot | 0.9 | 10.900 | +0.858 |
| Pre-mashing | cold | 4.4 | 10.042 | +0.000 |
| Mashing | cold | 3.5 | 10.042 | +0.000 |
| Lautering/Filtering | cold | 6 | 10.042 | +0.000 |
| Wortboiling (preheating) | cold | 3 | 10.042 | +0.000 |
| Wortboiling (boiling) | cold | 2.4 | 10.042 | +0.000 |
| Fermentation | hot | 1.5 | 10.042 | +0.000 |
| Beer cooling | hot | 1.1 | 10.042 | +0.000 |
| Filtration/centrifugation | hot | 0.4 | 10.042 | +0.000 |
| CIP | cold | 2.1 | 10.042 | +0.000 |
