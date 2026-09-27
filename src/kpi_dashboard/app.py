"""Streamlit UI for the revenue-reconciliation KPI dashboard.

All computation lives in :mod:`kpi_dashboard.kpis` (pure, unit tested).
This module only renders what that module returns - it never computes a
total, never re-derives a currency-summed figure, and never decides a run
is "complete" itself (it only reflects ``kpis.is_incomplete``).
"""

from __future__ import annotations

import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from kpi_dashboard import kpis

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "sample" / "reconciliation.duckdb"

# Fixed categorical color order (dataviz skill's validated 3-slot palette,
# all-pairs colorblind-safe): assigned by currency identity, never by rank,
# so a filter that hides a currency never repaints the ones left on screen.
CURRENCY_COLORS = {
    "USD": "#2a78d6",  # blue
    "EUR": "#eb6834",  # orange
    "GBP": "#1baf7a",  # aqua
}
CURRENCY_ORDER = ["USD", "EUR", "GBP"]

METRICS = {
    "Gross": "gross_cents",
    "Net": "net_cents",
    "Refunds": "refunds_cents",
    "Paid": "paid_cents",
    "Ordered": "ordered_cents",
    "Unmatched": "unmatched_cents",
}

CATEGORY_LABELS = {
    "missing_payment": "Missing payment",
    "overpayment": "Overpayment",
    "orphan_refund": "Orphan refund",
    "currency_mismatch": "Currency mismatch",
    "duplicate": "Duplicate payment",
    "indeterminate_incomplete_source": "Indeterminate (incomplete source)",
}


def _money(cents: int) -> str:
    return kpis.format_cents(cents)


def _db_path() -> Path:
    return Path(os.environ.get("KPI_DASHBOARD_DB", str(DEFAULT_DB)))


