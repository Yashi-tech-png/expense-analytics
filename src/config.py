"""Central configuration: paths and the category / budget definitions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "expenses.db"
SQL_DIR = ROOT / "sql"
EXPORT_DIR = ROOT / "exports"
REPORT_DIR = ROOT / "reports"

RAW_TRANSACTIONS = "transactions_raw.csv"
RAW_BUDGETS = "budgets.csv"

# category -> type. "Uncategorized" is the fallback bucket used by the ETL.
CATEGORY_TYPES = {
    "Rent": "Expense",
    "Food & Dining": "Expense",
    "Groceries": "Expense",
    "Transport": "Expense",
    "Entertainment": "Expense",
    "Shopping": "Expense",
    "Utilities & Bills": "Expense",
    "Health": "Expense",
    "Education": "Expense",
    "Travel": "Expense",
    "Subscriptions": "Expense",
    "Uncategorized": "Expense",
    "Allowance": "Income",
    "Internship Stipend": "Income",
    "Freelance": "Income",
}

PAYMENT_METHODS = ["UPI", "Credit Card", "Debit Card", "Cash", "Net Banking", "Unknown"]

# Monthly budget per expense category (INR)
MONTHLY_BUDGETS = {
    "Rent": 12000,
    "Food & Dining": 6000,
    "Groceries": 3500,
    "Transport": 2000,
    "Entertainment": 1500,
    "Shopping": 3000,
    "Utilities & Bills": 1800,
    "Health": 1000,
    "Education": 2000,
    "Travel": 2500,
    "Subscriptions": 400,
}
