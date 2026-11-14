# Dairy with integrated CO2 refrigeration

Dairy whose cooling, hot-water and steam loads were metered for a year; analysed on its mean production day, hour by hour. Today the CO2 refrigeration units heat the hot water and an electric boiler raises the steam.

## Energy targets

| Quantity | Value [kW] |
|---|---|
| Total hot / cold stream loads | 95.642 / 232.2034 |
| Q̇h,min | 232.2034 |
| Q̇c,min | 95.642 |
| Heat recovery | 0.0 |
| Pinch T* [°C] | 9.0, -0.5 |

## Heat pumps sized from the GCC

| Quantity | Value |
|---|---|
| Units | CO2 units (hot water), HTHP (steam demand) |
| Heat delivered [kW] | 232.2034 |
| Electricity [kW] | 94.145 |
| System COP [-] | 2.466 |
| Residual hot utility [kW] | 0.0 |
| Share of Q̇h,min electrified | 100.0 % |
| External (ambient) source [kW] | 42.4165 |

No annual basis given: results stay in the stream-data unit.

Economics skipped: no annual basis in the case file.

## COP ranges from manufacturer and demonstration data (step 4, pinch.cop_data)

COP of each heat pump on four bases: the case's Lorenz efficiency; manufacturer-data fits (Jesper et al. 2021) at lift = sink outlet - source inlet, with their standard deviation; a glide-matched blend (+16 %, Brendel et al. 2024) for sink glides of 25 K or more; the Lorenz model with the efficiencies achieved by IEA HPT Annex 58 closed-cycle demonstration plants (min, median, max). The fits come from small-glide machines, so for a large sink glide they are a pessimistic bound. fit_in_range = False: the point is outside the data behind the fit.

| Unit | Lift [K] | Sink glide [K] | Case basis | Fit −σ / fit / +σ | In fit range | Glide blend | Demonstration η_L min / median / max |
|---|---|---|---|---|---|---|---|
| CO2 units (hot water) | 73.5 | 58.5 | 3.58 | 1.68 / 1.96 / 2.24 | yes | 2.27 | 2.48 / 2.65 / 3.90 |
| HTHP (steam demand) | 108.5 | 35 | 1.97 | 1.45 / 1.64 / 1.83 | no (extrapolated) | 1.91 | 1.36 / 1.46 / 2.15 |

## Non-continuous operation (pinch.time_slices)

Time Slice Model (direct heat recovery only) and Time Average Model (storage at any temperature) per cycle; heat pump with hot and cold storage loops after Stampfli et al. (2019).

| Per cycle [kWh] | Time Slice Model (no storage) | Time Average Model (ideal storage) |
|---|---|---|
| Qh_kWh | 5,572.9 | 5,572.9 |
| Qc_kWh | 2,295.4 | 2,295.4 |
| recovery_kWh | 0.0 | 0.0 |

Heat pump with storage loops: condensing 73.75 °C, evaporating -11.52 °C, COP 1.424, 103.48 kW constant, hot storage 629 kWh, cold storage 347 kWh.

## Sources and provenance

- **data source**: Köster, Bengsch, Widell (2025), Int. J. Refrig. 180, 564-571 (CC BY 4.0) and its data, Zenodo doi:10.5281/zenodo.22877098 (CC BY 4.0): metered 2024 heat loads (one-minute) and hourly electric-boiler electricity.
- **stream data**: measured: mean production day of 2024 (weekdays with more than 1,500 kWh of boiler electricity), hour by hour; CO2 unit 1 (not metered) at 35 kW from 07:00 to 15:00 as the authors assume (Sec. 3). Published figures reproduced in outputs/koster2025_checks.csv
- **temperatures**: published (Sec. 2): glycol supply -3.5 to -5 °C, process water about 1 °C, hot water from city water 6.5 °C to 65 °C, steam demands 65-100 °C. Cooling loads are taken isothermal at the supply temperature (-3.5 °C, 1 °C): return temperatures are not published, so the source is a lower bound
- **dT_shift_K**: assumed: 2.5 K for every stream (dTmin 5 K)
- **steam demand**: measured boiler electricity with a thermal efficiency of about 1 (Sec. 4.4), including its heat losses (the 35.8 kW night baseload)
- **eta_lorenz**: assumed: 0.5, as the brewery case; the measured CO2 COPs (Table 2) are depressed by a fouled gas cooler (about 20 K approach, Sec. 4.2) and their operating conditions are not published, so they cannot calibrate it
- **source_T_C**: published glycol supply -3.5 °C, shifted by -2.5 K
- **sink levels**: published: hot water to 65 °C (the CO2 units today) and the 65-100 °C steam demands (the paper's proposal: a high-temperature heat pump replacing the electric boiler, Sec. 4.4); shifted by +2.5 K
- **basis**: none: a screening on the mean production day, in kW; no prices for Norway in this repository
- **ambient_T_C**: published: 2024 mean of August 15.5 °C and December 0.1 °C is not an annual mean; 7 °C assumed for the ambient-source check only
