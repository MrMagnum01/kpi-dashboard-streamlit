"""Reconciles the dashboard's KPI computation to the source pipeline's own
recorded ground truth (`data/sample/known_totals.json`, the mismatch report
written by the same run that produced the vendored sample DB), and exercises
every finding class this demo was designed against: strict schema
validation (missing file, zero-byte file, wrong-schema file), the
completeness banner never showing an incomplete run as complete, exact
per-currency (never cross-currency) reconciliation, complete pagination of
the mismatch drill-down, and CSV formula-injection sanitisation."""

from __future__ import annotations

import duckdb
import pytest

from kpi_dashboard import kpis

CURRENCIES = ("EUR", "GBP", "USD")


# --------------------------------------------------------------------------
# Known-total reconciliation
# --------------------------------------------------------------------------


def test_kpi_summary_matches_known_totals_exactly(con, run_id, known_totals):
    summary = kpis.kpi_summary(con, run_id)
    assert set(summary) == set(CURRENCIES)
    for currency in CURRENCIES:
        expected = known_totals["totals_cents"][currency]
        actual = summary[currency]
        for field in ("gross_cents", "net_cents", "refunds_cents", "paid_cents", "ordered_cents", "unmatched_cents"):
            assert actual[field] == expected[field], f"{currency}.{field}"


def test_unmatched_count_sums_across_currencies_matches_known_total(con, run_id, known_totals):
    summary = kpis.kpi_summary(con, run_id)
    total_unmatched_count = sum(row["unmatched_count"] for row in summary.values())
    assert total_unmatched_count == known_totals["totals_cents"]["unmatched_count"]


def test_mismatch_summary_matches_known_totals_exactly(con, run_id, known_totals):
    mm = kpis.mismatch_summary(con, run_id)
    assert set(mm) == set(kpis.MISMATCH_CATEGORIES)
    for category, expected in known_totals["mismatches"].items():
        actual = mm[category]
        actual_count = sum(v["count"] for v in actual.values())
        assert actual_count == expected["count"], category
        for currency, expected_amount in expected["amount_cents_by_currency"].items():
            assert actual[currency]["amount_cents"] == expected_amount, f"{category}/{currency}"
    # indeterminate_incomplete_source had zero findings in this complete run
    assert mm["indeterminate_incomplete_source"] == {}


def test_daily_trend_sums_to_the_same_kpi_summary_per_currency(con, run_id):
    """Cross-check: summing the daily trend rows reproduces kpi_summary -
    two independent query shapes over the same table must agree."""
    summary = kpis.kpi_summary(con, run_id)
    trend = kpis.daily_trend(con, run_id)
    from collections import defaultdict

    totals = defaultdict(lambda: defaultdict(int))
    for row in trend:
        for field in ("gross_cents", "net_cents", "refunds_cents", "paid_cents", "ordered_cents", "unmatched_cents"):
            totals[row["currency"]][field] += row[field]
    for currency in CURRENCIES:
        for field in totals[currency]:
            assert totals[currency][field] == summary[currency][field], f"{currency}.{field}"


def test_run_status_is_complete_for_the_vendored_sample(con, run_id, known_totals):
    run_row = kpis.get_run(con, run_id)
    assert run_row["status"] == known_totals["status"] == "complete"
    assert kpis.is_incomplete(run_row) is False


# --------------------------------------------------------------------------
# Completeness banner logic (pure - no DB needed)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [("complete", False), ("incomplete", True), ("failed", True)],
)
def test_is_incomplete_never_treats_a_non_complete_run_as_complete(status, expected):
    assert kpis.is_incomplete({"status": status}) is expected


def test_incomplete_source_list_parses_csv_field():
    assert kpis.incomplete_source_list({"incomplete_sources": "orders,refunds"}) == ["orders", "refunds"]
    assert kpis.incomplete_source_list({"incomplete_sources": ""}) == []
    assert kpis.incomplete_source_list({}) == []


# --------------------------------------------------------------------------
# Schema / input validation: zero-byte, missing, wrong-schema files
# --------------------------------------------------------------------------


def test_open_database_rejects_missing_file(tmp_path):
    with pytest.raises(kpis.SchemaError, match="not found"):
        kpis.open_database(tmp_path / "does_not_exist.duckdb")


