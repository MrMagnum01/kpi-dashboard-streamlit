# kpi-dashboard-streamlit

A Streamlit KPI dashboard over the `revenue-reconciliation` demo's DuckDB
output: gross/net/refunds/paid-vs-ordered per currency, mismatch counts
and amounts by category, a daily trend chart, and a paginated mismatch
drill-down table - with a data-completeness banner that never shows an
incomplete reconciliation run as complete.

**Everything in this repo is synthetic.** The dashboard reads a vendored,
committed sample DuckDB database (`data/sample/reconciliation.duckdb`)
produced by running the sibling `revenue-reconciliation` demo's own
deterministic seed-42 generator and reconciler once (see
`data/sample/PROVENANCE.md` for exactly how, and how to regenerate it).
No code, data, or client project is reused here, and this repo does not
reach into any other repository at import time or test time - it only
ever opens the DuckDB file already sitting in `data/sample/`.

**Job types this proves:** "Streamlit dashboard", "KPI dashboard from
database", "Python data dashboard" - the class of Upwork job where a
client already has a database (or gets one from an ETL/reconciliation
pipeline) and wants a read-only, currency-correct KPI view over it, not a
new data pipeline.

## What it does

Given the revenue-reconciliation demo's DuckDB schema (`docs/schema.md`,
reproduced here - see that file's header for the pin), this dashboard:

1. Lists every committed **run** and lets you pick one (default: most
   recent by `run_at`).
2. Shows a **data-completeness banner** driven only by that run's own
   `runs.status` - green "COMPLETE" only when every source was fully
   ingested, otherwise a red banner naming the incomplete source(s) and
   the ingestion issue count. An incomplete or failed run is never shown
   as complete.
3. Shows **KPIs by currency** - gross, net, refunds, paid vs ordered, and
   unmatched count/amount - one block per currency (`USD`/`EUR`/`GBP` in
   the vendored sample), never a cross-currency sum.
4. Shows **mismatches by category** (`missing_payment`, `overpayment`,
   `orphan_refund`, `currency_mismatch`, `duplicate`,
   `indeterminate_incomplete_source`), count and amount, per currency.
5. Draws a **daily trend chart** (Altair) for a chosen metric, one line per
   currency, fixed colour-per-currency, with hover tooltips - never a
   summed or dual-axis line.
6. Shows a **paginated mismatch drill-down table**, filterable by category
   and currency, with a "Showing N-M of total" caption computed from the
   same filtered query as the page itself (so a page can never look
   complete while rows are missing), and a "download this page as CSV"
   button whose values are passed through formula-injection sanitisation
   first (see "Formula safety" below).
7. Shows the run's **ingestion issues** (API failures, CSV parse errors,
   id conflicts) in a collapsed expander, verbatim from `run_issues`.

## KPI computation is a separate, pure, tested module

`src/kpi_dashboard/kpis.py` has **no Streamlit import** and no UI code at
all: every function takes a DuckDB connection (or a path) and returns
plain Python dicts/lists. `src/kpi_dashboard/app.py` only renders what
that module returns - it never recomputes a total, and it never decides a
run is complete itself (it only reflects `kpis.is_incomplete`).
`tests/test_kpis.py` exercises `kpis.py` directly, without launching
Streamlit at all.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## One-command run

```bash
./run_demo.sh
```

Serves the dashboard on `127.0.0.1` against the vendored sample database.
Pass a different DuckDB path as `$1` to point it at another
revenue-reconciliation output:

```bash
./run_demo.sh /path/to/another/reconciliation.duckdb
```

## Tests

```bash
source .venv/bin/activate
export PYTHONPATH=src   # or rely on pytest.ini's pythonpath=src
pytest tests -v
```

