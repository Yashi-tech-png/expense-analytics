-- Star-schema for personal expense analytics (SQLite).
-- Re-running this file rebuilds the database from scratch.
PRAGMA foreign_keys = OFF;

DROP VIEW  IF EXISTS vw_budget_vs_actual;
DROP VIEW  IF EXISTS vw_monthly_summary;
DROP VIEW  IF EXISTS vw_transactions_enriched;
DROP TABLE IF EXISTS fact_transactions;
DROP TABLE IF EXISTS budgets;
DROP TABLE IF EXISTS dim_payment_method;
DROP TABLE IF EXISTS dim_category;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_category (
    category_id   INTEGER PRIMARY KEY,
    category_name TEXT NOT NULL UNIQUE,
    category_type TEXT NOT NULL CHECK (category_type IN ('Income', 'Expense'))
);

CREATE TABLE dim_payment_method (
    payment_method_id INTEGER PRIMARY KEY,
    payment_method    TEXT NOT NULL UNIQUE
);

CREATE TABLE dim_date (
    date_key   INTEGER PRIMARY KEY,          -- YYYYMMDD
    full_date  TEXT    NOT NULL UNIQUE,      -- YYYY-MM-DD
    year       INTEGER NOT NULL,
    quarter    INTEGER NOT NULL,
    month      INTEGER NOT NULL,
    month_name TEXT    NOT NULL,
    year_month TEXT    NOT NULL,             -- YYYY-MM
    day        INTEGER NOT NULL,
    day_name   TEXT    NOT NULL,
    is_weekend INTEGER NOT NULL CHECK (is_weekend IN (0, 1))
);

CREATE TABLE fact_transactions (
    transaction_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_no            TEXT    NOT NULL UNIQUE,
    date_key          INTEGER NOT NULL REFERENCES dim_date (date_key),
    category_id       INTEGER NOT NULL REFERENCES dim_category (category_id),
    payment_method_id INTEGER NOT NULL REFERENCES dim_payment_method (payment_method_id),
    merchant          TEXT    NOT NULL,
    amount            REAL    NOT NULL CHECK (amount > 0)   -- always positive; type comes from category
);

CREATE TABLE budgets (
    budget_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id   INTEGER NOT NULL REFERENCES dim_category (category_id),
    year_month    TEXT    NOT NULL,
    budget_amount REAL    NOT NULL CHECK (budget_amount >= 0),
    UNIQUE (category_id, year_month)
);

CREATE INDEX idx_fact_date     ON fact_transactions (date_key);
CREATE INDEX idx_fact_category ON fact_transactions (category_id);

-- ---------------------------------------------------------------- views
CREATE VIEW vw_transactions_enriched AS
SELECT
    f.transaction_id,
    f.ref_no,
    d.full_date  AS txn_date,
    d.year,
    d.quarter,
    d.month,
    d.month_name,
    d.year_month,
    d.day_name,
    d.is_weekend,
    c.category_name,
    c.category_type,
    p.payment_method,
    f.merchant,
    f.amount,
    CASE WHEN c.category_type = 'Income' THEN f.amount ELSE -f.amount END AS signed_amount
FROM fact_transactions f
JOIN dim_date           d ON d.date_key = f.date_key
JOIN dim_category       c ON c.category_id = f.category_id
JOIN dim_payment_method p ON p.payment_method_id = f.payment_method_id;

CREATE VIEW vw_monthly_summary AS
WITH m AS (
    SELECT
        year_month,
        SUM(CASE WHEN category_type = 'Income'  THEN amount ELSE 0 END) AS income,
        SUM(CASE WHEN category_type = 'Expense' THEN amount ELSE 0 END) AS expense
    FROM vw_transactions_enriched
    GROUP BY year_month
)
SELECT
    year_month,
    ROUND(income, 2)            AS total_income,
    ROUND(expense, 2)           AS total_expense,
    ROUND(income - expense, 2)  AS net_savings,
    ROUND(100.0 * (income - expense) / NULLIF(income, 0), 1) AS savings_rate_pct
FROM m;

CREATE VIEW vw_budget_vs_actual AS
WITH actual AS (
    SELECT year_month, category_name, SUM(amount) AS actual_spend
    FROM vw_transactions_enriched
    WHERE category_type = 'Expense'
    GROUP BY year_month, category_name
)
SELECT
    b.year_month,
    DATE(b.year_month || '-01') AS month_start,
    c.category_name,
    b.budget_amount,
    ROUND(COALESCE(a.actual_spend, 0), 2)                         AS actual_spend,
    ROUND(b.budget_amount - COALESCE(a.actual_spend, 0), 2)       AS variance,
    ROUND(100.0 * COALESCE(a.actual_spend, 0) / NULLIF(b.budget_amount, 0), 1) AS utilisation_pct,
    CASE WHEN COALESCE(a.actual_spend, 0) > b.budget_amount
         THEN 'Over Budget' ELSE 'Within Budget' END              AS status
FROM budgets b
JOIN dim_category c ON c.category_id = b.category_id
LEFT JOIN actual a  ON a.year_month = b.year_month AND a.category_name = c.category_name;
