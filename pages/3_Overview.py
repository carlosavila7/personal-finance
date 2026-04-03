import sys
from datetime import date
from pathlib import Path

import altair as alt
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import db

st.set_page_config(page_title="Overview", layout="wide")
st.title("Overview")

try:
    conn = db.get_connection()
except ValueError as exc:
    st.error(str(exc))
    st.stop()


def _distinct(col: str) -> list:
    rows = conn.execute(
        f"SELECT DISTINCT {col} FROM expenses WHERE {col} IS NOT NULL ORDER BY {col}"
    ).fetchall()
    return [r[0] for r in rows]


# Sidebar filters
with st.sidebar:
    st.header("Filters")

    year_rows = conn.execute(
        "SELECT DISTINCT strftime('%Y', date) AS yr FROM expenses "
        "WHERE date IS NOT NULL ORDER BY yr DESC"
    ).fetchall()
    year_options = [r[0] for r in year_rows] or [str(date.today().year)]
    selected_year = st.selectbox("Year", options=year_options, index=0)

    persons = st.multiselect("Person", options=_distinct("person"))
    st.caption("Leave blank to include all persons.")

# WHERE clause
clauses = ["strftime('%Y', date) = ?"]
params: list = [selected_year]

if persons:
    ph = ",".join("?" * len(persons))
    clauses.append(f"person IN ({ph})")
    params.extend(persons)

where = " AND ".join(clauses)

# Query 1a — scalar KPIs
kpi = dict(conn.execute(
    f"SELECT COALESCE(SUM(cost), 0) AS total_spend, "
    f"COUNT(*) AS num_expenses, "
    f"COUNT(DISTINCT strftime('%m', date)) AS months_with_data "
    f"FROM expenses WHERE {where}",
    params,
).fetchone())

total_spend = kpi["total_spend"]
num_expenses = kpi["num_expenses"]
months_with_data = kpi["months_with_data"]
avg_per_month = total_spend / months_with_data if months_with_data > 0 else 0.0

# Query 1b — top category
top_cat_row = conn.execute(
    f"SELECT category, SUM(cost) AS cat_total FROM expenses "
    f"WHERE {where} AND category IS NOT NULL "
    f"GROUP BY category ORDER BY cat_total DESC LIMIT 1",
    params,
).fetchone()
top_category = top_cat_row["category"] if top_cat_row else "N/A"

# KPI row
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Spend", f"R$ {total_spend:,.2f}")
col2.metric("# Expenses", num_expenses)
col3.metric("Avg / Month", f"R$ {avg_per_month:,.2f}")
col4.metric("Top Category", top_category)

st.divider()

# Query 2 — monthly spend
monthly_rows = conn.execute(
    f"SELECT strftime('%Y-%m', date) AS month, SUM(cost) AS total_cost "
    f"FROM expenses WHERE {where} AND cost IS NOT NULL "
    f"GROUP BY month ORDER BY month",
    params,
).fetchall()

st.subheader("Monthly Spend")
if not monthly_rows:
    st.info("No spend data for the selected period.")
else:
    df_monthly = [dict(r) for r in monthly_rows]
    chart = (
        alt.Chart(alt.Data(values=df_monthly))
        .mark_bar()
        .encode(
            x=alt.X("month:O", title="Month", sort=None),
            y=alt.Y("total_cost:Q", title="Total Spend"),
            tooltip=["month:O", "total_cost:Q"],
        )
    )
    st.altair_chart(chart, use_container_width=True)

st.divider()

col_left, col_right = st.columns(2)

# Query 3 — spend by category
with col_left:
    st.subheader("Spend by Category")
    cat_rows = conn.execute(
        f"SELECT category, SUM(cost) AS total_cost FROM expenses "
        f"WHERE {where} AND cost IS NOT NULL AND category IS NOT NULL "
        f"GROUP BY category ORDER BY total_cost DESC",
        params,
    ).fetchall()

    if not cat_rows:
        st.info("No category data.")
    else:
        df_cat = [dict(r) for r in cat_rows]
        chart = (
            alt.Chart(alt.Data(values=df_cat))
            .mark_bar()
            .encode(
                x=alt.X("total_cost:Q", title="Total Spend"),
                y=alt.Y("category:N", sort="-x", title="Category"),
                tooltip=["category:N", "total_cost:Q"],
            )
        )
        st.altair_chart(chart, use_container_width=True)

# Query 4 — payment type distribution
with col_right:
    st.subheader("Payment Type")
    pay_rows = conn.execute(
        f"SELECT COALESCE(payment_type, 'unknown') AS payment_type, "
        f"COUNT(*) AS num_expenses, SUM(cost) AS total_cost "
        f"FROM expenses WHERE {where} "
        f"GROUP BY payment_type ORDER BY total_cost DESC",
        params,
    ).fetchall()

    if not pay_rows:
        st.info("No payment data.")
    else:
        df_pay = [dict(r) for r in pay_rows]
        chart = (
            alt.Chart(alt.Data(values=df_pay))
            .mark_bar()
            .encode(
                x=alt.X("payment_type:N", title="Payment Type", sort="-y"),
                y=alt.Y("total_cost:Q", title="Total Spend"),
                color=alt.Color("payment_type:N", legend=None),
                tooltip=["payment_type:N", "num_expenses:Q", "total_cost:Q"],
            )
        )
        st.altair_chart(chart, use_container_width=True)