42/42 passing. Covers:
- **Known-total reconciliation** (`test_kpi_summary_matches_known_totals_exactly`,
  `test_mismatch_summary_matches_known_totals_exactly`) - every per-currency
  KPI and every mismatch category/currency figure the dashboard computes is
  asserted equal, to the cent, against `data/sample/known_totals.json` - the
  mismatch report the *same* upstream reconciliation run wrote about
  itself. This is a consistency check (this dashboard's SQL reproduces
  that run's own recorded numbers exactly), not an independent check of
  the upstream reconciliation logic - see "How the sample database was
  produced" below for exactly what is and isn't reconciled here.
- **Pagination/filter-state regression** (`test_resolve_page_offset_*`,
  `test_pagination_survives_a_filter_change_end_to_end`) - the drill-down
  page offset is a pure function of the query identity (run, category,
  currency, page size); changing any of those resets to page 1 instead of
  reusing a numeric offset that can outrun a smaller filtered result set.
- **Schema validation of required columns** (`test_open_database_rejects_database_missing_required_column`) -
  a database with every required table but missing a column this
  dashboard queries (e.g. an older schema with no `runs.status`) is
  rejected at `open_database` with a `SchemaError`, not accepted and left
  to crash the first time a query touches that column.
- **Cross-check** (`test_daily_trend_sums_to_the_same_kpi_summary_per_currency`) -
  summing the daily-trend query's rows reproduces the KPI-summary query's
  totals; two independently written SQL queries over the same table must
  agree.
- **Schema/input validation** - a missing database file, a zero-byte file,
  a file that isn't a DuckDB database at all, and a database missing a
  required table (an older schema version) are each rejected with a clear
  `SchemaError`, never a stack trace or a silently empty dashboard; a
  database with the right tables but zero `runs` rows raises
  `EmptyDatabaseError` rather than crashing on `None`.
- **Completeness banner** (`test_is_incomplete_never_treats_a_non_complete_run_as_complete`) -
  a pure function of the `runs` row: `complete` -> not incomplete;
  `incomplete` / `failed` -> incomplete. No database needed to test it.
- **Pagination and completeness** (`test_mismatch_pages_cover_every_row_exactly_once`) -
  walking every page of the mismatch drill-down (by `run_id, id`, the
  table's own primary key) visits every row in the table exactly once, no
  row skipped or repeated, and the reported `total_count` matches a direct
  `COUNT(*)` under the same filter.
- **Formula injection** (`test_sanitize_for_csv_export_neutralises_formula_triggers`) -
  any string starting with `=`, `+`, `-`, `@`, a tab, or a carriage return
  gets a literal leading apostrophe before it can reach a downloaded CSV.
  Tested at the string-transform level only (no spreadsheet application
  was opened as part of this test suite - see "Formula safety" below for
  exactly what that does and doesn't establish).
- **format_cents** - integer-cents formatting stays exact at zero, one
  cent, and negative values; no float ever enters the money path.

## Formula safety

Every string value that can reach the "download this page as CSV" button
(`details`, ids, categories) is passed through
`kpis.sanitize_for_csv_export` first: a value starting with one of the six
formula-trigger characters this function checks for (`=`, `+`, `-`, `@`,
tab, or carriage return) gets a literal leading apostrophe prepended -
the widely-documented CSV formula-injection mitigation for spreadsheet
software that treats a leading `=`/`+`/`-`/`@` as a formula marker. What
is actually tested here (`tests/test_kpis.py`) is the string transform
itself: the prefixed value is unchanged apart from the leading
apostrophe, for exactly those six trigger characters. No spreadsheet
application (Excel, LibreOffice, Google Sheets, or any other) was opened,
imported into, or scripted as part of this test suite, so this repo makes
no tested claim about how any specific spreadsheet version, locale, or
import path renders the result - only that the exported string itself no
longer starts with an unescaped trigger character. This dashboard does
not write `.xlsx` files at all (only CSV, via Streamlit's own download
button), so there is no live-formula-cell concern the way there is in the
`excel-consolidation` demo - the CSV formula-injection vector is the one
that applies here, and it is defended (and tested) at the same layer the
export happens in (`kpis.py`).

## How the sample database was produced

See `data/sample/PROVENANCE.md`. In short: the sibling
`revenue-reconciliation` demo (pinned to its commit `144ede0`) was run
once, exactly as its own README documents (`generate` + `reconcile`,
seed 42), and the resulting `reconciliation.duckdb` was copied here as a
committed sample - not fetched or generated across repos at runtime. The
mismatch report that same run wrote was copied alongside as
`known_totals.json` - see "Known-total reconciliation" above and
`data/sample/PROVENANCE.md` for exactly what that report is and what
agreeing with it does and doesn't establish (it is not an independent
check of the upstream reconciliation logic).

## QA screenshots

Any screenshots of this dashboard (e.g. in a portfolio write-up) were
taken locally with an ordinary browser pointed at `streamlit run`. That is
a one-off manual QA step, outside this repo, and is not part of the demo,
its tests, or anything this repo runs or ships - there is no screenshot
step in `run_demo.sh` or the test suite.

## Limits

- **This dashboard is read-only.** It never writes to the DuckDB file
  (`kpis.open_database` connects with `read_only=True`) and never
  recomputes a KPI the source pipeline didn't already write - it queries
  `daily_kpis` / `mismatches` / `runs` / `run_issues` exactly as that
  pipeline wrote them. There is no "publish" step in this repo to make
  atomic: the vendored sample is a static committed file, and pointing
  `KPI_DASHBOARD_DB` at a live `revenue-reconciliation` output directory
  that pipeline is still writing to is the caller's responsibility, not
  something this dashboard coordinates with.
- **No FX conversion, ever.** Every money figure is shown per currency;
  nothing in this dashboard sums `*_cents` across `USD`/`EUR`/`GBP`. Only
  counts (mismatch counts, `unmatched_count`) are ever combined across
  currencies, matching the source schema's own rule.
- **Raw tables in the source database are latest-state, not history**
  (documented in `docs/schema.md`, inherited unchanged from
  `revenue-reconciliation`) - this dashboard reads per-run tables
  (`daily_kpis`, `mismatches`, `runs`, `run_issues`) for its numbers
  specifically so a chosen run's figures stay historically accurate even
  after a later run overwrites the raw `orders`/`payments`/`refunds`
  tables.
- **The mismatch drill-down paginates in the UI, not the whole dataset at
  once**, by design (see "Pagination and completeness" above) - the KPI
  summary and mismatch-by-category totals are always computed over the
  *entire* run in one SQL aggregate, never over just the currently
  displayed page.
- **One database, one schema version.** `kpis.open_database` refuses a
  database missing a required table (e.g. one written by an older schema)
  with a clear error rather than showing a partially blank dashboard.
- **Not a general-purpose BI tool.** The KPI set, chart, and drill-down
  columns are fixed to this schema; adding a new metric means adding a
  query to `kpis.py`, not configuring a chart builder.
- **`known_totals.json` matches exactly one run** (the one described in
  `data/sample/PROVENANCE.md`) - it is not regenerated or re-derived if
  the vendored sample database is ever swapped for a different run without
  also updating that file, and the reconciliation tests would then need
  updated expected figures.

## Project layout

```
src/kpi_dashboard/
  kpis.py          pure KPI computation over the DuckDB schema - no Streamlit import
  app.py           Streamlit UI; renders what kpis.py returns, computes nothing itself
streamlit_app.py   thin launcher (`streamlit run streamlit_app.py`) that wires src/ onto sys.path
tests/             pytest suite (see "Tests" above)
scripts/screenshot.py  optional local dev script, not part of the demo (see "QA screenshots" above)
data/sample/       vendored sample DuckDB + its known-totals ground truth (see PROVENANCE.md)
docs/schema.md     the DuckDB schema this dashboard reads, reproduced from revenue-reconciliation
LICENSES.md        every open-source library used and its licence
```

## Role

Synthetic portfolio demonstration, implemented with AI coding agents and
independently reviewed by a separate AI reviewer. No client data or
client work.