def render() -> None:
    st.set_page_config(page_title="Revenue KPI Dashboard", layout="wide")
    st.title("Revenue reconciliation KPI dashboard")
    st.caption(
        "Synthetic portfolio demonstration, implemented with AI coding agents "
        "and independently reviewed by a separate AI reviewer. No client data "
        "or client work."
    )

    db_path = _db_path()
    try:
        con = kpis.open_database(db_path)
    except kpis.SchemaError as exc:
        st.error(f"Cannot open the reconciliation database.\n\n{exc}")
        st.stop()
        return

    try:
        runs = kpis.list_runs(con)
        if not runs:
            st.error("The database has no committed run in its `runs` table. Nothing to show.")
            st.stop()
            return

        with st.sidebar:
            st.header("Run")
            run_labels = [f"{r['run_id']}  ({r['status']})" for r in runs]
            selected = st.selectbox("Select a run", options=range(len(runs)), format_func=lambda i: run_labels[i])
            run_row = runs[selected]
            st.caption(f"DB: `{db_path}`")

        run_id = run_row["run_id"]

        # --- Completeness banner: never show an incomplete run as complete ---
        if kpis.is_incomplete(run_row):
            missing = kpis.incomplete_source_list(run_row)
            missing_txt = ", ".join(missing) if missing else "unspecified source(s)"
            st.error(
                f"**Data completeness: {run_row['status'].upper()}** - "
                f"source(s) not fully ingested this run: {missing_txt}. "
                f"{run_row['issue_count']} ingestion issue(s) recorded. "
                "Figures below exclude anything the run could not determine "
                "(see `indeterminate_incomplete_source` in the mismatch table) "
                "rather than guessing at a complete picture."
            )
        else:
            st.success(f"Data completeness: COMPLETE - all sources fully ingested (run `{run_id}`).")

        st.caption(f"Run at {run_row['run_at']} UTC · source: `{run_row['source_note']}`")

        # --- KPI summary, per currency, never summed across currencies ---
        st.subheader("KPIs by currency")
        summary = kpis.kpi_summary(con, run_id)
        currencies_present = [c for c in CURRENCY_ORDER if c in summary] + [
            c for c in summary if c not in CURRENCY_ORDER
        ]
        if not currencies_present:
            st.info("No daily KPI rows for this run.")
        for currency in currencies_present:
            row = summary[currency]
            st.markdown(f"**{currency}**")
            cols = st.columns(6)
            cols[0].metric("Gross", _money(row["gross_cents"]))
            cols[1].metric("Net", _money(row["net_cents"]))
            cols[2].metric("Refunds", _money(row["refunds_cents"]))
            cols[3].metric("Paid", _money(row["paid_cents"]))
            cols[4].metric("Ordered", _money(row["ordered_cents"]))
            cols[5].metric(
                "Unmatched",
                _money(row["unmatched_cents"]),
                help=f"{row['unmatched_count']} unmatched payment(s) - see 'Currency is never summed' in the README",
            )
        st.caption(
            "Each currency's totals are independent - amounts are never added "
            "together across currencies (no FX conversion anywhere in this demo)."
        )

        # --- Mismatch counts/amounts by category, per currency ---
        st.subheader("Mismatches by category")
        mm = kpis.mismatch_summary(con, run_id)
        table_rows = []
        for category in kpis.MISMATCH_CATEGORIES:
            per_currency = mm.get(category, {})
            if not per_currency:
                table_rows.append({"Category": CATEGORY_LABELS[category], "Currency": "-", "Count": 0, "Amount": "0.00"})
                continue
            for currency, agg in sorted(per_currency.items()):
                table_rows.append(
                    {
                        "Category": CATEGORY_LABELS[category],
                        "Currency": currency,
                        "Count": agg["count"],
                        "Amount": _money(agg["amount_cents"]),
                    }
                )
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        # --- Daily trend chart ---
        st.subheader("Daily trend")
        trend = kpis.daily_trend(con, run_id)
        if trend:
            metric_label = st.selectbox("Metric", options=list(METRICS.keys()))
            metric_col = METRICS[metric_label]
            df = pd.DataFrame(trend)
            df["amount"] = df[metric_col] / 100.0
            df["day"] = pd.to_datetime(df["day"])
            domain = [c for c in CURRENCY_ORDER if c in df["currency"].unique()]
            range_ = [CURRENCY_COLORS[c] for c in domain]
            chart = (
                alt.Chart(df)
                .mark_line(point=True, strokeWidth=2)
                .encode(
                    x=alt.X("day:T", title="Day"),
                    y=alt.Y("amount:Q", title=f"{metric_label} (per currency, not summed)"),
                    color=alt.Color("currency:N", scale=alt.Scale(domain=domain, range=range_), title="Currency"),
                    tooltip=[
                        alt.Tooltip("day:T", title="Day"),
                        alt.Tooltip("currency:N", title="Currency"),
                        alt.Tooltip("amount:Q", title=metric_label, format=",.2f"),
                    ],
                )
                .properties(height=360)
                .interactive()
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No daily KPI rows for this run.")

        # --- Mismatch drill-down, paginated ---
        st.subheader("Mismatch drill-down")
        filter_cols = st.columns(3)
        category_filter = filter_cols[0].selectbox(
            "Category", options=["(all)"] + list(kpis.MISMATCH_CATEGORIES),
            format_func=lambda c: "(all)" if c == "(all)" else CATEGORY_LABELS[c],
        )
        currency_filter = filter_cols[1].selectbox("Currency", options=["(all)"] + currencies_present)
        page_size = filter_cols[2].selectbox("Rows per page", options=[10, 25, 50, 100], index=1)

        query_key = kpis.mismatch_query_key(
            run_id,
            category=None if category_filter == "(all)" else category_filter,
            currency=None if currency_filter == "(all)" else currency_filter,
            limit=page_size,
        )
        offset = kpis.resolve_page_offset(
            st.session_state.get("mismatch_page_offset", 0),
            st.session_state.get("mismatch_query_key"),
            query_key,
        )
        st.session_state.mismatch_page_offset = offset
        st.session_state.mismatch_query_key = query_key

        page = kpis.mismatch_page(
            con,
            run_id,
            category=None if category_filter == "(all)" else category_filter,
            currency=None if currency_filter == "(all)" else currency_filter,
            offset=offset,
            limit=page_size,
        )

        nav_cols = st.columns([1, 1, 4])
        if nav_cols[0].button("Previous", disabled=page.offset == 0):
            st.session_state.mismatch_page_offset = max(0, page.offset - page.limit)
            st.rerun()
        if nav_cols[1].button("Next", disabled=not page.has_more):
            st.session_state.mismatch_page_offset = page.offset + page.limit
            st.rerun()

        end = page.offset + page.returned_count
        start = page.offset + 1 if page.returned_count else 0
        st.caption(f"Showing {start}-{end} of {page.total_count} mismatch(es).")

        if page.rows:
            drill_df = pd.DataFrame(page.rows)
            drill_df["amount"] = drill_df.apply(
                lambda r: f"{r['currency']} {_money(r['amount_cents'])}", axis=1
            )
            drill_df["category"] = drill_df["category"].map(CATEGORY_LABELS)
            display_df = drill_df[["id", "category", "day", "order_id", "payment_id", "refund_id", "amount", "details"]]
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            export_df = display_df.copy()
            for col in export_df.columns:
                export_df[col] = export_df[col].map(kpis.sanitize_for_csv_export)
            st.download_button(
                "Download this page as CSV",
                data=export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"mismatches_{run_id}_offset{page.offset}.csv",
                mime="text/csv",
            )
        else:
            st.info("No mismatches match this filter.")

        with st.expander("Run issues (ingestion problems for this run)"):
            issues = kpis.run_issues(con, run_id)
            if issues:
                st.dataframe(pd.DataFrame(issues), use_container_width=True, hide_index=True)
            else:
                st.caption("No ingestion issues recorded for this run.")
    finally:
        con.close()


if __name__ == "__main__":
    render()
