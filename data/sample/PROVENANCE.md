# Sample database provenance

`reconciliation.duckdb` in this directory is a **vendored, committed
sample** - not generated at runtime by this repo, and not fetched from
another repo at runtime. That keeps this dashboard runnable and testable
standalone with nothing outside this repo on the path.

It was produced by running the sibling `revenue-reconciliation` demo
(pinned to its commit `144ede0`) exactly as documented in that repo's
README:

```bash
cd revenue-reconciliation   # commit 144ede0
source .venv/bin/activate
export PYTHONPATH=src
python -m revenue_reconciliation run --raw-dir data/raw --out data/output --seed 42
```

That produced a `complete` run (`run-20260927T042318`) over the
generator's deterministic seed-42 synthetic corpus (130 orders, 122
payments, 14 refunds) with its usual planted mismatches. The resulting
`data/output/reconciliation.duckdb` was copied here unmodified, and its
`data/output/mismatch_report.json` was copied alongside as
`known_totals.json` - a consistency reference this repo's tests reconcile
the dashboard's own KPI computation against (see `tests/test_kpis.py`).
It is the report the *same* reconciliation run wrote about itself, not a
result computed by a separate or independent process; agreement between
`known_totals.json` and this dashboard's SQL confirms the dashboard's
queries reproduce that run's own numbers exactly, it does not confirm the
upstream reconciliation logic itself was correct.

## Regenerating

This file documents a pinned, reproducible dependency step, not a live
cross-repo call: to regenerate the sample from scratch, check out
`revenue-reconciliation` at `144ede0`, run the command above with
`--seed 42`, and copy `reconciliation.duckdb` / `mismatch_report.json`
(renamed to `known_totals.json`) into this directory. Nothing in
`src/kpi_dashboard` or `tests/` reaches into that other repo at import
time or at test time - both only ever open the DuckDB file already
sitting in this directory.

## Known upstream limitation (not in this dashboard's scope)

As of `144ede0`, `revenue-reconciliation`'s own frozen acceptance list
(`vault/40-sessions/2026-09-27-astra-revenue-reconciliation-frozen-check.md`)
records one open finding in that repo (frozen item 2): its mock-orders-API
pagination client does not bind the expected total record count and page
size from the first page - it instead compares its running delivered
count against whatever total each subsequent page freshly reports, so a
mock API that changes its advertised total partway through a paginated
response (e.g. a genuine page-1 total of 3 followed by a page-2 total of
2) is accepted as a complete, uneventful fetch instead of being flagged
`incomplete`/`malformed_response`. Simple truncation of the final page is
already detected by that repo's existing probes; this is a narrower,
still-open case about pagination *metadata* changing mid-fetch, not about
missing pages.

It does not affect this vendored sample - the fixture-backed generator run
above delivers every page in full, with consistent metadata throughout,
and the run is genuinely `complete` - and it is a defect in that
repository's ingestion, not in this dashboard's KPI computation or the
schema it reads. This dashboard does not re-implement or re-verify that
pipeline; it only reads its documented DuckDB output and displays the
`runs.status` it finds exactly as written. That is also this limitation's
practical effect here: if that upstream bug ever caused a future run to
silently under-count while still being written as `runs.status =
'complete'`, this dashboard has no independent way to detect that and
would display it as complete too, unchanged - it is a status-only reader
of whatever the upstream pipeline decided, not a re-verification of that
decision.
