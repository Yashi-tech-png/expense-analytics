# Power BI guide (build the dashboard in ~45 minutes)

The pipeline writes Power BI-ready files to `exports/`. Power BI Desktop is Windows-only; if you
are on Mac/Linux, use a Windows machine, a university lab, or Power BI Service in a browser
(import the same CSVs there).

## 1. Load the data
`Home > Get data > Text/CSV`, then load these five files from `exports/`:

| File | Becomes table | Role |
|---|---|---|
| `transactions.csv` | `Transactions` | fact (income + expense rows) |
| `budget_vs_actual.csv` | `Budget` | fact (one row per month per category) |
| `dim_date.csv` | `Calendar` | date dimension |
| `dim_category.csv` | `Category` | category dimension |
| `monthly_summary.csv` | `Monthly` | optional, already aggregated |

In **Power Query** (Transform data) set types: `Transactions[txn_date]` = Date, `Calendar[full_date]` = Date,
`Budget[month_start]` = Date, amounts = Fixed decimal number. Then **Close & Apply**.

## 2. Build the model (Model view)
Create these relationships (all many-to-one, single direction, from the fact to the dimension):

- `Transactions[txn_date]` -> `Calendar[full_date]`
- `Budget[month_start]` -> `Calendar[full_date]`  (works because `month_start` is the 1st of each month)
- `Transactions[category_name]` -> `Category[category_name]`
- `Budget[category_name]` -> `Category[category_name]`

Mark `Calendar` as a date table (Table tools > Mark as date table > `full_date`).
Sort `Calendar[month_name]` by `Calendar[month]`, and `Calendar[day_name]` by a day-number column if you add one.

## 3. DAX measures
Create a table for measures: `Home > Enter data`, name it `_Measures`.

```DAX
Total Income =
CALCULATE ( SUM ( Transactions[amount] ), Transactions[category_type] = "Income" )

Total Expense =
CALCULATE ( SUM ( Transactions[amount] ), Transactions[category_type] = "Expense" )

Net Savings = [Total Income] - [Total Expense]

Savings Rate % = DIVIDE ( [Net Savings], [Total Income] )

Txn Count = COUNTROWS ( Transactions )

Avg Expense per Txn =
DIVIDE ( [Total Expense], CALCULATE ( [Txn Count], Transactions[category_type] = "Expense" ) )

Total Budget = SUM ( Budget[budget_amount] )

Budget Variance = [Total Budget] - [Total Expense]

Budget Utilisation % = DIVIDE ( [Total Expense], [Total Budget] )

Expense Previous Month =
CALCULATE ( [Total Expense], DATEADD ( Calendar[full_date], -1, MONTH ) )

Expense MoM % =
DIVIDE ( [Total Expense] - [Expense Previous Month], [Expense Previous Month] )

Expense YTD =
TOTALYTD ( [Total Expense], Calendar[full_date] )

Cumulative Savings =
CALCULATE (
    [Net Savings],
    FILTER ( ALL ( Calendar[full_date] ), Calendar[full_date] <= MAX ( Calendar[full_date] ) )
)

Weekend Share % =
DIVIDE (
    CALCULATE ( [Total Expense], Calendar[is_weekend] = 1 ),
    [Total Expense]
)
```

Note: `Total Expense` is used against `Budget` rows through the shared `Calendar` and `Category` tables,
so `Budget Utilisation %` works in any visual that slices by month or category.

## 4. Report pages

**Page 1: Overview**
- KPI cards: Total Income, Total Expense, Net Savings, Savings Rate %
- Clustered column chart: `Calendar[year_month]` vs Total Income and Total Expense
- Line chart: Cumulative Savings by month
- Slicers: `Calendar[year]`, `Category[category_name]`

**Page 2: Spending breakdown**
- Donut or bar: Total Expense by `Category[category_name]`
- Bar: Total Expense by `Transactions[merchant]` (Top N filter = 10)
- Column: Total Expense by `Calendar[day_name]`
- Donut: Total Expense by `Transactions[payment_method]`

**Page 3: Budget tracker**
- Clustered bar: Total Budget vs Total Expense by category
- Matrix: rows = category, columns = `year_month`, values = Budget Utilisation %; add conditional
  formatting (green < 90%, amber 90-100%, red > 100%)
- Card: count of over-budget category-months (`Budget[status] = "Over Budget"`)

**Page 4: Anomalies and trends**
- Table from `anomalies.csv` (load it as another table): date, merchant, category, amount, z_score
- Line chart with Expense MoM %

Tips: use one consistent theme (View > Themes), turn on tooltips, add a title text box on each page,
and keep the numbers in INR format (Modeling > Currency format).

## 5. Save and publish
- Save as `powerbi/Personal_Expense_Dashboard.pbix` and commit it (usually under 25 MB).
- Screenshot each page (Win+Shift+S) and save into `docs/screenshots/`; the README can then display them.
- Optional: `Home > Publish` to Power BI Service, then File > Embed or share a link if your account allows it.

## 6. Refreshing with your own data
Run the pipeline again, then in Power BI click **Home > Refresh**. If you moved the project folder, fix the
file paths in Power Query (Transform data > Data source settings).
