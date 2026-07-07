"""
Economics: CAPEX build-up, annual OPEX, savings (CNG offset + CO2), and
cash-flow metrics (net annual result, simple payback, NPV, IRR).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .config import PlantParams
from .simulation import SimulationResult


@dataclass
class EconomicsResult:
    capex_breakdown: Dict[str, float]
    opex_breakdown: Dict[str, float]
    savings_breakdown: Dict[str, float]
    total_capex: float
    total_opex: float
    total_savings: float
    net_annual: float
    simple_payback_years: float
    npv: float
    irr: float
    cashflows: List[float] = field(default_factory=list)


def _npv(rate: float, cashflows: List[float]) -> float:
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cashflows))


def _irr(cashflows: List[float]) -> float:
    """Robust IRR by scanning + bisection. Returns nan if no sign change."""
    if not cashflows or all(cf >= 0 for cf in cashflows) or all(cf <= 0 for cf in cashflows):
        return float("nan")

    lo, hi = -0.9, 10.0
    f_lo, f_hi = _npv(lo, cashflows), _npv(hi, cashflows)
    if f_lo * f_hi > 0:
        # scan for a bracket
        prev_r, prev_f = lo, f_lo
        r = lo
        found = False
        while r < hi:
            f = _npv(r, cashflows)
            if prev_f * f < 0:
                lo, hi, f_lo = prev_r, r, prev_f
                found = True
                break
            prev_r, prev_f = r, f
            r += 0.01
        if not found:
            return float("nan")

    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = _npv(mid, cashflows)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def evaluate_economics(sim: SimulationResult, p: PlantParams) -> EconomicsResult:
    s = sim.summary

    # ---------------- CAPEX ----------------
    elx_kw = p.elx_power_mw * 1000.0
    if p.comp_power_kw > 0:
        comp_kw = p.comp_power_kw
    else:
        # auto-size compressor to full ELX H2 production rate
        comp_kw = s["h2_prod_rate_kg_h"] * p.comp_spec_energy

    capex = {
        "Electrolyzer": elx_kw * p.capex_elx_eur_per_kw,
        "Compressor": comp_kw * p.capex_comp_eur_per_kw,
        "Storage (200 bar)": p.storage_capacity_kg * p.capex_storage_eur_per_kg,
        "Balance of plant": p.capex_bop_eur,
    }
    total_capex = sum(capex.values())

    # ---------------- OPEX ----------------
    elx_opex = s["elx_elec_mwh"] * p.elec_price_eur_mwh
    comp_opex = s["comp_elec_mwh"] * p.elec_price_eur_mwh
    maint = total_capex * p.opex_maint_pct / 100.0
    opex = {
        "Electricity - electrolyzer": elx_opex,
        "Electricity - compressor": comp_opex,
        "Maintenance": maint,
        "Fixed OPEX": p.opex_fixed_eur,
    }
    total_opex = sum(opex.values())

    # ---------------- Savings ----------------
    cng_saved_mwh = s["cng_offset_mwh"]
    cng_cost_saved = cng_saved_mwh * p.cng_price_eur_mwh
    co2_saved_t = cng_saved_mwh * p.co2_cng_t_per_mwh
    co2_saving = co2_saved_t * p.co2_price_eur_t
    savings = {
        "CNG fuel avoided": cng_cost_saved,
        "CO2 tax avoided": co2_saving,
    }
    total_savings = sum(savings.values())
    savings["_co2_saved_t"] = co2_saved_t  # metadata (leading underscore = not a €)

    # ---------------- Net & finance ----------------
    net_annual = total_savings - opex["Electricity - electrolyzer"] \
        - opex["Electricity - compressor"] - maint - p.opex_fixed_eur
    # (equivalently total_savings - total_opex, kept explicit for clarity)
    net_annual = total_savings - total_opex

    simple_payback = total_capex / net_annual if net_annual > 0 else float("inf")

    cashflows = [-total_capex] + [net_annual] * p.project_years
    npv = _npv(p.discount_rate, cashflows)
    irr = _irr(cashflows)

    return EconomicsResult(
        capex_breakdown=capex,
        opex_breakdown=opex,
        savings_breakdown=savings,
        total_capex=total_capex,
        total_opex=total_opex,
        total_savings=total_savings,
        net_annual=net_annual,
        simple_payback_years=simple_payback,
        npv=npv,
        irr=irr,
        cashflows=cashflows,
    )
