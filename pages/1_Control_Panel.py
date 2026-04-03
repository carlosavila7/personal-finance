import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import db
import extractor

st.set_page_config(page_title="Control Panel", layout="wide")
st.title("Control Panel")

if st.button("Run Extraction", type="primary"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    def on_progress(current: int, total: int, message: str) -> None:
        pct = int((current / total) * 100) if total > 0 else 100
        progress_bar.progress(pct)
        status_text.text(f"[{current}/{total}] {message}")

    try:
        result = extractor.run_extraction(progress_callback=on_progress)
        progress_bar.progress(100)
        status_text.empty()
        st.success(
            f"Done — {result['files_new']} new file(s) processed out of "
            f"{result['files_found']} found. "
            f"Date range: {result['earliest_date'] or 'n/a'} → {result['latest_date'] or 'n/a'}"
        )
    except Exception as exc:
        status_text.empty()
        st.error(f"Extraction failed: {exc}")

st.divider()
st.subheader("Run History")

try:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT id, run_at, files_found, files_new, earliest_date, latest_date, status "
        "FROM script_runs ORDER BY run_at DESC LIMIT 50"
    ).fetchall()

    if rows:
        data = [dict(row) for row in rows]
        st.dataframe(data, use_container_width=True)
    else:
        st.info("No runs yet.")
except ValueError as exc:
    st.error(str(exc))
