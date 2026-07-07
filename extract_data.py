"""
One-off extractor: reads the ZF paint-line gas consumption workbook and writes a
clean hourly demand profile to data/demand_hourly.csv used by the Streamlit app.

Run again if the source Excel changes:
    python extract_data.py
"""
from pathlib import Path
import pandas as pd

SRC = Path(
    r"c:\Users\User\OneDrive\Work\Hydrogenera\Sales\Projects\Companies\ZF"
    r"\New Data\Paint Drying Lines Passau Gas Consumption V3.xlsx"
)
OUT = Path(__file__).parent / "data" / "demand_hourly.csv"


def main() -> None:
    df = pd.read_excel(SRC, sheet_name="Gas Consumption 2023", header=0)

    ts = pd.to_datetime(df["Start Time"])
    line2 = pd.to_numeric(df.iloc[:, 2], errors="coerce").fillna(0.0)   # Line 2
    line13 = pd.to_numeric(df.iloc[:, 7], errors="coerce").fillna(0.0)  # Line 1/3
    line4 = pd.to_numeric(df.iloc[:, 8], errors="coerce").fillna(0.0)   # Line 4

    out = pd.DataFrame(
        {
            "timestamp": ts,
            "line2_nm3": line2,
            "line13_nm3": line13,
            "line4_nm3": line4,
            "cng_nm3": line2 + line13 + line4,  # total hourly CNG demand [Nm3/h]
        }
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    total = out["cng_nm3"].sum()
    print(f"Wrote {len(out)} hourly rows -> {OUT}")
    print(f"Annual CNG: {total:,.0f} Nm3  ({total * 9.97 / 1e6:.3f} GWh_th @ LHV 9.97)")
    print(f"Peak: {out['cng_nm3'].max():.0f} Nm3/h   Avg: {out['cng_nm3'].mean():.1f} Nm3/h")


if __name__ == "__main__":
    main()
