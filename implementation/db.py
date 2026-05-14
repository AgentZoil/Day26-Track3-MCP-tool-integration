from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class ValidationError(Exception):
    """Raised when a request cannot be safely executed."""


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str | None
    notnull: bool
    default_value: str | None
    pk: bool


class SQLiteAdapter:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def list_tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        return [row["name"] for row in rows]

    def _ensure_table(self, table: str) -> None:
        if table not in self.list_tables():
            raise ValidationError(f"Unknown table: {table}")

    def _ensure_column(self, table: str, column: str) -> None:
        if column not in self._table_columns(table):
            raise ValidationError(f"Unknown column for {table}: {column}")

    def get_table_schema(self, table: str) -> dict[str, Any]:
        self._ensure_table(table)
        with self.connect() as conn:
            columns = conn.execute(f"PRAGMA table_info({self._quote_identifier(table)})").fetchall()
            foreign_keys = conn.execute(f"PRAGMA foreign_key_list({self._quote_identifier(table)})").fetchall()
        return {
            "table": table,
            "columns": [
                ColumnInfo(
                    name=row["name"],
                    type=row["type"],
                    notnull=bool(row["notnull"]),
                    default_value=row["dflt_value"],
                    pk=bool(row["pk"]),
                ).__dict__
                for row in columns
            ],
            "foreign_keys": [dict(row) for row in foreign_keys],
        }

    def _table_columns(self, table: str) -> set[str]:
        schema = self.get_table_schema(table)
        return {column["name"] for column in schema["columns"]}

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        if not identifier or "\"" in identifier:
            raise ValidationError(f"Invalid identifier: {identifier}")
        return f'"{identifier}"'

    @staticmethod
    def _normalize_columns(columns: Iterable[str] | None) -> list[str] | None:
        if columns is None:
            return None
        cleaned = [column for column in columns if column]
        return cleaned or None

    def _validate_columns(self, table: str, columns: Iterable[str]) -> None:
        allowed = self._table_columns(table)
        invalid = [column for column in columns if column not in allowed]
        if invalid:
            raise ValidationError(f"Unknown column(s) for {table}: {', '.join(invalid)}")

    def _build_filter_clause(self, table: str, filters: list[dict[str, Any]] | None) -> tuple[str, list[Any]]:
        if not filters:
            return "", []

        allowed_columns = self._table_columns(table)
        allowed_ops = {
            "=": "=",
            "!=": "!=",
            "<>": "<>",
            ">": ">",
            ">=": ">=",
            "<": "<",
            "<=": "<=",
            "like": "LIKE",
            "contains": "LIKE",
            "in": "IN",
            "between": "BETWEEN",
            "is": "IS",
            "is not": "IS NOT",
        }

        clauses: list[str] = []
        params: list[Any] = []

        for item in filters:
            column = item.get("column")
            operator = str(item.get("operator", "=")).lower()
            value = item.get("value")
            if column not in allowed_columns:
                raise ValidationError(f"Unknown column for {table}: {column}")
            if operator not in allowed_ops:
                raise ValidationError(f"Unsupported operator: {operator}")

            sql_operator = allowed_ops[operator]
            quoted_column = self._quote_identifier(column)

            if operator == "contains":
                clauses.append(f"{quoted_column} LIKE ?")
                params.append(f"%{value}%")
            elif operator == "like":
                clauses.append(f"{quoted_column} LIKE ?")
                params.append(value)
            elif operator == "in":
                if not isinstance(value, (list, tuple, set)) or not value:
                    raise ValidationError("Operator 'in' requires a non-empty list value")
                placeholders = ", ".join("?" for _ in value)
                clauses.append(f"{quoted_column} IN ({placeholders})")
                params.extend(list(value))
            elif operator == "between":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise ValidationError("Operator 'between' requires a two-item list value")
                clauses.append(f"{quoted_column} BETWEEN ? AND ?")
                params.extend(list(value))
            elif operator in {"is", "is not"}:
                clauses.append(f"{quoted_column} {sql_operator} ?")
                params.append(value)
            else:
                clauses.append(f"{quoted_column} {sql_operator} ?")
                params.append(value)

        return " WHERE " + " AND ".join(clauses), params

    def search(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
    ) -> dict[str, Any]:
        self._ensure_table(table)
        selected_columns = self._normalize_columns(columns)
        if selected_columns is None:
            selected_columns = sorted(self._table_columns(table))
        self._validate_columns(table, selected_columns)
        if order_by is not None:
            self._validate_columns(table, [order_by])
        if limit < 1 or limit > 200:
            raise ValidationError("limit must be between 1 and 200")
        if offset < 0:
            raise ValidationError("offset must be >= 0")

        where_clause, params = self._build_filter_clause(table, filters)
        order_clause = ""
        if order_by:
            order_clause = f" ORDER BY {self._quote_identifier(order_by)} {'DESC' if descending else 'ASC'}"

        sql = (
            f"SELECT {', '.join(self._quote_identifier(column) for column in selected_columns)} "
            f"FROM {self._quote_identifier(table)}{where_clause}{order_clause} "
            "LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return {
            "table": table,
            "columns": selected_columns,
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "rows": [dict(row) for row in rows],
        }

    def insert(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        self._ensure_table(table)
        if not values:
            raise ValidationError("insert values cannot be empty")

        allowed_columns = self._table_columns(table)
        invalid = [column for column in values if column not in allowed_columns]
        if invalid:
            raise ValidationError(f"Unknown column(s) for {table}: {', '.join(invalid)}")

        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"INSERT INTO {self._quote_identifier(table)} "
            f"({', '.join(self._quote_identifier(column) for column in columns)}) "
            f"VALUES ({placeholders})"
        )
        with self.connect() as conn:
            cursor = conn.execute(sql, [values[column] for column in columns])
            conn.commit()
            row_id = cursor.lastrowid
            fetched = conn.execute(
                f"SELECT * FROM {self._quote_identifier(table)} WHERE rowid = ?",
                [row_id],
            ).fetchone()

        return {
            "table": table,
            "inserted_id": row_id,
            "values": dict(fetched) if fetched is not None else values,
        }

    def aggregate(
        self,
        table: str,
        metric: str,
        column: str | None = None,
        filters: list[dict[str, Any]] | None = None,
        group_by: list[str] | str | None = None,
    ) -> dict[str, Any]:
        self._ensure_table(table)

        metric = metric.lower()
        allowed_metrics = {"count", "avg", "sum", "min", "max"}
        if metric not in allowed_metrics:
            raise ValidationError(f"Unsupported aggregate metric: {metric}")

        allowed_columns = self._table_columns(table)
        if metric != "count":
            if not column:
                raise ValidationError(f"Metric '{metric}' requires a column")
            self._ensure_column(table, column)
            metric_expr = f"{metric.upper()}({self._quote_identifier(column)})"
        else:
            if column and column != "*":
                self._ensure_column(table, column)
                metric_expr = f"COUNT({self._quote_identifier(column)})"
            else:
                metric_expr = "COUNT(*)"

        group_columns: list[str] = []
        if group_by is not None:
            if isinstance(group_by, str):
                group_columns = [group_by]
            else:
                group_columns = list(group_by)
            self._validate_columns(table, group_columns)

        where_clause, params = self._build_filter_clause(table, filters)
        group_clause = ""
        select_prefix = ""
        if group_columns:
            select_prefix = ", ".join(self._quote_identifier(column) for column in group_columns) + ", "
            group_clause = " GROUP BY " + ", ".join(self._quote_identifier(column) for column in group_columns)

        sql = (
            f"SELECT {select_prefix}{metric_expr} AS value "
            f"FROM {self._quote_identifier(table)}{where_clause}{group_clause}"
        )

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return {
            "table": table,
            "metric": metric,
            "column": column,
            "group_by": group_columns,
            "rows": [dict(row) for row in rows],
        }

    def schema_snapshot(self) -> dict[str, Any]:
        return {
            "database": str(self.db_path),
            "tables": {table: self.get_table_schema(table) for table in self.list_tables()},
        }

    def resource_text(self) -> str:
        return json.dumps(self.schema_snapshot(), indent=2, ensure_ascii=False, sort_keys=True)
