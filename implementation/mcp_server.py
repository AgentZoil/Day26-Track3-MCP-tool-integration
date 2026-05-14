from __future__ import annotations

import os
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # fallback for local sandbox without external deps
    from fastmcp import FastMCP

from db import SQLiteAdapter, ValidationError
from init_db import create_database, DB_PATH


DATABASE_PATH = Path(os.environ.get("SQLITE_LAB_DB", DB_PATH))
if not DATABASE_PATH.exists():
    create_database(DATABASE_PATH)

adapter = SQLiteAdapter(DATABASE_PATH)
mcp = FastMCP("SQLite Lab MCP Server")


def _serialize_error(exc: Exception) -> str:
    return str(exc)


@mcp.tool(name="search", description="Search rows in a validated table with filters, sorting, and pagination.")
def search(
    table: str,
    filters: list[dict[str, object]] | None = None,
    columns: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    order_by: str | None = None,
    descending: bool = False,
):
    try:
        return adapter.search(
            table=table,
            columns=columns,
            filters=filters,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending,
        )
    except ValidationError as exc:
        raise ValueError(_serialize_error(exc)) from exc


@mcp.tool(name="insert", description="Insert a new row after validating table and column names.")
def insert(table: str, values: dict[str, object]):
    try:
        return adapter.insert(table=table, values=values)
    except ValidationError as exc:
        raise ValueError(_serialize_error(exc)) from exc


@mcp.tool(name="aggregate", description="Compute count, avg, sum, min, or max with optional filters and grouping.")
def aggregate(
    table: str,
    metric: str,
    column: str | None = None,
    filters: list[dict[str, object]] | None = None,
    group_by: list[str] | str | None = None,
):
    try:
        return adapter.aggregate(
            table=table,
            metric=metric,
            column=column,
            filters=filters,
            group_by=group_by,
        )
    except ValidationError as exc:
        raise ValueError(_serialize_error(exc)) from exc


@mcp.resource("schema://database", name="database_schema", description="Full database schema snapshot.")
def database_schema():
    return adapter.schema_snapshot()


@mcp.resource("schema://table/{table_name}", name="table_schema", description="Schema for one table.")
def table_schema(table_name: str):
    try:
        return adapter.get_table_schema(table_name)
    except ValidationError as exc:
        raise ValueError(_serialize_error(exc)) from exc


if __name__ == "__main__":
    mcp.run()
