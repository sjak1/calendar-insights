"""
Utility helpers to answer natural-language questions against the SQLite
snapshot created from Oracle views.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()


DB_PATH = Path("data/oracle_views.db")
SCHEMA_CACHE: str | None = None


def _load_schema() -> str:
    global SCHEMA_CACHE
    if SCHEMA_CACHE is not None:
        return SCHEMA_CACHE

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"SQLite database not found at {DB_PATH}. Run export_views_to_sqlite.py first."
        )

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

        schema_lines: List[str] = []
        for table_row in tables:
            table = table_row["name"]
            columns = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
            column_defs = ", ".join(
                f"{col['name']} ({col['type'] or 'TEXT'})" for col in columns
            )
            schema_lines.append(f"{table}: {column_defs}")

    SCHEMA_CACHE = "\n".join(schema_lines)
    return SCHEMA_CACHE


def _generate_sql(question: str, client: OpenAI) -> Tuple[str, str]:
    schema = _load_schema()
    system_prompt = (
        "You are a cautious SQLite data analyst. "
        "You will be given a question and the SQLite schema. "
        "Respond with a JSON object containing keys 'sql' and 'explanation'. "
        "Rules:\n"
        "- Only produce SELECT statements over the provided tables.\n"
        "- Do not modify data.\n"
        "- Limit to at most 100 rows using LIMIT if no explicit limit.\n"
        "- Use single quotes for string literals.\n"
        "- Avoid dangerous commands.\n"
        "- If unsure, explain why and set sql to an empty string.\n"
        f"Schema:\n{schema}"
    )
    prompt = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )
    content = response.output_text
    payload = json.loads(content)
    sql = payload.get("sql", "").strip()
    explanation = payload.get("explanation", "")
    if sql.endswith(";"):
        sql = sql[:-1]
    if sql and "limit" not in sql.lower():
        sql += "\nLIMIT 100"
    return sql, explanation


def _execute_sql(sql: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        data = [{col: row[col] for col in columns} for row in rows]
    return columns, data


def ask_sqlite(question: str) -> Dict[str, Any]:
    """
    Answer a natural-language question using the SQLite snapshot.
    """
    client = OpenAI()
    sql, explanation = _generate_sql(question, client)
    if not sql:
        return {
            "sql": sql,
            "explanation": explanation or "Could not generate SQL for the question.",
            "rows": [],
        }

    try:
        columns, data = _execute_sql(sql)
    except sqlite3.Error as exc:
        return {
            "sql": sql,
            "explanation": f"{explanation}\nSQLite error: {exc}",
            "rows": [],
        }

    return {
        "sql": sql,
        "explanation": explanation,
        "columns": columns,
        "rows": data,
    }


