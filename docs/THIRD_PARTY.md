# Third-party software and data

What this project takes from others, under which licence, and where it is used. Libraries are used as
installed dependencies (versions pinned in `requirements.txt`) unless stated otherwise; no third-party
source code is copied into this repository except where marked.

| Project | Authors | Licence | Used as | Where | What for |
|---|---|---|---|---|---|
| [ht](https://github.com/CalebBell/ht) 1.2.0 | Caleb Bell and contributors | MIT | dependency | `pinch/exchanger_rating.py` | LMTD correction factor with N shells (`ht.hx.F_LMTD_Fakheri`, Fakheri 2003); tube-side Nusselt numbers (`turbulent_Colburn`, `turbulent_Gnielinski`) |
| [fluids](https://github.com/CalebBell/fluids) 1.3.1 | Caleb Bell and contributors | MIT | dependency (of ht) | `pinch/exchanger_rating.py` | Darcy friction factor (`fluids.friction.friction_factor`, Clamond solution of Colebrook) |
| [TESPy](https://github.com/oemof/tespy) 0.12.0.post1 | Francesco Witte and contributors | MIT | dependency | `pinch/tespy_heat_pump.py` | Independent rebuild of single-stage cycles; off-design (part-load) simulation with its default characteristic lines. Cite: Witte and Tuschy (2020), J. Open Source Softw. 5(49), 2178, doi:10.21105/joss.02178 |
| [heatpumps](https://github.com/jfreissmann/heatpumps) | Jonas Freißmann and Malte Fritz | MIT | method and data re-implemented, not installed (it pins tespy < 0.12) | `pinch/tespy_heat_pump.py` (`kosmadakis_cost`, `CEPCI`) | Component cost method of Kosmadakis et al. (2020), Energy Convers. Manag. 226, 113488, as implemented in `HeatPumpBase.calc_cost` (cost laws, reference year 2013, 6.32 total-capital factor), and the CEPCI values of `models/input/CEPCI.json`. Copyright notice reproduced below |
| [entsoe-py](https://github.com/EnergieID/entsoe-py) 0.8.1 | EnergieID cvba-so and contributors | MIT | dependency (optional; only for fetching) | `scripts/data/fetch_entsoe_prices.py` | Day-ahead prices from the ENTSO-E Transparency Platform (`EntsoePandasClient.query_day_ahead_prices`); data subject to ENTSO-E's terms |
| [min_matches_heuristics](https://github.com/TYT0710/min_matches_heuristics) (commit 60894d2) | Dimitrios Letsios, Georgia Kouyialis, Ruth Misener | Apache 2.0 | data copied (23 instance files), line endings changed CRLF → LF | `data/benchmarks/letsios2018/`, `scripts/benchmarks/benchmark_min_matches.py` | Furman and Sahinidis (2004) instances as digitised by Letsios et al. (2018), Comput. Chem. Eng. 113, 57-85, and their exact results (`published_min_matches.json`). Licence: `data/benchmarks/letsios2018/LICENSE-Apache-2.0` |
| [OpenPinch](https://github.com/waikato-ahuora-smart-energy-systems/OpenPinch) 0.8.3 | Timothy G. Walmsley and contributors | MIT | stored results and sample files | `data/benchmarks/openpinch_*`, `scripts/benchmarks/benchmark_openpinch.py` | Independent check of the targets (Walmsley 2026, Process Integr. Optim. Sustain., doi:10.1007/s41660-026-00729-6) |
| [IBM Plex](https://github.com/IBM/plex) | IBM Corp. | SIL OFL 1.1 | font files copied | `static/fonts/` | Front-end typeface (`static/fonts/OFL.txt`) |

Not used, and why: OSMOSE/ROSMOSE (EPFL; access through EPFL GitLab only); PyPinch and pina (Problem Table
only, already covered); cog-imperial/hens (needs Gurobi and Pyomo 5); hplib (Keymark data for building
heat pumps, not industrial high-temperature units).

## heatpumps copyright notice

    MIT License

    Copyright (c) 2021-2026 Jonas Freißmann and Malte Fritz

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
    associated documentation files (the "Software"), to deal in the Software without restriction,
    including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
    and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
    subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial
    portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
    LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
    NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
    WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
    SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
