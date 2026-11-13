-- Analysis queries. Each block starts with "-- name: <id>" so Python can load them by name.
-- You can also open this file in DB Browser for SQLite / DBeaver and run them one by one.

-- name: monthly_summary
SELECT * FROM vw_monthly_summary ORDER BY year_month;

-- name: mom_change
-- Month-over-month change in spending using the LAG() window function.
WITH m AS (SELECT year_month, total_expense FROM vw_monthly_summary)
SELECT
    year_month,
    total_expense,
    LAG(total_expense) OVER (ORDER BY year_month) AS prev_expense,
    ROUND(100.0 * (total_expense - LAG(total_expense) OVER (ORDER BY year_month))
          / NULLIF(LAG(total_expense) OVER (ORDER BY year_month), 0), 1) AS mom_change_pct
FROM m
ORDER BY year_month;

-- name: category_spend
-- Share of total spend per category (window function over an aggregate).
SELECT
    category_name,
    ROUND(SUM(amount), 2)  AS total_spend,
    COUNT(*)               AS txn_count,
    ROUND(AVG(amount), 2)  AS avg_txn,
    ROUND(100.0 * SUM(amount) / SUM(SUM(amount)) OVER (), 1) AS pct_of_spend
FROM vw_transactions_enriched
WHERE category_type = 'Expense'
GROUP BY category_name
ORDER BY total_spend DESC;

-- name: top_merchants
SELECT
    merchant,
    ROUND(SUM(amount), 2) AS total_spend,
    COUNT(*)              AS txn_count,
    ROUND(AVG(amount), 2) AS avg_txn
FROM vw_transactions_enriched
WHERE category_type = 'Expense' AND merchant <> 'Unknown'
GROUP BY merchant
ORDER BY total_spend DESC
LIMIT 10;

-- name: weekday_pattern
SELECT
    day_name,
    ROUND(SUM(amount), 2) AS total_spend,
    COUNT(*)              AS txn_count,
    ROUND(AVG(amount), 2) AS avg_txn
FROM vw_transactions_enriched
WHERE category_type = 'Expense'
GROUP BY day_name
ORDER BY CASE day_name
    WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
    WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 ELSE 7 END;

-- name: weekend_vs_weekday
SELECT
    CASE WHEN is_weekend = 1 THEN 'Weekend' ELSE 'Weekday' END AS day_type,
    ROUND(SUM(amount), 2)                        AS total_spend,
    COUNT(DISTINCT txn_date)                     AS active_days,
    ROUND(SUM(amount) / COUNT(DISTINCT txn_date), 2) AS avg_spend_per_active_day
FROM vw_transactions_enriched
WHERE category_type = 'Expense'
GROUP BY is_weekend;

-- name: payment_split
SELECT
    payment_method,
    ROUND(SUM(amount), 2) AS total_spend,
    COUNT(*)              AS txn_count,
    ROUND(100.0 * SUM(amount) / SUM(SUM(amount)) OVER (), 1) AS pct_of_spend
FROM vw_transactions_enriched
WHERE category_type = 'Expense'
GROUP BY payment_method
ORDER BY total_spend DESC;

-- name: budget_summary
SELECT
    category_name,
    ROUND(SUM(budget_amount), 2) AS total_budget,
    ROUND(SUM(actual_spend), 2)  AS total_actual,
    ROUND(SUM(variance), 2)      AS total_variance,
    ROUND(100.0 * SUM(actual_spend) / NULLIF(SUM(budget_amount), 0), 1) AS utilisation_pct,
    SUM(CASE WHEN status = 'Over Budget' THEN 1 ELSE 0 END) AS months_over_budget
FROM vw_budget_vs_actual
GROUP BY category_name
ORDER BY utilisation_pct DESC;

-- name: running_savings
SELECT
    year_month,
    net_savings,
    ROUND(SUM(net_savings) OVER (ORDER BY year_month), 2) AS cumulative_savings
FROM vw_monthly_summary
ORDER BY year_month;

-- name: top3_categories_per_month
-- RANK() inside a CTE, filtered afterwards.
WITH monthly AS (
    SELECT year_month, category_name, SUM(amount) AS spend
    FROM vw_transactions_enriched
    WHERE category_type = 'Expense'
    GROUP BY year_month, category_name
),
ranked AS (
    SELECT *, RANK() OVER (PARTITION BY year_month ORDER BY spend DESC) AS rnk
    FROM monthly
)
SELECT year_month, rnk, category_name, ROUND(spend, 2) AS spend
FROM ranked
WHERE rnk <= 3
ORDER BY year_month, rnk;
