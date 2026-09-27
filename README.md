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

36/36 passing. Covers:
- **Known-total reconciliation** (`test_kpi_summary_matches_known_totals_exactly`,
  `test_mismatch_summary_matches_known_totals_exactly`) - every per-currency
  KPI and every mismatch category/currency figure the dashboard computes is
  asserted equal, to the cent, against `data/sample/known_totals.json` - the
  mismatch report the source pipeline itself wrote for the same run,
  independently of this dashboard's queries.
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
  gets a literal leading apostrophe before it can reach a downloaded CSV,
  so a spreadsheet never evaluates untrusted upstream text as a formula.
- **format_cents** - integer-cents formatting stays exact at zero, one
  cent, and negative values; no float ever enters the money path.

## Formula safety

Every string value that can reach the "download this page as CSV" button
(`details`, ids, categories) is passed through
`kpis.sanitize_for_csv_export` first: a value starting with a
formula-trigger character (`=`, `+`, `-`, `@`, tab, or carriage return)
gets a literal leading apostrophe, which every major spreadsheet renders
as plain text rather than evaluating as a formula when the CSV is opened.
This dashboard does not write `.xlsx` files at all (only CSV, via
Streamlit's own download button), so there is no live-formula-cell
concern the way there is in the `excel-consolidation` demo - the CSV
formula-injection vector is the one that applies here, and it is defended
at the same layer the export happens in (`kpis.py`, tested directly).

## How the sample database was produced

See `data/sample/PROVENANCE.md`. In short: the sibling
`revenue-reconciliation` demo (pinned to its commit `144ede0`) was run
once, exactly as its own README documents (`generate` + `reconcile`,
seed 42), and the resulting `reconciliation.duckdb` was copied here as a
committed sample - not fetched or generated across repos at runtime. The
mismatch report that same run wrote was copied alongside as
`known_totals.json`, the independent ground truth this repo's tests
reconcile against.

## QA screenshots

`scripts/screenshot.py` launches the dashboard with `streamlit run` bound
to `127.0.0.1` on a random free port, launches `google-chrome
--headless=new` on a separate random debugging port, drives it over raw
Chrome DevTools Protocol (no Selenium/Playwright) to capture the rendered
page at a 390px-wide phone viewport and a 1440px desktop viewport, then
kills both processes by PID (not by port or name match), including on
error. It needs `google-chrome` on `PATH` and the `websocket-client`
package (`pip install websocket-client`; dev-only, see `LICENSES.md` -
not a runtime dependency of the dashboard or the test suite):

```bash
PYTHONPATH=src python3 scripts/screenshot.py [output_dir]
```

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
scripts/screenshot.py  QA: headless-Chrome/raw-CDP screenshots at 390px and desktop width
data/sample/       vendored sample DuckDB + its known-totals ground truth (see PROVENANCE.md)
docs/schema.md     the DuckDB schema this dashboard reads, reproduced from revenue-reconciliation
LICENSES.md        every open-source library used and its licence
```

## Role

Synthetic portfolio demonstration, implemented with AI coding agents and
independently reviewed by a separate AI reviewer. No client data or
client work.
