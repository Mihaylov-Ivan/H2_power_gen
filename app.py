"""
H2 Power Generation - Plant Operation & Feasibility Simulator
=============================================================
Streamlit app that simulates replacing CNG heating with on-site green H2:
alkaline electrolyzer + waste-heat recovery + compressor + 200-bar storage.

Run:
    streamlit run app.py
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from h2plant import PlantParams, simulate, evaluate_economics, sweep

DATA_FILE = Path(__file__).parent / "data" / "demand_hourly.csv"
STATE_FILE = Path(__file__).parent / "data" / "app_state.json"
UPLOADED_DATA_FILE = Path(__file__).parent / "data" / "uploaded_demand.csv"

st.set_page_config(
    page_title="H2 Power Generation Simulator",
    page_icon="H2",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load_demand(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def load_persisted_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def save_persisted_state(state: dict, uploaded_df: pd.DataFrame | None = None) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if uploaded_df is not None:
        uploaded_df.to_csv(UPLOADED_DATA_FILE, index=False)
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


@st.cache_data(show_spinner=False)
def run_sim(demand: pd.DataFrame, params: dict):
    p = PlantParams(**params)
    sim = simulate(demand, p)
    eco = evaluate_economics(sim, p)
    return sim, eco


@st.cache_data(show_spinner=True)
def run_sweep(demand: pd.DataFrame, params: dict, sizes, hours):
    p = PlantParams(**params)
    return sweep(demand, p, sizes, hours)


def eur(x: float, digits: int = 0) -> str:
    if x != x or x in (float("inf"), float("-inf")):
        return "n/a"
    return f"{x:,.{digits}f} EUR"


# --------------------------------------------------------------------------- #
# Sidebar - all parameters
# --------------------------------------------------------------------------- #
st.sidebar.title("Plant parameters")

persisted = load_persisted_state()
persisted_params = persisted.get("params", {})

uploaded = st.sidebar.file_uploader(
    "Hourly demand CSV (optional)", type=["csv"],
    help="Must contain columns 'timestamp' and 'cng_nm3'. Defaults to the ZF Passau 2023 profile.",
)
if uploaded is not None:
    demand = pd.read_csv(uploaded)
    demand["timestamp"] = pd.to_datetime(demand["timestamp"])
    demand_source = "uploaded"
elif persisted.get("use_uploaded_data") and UPLOADED_DATA_FILE.exists():
    demand = load_demand(str(UPLOADED_DATA_FILE))
    demand_source = "persisted-uploaded"
else:
    demand = load_demand(str(DATA_FILE))
    demand_source = "default"

base_annual_nm3 = float(demand["cng_nm3"].sum())

d = PlantParams()  # defaults

with st.sidebar.expander("Demand", expanded=True):
    persisted_demand_target = persisted.get("demand_target_nm3")
    default_demand_target = (
        float(persisted_demand_target)
        if persisted_demand_target is not None
        else float(round(base_annual_nm3))
    )
    demand_target = st.number_input(
        "Design annual CNG demand (Nm3/yr)",
        min_value=0.0, value=default_demand_target, step=1000.0,
        help=f"Metered 2023 profile sums to {base_annual_nm3:,.0f} Nm3. "
             f"Enter a different value (e.g. 401,449 for the max scenario) to scale the profile.",
    )
    demand_scale = demand_target / base_annual_nm3 if base_annual_nm3 else 1.0
    h2_burner_rel_eff = st.slider(
        "H2 burner efficiency vs CNG", 0.7, 1.2, float(persisted_params.get("h2_burner_rel_eff", d.h2_burner_rel_eff)), 0.01,
        help="Useful heat delivered per kWh LHV: H2 burner relative to the CNG burner.",
    )

with st.sidebar.expander("Electrolyzer (alkaline)", expanded=True):
    elx_power_mw = st.slider("ELX rated power (MW)", 0.25, 6.0, float(persisted_params.get("elx_power_mw", d.elx_power_mw)), 0.05)
    elx_spec_energy = st.slider(
        "ELX specific energy (kWh/kg H2)", 45.0, 65.0, float(persisted_params.get("elx_spec_energy", d.elx_spec_energy)), 0.1,
        help="55.5 kWh/kg -> 60% LHV efficiency.",
    )
    elx_hours_per_day = st.slider(
        "Operating hours / day", 1, 24, int(persisted_params.get("elx_hours_per_day", d.elx_hours_per_day)),
        help="Hours the ELX runs. >=14 h OFF means <=10 h ON.",
    )
    elx_start_hour = st.slider("Start hour", 0, 23, int(persisted_params.get("elx_start_hour", d.elx_start_hour)))
    operate_weekends = st.checkbox("Operate weekends", bool(persisted_params.get("operate_weekends", d.operate_weekends)))
    elx_load_follow = st.checkbox(
        "Load-follow (minimise waste)", bool(persisted_params.get("elx_load_follow", d.elx_load_follow)),
        help="ON: ELX only draws power for H2 it can use/store. "
             "OFF: full rated power the whole window (matches spreadsheet, surplus H2 vented).",
    )

with st.sidebar.expander("Waste-heat recovery", expanded=False):
    wh_recovery_frac = st.slider(
        "Recovered heat (fraction of ELX power)", 0.0, 0.40, float(persisted_params.get("wh_recovery_frac", d.wh_recovery_frac)), 0.01,
        help="Usable process heat as a share of ELX electrical input. Physical ceiling ~0.40.",
    )

with st.sidebar.expander("Compressor (200 bar)", expanded=False):
    comp_spec_energy = st.slider("Compressor energy (kWh/kg)", 0.5, 4.0, float(persisted_params.get("comp_spec_energy", d.comp_spec_energy)), 0.1)
    comp_power_kw = st.number_input(
        "Compressor rated power (kW, 0=auto)", min_value=0.0, value=float(persisted_params.get("comp_power_kw", d.comp_power_kw)), step=10.0,
    )

with st.sidebar.expander("Storage (200 bar trailer)", expanded=False):
    storage_capacity_kg = st.slider(
        "Storage capacity (kg H2)", 50.0, 3000.0, float(persisted_params.get("storage_capacity_kg", d.storage_capacity_kg)), 10.0,
    )
    storage_init_frac = st.slider("Initial state of charge", 0.0, 1.0, float(persisted_params.get("storage_init_frac", d.storage_init_frac)), 0.05)
    allow_cng_backup = st.checkbox("Allow CNG backup for uncovered hours", bool(persisted_params.get("allow_cng_backup", d.allow_cng_backup)))

with st.sidebar.expander("Prices", expanded=False):
    elec_price_eur_mwh = st.number_input("Electricity (EUR/MWh)", value=float(persisted_params.get("elec_price_eur_mwh", d.elec_price_eur_mwh)), step=1.0)
    cng_price_eur_mwh = st.number_input("CNG (EUR/MWh)", value=float(persisted_params.get("cng_price_eur_mwh", d.cng_price_eur_mwh)), step=1.0)
    co2_price_eur_t = st.number_input("CO2 (EUR/t)", value=float(persisted_params.get("co2_price_eur_t", d.co2_price_eur_t)), step=5.0)
    co2_cng_t_per_mwh = st.number_input("CNG emission factor (tCO2/MWh)", value=float(persisted_params.get("co2_cng_t_per_mwh", d.co2_cng_t_per_mwh)), step=0.001, format="%.3f")

with st.sidebar.expander("CAPEX", expanded=False):
    capex_elx_eur_per_kw = st.number_input("Electrolyzer (EUR/kW)", value=float(persisted_params.get("capex_elx_eur_per_kw", d.capex_elx_eur_per_kw)), step=50.0)
    capex_comp_eur_per_kw = st.number_input("Compressor (EUR/kW)", value=float(persisted_params.get("capex_comp_eur_per_kw", d.capex_comp_eur_per_kw)), step=100.0)
    capex_storage_eur_per_kg = st.number_input("Storage (EUR/kg)", value=float(persisted_params.get("capex_storage_eur_per_kg", d.capex_storage_eur_per_kg)), step=50.0)
    capex_bop_eur = st.number_input("Balance of plant (EUR)", value=float(persisted_params.get("capex_bop_eur", d.capex_bop_eur)), step=10000.0)

with st.sidebar.expander("OPEX & Finance", expanded=False):
    opex_maint_pct = st.slider("Maintenance (% CAPEX/yr)", 0.0, 10.0, float(persisted_params.get("opex_maint_pct", d.opex_maint_pct)), 0.5)
    opex_fixed_eur = st.number_input("Other fixed OPEX (EUR/yr)", value=float(persisted_params.get("opex_fixed_eur", d.opex_fixed_eur)), step=5000.0)
    project_years = st.slider("Project lifetime (yr)", 5, 30, int(persisted_params.get("project_years", d.project_years)))
    discount_rate = st.slider("Discount rate", 0.0, 0.20, float(persisted_params.get("discount_rate", d.discount_rate)), 0.005)

params = dict(
    demand_scale=demand_scale,
    h2_burner_rel_eff=h2_burner_rel_eff,
    elx_power_mw=elx_power_mw,
    elx_spec_energy=elx_spec_energy,
    elx_hours_per_day=elx_hours_per_day,
    elx_start_hour=elx_start_hour,
    operate_weekends=operate_weekends,
    elx_load_follow=elx_load_follow,
    wh_recovery_frac=wh_recovery_frac,
    comp_spec_energy=comp_spec_energy,
    comp_power_kw=comp_power_kw,
    storage_capacity_kg=storage_capacity_kg,
    storage_init_frac=storage_init_frac,
    allow_cng_backup=allow_cng_backup,
    elec_price_eur_mwh=elec_price_eur_mwh,
    cng_price_eur_mwh=cng_price_eur_mwh,
    co2_price_eur_t=co2_price_eur_t,
    co2_cng_t_per_mwh=co2_cng_t_per_mwh,
    capex_elx_eur_per_kw=capex_elx_eur_per_kw,
    capex_comp_eur_per_kw=capex_comp_eur_per_kw,
    capex_storage_eur_per_kg=capex_storage_eur_per_kg,
    capex_bop_eur=capex_bop_eur,
    opex_maint_pct=opex_maint_pct,
    opex_fixed_eur=opex_fixed_eur,
    project_years=project_years,
    discount_rate=discount_rate,
)

sim, eco = run_sim(demand, params)
s = sim.summary
h = sim.hourly

save_persisted_state(
    {
        "demand_target_nm3": float(demand_target),
        "use_uploaded_data": demand_source in ("uploaded", "persisted-uploaded"),
        "params": params,
    },
    uploaded_df=demand if demand_source == "uploaded" else None,
)

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("H2 Power Generation - Plant Operation & Feasibility")
st.caption(
    "Replace CNG heating for the ZF Passau paint-drying lines with green H2 "
    "(alkaline electrolyzer + waste-heat recovery + 200 bar storage). "
    "All inputs are editable in the sidebar."
)
if demand_source == "persisted-uploaded":
    st.info("Using last uploaded hourly CSV restored from saved app state.")

# top-line KPIs
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("H2 energy coverage", f"{s['h2_coverage_frac']*100:.1f}%")
k2.metric("Net annual result", eur(eco.net_annual),
          delta="profit" if eco.net_annual > 0 else "loss",
          delta_color="normal" if eco.net_annual > 0 else "inverse")
k3.metric("Total CAPEX", eur(eco.total_capex))
k4.metric("Payback", "n/a" if eco.simple_payback_years == float("inf") else f"{eco.simple_payback_years:.1f} yr")
k5.metric("NPV @ %.0f%%" % (discount_rate*100), eur(eco.npv))

if s["unmet_hours"] > 0:
    st.warning(
        f"H2 supply is insufficient in {s['unmet_hours']} hours "
        f"({s['cng_residual_nm3']:,.0f} Nm3 CNG still burned). "
        "Increase ELX size, operating hours, or storage capacity."
    )
if s["h2_curtailed_kg"] > 1:
    st.info(
        f"{s['h2_curtailed_kg']:,.0f} kg H2 curtailed (storage full). "
        "Consider a smaller ELX, fewer hours, or more storage - or enable load-follow."
    )

tab_over, tab_op, tab_eco, tab_opt, tab_data = st.tabs(
    ["Overview", "Operation", "Economics", "Sizing & Optimization", "Data"]
)

# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
with tab_over:
    c1, c2 = st.columns([1, 1])

    with c1:
        st.subheader("Where the heat comes from")
        heat = {
            "H2 combustion": s["heat_covered_by_h2_mwh"],
            "ELX waste heat": s["heat_covered_by_wasteheat_mwh"],
            "Residual CNG": s["heat_covered_by_cng_mwh"],
        }
        fig = px.pie(
            names=list(heat.keys()), values=list(heat.values()), hole=0.5,
            color=list(heat.keys()),
            color_discrete_map={"H2 combustion": "#2E86DE", "ELX waste heat": "#F39C12", "Residual CNG": "#E74C3C"},
        )
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320)
        st.plotly_chart(fig, width="stretch")

    with c2:
        st.subheader("Annual balance")
        st.dataframe(
            pd.DataFrame(
                {
                    "Metric": [
                        "Heat demand", "Covered by H2", "Covered by waste heat",
                        "Residual CNG", "H2 produced", "H2 produced",
                        "H2 curtailed", "CNG offset", "Electricity used",
                        "CO2 avoided",
                    ],
                    "Value": [
                        f"{s['annual_heat_demand_mwh']:,.0f} MWh",
                        f"{s['heat_covered_by_h2_mwh']:,.0f} MWh",
                        f"{s['heat_covered_by_wasteheat_mwh']:,.0f} MWh",
                        f"{s['heat_covered_by_cng_mwh']:,.0f} MWh",
                        f"{s['h2_produced_kg']:,.0f} kg",
                        f"{s['h2_produced_nm3']:,.0f} Nm3",
                        f"{s['h2_curtailed_kg']:,.0f} kg",
                        f"{s['cng_offset_nm3']:,.0f} Nm3",
                        f"{s['total_elec_mwh']:,.0f} MWh",
                        f"{eco.savings_breakdown['_co2_saved_t']:,.0f} t",
                    ],
                }
            ),
            hide_index=True, width="stretch",
        )

    st.subheader("Sizing at a glance")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("ELX H2 rate (rated)", f"{s['h2_prod_rate_nm3_h']:,.0f} Nm3/h",
              help=f"{s['h2_prod_rate_kg_h']:.1f} kg/h at {elx_power_mw:.2f} MW")
    g2.metric("ELX equiv. full-load h", f"{s['elx_full_load_hours']:,.0f} h",
              help=f"Capacity factor {s['elx_capacity_factor']*100:.0f}% ; ON {s['elx_on_hours']:,} h")
    g3.metric("Peak storage used", f"{s['peak_soc_kg']:,.0f} kg",
              help=f"Installed capacity {s['storage_capacity_kg']:,.0f} kg")
    g4.metric("Storage capacity binding?", "Yes" if s["storage_binding"] else "No")

    # monthly stacked energy
    hh = h.copy()
    hh["month"] = hh["timestamp"].dt.month
    hh["h2_heat_mwh"] = hh["h2_burn_kg"] * PlantParams().lhv_h2_mass / 1000.0
    hh["wh_mwh"] = hh["wh_used_kwh"] / 1000.0
    hh["cng_mwh"] = hh["cng_backup_kwh"] / 1000.0
    monthly = hh.groupby("month")[["h2_heat_mwh", "wh_mwh", "cng_mwh"]].sum().reset_index()
    fig = go.Figure()
    fig.add_bar(x=monthly["month"], y=monthly["h2_heat_mwh"], name="H2", marker_color="#2E86DE")
    fig.add_bar(x=monthly["month"], y=monthly["wh_mwh"], name="Waste heat", marker_color="#F39C12")
    fig.add_bar(x=monthly["month"], y=monthly["cng_mwh"], name="Residual CNG", marker_color="#E74C3C")
    fig.update_layout(barmode="stack", height=340, xaxis_title="Month", yaxis_title="MWh_th",
                      margin=dict(t=10, b=10), legend=dict(orientation="h", y=1.1))
    st.subheader("Monthly heat supply")
    st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- #
# Operation
# --------------------------------------------------------------------------- #
with tab_op:
    st.subheader("Hourly operation")
    dmin = h["timestamp"].min().date()
    dmax = h["timestamp"].max().date()
    rng = st.date_input("Date range", value=(dmin, min(dmax, dmin + pd.Timedelta(days=13))),
                        min_value=dmin, max_value=dmax)
    if isinstance(rng, tuple) and len(rng) == 2:
        start, end = rng
    else:
        start, end = dmin, dmax
    mask = (h["timestamp"].dt.date >= start) & (h["timestamp"].dt.date <= end)
    win = h.loc[mask]

    fig = go.Figure()
    fig.add_bar(x=win["timestamp"], y=win["heat_demand_kwh"], name="Heat demand (kWh)",
                marker_color="rgba(150,150,150,0.5)")
    fig.add_scatter(x=win["timestamp"], y=win["wh_used_kwh"], name="Waste heat", line=dict(color="#F39C12"))
    fig.add_scatter(x=win["timestamp"], y=win["h2_burn_kg"] * PlantParams().lhv_h2_mass,
                    name="H2 heat", line=dict(color="#2E86DE"))
    fig.add_scatter(x=win["timestamp"], y=win["cng_backup_kwh"], name="CNG backup", line=dict(color="#E74C3C"))
    fig.update_layout(height=320, yaxis_title="kWh_th/h", margin=dict(t=10, b=10),
                      legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, width="stretch")

    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Storage state of charge (kg H2)**")
        fig = go.Figure()
        fig.add_scatter(x=win["timestamp"], y=win["soc_kg"], fill="tozeroy", line=dict(color="#16A085"))
        fig.add_hline(y=s["storage_capacity_kg"], line_dash="dash", line_color="gray",
                      annotation_text="capacity")
        fig.update_layout(height=280, yaxis_title="kg", margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    with cc2:
        st.markdown("**H2 flows (kg/h)**")
        fig = go.Figure()
        fig.add_scatter(x=win["timestamp"], y=win["h2_prod_kg"], name="Produced", line=dict(color="#2E86DE"))
        fig.add_scatter(x=win["timestamp"], y=win["h2_to_store_kg"], name="To storage", line=dict(color="#16A085"))
        fig.add_scatter(x=win["timestamp"], y=win["h2_from_store_kg"], name="From storage", line=dict(color="#8E44AD"))
        fig.update_layout(height=280, yaxis_title="kg/h", margin=dict(t=10, b=10),
                          legend=dict(orientation="h", y=1.2))
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Full-year storage state of charge**")
    fig = go.Figure()
    fig.add_scatter(x=h["timestamp"], y=h["soc_kg"], line=dict(color="#16A085", width=1))
    fig.add_hline(y=s["storage_capacity_kg"], line_dash="dash", line_color="gray")
    fig.update_layout(height=260, yaxis_title="kg", margin=dict(t=10, b=10))
    st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- #
# Economics
# --------------------------------------------------------------------------- #
with tab_eco:
    e1, e2, e3 = st.columns(3)
    with e1:
        st.markdown("**CAPEX**")
        cx = pd.DataFrame({"Item": list(eco.capex_breakdown.keys()),
                           "EUR": list(eco.capex_breakdown.values())})
        st.dataframe(cx.style.format({"EUR": "{:,.0f}"}), hide_index=True, width="stretch")
        st.metric("Total CAPEX", eur(eco.total_capex))
    with e2:
        st.markdown("**Annual OPEX**")
        ox = pd.DataFrame({"Item": list(eco.opex_breakdown.keys()),
                           "EUR/yr": list(eco.opex_breakdown.values())})
        st.dataframe(ox.style.format({"EUR/yr": "{:,.0f}"}), hide_index=True, width="stretch")
        st.metric("Total OPEX", eur(eco.total_opex) + "/yr")
    with e3:
        st.markdown("**Annual savings**")
        sv = {k: v for k, v in eco.savings_breakdown.items() if not k.startswith("_")}
        sx = pd.DataFrame({"Item": list(sv.keys()), "EUR/yr": list(sv.values())})
        st.dataframe(sx.style.format({"EUR/yr": "{:,.0f}"}), hide_index=True, width="stretch")
        st.metric("Total savings", eur(eco.total_savings) + "/yr")

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Net annual result", eur(eco.net_annual) + "/yr")
    m2.metric("Simple payback",
              "n/a" if eco.simple_payback_years == float("inf") else f"{eco.simple_payback_years:.1f} yr")
    m3.metric("NPV", eur(eco.npv))
    m4.metric("IRR", "n/a" if eco.irr != eco.irr else f"{eco.irr*100:.1f}%")

    # waterfall of annual cash result
    st.markdown("**Annual result build-up**")
    contrib = [
        ("CNG avoided", eco.savings_breakdown["CNG fuel avoided"]),
        ("CO2 avoided", eco.savings_breakdown["CO2 tax avoided"]),
        ("Electricity", -(eco.opex_breakdown["Electricity - electrolyzer"] + eco.opex_breakdown["Electricity - compressor"])),
        ("Maintenance", -eco.opex_breakdown["Maintenance"]),
        ("Fixed OPEX", -eco.opex_breakdown["Fixed OPEX"]),
    ]
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["relative"] * len(contrib) + ["total"],
        x=[c[0] for c in contrib] + ["Net annual"],
        y=[c[1] for c in contrib] + [0],
        connector={"line": {"color": "rgb(180,180,180)"}},
        increasing={"marker": {"color": "#27AE60"}},
        decreasing={"marker": {"color": "#E74C3C"}},
        totals={"marker": {"color": "#2E86DE"}},
    ))
    fig.update_layout(height=360, yaxis_title="EUR/yr", margin=dict(t=10, b=10))
    st.plotly_chart(fig, width="stretch")

    # cumulative cashflow
    st.markdown("**Cumulative discounted cash flow**")
    years = list(range(len(eco.cashflows)))
    disc = [cf / (1 + discount_rate) ** t for t, cf in enumerate(eco.cashflows)]
    cum = np.cumsum(disc)
    fig = go.Figure()
    fig.add_bar(x=years, y=eco.cashflows, name="Cash flow", marker_color="rgba(46,134,222,0.5)")
    fig.add_scatter(x=years, y=cum, name="Cumulative (discounted)", line=dict(color="#2E86DE"))
    fig.add_hline(y=0, line_color="gray")
    fig.update_layout(height=320, xaxis_title="Year", yaxis_title="EUR", margin=dict(t=10, b=10),
                      legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- #
# Sizing & Optimization
# --------------------------------------------------------------------------- #
with tab_opt:
    st.subheader("Sweep electrolyzer size x operating hours")
    st.caption("Storage is auto-sized to peak demand for each configuration so sizes compare fairly.")
    oc1, oc2, oc3 = st.columns(3)
    mw_lo, mw_hi = oc1.slider("ELX size range (MW)", 0.25, 6.0, (0.5, 3.0), 0.25)
    mw_step = oc2.select_slider("MW step", options=[0.25, 0.5, 1.0], value=0.5)
    hrs = oc3.multiselect("Operating hours/day", list(range(2, 25, 2)), default=[6, 8, 10, 12])
    metric = st.radio("Objective", ["net_annual_eur", "npv_eur", "payback_yr", "coverage_%", "irr_%"],
                      horizontal=True)

    if st.button("Run sweep", type="primary"):
        sizes = list(np.round(np.arange(mw_lo, mw_hi + 1e-9, mw_step), 3))
        if not hrs:
            st.error("Pick at least one operating-hours value.")
        else:
            res = run_sweep(demand, params, sizes, sorted(hrs))
            st.session_state["sweep"] = res

    if "sweep" in st.session_state:
        res = st.session_state["sweep"]
        pivot = res.pivot(index="hours_per_day", columns="elx_mw", values=metric)
        fig = px.imshow(
            pivot, aspect="auto", origin="lower",
            labels=dict(x="ELX MW", y="Hours/day", color=metric),
            color_continuous_scale="RdYlGn" if metric not in ("payback_yr",) else "RdYlGn_r",
            text_auto=".0f",
        )
        fig.update_layout(height=380, margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")

        # best config
        valid = res.copy()
        if metric == "payback_yr":
            valid = valid[np.isfinite(valid[metric])]
            best = valid.loc[valid[metric].idxmin()] if len(valid) else None
        else:
            best = valid.loc[valid[metric].idxmax()] if len(valid) else None
        if best is not None:
            st.success(
                f"Best by {metric}: ELX {best['elx_mw']:.2f} MW, "
                f"{int(best['hours_per_day'])} h/day, storage {best['storage_kg']:,.0f} kg -> "
                f"coverage {best['coverage_%']:.0f}%, net {best['net_annual_eur']:,.0f} EUR/yr, "
                f"payback {best['payback_yr']:.1f} yr, NPV {best['npv_eur']:,.0f} EUR."
            )
        st.dataframe(
            res.style.format({
                "coverage_%": "{:.0f}", "storage_kg": "{:,.0f}", "curtailed_kg": "{:,.0f}",
                "elec_mwh": "{:,.0f}", "capex_eur": "{:,.0f}", "opex_eur": "{:,.0f}",
                "savings_eur": "{:,.0f}", "net_annual_eur": "{:,.0f}", "payback_yr": "{:.1f}",
                "npv_eur": "{:,.0f}", "irr_%": "{:.1f}",
            }),
            hide_index=True, width="stretch",
        )
        st.download_button("Download sweep CSV", res.to_csv(index=False), "sweep_results.csv", "text/csv")

# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
with tab_data:
    st.subheader("Demand profile")
    dd = demand.copy()
    dd["scaled_nm3"] = dd["cng_nm3"] * demand_scale
    d1, d2, d3 = st.columns(3)
    d1.metric("Annual CNG", f"{dd['scaled_nm3'].sum():,.0f} Nm3")
    d2.metric("Peak", f"{dd['scaled_nm3'].max():,.0f} Nm3/h")
    d3.metric("Average", f"{dd['scaled_nm3'].mean():,.1f} Nm3/h")

    dd["hour"] = dd["timestamp"].dt.hour
    prof = dd.groupby("hour")["scaled_nm3"].mean().reset_index()
    fig = px.bar(prof, x="hour", y="scaled_nm3", labels={"scaled_nm3": "Avg Nm3/h", "hour": "Hour of day"})
    fig.update_layout(height=300, margin=dict(t=10, b=10))
    st.plotly_chart(fig, width="stretch")

    # load duration curve
    sorted_d = np.sort(dd["scaled_nm3"].to_numpy())[::-1]
    fig = px.area(x=np.arange(len(sorted_d)), y=sorted_d,
                  labels={"x": "Hours (sorted)", "y": "Nm3/h"})
    fig.update_layout(height=280, margin=dict(t=10, b=10), title="Load duration curve")
    st.plotly_chart(fig, width="stretch")

    with st.expander("Raw hourly simulation output"):
        st.dataframe(h, hide_index=True, width="stretch", height=400)
        st.download_button("Download hourly CSV", h.to_csv(index=False), "hourly_simulation.csv", "text/csv")