def test_open_database_rejects_zero_byte_file(tmp_path):
    p = tmp_path / "empty.duckdb"
    p.write_bytes(b"")
    with pytest.raises(kpis.SchemaError, match="zero bytes"):
        kpis.open_database(p)


def test_open_database_rejects_non_database_file(tmp_path):
    p = tmp_path / "not_a_db.duckdb"
    p.write_text("this is plainly not a duckdb file, just some header-ish text\n")
    with pytest.raises(kpis.SchemaError):
        kpis.open_database(p)


def test_open_database_rejects_database_missing_required_tables(tmp_path):
    p = tmp_path / "wrong_schema.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE TABLE orders (order_id VARCHAR)")
    con.close()
    with pytest.raises(kpis.SchemaError, match="missing required table"):
        kpis.open_database(p)


def test_open_database_accepts_the_vendored_sample():
    con = kpis.open_database(
        __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "sample" / "reconciliation.duckdb"
    )
    try:
        assert kpis.latest_run_id(con)
    finally:
        con.close()


def _create_full_schema(con, *, omit: tuple[str, str] | None = None) -> None:
    """Create every REQUIRED_TABLES table with every column this module
    reads (REQUIRED_COLUMNS), all VARCHAR and empty - a minimal but
    column-complete schema. ``omit=(table, column)`` drops one column, to
    build an older-schema-version fixture for a single missing-column case."""
    for table in kpis.REQUIRED_TABLES:
        columns = list(kpis.REQUIRED_COLUMNS.get(table, ()))
        if not columns:
            columns = ["dummy"]
        if omit is not None and omit[0] == table:
            columns = [c for c in columns if c != omit[1]]
        col_defs = ", ".join(f"{c} VARCHAR" for c in columns)
        con.execute(f"CREATE TABLE {table} ({col_defs})")


def test_open_database_rejects_database_missing_required_column(tmp_path):
    """A schema missing runs.status (the older schema docs/schema.md says is
    refused) must be caught at open_database, not surfaced as a crash the
    first time a query touches the column - see test_kpis.py::MUST-FIX 2."""
    p = tmp_path / "no_status_column.duckdb"
    con = duckdb.connect(str(p))
    _create_full_schema(con, omit=("runs", "status"))
    con.close()
    with pytest.raises(kpis.SchemaError, match=r"missing required column.*runs\.status"):
        kpis.open_database(p)


def test_empty_database_error_on_db_with_no_runs(tmp_path):
    p = tmp_path / "no_runs.duckdb"
    con = duckdb.connect(str(p))
    _create_full_schema(con)
    con.close()
    con2 = kpis.open_database(p)
    try:
        with pytest.raises(kpis.EmptyDatabaseError):
            kpis.latest_run_id(con2)
        assert kpis.list_runs(con2) == []
    finally:
        con2.close()


# --------------------------------------------------------------------------
# Pagination and completeness of the mismatch drill-down
# --------------------------------------------------------------------------


def test_mismatch_pages_cover_every_row_exactly_once(con, run_id):
    seen = []
    offset = 0
    limit = 3
    total = None
    for _ in range(1000):  # hard bound so a bug can't hang the test
        page = kpis.mismatch_page(con, run_id, offset=offset, limit=limit)
        total = page.total_count
        seen.extend((r["run_id"], r["id"]) for r in page.rows)
        if not page.has_more:
            break
        offset += limit
    else:
        pytest.fail("pagination did not terminate")

    assert len(seen) == total
    assert len(set(seen)) == total, "pagination must not repeat a row"

    direct = con.execute("SELECT run_id, id FROM mismatches WHERE run_id = ?", [run_id]).fetchall()
    assert sorted(seen) == sorted(direct)


def test_mismatch_page_total_count_matches_filtered_query(con, run_id):
    page = kpis.mismatch_page(con, run_id, category="missing_payment", limit=100)
    direct_count = con.execute(
        "SELECT COUNT(*) FROM mismatches WHERE run_id = ? AND category = ?", [run_id, "missing_payment"]
    ).fetchone()[0]
    assert page.total_count == direct_count
    assert all(r["category"] == "missing_payment" for r in page.rows)


def test_mismatch_page_rejects_bad_arguments(con, run_id):
    with pytest.raises(ValueError):
        kpis.mismatch_page(con, run_id, limit=0)
    with pytest.raises(ValueError):
        kpis.mismatch_page(con, run_id, offset=-1)


