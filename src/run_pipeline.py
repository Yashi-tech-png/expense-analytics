"""One command to run everything:  python -m src.run_pipeline

    --regenerate   re-create the synthetic raw data before running
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src import analysis, config, etl, generate_data


def run(regenerate: bool = False, raw_dir: Path = config.RAW_DIR, db_path: Path = config.DB_PATH,
        export_dir: Path = config.EXPORT_DIR, report_dir: Path = config.REPORT_DIR,
        verbose: bool = True) -> dict:
    raw_dir = Path(raw_dir)
    log = print if verbose else (lambda *a, **k: None)

    tx_file = raw_dir / config.RAW_TRANSACTIONS
    if regenerate or not tx_file.exists():
        log("[1/3] Generating synthetic raw data ...")
        generate_data.generate(raw_dir)
    else:
        log(f"[1/3] Using existing raw data: {tx_file}")

    log("[2/3] ETL: cleaning and loading SQLite ...")
    stats, counts = etl.run_etl(raw_dir, db_path)
    for k, v in stats.items():
        log(f"      {k:<24} {v}")
    log(f"      tables loaded: {counts}")

    log("[3/3] Analysis: SQL queries, charts, exports, insights ...")
    summary = analysis.run_analysis(db_path, export_dir, report_dir)
    log(f"      income {summary['total_income']:,.0f} | expense {summary['total_expense']:,.0f} "
        f"| savings rate {summary['savings_rate_pct']}%")
    log(f"      {summary['figures']} charts, {summary['exports']} CSV exports, "
        f"{summary['anomalies']} anomalies flagged")
    log("Done. See reports/insights.md, reports/figures/ and exports/.")
    return {"etl_stats": stats, "table_counts": counts, **summary}


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal Expense Analytics pipeline")
    parser.add_argument("--regenerate", action="store_true", help="regenerate synthetic raw data")
    args = parser.parse_args()
    run(regenerate=args.regenerate)


if __name__ == "__main__":
    main()
