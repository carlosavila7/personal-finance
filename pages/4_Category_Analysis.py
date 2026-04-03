import sys
from pathlib import Path

import altair as alt
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import db

st.set_page_config(page_title="Category Analysis", layout="wide")
st.title("Category Analysis")

exclude_extraordinary = st.toggle("Exclude extraordinary expenses", value=False)

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

    date_start = st.date_input("Date from", value=None)
    date_end = st.date_input("Date to", value=None)
    persons = st.multiselect("Person", options=_distinct("person"))
    st.caption("Leave blank to include all persons.")
    st.divider()
    category_options = _distinct("category")
    selected_category = st.selectbox(
        "Category (drill-down)", options=["(all)"] + category_options
    )

# Shared WHERE clause
clauses = ["1=1"]
if exclude_extraordinary:
    clauses.append("(grouping_tag IS NULL OR grouping_tag = '')")
params: list = []

if date_start:
    clauses.append("date >= ?")
    params.append(str(date_start))
if date_end:
    clauses.append("date <= ?")
    params.append(str(date_end))
if persons:
    ph = ",".join("?" * len(persons))
    clauses.append(f"person IN ({ph})")
    params.extend(persons)

where = " AND ".join(clauses)

# Query 1 — stacked monthly by category
st.subheader("Monthly Spend by Category")
monthly_cat_rows = conn.execute(
    f"SELECT strftime('%Y-%m', date) AS month, "
    f"COALESCE(category, 'uncategorised') AS category, "
    f"SUM(cost) AS total_cost "
    f"FROM expenses WHERE {where} AND cost IS NOT NULL "
    f"GROUP BY month, category ORDER BY month, category",
    params,
).fetchall()

if not monthly_cat_rows:
    st.info("No data for the selected period.")
else:
    df = [dict(r) for r in monthly_cat_rows]
    chart = (
        alt.Chart(alt.Data(values=df))
        .mark_bar()
        .encode(
            x=alt.X("month:O", title="Month", sort=None),
            y=alt.Y("total_cost:Q", title="Total Spend"),
            color=alt.Color("category:N", title="Category"),
            tooltip=["month:O", "category:N", "total_cost:Q"],
        )
    )
    st.altair_chart(chart, use_container_width=True)

st.divider()

col_left, col_right = st.columns(2)

# Query 2 — sub-category breakdown
with col_left:
    label = f"Sub-categories — {selected_category}" if selected_category != "(all)" else "Sub-categories — all"
    st.subheader(label)

    sub_clauses = list(clauses)
    sub_params = list(params)
    if selected_category != "(all)":
        sub_clauses.append("category = ?")
        sub_params.append(selected_category)
    sub_where = " AND ".join(sub_clauses)

    sub_rows = conn.execute(
        f"SELECT COALESCE(sub_category, 'none') AS sub_category, SUM(cost) AS total_cost "
        f"FROM expenses WHERE {sub_where} AND cost IS NOT NULL "
        f"GROUP BY sub_category ORDER BY total_cost DESC",
        sub_params,
    ).fetchall()

    if not sub_rows:
        st.info("No sub-category data.")
    else:
        df = [dict(r) for r in sub_rows]
        chart = (
            alt.Chart(alt.Data(values=df))
            .mark_bar()
            .encode(
                x=alt.X("total_cost:Q", title="Total Spend"),
                y=alt.Y("sub_category:N", sort="-x", title="Sub-category"),
                tooltip=["sub_category:N", "total_cost:Q"],
            )
        )
        st.altair_chart(chart, use_container_width=True)

# Query 3 — top 10 merchants
with col_right:
    st.subheader("Top 10 Merchants")
    merchant_rows = conn.execute(
        f"SELECT COALESCE(bought_at, 'unknown') AS bought_at, "
        f"SUM(cost) AS total_cost, COUNT(*) AS num_visits "
        f"FROM expenses WHERE {where} AND cost IS NOT NULL "
        f"GROUP BY bought_at ORDER BY total_cost DESC LIMIT 10",
        params,
    ).fetchall()

    if not merchant_rows:
        st.info("No merchant data.")
    else:
        df = [dict(r) for r in merchant_rows]
        chart = (
            alt.Chart(alt.Data(values=df))
            .mark_bar()
            .encode(
                x=alt.X("total_cost:Q", title="Total Spend"),
                y=alt.Y("bought_at:N", sort="-x", title="Merchant"),
                tooltip=["bought_at:N", "total_cost:Q", "num_visits:Q"],
            )
        )
        st.altair_chart(chart, use_container_width=True)

st.divider()

# Query 4 — recurrent vs one-off
st.subheader("Recurrent vs One-off")
recurrent_rows = conn.execute(
    f"SELECT is_recurrent, COUNT(*) AS num_expenses, SUM(cost) AS total_cost "
    f"FROM expenses WHERE {where} AND cost IS NOT NULL "
    f"GROUP BY is_recurrent",
    params,
).fetchall()

if not recurrent_rows:
    st.info("No data.")
else:
    lookup = {r["is_recurrent"]: dict(r) for r in recurrent_rows}
    recurrent = lookup.get(1, {"num_expenses": 0, "total_cost": 0.0})
    one_off = lookup.get(0, {"num_expenses": 0, "total_cost": 0.0})
    grand_total = recurrent["total_cost"] + one_off["total_cost"]
    recurrent_pct = recurrent["total_cost"] / grand_total * 100 if grand_total > 0 else 0.0
    one_off_pct = 100.0 - recurrent_pct

    col1, col2 = st.columns(2)
    col1.metric(
        "Recurrent Spend",
        f"R$ {recurrent['total_cost']:,.2f}",
        delta=f"{recurrent_pct:.1f}% of total",
        delta_color="off",
    )
    col2.metric(
        "One-off Spend",
        f"R$ {one_off['total_cost']:,.2f}",
        delta=f"{one_off_pct:.1f}% of total",
        delta_color="off",
    )
