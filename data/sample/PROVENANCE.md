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
`known_totals.json` - the independent ground truth this repo's tests
reconcile the dashboard's own KPI computation against (see
`tests/test_kpis.py`).

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
records one open finding in that repo: its mock-orders-API pagination
client can under-count a truncated final page instead of marking the run
incomplete. It does not affect this sample - the fixture-backed generator
run above delivers every page in full and the run is genuinely
`complete` - and it is a defect in that repository's ingestion, not in
this dashboard's KPI computation or the schema it reads. This dashboard
does not re-implement or re-verify that pipeline; it only reads its
documented DuckDB output and displays the `runs.status` it finds exactly
as written, including showing an `incomplete` run as incomplete were the
sample ever regenerated from a run affected by that bug.
