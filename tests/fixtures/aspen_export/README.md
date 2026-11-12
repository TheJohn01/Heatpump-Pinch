# Synthetic Aspen Plus export (test fixture)

Invented values in the file layout written by the Python-Aspen Plus interface of Maier, Weyand et al.
(2025), ESCAPE 35, Syst. Control Trans. 4, 1631-1636 (one folder per run: `blocks/Heater.csv`,
`blocks/HeatX.csv`, `streams/MATERIAL.csv`; units in the column headers). No simulation produced these
numbers; they are chosen so that `tests/test_data_input.py` knows the answers:

* 239005.736 cal/s = 1000 kW (thermochemical calorie, 4.184 J);
* COOLER cools S1 (120 °C, all vapour) to 40 °C, removing 1000 kW, with a phase change;
* HEATER heats S3 from 25 °C to 85 °C, adding 500 kW;
* MIXHEAT has two inlets (S5, S6): left out (mixing);
* HX1 exchanges 250 kW between S7 (150 → 110 °C) and S9 (60 → 90 °C).
