"""
Export Oracle views into a local SQLite database.

Usage:
    python scripts/export_views_to_sqlite.py \
        --sqlite-path data/oracle_views.db

Connections rely on environment variables expected by the project
(.env should already be loaded when running via the existing tooling).
"""

from __future__ import annotations

import argparse
import pathlib
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Tuple

import oracledb  # type: ignore
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.oracle.base import ischema_names
from sqlalchemy.types import Date


VIEWS = [
    "VW_OPERATIONS_REPORT",
    "VW_ATTENDEE_REPORT",
    "VW_OPP_TRACKING_REPORT",
]

# Map Oracle CLOUD_DATE UDT to SQLAlchemy Date so reflection works
ischema_names.setdefault("CLOUD_DATE", Date)


def normalize_value(value: Any) -> Any:
    """Convert Oracle-specific values into types SQLite can store."""
    if isinstance(value, oracledb.DbObject):
        zonedate = getattr(value, "ZONEDATE", None)
        zonetime = getattr(value, "ZONETIME", None)
        zoneid = getattr(value, "ZONEID", None)
        if zonedate:
            base = zonedate.isoformat()
            if zonetime:
                base = f"{base}T{zonetime}"
            if zoneid:
                return f"{base} [{zoneid}]"
            return base
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return int(value)
    return value


def infer_sqlite_type(values: Iterable[Any]) -> str:
    """Infer a SQLite column type from the provided values."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        if isinstance(value, (bytes, bytearray)):
            return "BLOB"
        break
    return "TEXT"


def fetch_view_rows(engine, view_name: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {view_name}"))
        columns = list(result.keys())
        rows = []
        for row in result:
            normalized = {
                key: normalize_value(value) for key, value in row._mapping.items()
            }
            rows.append(normalized)
        return columns, rows


def write_sqlite_table(sqlite_path: pathlib.Path, view_name: str, columns: List[str], rows: List[Dict[str, Any]]) -> None:
    import sqlite3

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.cursor()
        cursor.execute(f'DROP TABLE IF EXISTS "{view_name}"')

        column_types = {}
        if rows:
            column_data = defaultdict(list)
            for row in rows:
                for name, value in row.items():
                    column_data[name].append(value)
            column_types = {
                name: infer_sqlite_type(column_data[name]) for name in columns
            }
        else:
            column_types = {name: "TEXT" for name in columns}

        columns_sql = ", ".join(f'"{name}" {column_types[name]}' for name in columns)
        cursor.execute(f'CREATE TABLE "{view_name}" ({columns_sql})')

        if rows:
            placeholders = ", ".join("?" for _ in columns)
            column_list = ", ".join(f'"{col}"' for col in columns)
            insert_sql = f'INSERT INTO "{view_name}" ({column_list}) VALUES ({placeholders})'
            cursor.executemany(
                insert_sql,
                [[row.get(col) for col in columns] for row in rows],
            )
        conn.commit()


def export_views(sqlite_path: pathlib.Path) -> None:
    engine = create_engine(
        "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL"
    )
    for view in VIEWS:
        print(f"Exporting {view}...")
        columns, rows = fetch_view_rows(engine, view)
        write_sqlite_table(sqlite_path, view, columns, rows)
        print(f"  -> {len(rows)} rows written")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Oracle views into SQLite")
    parser.add_argument(
        "--sqlite-path",
        type=pathlib.Path,
        default=pathlib.Path("data/oracle_views.db"),
        help="Path to the SQLite database to create/update",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_views(args.sqlite_path)


if __name__ == "__main__":
    main()

