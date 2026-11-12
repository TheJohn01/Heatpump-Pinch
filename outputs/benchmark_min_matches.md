# Minimum number of matches: Letsios et al. (2018) benchmark

20 of 20 instances give the published number of units (19 published values are proven optima).
Instances: Furman and Sahinidis (2004) test set, digitised by Letsios, Kouyialis and Misener (2018), Apache License 2.0 (data/benchmarks/letsios2018/). Excluded instances and why: published_min_matches.json, key _excluded. The whole set solves in a few seconds with HiGHS.

| instance   |   streams |   utilities |   dTmin_K |     Qh_min |   units_here |   units_published | published_proven_optimal   | agrees   |
|:-----------|----------:|------------:|----------:|-----------:|-------------:|------------------:|:---------------------------|:---------|
| 4sp1       |         4 |           2 |        10 |    345.9   |            5 |                 5 | True                       | True     |
| 6sp-cf1    |         6 |           2 |        10 |      0     |            6 |                 6 | True                       | True     |
| 6sp-gg1    |         6 |           2 |        10 |      0     |            3 |                 3 | True                       | True     |
| 6sp1       |         6 |           2 |        10 |      0     |            6 |                 6 | True                       | True     |
| 7sp-cm1    |         7 |           2 |        10 |    182.521 |           10 |                10 | True                       | True     |
| 7sp-s1     |         7 |           2 |        10 |  82143.2   |           10 |                10 | True                       | True     |
| 7sp-torw1  |         7 |           2 |        10 |    231.36  |           10 |                10 | True                       | True     |
| 7sp1       |         7 |           1 |        10 |      0     |            7 |                 7 | True                       | True     |
| 7sp2       |         7 |           2 |        10 |   2175.53  |            7 |                 7 | True                       | True     |
| 7sp4       |         7 |           2 |        10 |   2431.49  |            8 |                 8 | True                       | True     |
| 8sp-fs1    |         8 |           2 |        10 |   2643.47  |           11 |                11 | True                       | True     |
| 8sp1       |         8 |           2 |        10 |   1942     |            9 |                 9 | True                       | True     |
| 9sp-al1    |         9 |           2 |        10 |     17.28  |           12 |                12 | True                       | True     |
| 9sp-has1   |         9 |           2 |        10 |  18450     |           13 |                13 | True                       | True     |
| 10sp-la1   |         9 |           2 |        10 |     17.28  |           12 |                12 | True                       | True     |
| 10sp-ol1   |        10 |           2 |        10 |     29.98  |           14 |                14 | True                       | True     |
| 10sp1      |        10 |           1 |        10 |      0     |           10 |                10 | True                       | True     |
| 12sp1      |        12 |           2 |        10 | 105554     |           12 |                12 | True                       | True     |
| 15sp-tkm   |        15 |           2 |        10 |   5828.5   |           19 |                19 | True                       | True     |
| 28sp-as1   |        28 |           2 |        10 |   5446     |           30 |                30 | False                      | True     |
