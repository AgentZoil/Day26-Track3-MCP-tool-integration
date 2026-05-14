#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

mkdir -p ../.npm-cache
rm -f /private/tmp/mcp_server_debug.log
MCP_DEBUG=1 MCP_DEBUG_LOG=/private/tmp/mcp_server_debug.log NPM_CONFIG_CACHE="$ROOT_DIR/../.npm-cache" npx -y @modelcontextprotocol/inspector python3 "$ROOT_DIR/mcp_server.py"
