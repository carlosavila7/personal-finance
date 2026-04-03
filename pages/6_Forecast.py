import statistics
import sys
from datetime import date
from pathlib import Path

import altair as alt
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import db

st.set_page_config(page_title="Spending Forecast", layout="wide")
st.title("Spending Forecast")

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


def _month_str_ago(n_months: int) -> str:
    today = date.today()
    total = today.year * 12 + (today.month - 1) - n_months
    y, m = divmod(total, 12)
    return f"{y:04d}-{m + 1:02d}"


def _next_month_strs(n: int) -> list:
    today = date.today()
    total = today.year * 12 + today.month
    results = []
    for i in range(1, n + 1):
        t = total + i
        y, m = divmod(t - 1, 12)
        results.append(f"{y:04d}-{m + 1:02d}")
    return results


def _group_avg(rows, dim_key: str) -> list:
    """Group sqlite rows by dim_key, compute mean monthly spend per group."""
    groups: dict[str, list] = {}
    for r in rows:
        d = dict(r)
        key = d[dim_key]
        groups.setdefault(key, []).append(d["total_cost"])
    result = []
    for key, totals in groups.items():
        avg = statistics.mean(totals) if totals else 0.0
        result.append({"label": key, "avg_monthly": avg})
    result.sort(key=lambda x: x["avg_monthly"], reverse=True)
    return result


# Sidebar
with st.sidebar:
    st.header("Filters")

    selected_lookback = st.selectbox(
        "Look-back period", ["3 months", "6 months", "12 months", "All time"]
    )
    selected_horizon = st.selectbox(
        "Forecast horizon", ["1 month", "3 months", "6 months", "12 months"]
    )
    horizon_n = {"1 month": 1, "3 months": 3, "6 months": 6, "12 months": 12}[selected_horizon]

    st.divider()

    selected_origins = st.multiselect("Origin", options=_distinct("origin"))
    selected_payment_types = st.multiselect("Payment Type", options=_distinct("payment_type"))
    st.caption("Leave blank to include all.")

    st.divider()

    exclude_extraordinary = st.toggle("Exclude extraordinary expenses", value=False)

# Base WHERE clause (origin, payment_type, extraordinary)
clauses = ["1=1"]
params: list = []

if exclude_extraordinary:
    clauses.append("(grouping_tag IS NULL OR grouping_tag = '')")
if selected_origins:
    ph = ",".join("?" * len(selected_origins))
    clauses.append(f"origin IN ({ph})")
    params.extend(selected_origins)
if selected_payment_types:
    ph = ",".join("?" * len(selected_payment_types))
    clauses.append(f"payment_type IN ({ph})")
    params.extend(selected_payment_types)

# Lookback-aware WHERE clause (copied from base, not mutated)
lookback_map = {"3 months": 3, "6 months": 6, "12 months": 12}
if selected_lookback == "All time":
    lookback_month = None
else:
    lookback_month = _month_str_ago(lookback_map[selected_lookback])

hist_clauses = list(clauses)
hist_params = list(params)
if lookback_month is not None:
    hist_clauses.append("strftime('%Y-%m', date) >= ?")
    hist_params.append(lookback_month)
hist_where = " AND ".join(hist_clauses)

# Query A — historical monthly totals
monthly_rows = conn.execute(
    f"SELECT strftime('%Y-%m', date) AS month, SUM(cost) AS total_cost "
    f"FROM expenses WHERE {hist_where} AND cost IS NOT NULL "
    f"GROUP BY month ORDER BY month",
    hist_params,
).fetchall()

monthly_totals = [r["total_cost"] for r in monthly_rows]

if len(monthly_totals) == 0:
    st.warning("Not enough historical data to generate a forecast. Adjust the look-back period or filters.")
    st.stop()

single_month_warning = len(monthly_totals) == 1
mean_monthly = statistics.mean(monthly_totals)
stdev_monthly = statistics.stdev(monthly_totals) if not single_month_warning else 0.0
optimistic = max(0.0, mean_monthly - stdev_monthly)
pessimistic = mean_monthly + stdev_monthly

# KPI row
st.subheader("Forecast at a Glance")
if single_month_warning:
    st.info("Only 1 month of data — confidence range unavailable. Optimistic and Pessimistic equal the historical average.")

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Historical Avg / Month", f"R$ {mean_monthly:,.2f}")
kpi2.metric(
    "Optimistic / month",
    f"R$ {optimistic:,.2f}",
    delta=f"R$ {optimistic - mean_monthly:,.2f} vs expected",
    delta_color="off",
)
kpi3.metric("Expected / month", f"R$ {mean_monthly:,.2f}")
kpi4.metric(
    "Pessimistic / month",
    f"R$ {pessimistic:,.2f}",
    delta=f"R$ {pessimistic - mean_monthly:,.2f} vs expected",
    delta_color="off",
)

st.divider()

# Combined historical + forecast bar chart
st.subheader("Historical Spend + Forecast")

chart_data = []
for r in monthly_rows:
    chart_data.append({"month": r["month"], "total_cost": r["total_cost"], "type": "Historical"})
