import sys
from pathlib import Path

import altair as alt
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import db

st.set_page_config(page_title="Fuel Tracker", layout="wide")
st.title("Fuel & Vehicle Tracker")

try:
    conn = db.get_connection()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

# Sidebar filters
with st.sidebar:
    st.header("Filters")
    date_start = st.date_input("Date from", value=None)
    date_end = st.date_input("Date to", value=None)

# WHERE clause — base condition always restricts to vehicle-related rows
clauses = ["(odometer_reading IS NOT NULL OR (fuel_price IS NOT NULL AND fuel_price > 0))"]
params: list = []

if date_start:
    clauses.append("date >= ?")
    params.append(str(date_start))
if date_end:
    clauses.append("date <= ?")
    params.append(str(date_end))

where = " AND ".join(clauses)

# Query 1 — KPI aggregates
kpi = dict(conn.execute(
    f"SELECT COALESCE(SUM(cost), 0) AS total_fuel_spend, "
    f"COUNT(*) AS num_entries, "
    f"SUM(CASE WHEN full_fuel = 1 THEN 1 ELSE 0 END) AS full_tank_count, "
    f"COALESCE(AVG(CASE WHEN fuel_price IS NOT NULL AND fuel_price > 0 THEN fuel_price END), 0) AS avg_fuel_price "
    f"FROM expenses WHERE {where}",
    params,
).fetchone())

num_entries = kpi["num_entries"]
full_tank_pct = kpi["full_tank_count"] / num_entries * 100 if num_entries > 0 else 0.0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Fuel Spend", f"R$ {kpi['total_fuel_spend']:,.2f}")
col2.metric("Fill-ups / Entries", num_entries)
col3.metric("Full Tank %", f"{full_tank_pct:.1f}%")
col4.metric("Avg Fuel Price", f"R$ {kpi['avg_fuel_price']:.3f}")

st.divider()

col_left, col_right = st.columns(2)

# Query 2 — fuel price over time
with col_left:
    st.subheader("Fuel Price Over Time")
    price_rows = conn.execute(
        f"SELECT date, fuel_price FROM expenses "
        f"WHERE {where} AND fuel_price IS NOT NULL AND fuel_price > 0 "
        f"ORDER BY date",
        params,
    ).fetchall()

    if not price_rows:
        st.info("No fuel price data available.")
    else:
        df = [dict(r) for r in price_rows]
        chart = (
            alt.Chart(alt.Data(values=df))
            .mark_line(point=True)
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("fuel_price:Q", title="Fuel Price", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("date:T", format="%Y-%m-%d"), "fuel_price:Q"],
            )
        )
        st.altair_chart(chart, use_container_width=True)

# Query 3 — monthly fuel spend
with col_right:
    st.subheader("Monthly Fuel Spend")
    monthly_rows = conn.execute(
        f"SELECT strftime('%Y-%m', date) AS month, SUM(cost) AS total_cost "
        f"FROM expenses WHERE {where} AND cost IS NOT NULL "
        f"GROUP BY month ORDER BY month",
        params,
    ).fetchall()

    if not monthly_rows:
        st.info("No monthly data.")
    else:
        df = [dict(r) for r in monthly_rows]
        chart = (
            alt.Chart(alt.Data(values=df))
            .mark_bar()
            .encode(
                x=alt.X("month:O", title="Month", sort=None),
                y=alt.Y("total_cost:Q", title="Total Fuel Spend"),
                tooltip=["month:O", "total_cost:Q"],
            )
        )
        st.altair_chart(chart, use_container_width=True)

st.divider()

# Query 4 — fuel log with km calculation
st.subheader("Fuel Log")
log_rows = conn.execute(
    f"SELECT date, bought_at, cost, fuel_price, full_fuel, odometer_reading "
    f"FROM expenses WHERE {where} ORDER BY date ASC, time ASC",
    params,
).fetchall()

if not log_rows:
    st.info("No vehicle records for the selected period.")
else:
    prev_odo = None
    rows = []
    for raw in log_rows:
        row = dict(raw)
        row["full_fuel"] = bool(row["full_fuel"]) if row.get("full_fuel") is not None else None
        odo = row["odometer_reading"]
        row["km_since_last"] = round(odo - prev_odo, 1) if (odo is not None and prev_odo is not None) else None
        if odo is not None:
            prev_odo = odo
        rows.append(row)

    st.dataframe(
        rows,
        use_container_width=True,
        column_config={
            "full_fuel": st.column_config.CheckboxColumn("Full Tank"),
            "km_since_last": st.column_config.NumberColumn("km Since Last", format="%.1f"),
            "fuel_price": st.column_config.NumberColumn("Fuel Price", format="%.3f"),
            "cost": st.column_config.NumberColumn("Cost", format="%.2f"),
        },
    )
