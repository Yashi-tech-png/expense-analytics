"""Analysis layer: runs the named SQL queries, builds charts, anomaly flags,
a simple spend forecast, Power BI export files and a written insights report."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless - works on servers / CI
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config  # noqa: E402

BLUE, ORANGE, GREEN, GREY = "#2F6DB5", "#E8833A", "#3A9D6E", "#8A8F98"
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ------------------------------------------------------------------ SQL helpers
def load_queries(path: Path | None = None) -> dict[str, str]:
    """Parse sql/analysis_queries.sql into {name: sql} using '-- name:' markers."""
    path = path or (config.SQL_DIR / "analysis_queries.sql")
    queries: dict[str, str] = {}
    name, buf = None, []
    for line in Path(path).read_text().splitlines():
        if line.startswith("-- name:"):
            if name:
                queries[name] = "\n".join(buf).strip()
            name, buf = line.split(":", 1)[1].strip(), []
        elif name is not None:
            buf.append(line)
    if name:
        queries[name] = "\n".join(buf).strip()
    return queries


def run_query(conn: sqlite3.Connection, queries: dict[str, str], name: str) -> pd.DataFrame:
    return pd.read_sql_query(queries[name], conn)


# ------------------------------------------------------------------ analytics
def detect_anomalies(conn: sqlite3.Connection, z_threshold: float = 3.0) -> pd.DataFrame:
    """Flag expenses that are unusually large for their category (z-score)."""
    tx = pd.read_sql_query(
        "SELECT txn_date, category_name, merchant, payment_method, amount "
        "FROM vw_transactions_enriched WHERE category_type = 'Expense'", conn)
    g = tx.groupby("category_name")["amount"]
    tx["category_mean"] = g.transform("mean").round(2)
    tx["category_std"] = g.transform("std")
    tx["category_txns"] = g.transform("count")
    tx["z_score"] = (tx["amount"] - tx["category_mean"]) / tx["category_std"]
    out = tx[(tx["category_txns"] >= 8) & (tx["category_std"] > 0) & (tx["z_score"] > z_threshold)].copy()
    out["z_score"] = out["z_score"].round(2)
    return (out.drop(columns=["category_std", "category_txns"])
               .sort_values("z_score", ascending=False).reset_index(drop=True))


def forecast_next_month(monthly: pd.DataFrame) -> dict:
    """Two transparent baselines: 3-month moving average and a linear trend."""
    y = monthly["total_expense"].to_numpy(dtype=float)
    x = np.arange(len(y))
    slope, intercept = np.polyfit(x, y, 1) if len(y) >= 2 else (0.0, float(y.mean()))
    next_label = str(pd.Period(monthly["year_month"].iloc[-1], freq="M") + 1)
    return {
        "next_month": next_label,
        "moving_avg_3m": round(float(y[-3:].mean()), 2),
        "linear_trend": round(float(slope * len(y) + intercept), 2),
        "trend_slope_per_month": round(float(slope), 2),
    }


# ------------------------------------------------------------------ charts
def _save(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def make_charts(data: dict[str, pd.DataFrame], forecast: dict, fig_dir: Path) -> list[Path]:
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # 1. income vs expense
    m = data["monthly_summary"]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    x = np.arange(len(m))
    ax.bar(x - 0.2, m["total_income"], 0.4, label="Income", color=GREEN)
    ax.bar(x + 0.2, m["total_expense"], 0.4, label="Expense", color=ORANGE)
    ax.plot(x, m["net_savings"], color=BLUE, marker="o", label="Net savings")
    ax.set_xticks(x, m["year_month"], rotation=45, ha="right")
    ax.set_title("Monthly income vs expense (INR)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    p = fig_dir / "01_monthly_income_vs_expense.png"
    _save(fig, p); paths.append(p)

    # 2. category share
    c = data["category_spend"].sort_values("total_spend")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(c["category_name"], c["total_spend"], color=BLUE)
    for i, (v, pct) in enumerate(zip(c["total_spend"], c["pct_of_spend"])):
        ax.text(v, i, f"  {pct}%", va="center", fontsize=8)
    ax.set_title("Where the money goes: spend by category (INR)")
    ax.margins(x=0.12)
    p = fig_dir / "02_spend_by_category.png"
    _save(fig, p); paths.append(p)

    # 3. budget vs actual
    b = data["budget_summary"].sort_values("total_actual")
    fig, ax = plt.subplots(figsize=(8, 5))
    y = np.arange(len(b))
    ax.barh(y - 0.2, b["total_budget"], 0.4, label="Budget", color=GREY)
    ax.barh(y + 0.2, b["total_actual"], 0.4, label="Actual", color=ORANGE)
    ax.set_yticks(y, b["category_name"])
    ax.set_title("Budget vs actual by category (12 months, INR)")
    ax.legend()
    p = fig_dir / "03_budget_vs_actual.png"
    _save(fig, p); paths.append(p)

    # 4. weekday pattern
    w = data["weekday_pattern"].set_index("day_name").reindex(DAY_ORDER).reset_index()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(w["day_name"].str[:3], w["total_spend"], color=BLUE)
    ax.set_title("Total spend by day of week (INR)")
    ax.grid(axis="y", alpha=0.3)
    p = fig_dir / "04_weekday_spend.png"
    _save(fig, p); paths.append(p)

    # 5. cumulative savings
    r = data["running_savings"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(r["year_month"], r["cumulative_savings"], marker="o", color=GREEN)
    ax.fill_between(r["year_month"], r["cumulative_savings"], alpha=0.15, color=GREEN)
    ax.set_xticks(range(len(r)), r["year_month"], rotation=45, ha="right")
    ax.set_title("Cumulative savings (INR)")
    ax.grid(alpha=0.3)
    p = fig_dir / "05_cumulative_savings.png"
    _save(fig, p); paths.append(p)

    # 6. expense trend + forecast
    fig, ax = plt.subplots(figsize=(9, 4.5))
    labels = list(m["year_month"]) + [forecast["next_month"]]
    ax.plot(range(len(m)), m["total_expense"], marker="o", color=ORANGE, label="Actual")
    ax.scatter([len(m)], [forecast["moving_avg_3m"]], color=BLUE, zorder=3, label="Forecast: 3-mo moving avg")
    ax.scatter([len(m)], [forecast["linear_trend"]], color=GREEN, marker="s", zorder=3, label="Forecast: linear trend")
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_title("Monthly expense trend and next-month forecast (INR)")
    ax.legend()
    ax.grid(alpha=0.3)
    p = fig_dir / "06_expense_forecast.png"
    _save(fig, p); paths.append(p)
    return paths


# ------------------------------------------------------------------ exports + report
def export_for_powerbi(conn: sqlite3.Connection, anomalies: pd.DataFrame, export_dir: Path) -> list[Path]:
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "transactions.csv": "SELECT * FROM vw_transactions_enriched ORDER BY txn_date, transaction_id",
        "monthly_summary.csv": "SELECT * FROM vw_monthly_summary ORDER BY year_month",
        "budget_vs_actual.csv": "SELECT * FROM vw_budget_vs_actual ORDER BY year_month, category_name",
        "dim_category.csv": "SELECT category_name, category_type FROM dim_category",
        "dim_date.csv": "SELECT * FROM dim_date ORDER BY date_key",
    }
    out = []
    for fname, sql in tables.items():
        pd.read_sql_query(sql, conn).to_csv(export_dir / fname, index=False)
        out.append(export_dir / fname)
    anomalies.to_csv(export_dir / "anomalies.csv", index=False)
    out.append(export_dir / "anomalies.csv")
    return out


def write_insights(data: dict[str, pd.DataFrame], anomalies: pd.DataFrame,
                   forecast: dict, path: Path) -> dict:
    m = data["monthly_summary"]
    cat = data["category_spend"]
    bud = data["budget_summary"]
    wk = data["weekend_vs_weekday"].set_index("day_type")
    pay = data["payment_split"]

    total_income = float(m["total_income"].sum())
    total_expense = float(m["total_expense"].sum())
    savings_rate = 100 * (total_income - total_expense) / total_income
    top_cat = cat.iloc[0]
    worst_bud = bud.iloc[0]
    peak = m.loc[m["total_expense"].idxmax()]
    low = m.loc[m["total_expense"].idxmin()]
    wkend = wk.loc["Weekend", "avg_spend_per_active_day"]
    wkday = wk.loc["Weekday", "avg_spend_per_active_day"]
    over = bud[bud["months_over_budget"] > 0]

    lines = [
        "# Insights report",
        "",
        f"Period analysed: **{m['year_month'].iloc[0]} to {m['year_month'].iloc[-1]}** "
        f"({len(m)} months). All amounts in INR.",
        "",
        "## Headline numbers",
        f"- Total income: **{total_income:,.0f}**; total expenses: **{total_expense:,.0f}**; "
        f"net savings: **{total_income - total_expense:,.0f}** (savings rate **{savings_rate:.1f}%**).",
        f"- Highest-spend month: **{peak['year_month']}** ({peak['total_expense']:,.0f}); "
        f"lowest: **{low['year_month']}** ({low['total_expense']:,.0f}).",
        "",
        "## Spending behaviour",
        f"- Biggest category: **{top_cat['category_name']}** at {top_cat['pct_of_spend']}% of spend.",
        f"- Average spend per active day is {wkend:,.0f} on weekends vs {wkday:,.0f} on weekdays.",
        f"- Most-used payment method by value: **{pay.iloc[0]['payment_method']}** "
        f"({pay.iloc[0]['pct_of_spend']}% of spend).",
        "",
        "## Budget discipline",
        f"- Highest budget utilisation: **{worst_bud['category_name']}** at {worst_bud['utilisation_pct']}% "
        f"(over budget in {int(worst_bud['months_over_budget'])} of {len(m)} months).",
        f"- Categories that went over budget in at least one month: "
        f"{', '.join(over['category_name']) if len(over) else 'none'}.",
        "",
        "## Anomalies",
        f"- {len(anomalies)} transactions flagged as unusually large for their category (z-score > 3).",
    ]
    for _, r in anomalies.head(5).iterrows():
        lines.append(f"  - {r['txn_date']}: {r['merchant']} ({r['category_name']}) - {r['amount']:,.0f} "
                     f"(z = {r['z_score']})")
    lines += [
        "",
        "## Forecast for next month",
        f"- {forecast['next_month']}: about **{forecast['moving_avg_3m']:,.0f}** (3-month moving average) "
        f"or **{forecast['linear_trend']:,.0f}** (linear trend, slope {forecast['trend_slope_per_month']:+,.0f}/month).",
        "- These are simple baselines meant to show the method, not a precise prediction.",
        "",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "savings_rate_pct": round(savings_rate, 1),
        "top_category": top_cat["category_name"],
        "anomalies": len(anomalies),
    }


def run_analysis(db_path: Path = config.DB_PATH, export_dir: Path = config.EXPORT_DIR,
                 report_dir: Path = config.REPORT_DIR) -> dict:
    report_dir = Path(report_dir)
    queries = load_queries()
    with closing(sqlite3.connect(db_path)) as conn:
        data = {name: run_query(conn, queries, name) for name in queries}
        anomalies = detect_anomalies(conn)
        forecast = forecast_next_month(data["monthly_summary"])
        figs = make_charts(data, forecast, report_dir / "figures")
        exports = export_for_powerbi(conn, anomalies, export_dir)
    summary = write_insights(data, anomalies, forecast, report_dir / "insights.md")
    summary.update({"figures": len(figs), "exports": len(exports), "forecast": forecast})
    return summary