for m in _next_month_strs(horizon_n):
    chart_data.append({"month": m, "total_cost": mean_monthly, "type": "Forecast"})

bars = (
    alt.Chart(alt.Data(values=chart_data))
    .mark_bar()
    .encode(
        x=alt.X("month:O", title="Month", sort=None),
        y=alt.Y("total_cost:Q", title="Spend (R$)"),
        color=alt.Color(
            "type:N",
            scale=alt.Scale(domain=["Historical", "Forecast"], range=["steelblue", "orange"]),
            title="Type",
        ),
        tooltip=[
            alt.Tooltip("month:O", title="Month"),
            alt.Tooltip("total_cost:Q", title="Amount (R$)", format=",.2f"),
            alt.Tooltip("type:N", title="Type"),
        ],
    )
)

rule = (
    alt.Chart(alt.Data(values=[{"mean": mean_monthly}]))
    .mark_rule(strokeDash=[4, 4], color="gray", strokeWidth=1.5)
    .encode(
        y=alt.Y("mean:Q"),
        tooltip=[alt.Tooltip("mean:Q", title="Avg (R$)", format=",.2f")],
    )
)

st.altair_chart(alt.layer(bars, rule).properties(height=350), use_container_width=True)

st.divider()

# Tabs: breakdown by category / by origin+payment type
tab_cat, tab_origin = st.tabs(["By Category", "By Origin / Payment Type"])

with tab_cat:
    cat_rows = conn.execute(
        f"SELECT COALESCE(category, 'uncategorised') AS category, "
        f"strftime('%Y-%m', date) AS month, SUM(cost) AS total_cost "
        f"FROM expenses WHERE {hist_where} AND cost IS NOT NULL "
        f"GROUP BY category, month",
        hist_params,
    ).fetchall()

    cat_avgs = _group_avg(cat_rows, "category")

    if not cat_avgs:
        st.info("No category data for the selected period.")
    else:
        chart = (
            alt.Chart(alt.Data(values=cat_avgs))
            .mark_bar()
            .encode(
                x=alt.X("avg_monthly:Q", title="Avg / Month (R$)"),
                y=alt.Y("label:N", sort="-x", title="Category"),
                tooltip=[
                    alt.Tooltip("label:N", title="Category"),
                    alt.Tooltip("avg_monthly:Q", title="Avg/Month (R$)", format=",.2f"),
                ],
            )
        )
        st.altair_chart(chart, use_container_width=True)

        horizon_label = f"Projected ({selected_horizon})"
        table_data = [
            {
                "Category": row["label"],
                "Avg / Month": f"R$ {row['avg_monthly']:,.2f}",
                horizon_label: f"R$ {row['avg_monthly'] * horizon_n:,.2f}",
            }
            for row in cat_avgs
        ]
        st.dataframe(table_data, use_container_width=True, hide_index=True)

with tab_origin:
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("By Origin")
        origin_rows = conn.execute(
            f"SELECT COALESCE(origin, 'unknown') AS origin, "
            f"strftime('%Y-%m', date) AS month, SUM(cost) AS total_cost "
            f"FROM expenses WHERE {hist_where} AND cost IS NOT NULL "
            f"GROUP BY origin, month",
            hist_params,
        ).fetchall()

        origin_avgs = _group_avg(origin_rows, "origin")

        if not origin_avgs:
            st.info("No origin data.")
        else:
            chart = (
                alt.Chart(alt.Data(values=origin_avgs))
                .mark_bar()
                .encode(
                    x=alt.X("avg_monthly:Q", title="Avg / Month (R$)"),
                    y=alt.Y("label:N", sort="-x", title="Origin"),
                    tooltip=[
                        alt.Tooltip("label:N", title="Origin"),
                        alt.Tooltip("avg_monthly:Q", title="Avg/Month (R$)", format=",.2f"),
                    ],
                )
            )
            st.altair_chart(chart, use_container_width=True)

    with col_right:
        st.subheader("By Payment Type")
        pay_rows = conn.execute(
            f"SELECT COALESCE(payment_type, 'unknown') AS payment_type, "
            f"strftime('%Y-%m', date) AS month, SUM(cost) AS total_cost "
            f"FROM expenses WHERE {hist_where} AND cost IS NOT NULL "
            f"GROUP BY payment_type, month",
            hist_params,
        ).fetchall()

        pay_avgs = _group_avg(pay_rows, "payment_type")

        if not pay_avgs:
            st.info("No payment type data.")
        else:
            chart = (
                alt.Chart(alt.Data(values=pay_avgs))
                .mark_bar()
                .encode(
                    x=alt.X("avg_monthly:Q", title="Avg / Month (R$)"),
                    y=alt.Y("label:N", sort="-x", title="Payment Type"),
                    tooltip=[
                        alt.Tooltip("label:N", title="Payment Type"),
                        alt.Tooltip("avg_monthly:Q", title="Avg/Month (R$)", format=",.2f"),
                    ],
                )
            )
            st.altair_chart(chart, use_container_width=True)
