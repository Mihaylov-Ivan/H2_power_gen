# H2 Power Generation - Plant Simulator (ZF Passau paint lines)

A Streamlit app that simulates replacing the compressed-natural-gas (CNG) heating
of the ZF Passau paint-drying lines with on-site **green hydrogen**:

- **Alkaline electrolyzer (ELX)** produces H2 during a chosen daily operating window.
- **Waste heat** from the ELX offsets part of the heating demand (reduces H2 use).
- A **compressor** stores surplus H2 in a **200 bar trailer**.
- Stored H2 feeds the pure-H2 burners when the ELX is off (>=14 h/day off).
- Optional **CNG backup** covers any hours H2 cannot.

It then evaluates **feasibility**: CAPEX, OPEX (electricity + maintenance),
CNG fuel avoided, CO2 tax avoided, net annual result, payback, NPV and IRR - and
lets you **sweep component sizes** to find the optimal configuration.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser. Every model input is on the left sidebar.

## Data

The hourly demand comes from `data/demand_hourly.csv`, extracted from
`Paint Drying Lines Passau Gas Consumption V3.xlsx` (metered 2023, 8760 hours,
three paint lines). Regenerate it with:

```bash
python extract_data.py
```

Metered 2023 total: **279,509 Nm3 CNG = 2.79 GWh_th** (LHV 9.97 kWh/Nm3).
To model a different design scenario (e.g. the 401,449 Nm3 max case from the
spreadsheet), just set the "Design annual CNG demand" field in the sidebar - the
whole hourly profile is scaled proportionally.

You can also upload your own hourly CSV (columns: `timestamp`, `cng_nm3`).

## Model at a glance

Per hour:

1. Heat demand = `cng_nm3 x LHV_CNG` (kWh thermal).
2. If the ELX is running, waste heat (`fraction x ELX power`) covers part of it.
3. Remaining heat is delivered by H2 - fresh from the ELX, otherwise from storage.
4. Surplus ELX H2 is compressed and charged into the 200 bar store.
5. Anything H2 cannot cover is burned as residual CNG.

Two ELX operating modes:

- **Load-follow** (default): the ELX only draws power for H2 it can use or store -
  realistic electricity OPEX, minimal curtailment.
- **Full-load-in-window**: the ELX runs at rated power the whole window and vents
  surplus H2. This reproduces the ZF spreadsheet's electricity OPEX
  (e.g. 3 MW x 2600 h x 59 EUR/MWh = 460,200 EUR/yr).

## Project layout

```
app.py               Streamlit UI (Overview / Operation / Economics / Sizing / Data)
extract_data.py      One-off Excel -> data/demand_hourly.csv extractor
data/demand_hourly.csv
h2plant/
  config.py          PlantParams dataclass - every tunable variable + defaults
  simulation.py      Hourly physical simulation
  economics.py       CAPEX / OPEX / savings / payback / NPV / IRR
  optimize.py        Size x hours sweep
requirements.txt
```

## Key default assumptions (all editable)

| Parameter | Default | Source |
|---|---|---|
| CNG LHV | 9.97 kWh/Nm3 | spreadsheet |
| H2 LHV | 3.0 kWh/Nm3 / 33.33 kWh/kg | spreadsheet |
| ELX specific energy | 55.5 kWh/kg (60% LHV) | spreadsheet |
| Electricity price | 59 EUR/MWh | spreadsheet |
| CNG price | 120 EUR/MWh | spreadsheet |
| Compressor | 2.0 kWh/kg to 200 bar | estimate |
| Waste-heat recovery | 25% of ELX power | estimate (ceiling ~40%) |
| CO2 factor | 0.201 tCO2/MWh_th | natural gas |

CAPEX/OPEX unit costs are editable estimates - replace them with your quotes.
