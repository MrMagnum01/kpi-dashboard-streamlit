import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DB = REPO_ROOT / "data" / "sample" / "reconciliation.duckdb"
KNOWN_TOTALS_PATH = REPO_ROOT / "data" / "sample" / "known_totals.json"


@pytest.fixture(scope="session")
def known_totals() -> dict:
    return json.loads(KNOWN_TOTALS_PATH.read_text())


@pytest.fixture()
def con():
    from kpi_dashboard import kpis

    connection = kpis.open_database(SAMPLE_DB)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def run_id(con, known_totals) -> str:
    # The vendored sample has exactly one run; use the known-totals fixture's
    # run_id as the independently recorded ground truth for "which run".
    return known_totals["run_id"]
