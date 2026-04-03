import sys
from datetime import date, time as time_type
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import db

PAGE_SIZE = 50

st.set_page_config(page_title="Expenses Dashboard", layout="wide")
st.title("Expenses Dashboard")

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

    categories = st.multiselect("Category", options=_distinct("category"))

    if categories:
        placeholders = ",".join("?" * len(categories))
        sub_options = [
            r[0] for r in conn.execute(
                f"SELECT DISTINCT sub_category FROM expenses "
                f"WHERE category IN ({placeholders}) AND sub_category IS NOT NULL "
                f"ORDER BY sub_category",
                categories,
            ).fetchall()
        ]
        sub_categories = st.multiselect("Sub-category", options=sub_options)
    else:
        st.multiselect("Sub-category", options=[], disabled=True)
        sub_categories = []

    cities = st.multiselect("City", options=_distinct("city"))
    persons = st.multiselect("Person", options=_distinct("person"))

# Build parameterized query
clauses = ["1=1"]
params: list = []

if date_start:
    clauses.append("date >= ?")
    params.append(str(date_start))
if date_end:
    clauses.append("date <= ?")
    params.append(str(date_end))
if categories:
    placeholders = ",".join("?" * len(categories))
    clauses.append(f"category IN ({placeholders})")
    params.extend(categories)
if sub_categories:
    placeholders = ",".join("?" * len(sub_categories))
    clauses.append(f"sub_category IN ({placeholders})")
    params.extend(sub_categories)
if cities:
    placeholders = ",".join("?" * len(cities))
    clauses.append(f"city IN ({placeholders})")
    params.extend(cities)
if persons:
    placeholders = ",".join("?" * len(persons))
    clauses.append(f"person IN ({placeholders})")
    params.extend(persons)

where = " AND ".join(clauses)

total_rows = conn.execute(f"SELECT COUNT(*) FROM expenses WHERE {where}", params).fetchone()[0]

st.write(f"**{total_rows}** expense(s) found")

if total_rows == 0:
    st.info("No expenses match the current filters.")
    st.stop()

max_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
page = st.number_input("Page", min_value=1, max_value=max_pages, value=1, step=1)
offset = (page - 1) * PAGE_SIZE

rows = conn.execute(
    f"SELECT id, date, time, category, sub_category, cost, city, bought_at, "
    f"payment_type, origin, person, is_delivery, is_recurrent, "
    f"credit_card_statement, full_fuel, fuel_price, odometer_reading, description, grouping_tag "
    f"FROM expenses WHERE {where} ORDER BY date DESC, time DESC LIMIT ? OFFSET ?",
    params + [PAGE_SIZE, offset],
).fetchall()

def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_time(value: str | None) -> time_type | None:
    try:
        return time_type.fromisoformat(value) if value else None
    except ValueError:
        return None


data = []
for row in rows:
    r = dict(row)
    r["date"] = _parse_date(r.get("date"))
    r["time"] = _parse_time(r.get("time"))
    r["is_delivery"] = bool(r["is_delivery"]) if r.get("is_delivery") is not None else None
    r["is_recurrent"] = bool(r["is_recurrent"]) if r.get("is_recurrent") is not None else None
    r["full_fuel"] = bool(r["full_fuel"]) if r.get("full_fuel") is not None else None
    data.append(r)

st.dataframe(
    data,
    use_container_width=True,
    column_config={
        "date": st.column_config.DateColumn("date"),
        "time": st.column_config.TimeColumn("time"),
        "is_delivery": st.column_config.CheckboxColumn("is_delivery"),
        "is_recurrent": st.column_config.CheckboxColumn("is_recurrent"),
        "full_fuel": st.column_config.CheckboxColumn("full_fuel"),
    },
)
st.caption(f"Page {page} of {max_pages}")
