"""ETL: clean the raw CSV, then load it into a star-schema SQLite database."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from src import config

REQUIRED_COLUMNS = {"ref_no", "date", "merchant", "category", "payment_method", "amount"}
OUTPUT_COLUMNS = ["ref_no", "date", "merchant", "category", "payment_method", "amount"]


def _auto_ref(row: pd.Series) -> str:
    key = f"{row['date']}|{row['merchant']}|{row['category']}|{row['amount']}"
    return "AUTO-" + hashlib.sha1(key.encode()).hexdigest()[:10]


def clean_transactions(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return (clean_df, stats). Every fix is counted so it can be reported."""
    df = raw.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Raw file is missing required columns: {sorted(missing)}")

    stats: dict[str, int] = {"raw_rows": len(df)}

    for col in ("ref_no", "date", "merchant", "category", "payment_method"):
        df[col] = df[col].fillna("").astype(str).str.strip()

    # rows with no reference number get a deterministic one so de-duplication still works
    blank_ref = df["ref_no"] == ""
    if blank_ref.any():
        df.loc[blank_ref, "ref_no"] = df[blank_ref].apply(_auto_ref, axis=1)

    before = len(df)
    df = df.drop_duplicates(subset="ref_no", keep="first").copy()
    stats["duplicates_removed"] = before - len(df)

    # dates: ISO first, then dd/mm/yyyy fallback
    iso = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    alt = pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce")
    stats["dates_reformatted"] = int((iso.isna() & alt.notna()).sum())
    df["date"] = iso.fillna(alt)

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    bad = df["date"].isna() | df["amount"].isna() | (df["amount"] == 0)
    stats["invalid_rows_dropped"] = int(bad.sum())
    df = df[~bad].copy()

    stats["negative_amounts_fixed"] = int((df["amount"] < 0).sum())
    df["amount"] = df["amount"].abs().round(2)

    canon_cat = {k.lower(): k for k in config.CATEGORY_TYPES}
    mapped = df["category"].str.lower().map(canon_cat)
    stats["categories_normalised"] = int(((mapped != df["category"]) & mapped.notna()).sum())
    stats["uncategorised"] = int(mapped.isna().sum())
    df["category"] = mapped.fillna("Uncategorized")

    canon_pm = {k.lower(): k for k in config.PAYMENT_METHODS}
    pm = df["payment_method"].str.lower().map(canon_pm)
    stats["payment_method_filled"] = int(pm.isna().sum())
    df["payment_method"] = pm.fillna("Unknown")

    stats["merchant_filled"] = int((df["merchant"] == "").sum())
    df.loc[df["merchant"] == "", "merchant"] = "Unknown"

    df = df.sort_values(["date", "ref_no"]).reset_index(drop=True)
    stats["clean_rows"] = len(df)
    return df[OUTPUT_COLUMNS], stats


def build_dim_date(min_date: pd.Timestamp, max_date: pd.Timestamp) -> pd.DataFrame:
    start = min_date.replace(day=1)
    end = (max_date + pd.offsets.MonthEnd(0)).normalize()
    dates = pd.date_range(start, end, freq="D")
    return pd.DataFrame({
        "date_key": dates.strftime("%Y%m%d").astype(int),
        "full_date": dates.strftime("%Y-%m-%d"),
        "year": dates.year,
        "quarter": dates.quarter,
        "month": dates.month,
        "month_name": dates.strftime("%B"),
        "year_month": dates.strftime("%Y-%m"),
        "day": dates.day,
        "day_name": dates.strftime("%A"),
        "is_weekend": (dates.dayofweek >= 5).astype(int),
    })


def load_database(clean: pd.DataFrame, budgets: pd.DataFrame, db_path: Path,
                  schema_path: Path | None = None) -> dict:
    """Create the schema and load all tables. Returns row counts per table."""
    schema_path = schema_path or (config.SQL_DIR / "schema.sql")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    cats = pd.DataFrame({
        "category_id": range(1, len(config.CATEGORY_TYPES) + 1),
        "category_name": list(config.CATEGORY_TYPES),
        "category_type": list(config.CATEGORY_TYPES.values()),
    })
    pms = pd.DataFrame({
        "payment_method_id": range(1, len(config.PAYMENT_METHODS) + 1),
        "payment_method": config.PAYMENT_METHODS,
    })
    dim_date = build_dim_date(clean["date"].min(), clean["date"].max())

    cat_id = dict(zip(cats["category_name"], cats["category_id"]))
    pm_id = dict(zip(pms["payment_method"], pms["payment_method_id"]))

    fact = pd.DataFrame({
        "ref_no": clean["ref_no"],
        "date_key": clean["date"].dt.strftime("%Y%m%d").astype(int),
        "category_id": clean["category"].map(cat_id),
        "payment_method_id": clean["payment_method"].map(pm_id),
        "merchant": clean["merchant"],
        "amount": clean["amount"],
    })

    bud = budgets.copy()
    bud.columns = [c.strip().lower() for c in bud.columns]
    bud["category"] = bud["category"].str.strip()
    bud = pd.DataFrame({
        "category_id": bud["category"].map(cat_id),
        "year_month": bud["year_month"].str.strip(),
        "budget_amount": pd.to_numeric(bud["budget_amount"]),
    }).dropna()
    bud["category_id"] = bud["category_id"].astype(int)

    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(schema_path.read_text())
        conn.execute("PRAGMA foreign_keys = ON")
        cats.to_sql("dim_category", conn, if_exists="append", index=False)
        pms.to_sql("dim_payment_method", conn, if_exists="append", index=False)
        dim_date.to_sql("dim_date", conn, if_exists="append", index=False)
        fact.to_sql("fact_transactions", conn, if_exists="append", index=False)
        bud.to_sql("budgets", conn, if_exists="append", index=False)
        conn.commit()
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("dim_category", "dim_payment_method", "dim_date", "fact_transactions", "budgets")
        }
        fk_problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_problems:
        raise RuntimeError(f"Foreign-key violations found: {fk_problems[:5]}")
    return counts


def run_etl(raw_dir: Path = config.RAW_DIR, db_path: Path = config.DB_PATH) -> tuple[dict, dict]:
    raw_dir = Path(raw_dir)
    raw = pd.read_csv(raw_dir / config.RAW_TRANSACTIONS, dtype=str, keep_default_na=False)
    budgets = pd.read_csv(raw_dir / config.RAW_BUDGETS, dtype=str, keep_default_na=False)
    clean, stats = clean_transactions(raw)
    counts = load_database(clean, budgets, db_path)
    return stats, counts
