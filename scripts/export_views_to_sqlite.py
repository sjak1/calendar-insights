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
from typing import Any, Dict, Iterable, List, Tuple, Union

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


def _normalize_cloud_date(column_name: str, value: oracledb.DbObject) -> Tuple[Any, Dict[str, Any]]:
    """Normalize Oracle CLOUD_DATE objects to friendlier SQLite values."""
    extras: Dict[str, Any] = {}
    zonedate = getattr(value, "ZONEDATE", None)
    zonetime = getattr(value, "ZONETIME", None)
    zoneid = getattr(value, "ZONEID", None)
    utcms = getattr(value, "UTCMS", None)

    lower_name = column_name.lower()
    base: Union[str, None] = None

    if zonedate:
        date_str = zonedate.date().isoformat() if isinstance(zonedate, datetime) else zonedate.isoformat()
        extras[f"{column_name}_date"] = date_str
        if base is None:
            if lower_name.endswith("date"):
                base = date_str

    if zonetime:
        extras[f"{column_name}_time"] = zonetime
        if base is None and lower_name.endswith("time"):
            base = zonetime

    if zoneid:
        extras[f"{column_name}_zone"] = zoneid

    if utcms is not None:
        try:
            extras[f"{column_name}_utcms"] = int(utcms)
        except (TypeError, ValueError):
            extras[f"{column_name}_utcms"] = utcms

    if base is None:
        parts = []
        if zonedate:
            parts.append(zonedate.isoformat())
        if zonetime:
            parts.append(zonetime)
        base = "T".join(parts) if parts else None

    return base, extras


def normalize_value(column_name: str, value: Any) -> Tuple[Any, Dict[str, Any]]:
    """Convert Oracle-specific values into types SQLite can store."""
    if isinstance(value, oracledb.DbObject):
        return _normalize_cloud_date(column_name, value)
    if isinstance(value, datetime):
        return value.isoformat(), {}
    if isinstance(value, date):
        return value.isoformat(), {}
    if isinstance(value, Decimal):
        return float(value), {}
    if isinstance(value, bool):
        return int(value), {}
    return value, {}


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
        base_columns = list(result.keys())
        extra_columns: List[str] = []
        rows = []
        for row in result:
            normalized: Dict[str, Any] = {}
            for key, value in row._mapping.items():
                base_value, extras = normalize_value(key, value)
                normalized[key] = base_value
                for extra_key, extra_value in extras.items():
                    normalized[extra_key] = extra_value
                    if extra_key not in extra_columns:
                        extra_columns.append(extra_key)
            rows.append(normalized)
        columns = base_columns + extra_columns
        # ensure every row has all columns
        for row in rows:
            for column in columns:
                row.setdefault(column, None)
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

