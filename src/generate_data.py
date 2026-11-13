"""Generate a realistic, deliberately messy synthetic expense dataset (INR).

Why synthetic?  It lets anyone clone the repo and run it immediately, and it
contains injected data-quality problems (duplicates, mixed casing, missing
values, negative amounts, mixed date formats) so the ETL step has real work to do.

To use YOUR OWN data instead, replace data/raw/transactions_raw.csv with a file
that has the same columns (see README) and run the pipeline without --regenerate.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

SEED = 42
START = date(2025, 11, 1)
END = date(2026, 10, 31)

FOOD = ["Swiggy", "Zomato", "Campus Canteen", "Starbucks", "Chai Point", "Domino's"]
GROCERY = ["BigBasket", "DMart", "Blinkit", "Zepto"]
TRANSPORT = {"Namma Metro": (20, 60), "Rapido": (50, 150), "Uber": (120, 450), "Ola": (110, 400)}
SHOPPING = ["Amazon", "Flipkart", "Myntra", "Decathlon"]
ENTERTAINMENT = ["BookMyShow", "Steam", "PVR Cinemas", "Cafe Outing"]
HEALTH = ["Apollo Pharmacy", "Practo", "MedPlus"]
EDUCATION = ["Udemy", "Coursera", "Amazon Books", "Printout & Stationery"]

# (date, merchant, category, method, amount)
FIXED_EVENTS = [
    (date(2025, 12, 22), "IRCTC", "Travel", "UPI", 2850),
    (date(2026, 1, 2), "RedBus", "Travel", "UPI", 1200),
    (date(2026, 4, 10), "MakeMyTrip", "Travel", "Credit Card", 6400),
    (date(2026, 6, 14), "Ola Outstation", "Travel", "UPI", 2100),
    (date(2026, 10, 20), "IRCTC", "Travel", "UPI", 3100),
    (date(2026, 10, 28), "RedBus", "Travel", "UPI", 1800),
    # genuine one-off large expenses - good targets for anomaly detection
    (date(2026, 7, 18), "Croma Laptop Repair", "Shopping", "Credit Card", 14999),
    (date(2026, 3, 9), "Apollo Hospital", "Health", "Debit Card", 6200),
]


def _method(rng: random.Random, category: str) -> str:
    if category == "Shopping":
        return rng.choices(["UPI", "Credit Card", "Debit Card"], [0.35, 0.45, 0.20])[0]
    return rng.choices(["UPI", "Debit Card", "Cash", "Credit Card"], [0.62, 0.12, 0.13, 0.13])[0]


def _clip(x: float, lo: float, hi: float) -> float:
    return float(min(max(x, lo), hi))


def _build_clean_rows(seed: int, start: date, end: date) -> pd.DataFrame:
    rng = random.Random(seed)
    rows: list[dict] = []

    def add(d: date, merchant: str, category: str, method: str, amount: float) -> None:
        rows.append({
            "ref_no": f"TXN{len(rows) + 1:06d}",
            "date": d.isoformat(),
            "merchant": merchant,
            "category": category,
            "payment_method": method,
            "amount": round(float(amount), 2),
            "notes": "",
        })

    d = start
    while d <= end:
        weekend = d.weekday() >= 5
        festive = 1.8 if d.month in (10, 11) else 1.0  # Diwali / festive shopping

        # ---- income
        if d.day == 1:
            add(d, "Parents Transfer", "Allowance", "Net Banking", 28000)
        if d.day == 28 and date(2026, 3, 1) <= d <= date(2026, 8, 31):
            add(d, "Internship Co.", "Internship Stipend", "Net Banking", 15000)
        if rng.random() < 0.02:
            add(d, "Freelance Client", "Freelance", "UPI", rng.randint(2000, 6000))

        # ---- fixed monthly bills
        if d.day == 3:
            add(d, "PG Rent", "Rent", "UPI", 12000)
        if d.day == 5:
            add(d, "Netflix", "Subscriptions", "Credit Card", 199)
        if d.day == 7:
            add(d, "Spotify", "Subscriptions", "Credit Card", 119)
        if d.day == 10:
            add(d, "Jio Recharge", "Utilities & Bills", "UPI", 299)
        if d.day == 12:
            add(d, "Electricity Share", "Utilities & Bills", "UPI", rng.randint(400, 700))
        if d.day == 15:
            add(d, "WiFi Share", "Utilities & Bills", "UPI", 350)
        if d.day == 20 and rng.random() < 0.8:
            add(d, rng.choice(EDUCATION), "Education", _method(rng, "Education"), rng.randint(300, 1500))

        # ---- variable daily spending
        weights = [0.15, 0.50, 0.35] if weekend else [0.35, 0.50, 0.15]
        for _ in range(rng.choices([0, 1, 2], weights)[0]):
            amt = _clip(rng.lognormvariate(5.3, 0.45) * (1.2 if weekend else 1.0), 60, 1500)
            add(d, rng.choice(FOOD), "Food & Dining", _method(rng, "Food & Dining"), amt)

        if d.weekday() == 6 and rng.random() < 0.9:
            add(d, rng.choice(GROCERY), "Groceries", _method(rng, "Groceries"),
                _clip(rng.lognormvariate(6.5, 0.4), 250, 2500))

        if rng.random() < 0.38:
            merchant = rng.choice(list(TRANSPORT))
            lo, hi = TRANSPORT[merchant]
            add(d, merchant, "Transport", _method(rng, "Transport"), rng.randint(lo, hi))

        if rng.random() < 0.07 * festive:
            add(d, rng.choice(SHOPPING), "Shopping", _method(rng, "Shopping"),
                _clip(rng.lognormvariate(6.8, 0.6), 199, 5000))

        if rng.random() < (0.09 if weekend else 0.04):
            add(d, rng.choice(ENTERTAINMENT), "Entertainment", _method(rng, "Entertainment"),
                rng.randint(150, 900))

        if rng.random() < 0.035:
            add(d, rng.choice(HEALTH), "Health", _method(rng, "Health"), rng.randint(100, 900))

        d += timedelta(days=1)

    for ev_date, merchant, category, method, amount in FIXED_EVENTS:
        if start <= ev_date <= end:
            add(ev_date, merchant, category, method, amount)

    df = pd.DataFrame(rows).sort_values(["date", "ref_no"]).reset_index(drop=True)
    return df


def _inject_noise(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Add realistic data-quality problems for the ETL to fix."""
    nprng = np.random.default_rng(seed)
    df = df.copy()
    n = len(df)

    def pick(frac: float) -> np.ndarray:
        return nprng.choice(n, size=max(1, int(frac * n)), replace=False)

    # bank-style negative signs on some expense rows
    for i in pick(0.03):
        if config.CATEGORY_TYPES.get(df.at[i, "category"]) == "Expense":
            df.at[i, "amount"] = -abs(df.at[i, "amount"])

    # messy category text
    for i in pick(0.03):
        c = df.at[i, "category"]
        df.at[i, "category"] = str(nprng.choice([c.lower(), c.upper(), f" {c} ", c + " "]))

    # missing payment method / merchant
    for i in pick(0.012):
        df.at[i, "payment_method"] = ""
    for i in pick(0.008):
        df.at[i, "merchant"] = ""

    # mixed date format (dd/mm/yyyy)
    for i in pick(0.006):
        y, m, dd = df.at[i, "date"].split("-")
        df.at[i, "date"] = f"{dd}/{m}/{y}"

    # exact duplicate rows (same ref_no) - e.g. a statement imported twice
    dupes = df.iloc[pick(0.015)]
    df = pd.concat([df, dupes], ignore_index=True)
    return df


def _build_budgets(start: date, end: date) -> pd.DataFrame:
    months = pd.period_range(start, end, freq="M")
    rows = [
        {"year_month": str(m), "category": cat, "budget_amount": amt}
        for m in months
        for cat, amt in config.MONTHLY_BUDGETS.items()
    ]
    return pd.DataFrame(rows)


def generate(raw_dir: Path = config.RAW_DIR, seed: int = SEED,
             start: date = START, end: date = END) -> tuple[Path, Path]:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean = _build_clean_rows(seed, start, end)
    noisy = _inject_noise(clean, seed)
    budgets = _build_budgets(start, end)
    tx_path = raw_dir / config.RAW_TRANSACTIONS
    bud_path = raw_dir / config.RAW_BUDGETS
    noisy.to_csv(tx_path, index=False)
    budgets.to_csv(bud_path, index=False)
    return tx_path, bud_path


if __name__ == "__main__":
    tx, bud = generate()
    print(f"Wrote {tx} and {bud}")
