"""Pure KPI computation over the revenue-reconciliation DuckDB output.

No Streamlit import anywhere in this module. Every function here takes a
DuckDB connection (or a path to open one) and returns plain Python data
(dicts / lists of dicts) so it can be unit tested without a UI and without
any network or filesystem side effect beyond reading the given database
file.

Schema reference: ``docs/schema.md`` in this repo, reproduced from the
revenue-reconciliation demo's own ``docs/schema.md``. This module only
ever reads that schema's tables; it does not write to the database.

Currency discipline: every money aggregate returned by this module is
keyed by currency. Nothing here ever sums ``amount_cents`` /
``*_cents`` columns across different currencies - only counts (e.g. the
number of mismatches, or ``unmatched_count``) are ever combined across
currencies, matching the source pipeline's own rule.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

MISMATCH_CATEGORIES = (
    "missing_payment",
    "overpayment",
    "orphan_refund",
    "currency_mismatch",
    "duplicate",
    "indeterminate_incomplete_source",
)

# Sources a run tracks completeness for; mirrors revenue_reconciliation.db.
RUN_SOURCES = ("orders", "payments", "refunds")


class EmptyDatabaseError(RuntimeError):
    """Raised when the database has no committed run to show."""


class SchemaError(RuntimeError):
    """Raised when the file at ``db_path`` isn't a usable reconciliation DB."""


REQUIRED_TABLES = ("orders", "payments", "refunds", "daily_kpis", "mismatches", "runs", "run_issues")

# Columns this module actually selects from each table (docs/schema.md).
# orders/payments/refunds are not queried directly by this module (only
# their existence is required above), so they are not listed here.
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "runs": ("run_id", "run_at", "source_note", "status", "incomplete_sources", "issue_count"),
    "daily_kpis": (
        "run_id", "day", "currency", "gross_cents", "net_cents", "refunds_cents",
        "paid_cents", "ordered_cents", "unmatched_count", "unmatched_cents",
    ),
    "mismatches": (
        "run_id", "id", "category", "day", "order_id", "payment_id", "refund_id",
        "currency", "amount_cents", "details",
    ),
    "run_issues": (
        "run_id", "id", "source", "kind", "category", "record_id", "line_number", "detail",
    ),
}

# Expected DuckDB `information_schema.columns.data_type` for every column in
# REQUIRED_COLUMNS (types are as documented in docs/schema.md). A column of
# the right name but the wrong type (e.g. daily_kpis.gross_cents written as
# VARCHAR instead of BIGINT) passes the missing-column check above and then
# fails only deep inside a query, as an uncaught duckdb.BinderException -
# check this before returning the connection.
REQUIRED_COLUMN_TYPES: dict[str, dict[str, str]] = {
    "runs": {
        "run_id": "VARCHAR",
        "run_at": "TIMESTAMP",
        "source_note": "VARCHAR",
        "status": "VARCHAR",
        "incomplete_sources": "VARCHAR",
        "issue_count": "BIGINT",
    },
    "daily_kpis": {
        "run_id": "VARCHAR",
        "day": "DATE",
        "currency": "VARCHAR",
        "gross_cents": "BIGINT",
        "net_cents": "BIGINT",
        "refunds_cents": "BIGINT",
        "paid_cents": "BIGINT",
        "ordered_cents": "BIGINT",
        "unmatched_count": "BIGINT",
        "unmatched_cents": "BIGINT",
    },
    "mismatches": {
        "run_id": "VARCHAR",
        "id": "BIGINT",
        "category": "VARCHAR",
        "day": "DATE",
        "order_id": "VARCHAR",
        "payment_id": "VARCHAR",
        "refund_id": "VARCHAR",
        "currency": "VARCHAR",
        "amount_cents": "BIGINT",
        "details": "VARCHAR",
    },
    "run_issues": {
        "run_id": "VARCHAR",
        "id": "BIGINT",
        "source": "VARCHAR",
        "kind": "VARCHAR",
        "category": "VARCHAR",
        "record_id": "VARCHAR",
        "line_number": "BIGINT",
        "detail": "VARCHAR",
    },
}


