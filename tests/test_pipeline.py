"""Automated checks that the whole pipeline works and the numbers reconcile."""
import sqlite3
from contextlib import closing

import pandas as pd
import pytest

from src import analysis, etl, run_pipeline


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    base = tmp_path_factory.mktemp("run")
    result = run_pipeline.run(
        regenerate=True,
        raw_dir=base / "raw",
        db_path=base / "expenses.db",
        export_dir=base / "exports",
        report_dir=base / "reports",
        verbose=False,
    )
    return base, result


def _query(db, sql):
    with closing(sqlite3.connect(db)) as conn:
        return pd.read_sql_query(sql, conn)


# ---------------------------------------------------------------- cleaning rules
def test_clean_transactions_fixes_known_problems():
    raw = pd.DataFrame({
        "ref_no": ["A1", "A1", "A2", "A3", "A4", ""],
        "date": ["2026-01-05", "2026-01-05", "06/01/2026", "not a date", "2026-01-08", "2026-01-09"],
        "merchant": ["Swiggy", "Swiggy", "", "X", "Uber", "Amazon"],
        "category": ["  food & dining ", "  food & dining ", "TRANSPORT", "Rent", "mystery", "Shopping"],
        "payment_method": ["upi", "upi", "", "UPI", "Cash", "Credit Card"],
        "amount": ["-250.50", "-250.50", "120", "5000", "80", "999"],
    })
    clean, stats = etl.clean_transactions(raw)

    assert stats["duplicates_removed"] == 1
    assert stats["dates_reformatted"] == 1
    assert stats["invalid_rows_dropped"] == 1            # "not a date"
    assert stats["negative_amounts_fixed"] == 1
    assert (clean["amount"] > 0).all()
    assert clean["ref_no"].is_unique
    assert set(clean["category"]) <= {"Food & Dining", "Transport", "Uncategorized", "Shopping"}
    assert "Unknown" in set(clean["payment_method"])
    assert "Unknown" in set(clean["merchant"])


def test_missing_columns_raise():
    with pytest.raises(ValueError):
        etl.clean_transactions(pd.DataFrame({"date": ["2026-01-01"], "amount": [1]}))


# ---------------------------------------------------------------- database
def test_tables_loaded_and_no_duplicates(pipeline):
    base, result = pipeline
    counts = result["table_counts"]
    assert counts["fact_transactions"] > 500
    assert counts["dim_date"] >= 365
    dup = _query(base / "expenses.db",
                 "SELECT COUNT(*) - COUNT(DISTINCT ref_no) AS d FROM fact_transactions")
    assert dup["d"].iloc[0] == 0


def test_monthly_summary_reconciles_with_fact_table(pipeline):
    base, _ = pipeline
    db = base / "expenses.db"
    summary = _query(db, "SELECT SUM(total_income) AS i, SUM(total_expense) AS e, SUM(net_savings) AS n "
                         "FROM vw_monthly_summary").iloc[0]
    direct = _query(db, "SELECT SUM(signed_amount) AS n FROM vw_transactions_enriched").iloc[0]
    assert abs(summary["n"] - direct["n"]) < 0.5
    assert abs((summary["i"] - summary["e"]) - summary["n"]) < 0.5


def test_budget_view_covers_every_budget_row(pipeline):
    base, result = pipeline
    n = _query(base / "expenses.db", "SELECT COUNT(*) AS n FROM vw_budget_vs_actual")["n"].iloc[0]
    assert n == result["table_counts"]["budgets"]


# ---------------------------------------------------------------- SQL file
def test_every_named_query_runs(pipeline):
    base, _ = pipeline
    queries = analysis.load_queries()
    assert len(queries) >= 10
    with closing(sqlite3.connect(base / "expenses.db")) as conn:
        for name in queries:
            df = analysis.run_query(conn, queries, name)
            assert len(df) > 0, f"query '{name}' returned no rows"


# ---------------------------------------------------------------- outputs
def test_outputs_exist(pipeline):
    base, _ = pipeline
    for f in ("transactions.csv", "monthly_summary.csv", "budget_vs_actual.csv",
              "dim_category.csv", "dim_date.csv", "anomalies.csv"):
        assert (base / "exports" / f).stat().st_size > 0, f
    assert (base / "reports" / "insights.md").stat().st_size > 0
    assert len(list((base / "reports" / "figures").glob("*.png"))) == 6


def test_forecast_shape():
    monthly = pd.DataFrame({"year_month": ["2026-01", "2026-02", "2026-03", "2026-04"],
                            "total_expense": [100.0, 110.0, 120.0, 130.0]})
    f = analysis.forecast_next_month(monthly)
    assert f["next_month"] == "2026-05"
    assert f["moving_avg_3m"] == 120.0
    assert abs(f["linear_trend"] - 140.0) < 1e-6
