import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

import db

load_dotenv()

_KEY_MAP = {
    "sub-category": "sub_category",
    "is-delivery": "is_delivery",
    "odometer-reading": "odometer_reading",
    "full-fuel": "full_fuel",
    "fuel-price": "fuel_price",
    "payment-type": "payment_type",
    "credit-card-statement": "credit_card_statement",
    "is-recurrent": "is_recurrent",
    "bought-at": "bought_at",
    "grouping-tag": "grouping_tag",
}

_BOOL_COLS = {"is_delivery", "full_fuel", "is_recurrent"}
_FLOAT_COLS = {"cost", "odometer_reading", "fuel_price"}

_EXPENSE_COLS = (
    "id", "file_path", "date", "time", "category", "sub_category", "is_delivery",
    "cost", "odometer_reading", "full_fuel", "fuel_price", "origin",
    "payment_type", "credit_card_statement", "is_recurrent", "city",
    "bought_at", "description", "person", "grouping_tag",
)


def _parse_frontmatter(file_path: Path) -> dict | None:
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None


def _coerce_row(fm: dict, file_path: str) -> dict:
    row = {"id": Path(file_path).stem, "file_path": file_path}
    for raw_key, value in fm.items():
        col = _KEY_MAP.get(raw_key, raw_key)
        if col not in _EXPENSE_COLS:
            continue
        # Normalize empty / None
        if value == "" or value is None:
            row[col] = None
            continue
        if col in _BOOL_COLS:
            row[col] = 1 if value else 0
        elif col in _FLOAT_COLS:
            try:
                row[col] = float(value)
            except (TypeError, ValueError):
                row[col] = None
        elif col == "date":
            row[col] = str(value)
        elif col == "time":
            # PyYAML parses unquoted HH:MM as a sexagesimal integer (e.g. 17:21 → 1041)
            if isinstance(value, int):
                row[col] = f"{value // 60:02d}:{value % 60:02d}"
            else:
                row[col] = str(value)
        else:
            row[col] = str(value) if not isinstance(value, str) else value

    # Validation: credit_card_statement only applies to credit payments
    if row.get("payment_type", "").lower() != "credit":
        row["credit_card_statement"] = None

    return row


def _insert_expense(conn, row: dict) -> None:
    cols = [c for c in _EXPENSE_COLS if c in row]
    placeholders = ", ".join("?" * len(cols))
    col_names = ", ".join(cols)
    values = [row[c] for c in cols]
    conn.execute(
        f"INSERT OR IGNORE INTO expenses ({col_names}) VALUES ({placeholders})",
        values,
    )


def run_extraction(progress_callback=None) -> dict:
    expenses_dir = os.environ.get("EXPENSES_DIR")
    if not expenses_dir:
        raise ValueError("EXPENSES_DIR environment variable is not set")
    expenses_path = Path(expenses_dir)
    if not expenses_path.is_dir():
        raise ValueError(f"EXPENSES_DIR does not exist or is not a directory: {expenses_dir}")

    all_files = sorted(expenses_path.rglob("*.md"))
    files_found = len(all_files)

    conn = db.get_connection()

    already_processed = {
        row[0] for row in conn.execute("SELECT file_path FROM processed_files")
    }

    new_files = [f for f in all_files if str(f) not in already_processed]

    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO script_runs (run_at, files_found, files_new, status) VALUES (?, ?, ?, ?)",
        (now, files_found, len(new_files), "running"),
    )
    run_id = cursor.lastrowid
    conn.commit()

    dates_processed = []
    try:
        total = len(new_files)
        for i, file_path in enumerate(new_files):
            if progress_callback:
                progress_callback(i, total, file_path.name)

            fm = _parse_frontmatter(file_path)
            if fm is None:
                continue

            row = _coerce_row(fm, str(file_path))
            _insert_expense(conn, row)

            file_date = row.get("date")
            if file_date:
                dates_processed.append(file_date)

            processed_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO processed_files (file_path, file_date, processed_at, run_id) VALUES (?, ?, ?, ?)",
                (str(file_path), file_date, processed_at, run_id),
            )

        if progress_callback and total > 0:
            progress_callback(total, total, "Done")

        earliest_date = min(dates_processed) if dates_processed else None
        latest_date = max(dates_processed) if dates_processed else None

        conn.execute(
            "UPDATE script_runs SET files_found=?, files_new=?, earliest_date=?, latest_date=?, status=? WHERE id=?",
            (files_found, len(new_files), earliest_date, latest_date, "success", run_id),
        )
        conn.commit()

        return {
            "files_found": files_found,
            "files_new": len(new_files),
            "earliest_date": earliest_date,
            "latest_date": latest_date,
            "status": "success",
        }

    except Exception as exc:
        conn.execute(
            "UPDATE script_runs SET files_found=?, files_new=?, status=? WHERE id=?",
            (files_found, len(new_files), "error", run_id),
        )
        conn.commit()
        raise exc