# --------------------------------------------------------------------------
# MUST-FIX 1 regression: changing a filter after paging must reset to page 1.
# Pure logic, no Streamlit/AppTest - kpis.resolve_page_offset has no UI
# dependency at all, so the bug ("Next", then change a filter -> "no
# matches" despite rows existing) is reproduced and pinned here directly.
# --------------------------------------------------------------------------


def test_resolve_page_offset_keeps_offset_when_query_key_unchanged():
    key = kpis.mismatch_query_key("run-1", category=None, currency=None, limit=10)
    assert kpis.resolve_page_offset(10, key, key) == 10


def test_resolve_page_offset_resets_to_zero_when_category_changes():
    old_key = kpis.mismatch_query_key("run-1", category=None, currency=None, limit=10)
    new_key = kpis.mismatch_query_key("run-1", category="orphan_refund", currency=None, limit=10)
    # Reproduces the reported bug: page to offset 10, then pick a filter
    # that only has 4 matching rows - offset 10 must not survive.
    assert kpis.resolve_page_offset(10, old_key, new_key) == 0


def test_resolve_page_offset_resets_on_currency_run_or_page_size_change():
    base = kpis.mismatch_query_key("run-1", category=None, currency=None, limit=10)
    variants = [
        kpis.mismatch_query_key("run-1", category=None, currency="EUR", limit=10),
        kpis.mismatch_query_key("run-2", category=None, currency=None, limit=10),
        kpis.mismatch_query_key("run-1", category=None, currency=None, limit=25),
    ]
    for variant in variants:
        assert kpis.resolve_page_offset(10, base, variant) == 0


def test_resolve_page_offset_treats_no_previous_key_as_first_render():
    key = kpis.mismatch_query_key("run-1", category=None, currency=None, limit=10)
    # First render of a session: nothing stored yet - use whatever offset
    # was given (0, from session_state.get default) rather than forcing a
    # reset that would just be a no-op.
    assert kpis.resolve_page_offset(0, None, key) == 0


def test_pagination_survives_a_filter_change_end_to_end(con, run_id):
    """End-to-end version of the same fix at the kpis layer: page to the
    last page under no filter, then switch to a filter with fewer rows -
    the resolved offset must land on a page that actually has rows,
    matching what the UI's "Showing N-M of total" caption promises."""
    unfiltered = kpis.mismatch_page(con, run_id, limit=10)
    assert unfiltered.total_count > 10  # sample must exercise > 1 page
    old_key = kpis.mismatch_query_key(run_id, category=None, currency=None, limit=10)

    filtered_key = kpis.mismatch_query_key(run_id, category="orphan_refund", currency=None, limit=10)
    resolved_offset = kpis.resolve_page_offset(10, old_key, filtered_key)
    assert resolved_offset == 0

    filtered_page = kpis.mismatch_page(con, run_id, category="orphan_refund", offset=resolved_offset, limit=10)
    assert filtered_page.total_count > 0
    assert filtered_page.returned_count > 0


# --------------------------------------------------------------------------
# CSV formula injection
# --------------------------------------------------------------------------


@pytest.mark.parametrize("dangerous", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\tformula", "\rformula"])
def test_sanitize_for_csv_export_neutralises_formula_triggers(dangerous):
    out = kpis.sanitize_for_csv_export(dangerous)
    assert out.startswith("'")
    assert out[1:] == dangerous


@pytest.mark.parametrize("safe", ["normal text", "", "order-123", None, 42, 12.5])
def test_sanitize_for_csv_export_leaves_safe_values_unchanged(safe):
    assert kpis.sanitize_for_csv_export(safe) == safe


def test_no_mismatch_detail_field_would_pass_csv_export_unsanitised(con, run_id):
    """Regression guard: if the sample ever grows a details string that looks
    like a formula, this fails loudly instead of silently shipping it."""
    page = kpis.mismatch_page(con, run_id, limit=1000)
    for row in page.rows:
        for field in ("details", "order_id", "payment_id", "refund_id"):
            value = row[field]
            sanitized = kpis.sanitize_for_csv_export(value)
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                assert sanitized.startswith("'")


# --------------------------------------------------------------------------
# format_cents
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cents,expected",
    [(0, "0.00"), (1, "0.01"), (100, "1.00"), (123456, "1234.56"), (-150, "-1.50")],
)
def test_format_cents(cents, expected):
    assert kpis.format_cents(cents) == expected
