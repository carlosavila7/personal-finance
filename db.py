import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

_DDL = """
CREATE TABLE IF NOT EXISTS script_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at        TEXT NOT NULL,
    files_found   INTEGER NOT NULL DEFAULT 0,
    files_new     INTEGER NOT NULL DEFAULT 0,
    earliest_date TEXT,
    latest_date   TEXT,
    status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path    TEXT NOT NULL UNIQUE,
    file_date    TEXT,
    processed_at TEXT NOT NULL,
    run_id       INTEGER NOT NULL REFERENCES script_runs(id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id                     TEXT PRIMARY KEY,
    file_path              TEXT NOT NULL UNIQUE,
    date                   TEXT,
    time                   TEXT,
    category               TEXT,
    sub_category           TEXT,
    is_delivery            INTEGER,
    cost                   REAL,
    odometer_reading       REAL,
    full_fuel              INTEGER,
    fuel_price             REAL,
    origin                 TEXT,
    payment_type           TEXT,
    credit_card_statement  TEXT,
    is_recurrent           INTEGER,
    city                   TEXT,
    bought_at              TEXT,
    description            TEXT,
    person                 TEXT,
    grouping_tag           TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    db_path = os.environ.get("DB_PATH")
    if not db_path:
        raise ValueError("DB_PATH environment variable is not set")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for statement in _DDL.strip().split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)
    conn.commit()
    return conn
