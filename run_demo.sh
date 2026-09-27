#!/usr/bin/env bash
# One-command demo run: launches the Streamlit dashboard against the
# vendored sample DuckDB (see data/sample/PROVENANCE.md). Assumes the venv
# is already created and activated (see README "Setup"), or falls back to
# the system python3/streamlit if not.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

DB="${1:-data/sample/reconciliation.duckdb}"
export KPI_DASHBOARD_DB="$DB"

echo "Serving the KPI dashboard against: $DB"
echo "Open the URL streamlit prints below (Ctrl+C to stop)."
exec python3 -m streamlit run streamlit_app.py --server.address 127.0.0.1
