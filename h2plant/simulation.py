"""
Hourly techno-physical simulation of the H2 plant.

Chain per hour:
    heat demand (from CNG profile)
      -> waste heat from ELX (when running) covers part of it
      -> remaining heat covered by H2 (fresh from ELX, else from 200-bar storage)
      -> surplus H2 from ELX is compressed and stored
      -> if H2 (fresh + stored) is insufficient, CNG backup covers the rest

Modelling choices (kept transparent on purpose):
  * The electrolyzer runs at RATED power during its daily operating window
    (full-load-in-window). This matches the ZF spreadsheet's electricity OPEX
    and makes the operating-window the key optimisation lever.
  * Surplus H2 that cannot be stored (storage full) is curtailed/vented.
  * Waste-heat recovery is a fraction of ELX electrical input, capped by demand.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import PlantParams


@dataclass
class SimulationResult:
    hourly: pd.DataFrame          # full 8760-row hourly time series
    summary: dict                 # scalar KPIs

    # convenience accessors
    @property
    def h2_coverage(self) -> float:
        return self.summary["h2_coverage_frac"]


def _build_schedule(index: pd.DatetimeIndex, p: PlantParams) -> np.ndarray:
    """Boolean array: True when the electrolyzer is running."""
    hours = index.hour.to_numpy()
    hpd = int(np.clip(p.elx_hours_per_day, 0, 24))
    start = int(p.elx_start_hour) % 24
    on_hours = {(start + i) % 24 for i in range(hpd)}
    on = np.isin(hours, list(on_hours)) if hpd > 0 else np.zeros(len(index), bool)

    if not p.operate_weekends:
        weekday = index.dayofweek.to_numpy()  # 5,6 = Sat,Sun
        on = on & (weekday < 5)
    return on


def simulate(demand: pd.DataFrame, p: PlantParams) -> SimulationResult:
    """
    demand: DataFrame with a 'timestamp' column and 'cng_nm3' column (Nm3/h).
    """
    df = demand.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    idx = pd.DatetimeIndex(df["timestamp"])
    n = len(df)

    # ---- heat demand [kWh_th] that must be delivered every hour --------------
    heat_demand = df["cng_nm3"].to_numpy() * p.demand_scale * p.lhv_cng
    # H2 energy needed to deliver that heat (burner efficiency ratio)
    demand_h2_energy = heat_demand / max(p.h2_burner_rel_eff, 1e-9)

    elx_on = _build_schedule(idx, p)

    # ---- fixed per-hour ELX quantities (full load when on) -------------------
    elx_kw = p.elx_power_mw * 1000.0
    h2_prod_rate = elx_kw / max(p.elx_spec_energy, 1e-9)      # kg/h when ON
    wh_rate = elx_kw * p.wh_recovery_frac                     # kWh_th/h when ON

    cap = max(p.storage_capacity_kg, 0.0)
    soc = np.clip(p.storage_init_frac, 0.0, 1.0) * cap

    # output arrays
    a_soc = np.zeros(n)
    a_wh_used = np.zeros(n)          # kWh_th waste heat actually used
    a_h2_burn = np.zeros(n)         # kg H2 to burners (fresh + storage)
    a_h2_from_fresh = np.zeros(n)   # kg H2 burner from fresh ELX
    a_h2_from_store = np.zeros(n)   # kg H2 burner from storage
    a_h2_to_store = np.zeros(n)     # kg H2 charged into storage
    a_h2_curtail = np.zeros(n)      # kg H2 vented (storage full)
    a_h2_prod = np.zeros(n)         # kg H2 produced by ELX
    a_elx_elec = np.zeros(n)        # kWh electricity ELX
    a_comp_elec = np.zeros(n)       # kWh electricity compressor
    a_cng_backup = np.zeros(n)      # kWh_th covered by residual CNG

    for i in range(n):
        d_th = heat_demand[i]
        on = elx_on[i]

        if on:
            space = cap - soc
            if p.elx_load_follow:
                # Choose load fraction f so the ELX makes just enough H2 to feed
                # the burner (after waste heat) and top up storage. Waste heat is
                # proportional to electricity, so solve the fixed point by
                # bisection on f in [0, 1] (g(f) is monotone decreasing).
                def g(f: float) -> float:
                    wh_f = min(f * wh_rate, d_th)
                    burner = max(d_th - wh_f, 0.0) / p.lhv_h2_mass
                    target = burner + space
                    return min(1.0, target / h2_prod_rate) if h2_prod_rate > 0 else 0.0

                lo, hi = 0.0, 1.0
                for _ in range(18):
                    mid = 0.5 * (lo + hi)
                    if g(mid) - mid > 0:
                        lo = mid
                    else:
                        hi = mid
                f = 0.5 * (lo + hi)
            else:
                f = 1.0

            wh = min(f * wh_rate, d_th)
            a_wh_used[i] = wh
            a_elx_elec[i] = f * elx_kw
            a_h2_prod[i] = f * h2_prod_rate
        else:
            wh = 0.0

        residual_th = d_th - wh
        h2_needed = residual_th / p.lhv_h2_mass  # kg for the burner this hour

        if on:
            prod = a_h2_prod[i]
            if prod >= h2_needed:
                # fresh H2 covers burner; surplus to storage
                a_h2_from_fresh[i] = h2_needed
                surplus = prod - h2_needed
                space = cap - soc
                to_store = min(surplus, space)
                soc += to_store
                a_h2_to_store[i] = to_store
                a_h2_curtail[i] = surplus - to_store
                a_comp_elec[i] = to_store * p.comp_spec_energy
            else:
                # ELX cannot meet burner alone -> draw storage
                a_h2_from_fresh[i] = prod
                deficit = h2_needed - prod
                from_store = min(deficit, soc)
                soc -= from_store
                a_h2_from_store[i] = from_store
                short = deficit - from_store
                a_cng_backup[i] = short * p.lhv_h2_mass  # unmet -> CNG (th)
        else:
            # ELX off -> everything from storage
            from_store = min(h2_needed, soc)
            soc -= from_store
            a_h2_from_store[i] = from_store
            short = h2_needed - from_store
            a_cng_backup[i] = short * p.lhv_h2_mass

        a_h2_burn[i] = a_h2_from_fresh[i] + a_h2_from_store[i]
        a_soc[i] = soc

    hourly = pd.DataFrame(
        {
            "timestamp": df["timestamp"].to_numpy(),
            "cng_nm3": df["cng_nm3"].to_numpy() * p.demand_scale,
            "heat_demand_kwh": heat_demand,
            "elx_on": elx_on.astype(int),
            "h2_prod_kg": a_h2_prod,
            "h2_burn_kg": a_h2_burn,
            "h2_from_fresh_kg": a_h2_from_fresh,
            "h2_from_store_kg": a_h2_from_store,
            "h2_to_store_kg": a_h2_to_store,
            "h2_curtail_kg": a_h2_curtail,
            "wh_used_kwh": a_wh_used,
            "elx_elec_kwh": a_elx_elec,
            "comp_elec_kwh": a_comp_elec,
            "cng_backup_kwh": a_cng_backup,
            "soc_kg": a_soc,
        }
    )

    # ---- KPIs ----------------------------------------------------------------
    total_heat = heat_demand.sum()
    cng_backup_th = a_cng_backup.sum()
    heat_by_h2 = (a_h2_burn.sum() * p.lhv_h2_mass)
    heat_by_wh = a_wh_used.sum()

    cng_original_nm3 = df["cng_nm3"].sum() * p.demand_scale
    cng_residual_nm3 = cng_backup_th / p.lhv_cng
    cng_offset_nm3 = cng_original_nm3 - cng_residual_nm3

    elx_mwh = a_elx_elec.sum() / 1000.0
    comp_mwh = a_comp_elec.sum() / 1000.0

    elx_on_hours = int(elx_on.sum())
    # equivalent full-load hours from actual electricity consumed
    elx_flh = (elx_mwh * 1000.0) / elx_kw if elx_kw > 0 else 0.0
    elx_cap_factor = (elx_mwh * 1000.0) / (elx_kw * n) if (elx_kw > 0 and n) else 0.0

    peak_soc = float(a_soc.max()) if n else 0.0
    unmet_hours = int((a_cng_backup > 1e-6).sum())

    summary = {
        "hours": n,
        "annual_heat_demand_mwh": total_heat / 1000.0,
        "heat_covered_by_h2_mwh": heat_by_h2 / 1000.0,
        "heat_covered_by_wasteheat_mwh": heat_by_wh / 1000.0,
        "heat_covered_by_cng_mwh": cng_backup_th / 1000.0,
        "h2_coverage_frac": (total_heat - cng_backup_th) / total_heat if total_heat else 0.0,
        "h2_produced_kg": float(a_h2_prod.sum()),
        "h2_burned_kg": float(a_h2_burn.sum()),
        "h2_curtailed_kg": float(a_h2_curtail.sum()),
        "h2_produced_nm3": float(a_h2_prod.sum()) * (p.lhv_h2_mass / p.lhv_h2_vol),
        "cng_original_nm3": float(cng_original_nm3),
        "cng_offset_nm3": float(cng_offset_nm3),
        "cng_residual_nm3": float(cng_residual_nm3),
        "cng_offset_mwh": cng_offset_nm3 * p.lhv_cng / 1000.0,
        "elx_elec_mwh": elx_mwh,
        "comp_elec_mwh": comp_mwh,
        "total_elec_mwh": elx_mwh + comp_mwh,
        "elx_on_hours": elx_on_hours,
        "elx_full_load_hours": elx_flh,
        "elx_capacity_factor": elx_cap_factor,
        "h2_prod_rate_kg_h": float(h2_prod_rate),
        "h2_prod_rate_nm3_h": float(h2_prod_rate) * (p.lhv_h2_mass / p.lhv_h2_vol),
        "peak_soc_kg": peak_soc,
        "min_storage_needed_kg": peak_soc,   # if capacity not binding, this is what's used
        "storage_capacity_kg": cap,
        "storage_binding": peak_soc >= cap - 1e-6 and cap > 0,
        "unmet_hours": unmet_hours,
    }

    return SimulationResult(hourly=hourly, summary=summary)
