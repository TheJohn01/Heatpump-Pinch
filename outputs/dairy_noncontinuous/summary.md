# Non-continuous dairy

Dairy site (cream treatment, butter oil, cleaning in place) whose streams run in batches within a daily cycle, loads in kW with start and end times. Analysed on its time-averaged streams (storage at any temperature) and, for operation, slice by slice with a heat pump between hot and cold storage loops.

## Energy targets

| Quantity | Value [kW] |
|---|---|
| Total hot / cold stream loads | 1148.6206 / 1259.0726 |
| Q̇h,min | 209.4194 |
| Q̇c,min | 98.9675 |
| Heat recovery | 1049.6531 |
| Pinch T* [°C] | 13.0 |

## Heat pumps sized from the GCC

| Quantity | Value |
|---|---|
| Units | HP with storage loops |
| Heat delivered [kW] | 86.0889 |
| Electricity [kW] | 39.1686 |
| System COP [-] | 2.198 |
| Residual hot utility [kW] | 123.3305 |
| Share of Q̇h,min electrified | 41.1 % |
| External (ambient) source [kW] | 0.0 |

No annual basis given: results stay in the stream-data unit.

Economics skipped: no annual basis in the case file.

## COP ranges from manufacturer and demonstration data (step 4, pinch.cop_data)

COP of each heat pump on four bases: the case's Lorenz efficiency; manufacturer-data fits (Jesper et al. 2021) at lift = sink outlet - source inlet, with their standard deviation; a glide-matched blend (+16 %, Brendel et al. 2024) for sink glides of 25 K or more; the Lorenz model with the efficiencies achieved by IEA HPT Annex 58 closed-cycle demonstration plants (min, median, max). The fits come from small-glide machines, so for a large sink glide they are a pessimistic bound. fit_in_range = False: the point is outside the data behind the fit.

| Unit | Lift [K] | Sink glide [K] | Case basis | Fit −σ / fit / +σ | In fit range | Glide blend | Demonstration η_L min / median / max |
|---|---|---|---|---|---|---|---|
| HP with storage loops | 50.87 | 0 | 2.20 | 2.85 / 3.13 / 3.41 | yes | – | 2.17 / 2.33 / 3.42 |

## Non-continuous operation (pinch.time_slices)

Time Slice Model (direct heat recovery only) and Time Average Model (storage at any temperature) per cycle; heat pump with hot and cold storage loops after Stampfli et al. (2019); hourly operation against the year's hourly prices (pinch.time_slices.annual_dispatch).

| Per cycle [kWh] | Time Slice Model (no storage) | Time Average Model (ideal storage) |
|---|---|---|
| Qh_kWh | 5,034.7 | 5,026.1 |
| Qc_kWh | 2,383.8 | 2,375.2 |
| recovery_kWh | 25,183.1 | 25,191.7 |

Heat pump with storage loops: condensing 46.3 °C, evaporating -4.57 °C, COP 2.198, 86.45 kW constant, hot storage 1,359 kWh, cold storage 740 kWh.

Hourly operation over the price year (COP constant at part load; extra capacity's investment not counted; days with a clock change left out); back-up heat at 0.0606 EUR/kWh.

| Mode | Capacity [kW] | Heat pump [MWh] | Back-up [MWh] | Electricity [MWh] | Energy cost [EUR] | Capacity charges [EUR] | Total [EUR] | Saving |
|---|---|---|---|---|---|---|---|---|
| constant (design) | 86.4 | 753.13 | 0.0 | 342.64 | 33,601 | 3,536 | 37,137 | 0.0 % |
| dispatch, capacity x 1 | 86.4 | 515.4 | 237.73 | 234.48 | 30,522 | 2,566 | 33,088 | 10.9 % |
| dispatch, capacity x 1.5 | 129.7 | 617.84 | 135.29 | 281.09 | 25,978 | 3,513 | 29,491 | 20.6 % |
| dispatch, capacity x 2 | 172.9 | 662.92 | 90.21 | 301.6 | 23,225 | 4,405 | 27,630 | 25.6 % |

## Sources and provenance

- **data source**: Stampfli, Atkins, Olsen, Walmsley, Wellig (2019), Energy 182, 236-253, Table 1 (CC BY); companion paper Stampfli et al. (2018), CET 70, 1789-1794.
- **stream data**: published (Table 1, with start and end times); wash water heating uses CP x dT (242.9 kW) instead of the printed 260.25 kW (scripts/validation/reproduce_stampfli2019.py)
- **eta_lorenz**: published: zeta = 0.35, the Carnot fraction of Sec. 2.3 (isothermal condenser and evaporator, so Lorenz = Carnot)
- **source_T_C**: reproduced: T*ev = 7.93 °C from Eq. 9 (pinch.time_slices.storage_heat_pump) at the paper's T*co,sel = 33.8 °C
- **dT_cont_K**: published: real temperatures = shifted +/- 1.25 dTmin = 12.5 K (Eqs 5-6, two loop exchangers and the refrigerant)
- **sink levels**: published: T*co,sel = 33.8 °C (Sec. 3.2)
- **basis**: none: operating days per year are not published; the hourly operation is reported per year of prices, every day running the published daily schedule
- **ambient_T_C**: assumed: 15 °C, as the other secondary cases
- **economics**: prices only (see economics.sources); capacity factors of the dispatch are illustrative (1, 1.5, 2 x the design rate) and their extra investment is not counted