def open_database(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    """Open the DuckDB file read-only, validating it before returning it.

    Read-only avoids ever creating or mutating the source file just by
    opening it. Rejects, with a clear message rather than a stack trace or
    a silently empty dashboard, each of: a missing path, a zero-byte file,
    a file that isn't a DuckDB database at all, and a database missing one
    of the tables this module reads (e.g. an older schema version).
    """
    path = Path(db_path)
    if not path.exists():
        raise SchemaError(f"database not found: {path}")
    if path.stat().st_size == 0:
        raise SchemaError(f"database file is zero bytes: {path}")
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        raise SchemaError(f"not a readable DuckDB database: {path} ({exc})") from exc
    try:
        existing = {
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        missing = [t for t in REQUIRED_TABLES if t not in existing]
        if missing:
            con.close()
            raise SchemaError(
                f"database is missing required table(s) {missing}: {path} "
                "(wrong file, or written by an older schema version)"
            )

        # Table names alone aren't enough: an older schema version (e.g. no
        # runs.status, no daily_kpis.currency) can have every required table
        # present but be missing a column every query above assumes exists,
        # which would otherwise pass this check and only fail later with an
        # uncaught duckdb.BinderException deep in a query. Check columns too.
        cols_by_table: dict[str, set[str]] = {}
        types_by_table: dict[str, dict[str, str]] = {}
        for table_name, column_name, data_type in con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main'"
        ).fetchall():
            cols_by_table.setdefault(table_name, set()).add(column_name)
            types_by_table.setdefault(table_name, {})[column_name] = data_type
        missing_columns = [
            f"{table}.{column}"
            for table, columns in REQUIRED_COLUMNS.items()
            for column in columns
            if column not in cols_by_table.get(table, set())
        ]
        if missing_columns:
            con.close()
            raise SchemaError(
                f"database is missing required column(s) {missing_columns}: {path} "
                "(wrong file, or written by an older schema version)"
            )

        # Column present but the wrong type (e.g. a text amount column, or a
        # non-date date column) still passes the check above and would
        # otherwise only fail later, mid-query, as an uncaught
        # duckdb.BinderException. Check the type of every column this module
        # actually reads before returning the connection.
        wrong_type_columns = [
            f"{table}.{column} (expected {expected_type}, got {types_by_table[table][column]})"
            for table, columns in REQUIRED_COLUMN_TYPES.items()
            for column, expected_type in columns.items()
            if types_by_table.get(table, {}).get(column) != expected_type
        ]
        if wrong_type_columns:
            con.close()
            raise SchemaError(
                f"database has required column(s) with an incompatible type {wrong_type_columns}: {path} "
                "(wrong file, or written by an older/incompatible schema version)"
            )
    except duckdb.Error as exc:
        con.close()
        raise SchemaError(f"could not read schema from database: {path} ({exc})") from exc
    return con


@contextlib.contextmanager
def connect(db_path: str | Path):
    """Context-manager wrapper around :func:`open_database`."""
    con = open_database(db_path)
    try:
        yield con
    finally:
        con.close()


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_for_csv_export(value: Any) -> Any:
    """Neutralise CSV formula injection for a value bound for a downloaded CSV.

    Spreadsheet software (Excel, LibreOffice, Google Sheets) treats a cell
    that starts with ``=``, ``+``, ``-`` or ``@`` as a formula when a CSV is
    opened, even though CSV has no formula syntax of its own. Any string
    field surfaced in this dashboard's exports (``details``, ids, the run's
    ``source_note``) is untrusted in the sense that it came from an upstream
    CSV/API record, so every exported string value is passed through this
    function first: a leading formula-trigger character gets a literal
    leading apostrophe, which every major spreadsheet renders as plain text
    instead of evaluating. Non-strings and empty strings pass through
    unchanged.
    """
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def list_runs(con) -> list[dict[str, Any]]:
    """All runs, most recent first, with their completeness status."""
    rows = con.execute(
        """
        SELECT run_id, run_at, source_note, status, incomplete_sources,
               issue_count
        FROM runs
        ORDER BY run_at DESC, run_id DESC
        """
    ).fetchall()
    cols = ["run_id", "run_at", "source_note", "status", "incomplete_sources", "issue_count"]
    return [dict(zip(cols, r)) for r in rows]


def latest_run_id(con) -> str:
    runs = list_runs(con)
    if not runs:
        raise EmptyDatabaseError("no rows in 'runs' - database has no committed run")
    return runs[0]["run_id"]


def get_run(con, run_id: str) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT run_id, run_at, source_note, status, incomplete_sources,
               issue_count
        FROM runs WHERE run_id = ?
        """,
        [run_id],
    ).fetchone()
    if row is None:
        raise EmptyDatabaseError(f"no such run_id: {run_id!r}")
    cols = ["run_id", "run_at", "source_note", "status", "incomplete_sources", "issue_count"]
    return dict(zip(cols, row))


def is_incomplete(run_row: dict[str, Any]) -> bool:
    """True whenever a run must not be presented as a clean/complete run.

    Pure function of the ``runs`` row alone (status is written by the
    source pipeline as ``complete`` / ``incomplete`` / ``failed``) so the
    "never show an incomplete run as complete" rule can be unit tested
    without a database at all.
    """
    return run_row.get("status") != "complete"


def incomplete_source_list(run_row: dict[str, Any]) -> list[str]:
    raw = run_row.get("incomplete_sources") or ""
    return [s for s in raw.split(",") if s]


def kpi_summary(con, run_id: str) -> dict[str, dict[str, int]]:
    """Gross / net / refunds / paid-vs-ordered / unmatched, per currency.

    Returns ``{currency: {gross_cents, net_cents, refunds_cents,
    paid_cents, ordered_cents, unmatched_count, unmatched_cents}}``.
    Summed across the run's days, never across currencies (one dict entry
    per currency; no "total" key that would imply a cross-currency sum).
    """
    rows = con.execute(
        """
        SELECT currency,
               SUM(gross_cents)      AS gross_cents,
               SUM(net_cents)        AS net_cents,
               SUM(refunds_cents)    AS refunds_cents,
               SUM(paid_cents)       AS paid_cents,
               SUM(ordered_cents)    AS ordered_cents,
               SUM(unmatched_count)  AS unmatched_count,
               SUM(unmatched_cents)  AS unmatched_cents
        FROM daily_kpis
        WHERE run_id = ?
        GROUP BY currency
        ORDER BY currency
        """,
        [run_id],
    ).fetchall()
    cols = [
        "gross_cents", "net_cents", "refunds_cents", "paid_cents",
        "ordered_cents", "unmatched_count", "unmatched_cents",
    ]
    return {r[0]: dict(zip(cols, r[1:])) for r in rows}


def mismatch_summary(con, run_id: str) -> dict[str, dict[str, dict[str, int]]]:
    """Mismatch counts + amounts, grouped by category then currency.

    Returns ``{category: {currency: {"count": n, "amount_cents": c}}}``.
    Every known category is present (with an empty ``{}`` currency map)
    even when a run had zero findings in it, so a dashboard never has to
    guess whether a missing key means "zero" or "not computed".
    """
    result: dict[str, dict[str, dict[str, int]]] = {c: {} for c in MISMATCH_CATEGORIES}
    rows = con.execute(
        """
        SELECT category, currency, COUNT(*) AS n, SUM(amount_cents) AS total
        FROM mismatches
        WHERE run_id = ?
        GROUP BY category, currency
        ORDER BY category, currency
        """,
        [run_id],
    ).fetchall()
    for category, currency, n, total in rows:
        result.setdefault(category, {})[currency] = {
            "count": int(n),
            "amount_cents": int(total),
        }
    return result


def daily_trend(con, run_id: str) -> list[dict[str, Any]]:
    """One row per (day, currency) for the run's daily KPI history, in
    day order, currency kept as its own column (never merged)."""
    rows = con.execute(
        """
        SELECT day, currency, gross_cents, net_cents, refunds_cents,
               paid_cents, ordered_cents, unmatched_count, unmatched_cents
        FROM daily_kpis
        WHERE run_id = ?
        ORDER BY day, currency
        """,
        [run_id],
    ).fetchall()
    cols = [
        "day", "currency", "gross_cents", "net_cents", "refunds_cents",
        "paid_cents", "ordered_cents", "unmatched_count", "unmatched_cents",
    ]
    return [dict(zip(cols, r)) for r in rows]


@dataclass(frozen=True)
class MismatchPage:
    rows: list[dict[str, Any]]
    total_count: int
    offset: int
    limit: int

    @property
    def returned_count(self) -> int:
        return len(self.rows)

    @property
    def has_more(self) -> bool:
        return self.offset + self.returned_count < self.total_count


def mismatch_query_key(
    run_id: str, *, category: str | None, currency: str | None, limit: int
) -> tuple[str, str | None, str | None, int]:
    """Identity of a mismatch-drill-down query: everything that selects
    *which rows* page 0 would start from. A stored page offset is only
    ever valid for the query it was paginated from - reused against a
    different key it points past whatever rows now match (or past all of
    them), which is exactly the "no matches" bug this pairs with (see
    ``resolve_page_offset``)."""
    return (run_id, category, currency, limit)


def resolve_page_offset(
    stored_offset: int,
    previous_key: tuple[str, str | None, str | None, int] | None,
    current_key: tuple[str, str | None, str | None, int],
) -> int:
    """The offset to actually query with: 0 whenever the query identity
    (run/category/currency/page-size) just changed, otherwise whatever was
    stored.

    Pure function, no Streamlit/session_state - this is the fix for the
    reported bug (choose 10 rows, Next, then change a filter: the UI kept
    the old numeric offset and rendered "no matches" against a filter that
    actually has rows, because an offset valid for the old page had simply
    outrun the new, usually-shorter result set). A page offset only ever
    makes sense for the exact query it was computed against.
    """
    if previous_key is not None and previous_key != current_key:
        return 0
    return stored_offset


def mismatch_page(
    con,
    run_id: str,
    *,
    category: str | None = None,
    currency: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> MismatchPage:
    """A stable, complete page of the mismatch drill-down table.

    Ordered by the table's own primary key ``(run_id, id)`` - never by an
    unstable sort - so paging through every page yields the full set
    exactly once (no row skipped or repeated), and ``total_count`` is
    computed from the same filtered query so the UI can show
    "N-M of total" instead of a page that looks complete but isn't.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must not be negative")

    where = ["run_id = ?"]
    params: list[Any] = [run_id]
    if category is not None:
        where.append("category = ?")
        params.append(category)
    if currency is not None:
        where.append("currency = ?")
        params.append(currency)
    where_sql = " AND ".join(where)

    total = con.execute(
        f"SELECT COUNT(*) FROM mismatches WHERE {where_sql}", params
    ).fetchone()[0]

    rows = con.execute(
        f"""
        SELECT run_id, id, category, day, order_id, payment_id, refund_id,
               currency, amount_cents, details
        FROM mismatches
        WHERE {where_sql}
        ORDER BY run_id, id
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    cols = [
        "run_id", "id", "category", "day", "order_id", "payment_id",
        "refund_id", "currency", "amount_cents", "details",
    ]
    return MismatchPage(
        rows=[dict(zip(cols, r)) for r in rows],
        total_count=int(total),
        offset=offset,
        limit=limit,
    )


def run_issues(con, run_id: str) -> list[dict[str, Any]]:
    """Every ingestion problem recorded for the run (api/csv/id-conflict)."""
    rows = con.execute(
        """
        SELECT run_id, id, source, kind, category, record_id, line_number,
               detail
        FROM run_issues
        WHERE run_id = ?
        ORDER BY run_id, id
        """,
        [run_id],
    ).fetchall()
    cols = ["run_id", "id", "source", "kind", "category", "record_id", "line_number", "detail"]
    return [dict(zip(cols, r)) for r in rows]


def format_cents(cents: int) -> str:
    """Render integer cents as a fixed-point decimal string, e.g. 123456 -> '1234.56'.

    Never a float: string formatting only, so this can't reintroduce the
    floating-point drift the source pipeline avoids by using integer cents.
    """
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100}.{cents % 100:02d}"
