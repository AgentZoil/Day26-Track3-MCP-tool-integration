# Lab: Build a Database MCP Server with FastMCP and SQLite

This repo contains a self-contained MCP lab server with:

- `search`
- `insert`
- `aggregate`
- `schema://database`
- `schema://table/{table_name}`

The implementation lives in [`implementation/`](implementation).

The server uses the official `FastMCP` API from `mcp.server.fastmcp` when that
package is installed. The local fallback in `implementation/fastmcp.py` exists
only so this sandbox can still run the lab end-to-end.

## Project Layout

```text
implementation/
  db.py
  fastmcp.py
  init_db.py
  mcp_server.py
  verify_server.py
  start_inspector.sh
```

## What It Does

- starts an MCP server over `stdio`
- stores data in SQLite
- validates table names, column names, and aggregate metrics
- uses parameterized SQL for user input
- exposes full schema and per-table schema resources
- includes a repeatable verification script

## Setup

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

1. Open terminal in repo root.
2. Move into implementation folder:

```bash
cd implementation
```

3. Initialize database:

```bash
python3 init_db.py
```

That creates `sqlite_lab.db` with seed data.

## Run Server

```bash
python3 mcp_server.py
```

Server reads MCP messages from `stdin` and writes framed JSON-RPC responses to `stdout`.

## Verify

Run full smoke test:

```bash
python3 verify_server.py
```

Expected result:

- server initializes
- `search`, `insert`, `aggregate` appear in tool list
- `schema://database` appears in resource list
- `schema://table/{table_name}` appears in resource template list
- valid calls succeed
- invalid calls return clear errors

## Inspector

Launch MCP Inspector:

```bash
bash start_inspector.sh
```

If `npx` must download Inspector, allow network once.

Useful demo calls:

- read `schema://database`
- read `schema://table/students`
- search students in cohort `A1`
- insert one student
- aggregate average score by cohort
- try invalid table name

## Example Tool Calls

### Search

```json
{
  "table": "students",
  "filters": [
    {"column": "cohort", "operator": "=", "value": "A1"}
  ],
  "columns": ["id", "name", "cohort", "score"],
  "order_by": "score",
  "descending": true,
  "limit": 5,
  "offset": 0
}
```

### Insert

```json
{
  "table": "students",
  "values": {
    "name": "Lan",
    "cohort": "A1",
    "score": 97,
    "email": "lan@example.com"
  }
}
```

### Aggregate

```json
{
  "table": "students",
  "metric": "avg",
  "column": "score",
  "group_by": "cohort"
}
```

## MCP Client Examples

See [`Tips.md`](Tips.md) for Claude Code, Codex, Gemini CLI, and Inspector examples.

## Demo Checklist

- show server start
- show tools discovery
- show schema resource read
- show one valid search
- show one valid insert
- show one valid aggregate
- show one invalid request with error
- show at least one MCP client connected
