"""
Central parameter definition for the H2 power-generation plant model.

Every field here is a variable you can change in the Streamlit sidebar.
Defaults are taken from the ZF Passau sizing spreadsheet (Sheet1) where available.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict


@dataclass
class PlantParams:
    # ------------------------------------------------------------------ #
    # Energy constants
    # ------------------------------------------------------------------ #
    lhv_cng: float = 9.97          # kWh / Nm3  (lower heating value of CNG)
    lhv_h2_vol: float = 3.0        # kWh / Nm3  (H2, used for volume reporting)
    lhv_h2_mass: float = 33.33     # kWh / kg   (H2)
    co2_cng_t_per_mwh: float = 0.201  # tCO2 / MWh_th of natural gas burned

    # ------------------------------------------------------------------ #
    # Demand
    # ------------------------------------------------------------------ #
    demand_scale: float = 1.0      # multiply the metered hourly profile
    h2_burner_rel_eff: float = 1.0  # useful heat per kWh LHV, H2 vs CNG (1.0 = same)

    # ------------------------------------------------------------------ #
    # Electrolyzer (alkaline)
    # ------------------------------------------------------------------ #
    elx_power_mw: float = 3.0          # rated electrical power
    elx_spec_energy: float = 55.5      # kWh electricity / kg H2 (LHV eff = 33.33/55.5 = 60%)
    elx_hours_per_day: int = 7         # operating hours per day (>=14h OFF => <=10h)
    elx_start_hour: int = 6            # hour of day the ELX turns on
    operate_weekends: bool = True      # run ELX on Sat/Sun as well
    # Load-follow: ELX only draws power for H2 it can use/store (minimises waste
    # and electricity OPEX). If False -> full rated power the whole window
    # (matches the ZF spreadsheet; surplus H2 is curtailed/vented).
    elx_load_follow: bool = True

    # ------------------------------------------------------------------ #
    # Waste-heat recovery
    # ------------------------------------------------------------------ #
    # Fraction of ELX *electrical* input recovered as useful process heat.
    # Physical ceiling ~ 1 - 33.33/55.5 = 0.40. Default is a realistic usable value.
    wh_recovery_frac: float = 0.25

    # ------------------------------------------------------------------ #
    # Compressor (to 200 bar trailer)
    # ------------------------------------------------------------------ #
    comp_spec_energy: float = 2.0      # kWh electricity / kg H2 compressed
    comp_power_kw: float = 0.0         # 0 => auto-size to full ELX H2 rate

    # ------------------------------------------------------------------ #
    # Storage (200 bar trailer)
    # ------------------------------------------------------------------ #
    storage_capacity_kg: float = 500.0  # usable H2 mass at 200 bar
    storage_init_frac: float = 0.5      # initial state of charge (fraction of capacity)

    # ------------------------------------------------------------------ #
    # Backup
    # ------------------------------------------------------------------ #
    allow_cng_backup: bool = True   # keep CNG burners for hours H2 can't cover

    # ------------------------------------------------------------------ #
    # Prices / economics
    # ------------------------------------------------------------------ #
    elec_price_eur_mwh: float = 59.0
    cng_price_eur_mwh: float = 120.0
    co2_price_eur_t: float = 80.0

    # CAPEX (specific)
    capex_elx_eur_per_kw: float = 900.0        # €/kW electrical (turnkey alkaline)
    capex_comp_eur_per_kw: float = 3000.0      # €/kW compressor
    capex_storage_eur_per_kg: float = 800.0    # €/kg usable H2 (200 bar)
    capex_bop_eur: float = 250000.0            # balance of plant / installation (fixed)

    # OPEX
    opex_maint_pct: float = 3.0     # % of total CAPEX per year (maintenance)
    opex_fixed_eur: float = 0.0     # extra fixed OPEX per year (water, staff, ...)

    # Finance
    project_years: int = 15
    discount_rate: float = 0.07

    def to_dict(self) -> Dict:
        return asdict(self)
