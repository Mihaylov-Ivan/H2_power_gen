"""
Parameter sweeps and storage auto-sizing to find a good plant configuration.

Given a base PlantParams, vary the electrolyzer size and daily operating hours,
auto-size the storage to the minimum needed for (near-)full coverage, and record
coverage + economics for every combination.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, List

import pandas as pd

from .config import PlantParams
from .simulation import simulate
from .economics import evaluate_economics


def _coverage(demand: pd.DataFrame, p: PlantParams, cap_kg: float) -> float:
    pp = replace(p, storage_capacity_kg=cap_kg, storage_init_frac=0.0)
    return simulate(demand, pp).summary["h2_coverage_frac"]


def min_storage_for_coverage(
    demand: pd.DataFrame,
    p: PlantParams,
    target: float = 0.995,
    cap_max: float | None = None,
) -> tuple[float, float]:
    """
    Smallest storage capacity (kg) giving coverage >= target.
    Coverage is monotone non-decreasing in capacity, so we bisect.
    Returns (capacity_kg, achieved_coverage). If the ELX itself is too small to
    reach `target` even with lots of storage, returns (cap_max, coverage@cap_max).
    """
    # sensible upper bound: ~1 month of average H2 demand
    if cap_max is None:
        annual_h2_kg = demand["cng_nm3"].sum() * p.demand_scale * p.lhv_cng / p.lhv_h2_mass
        cap_max = max(50.0, 30.0 * annual_h2_kg / 365.0)

    cov0 = _coverage(demand, p, 0.0)
    if cov0 >= target:
        return 0.0, cov0

    cov_hi = _coverage(demand, p, cap_max)
    # If target unreachable (ELX/hours limited), size storage to the "knee":
    # the smallest capacity reaching 99% of the max achievable coverage.
    eff_target = target if cov_hi >= target else 0.99 * cov_hi

    lo, hi = 0.0, cap_max
    for _ in range(16):
        mid = 0.5 * (lo + hi)
        if _coverage(demand, p, mid) >= eff_target:
            hi = mid
        else:
            lo = mid
    return hi, _coverage(demand, p, hi)


def sweep(
    demand: pd.DataFrame,
    base: PlantParams,
    elx_sizes_mw: Iterable[float],
    hours_per_day: Iterable[int],
    coverage_target: float = 0.995,
    storage_margin: float = 1.1,
) -> pd.DataFrame:
    """One row per (elx_size, hours) combination, with auto-sized storage."""
    rows: List[dict] = []
    for mw in elx_sizes_mw:
        for hpd in hours_per_day:
            p = replace(base, elx_power_mw=float(mw), elx_hours_per_day=int(hpd))

            cap, _ = min_storage_for_coverage(demand, p, target=coverage_target)
            cap = max(cap * storage_margin, 1.0)
            p = replace(p, storage_capacity_kg=cap)

            sim = simulate(demand, p)
            eco = evaluate_economics(sim, p)
            s = sim.summary

            rows.append(
                {
                    "elx_mw": float(mw),
                    "hours_per_day": int(hpd),
                    "coverage_%": 100.0 * s["h2_coverage_frac"],
                    "storage_kg": cap,
                    "curtailed_kg": s["h2_curtailed_kg"],
                    "elec_mwh": s["total_elec_mwh"],
                    "capex_eur": eco.total_capex,
                    "opex_eur": eco.total_opex,
                    "savings_eur": eco.total_savings,
                    "net_annual_eur": eco.net_annual,
                    "payback_yr": eco.simple_payback_years,
                    "npv_eur": eco.npv,
                    "irr_%": eco.irr * 100.0,
                }
            )
    return pd.DataFrame(rows)
