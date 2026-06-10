# AI Analyst Skills

This document defines specialized skills for AI agents (like Claude or GPT) to interact with `finjuice` effectively.

## Core Capabilities

The `finjuice` CLI provides a suite of tools designed for AI analysts to query, inspect, and understand financial data without needing direct access to raw storage files.

### 1. Context Gathering
- **Command**: `finjuice context`
- **Purpose**: Get a summary of available data (months, transaction counts) and schema.
- **Usage**: Run this first to understand what data is available.
- **Option**: `finjuice context --full` includes a snapshot of the most recent month.

### 2. SQL Querying
- **Command**: `finjuice query "SELECT ..."`
- **Purpose**: Execute arbitrary SQL queries on the transaction data.
- **Safety**: READ-ONLY. Only `SELECT` and `WITH` statements are allowed.
- **View**: Data is available in the `transactions` view.
- **Schema**:
  - `date`: YYYY-MM-DD string
  - `merchant_raw`: Original merchant name
  - `amount`: Transaction amount (negative for expense, positive for income)
  - `tags_final`: List of tags (JSON string in some contexts)
  - `category_final`: Final category assigned
  - `memo_raw`: Transaction memo
  - `is_transfer`: Boolean

### 3. Inspection Presets
- **Command**: `finjuice inspect <preset>`
- **Purpose**: Run pre-defined deep-dive analyses.
- **Available Presets**:
  - `monthly_summary`: Monthly totals
  - `category_breakdown`: Category stats for recent month
  - `high_value`: Transactions > 500k KRW
  - `subscriptions`: Potential recurring payments
  - `untagged`: Top untagged expenses

### 4. Classification Explanation
- **Command**: `finjuice explain "<search_term>"`
- **Purpose**: Debug why a transaction was tagged (or not tagged) a certain way.
- **Output**: Shows which rules matched and in what priority order.

### 5. Rule Simulation
- **Command**: `finjuice simulate "<pattern>" --tags "tag1,tag2"`
- **Purpose**: Test a new rule before adding it to `rules.yaml`.
- **Output**: Shows how many transactions would be matched and how many new tags would be applied.

## Workflow Examples

### Workflow A: Investigating a Spending Spike
1. **Check Context**: `finjuice context` to see available months.
2. **Query Monthly Totals**: `finjuice inspect monthly_summary` to confirm the spike.
3. **Drill Down**: `finjuice query "SELECT category_final, SUM(amount) FROM transactions WHERE date LIKE '2024-10%' GROUP BY category_final ORDER BY SUM(amount) ASC"`
4. **Find Culprit**: `finjuice query "SELECT * FROM transactions WHERE date LIKE '2024-10%' AND category_final = 'Travel' ORDER BY amount ASC LIMIT 5"`

### Workflow B: Cleaning Up Untagged Transactions
1. **Identify**: `finjuice inspect untagged` to find top untagged items.
2. **Explain**: `finjuice explain "MerchantName"` to see why it wasn't caught by existing rules.
3. **Simulate**: `finjuice simulate "MerchantName" --tags "Food" --fields "merchant_raw"` to test a fix.
4. **Apply**: Suggest adding the rule to `rules.yaml`.

### Workflow C: Subscription Audit
1. **Scan**: `finjuice inspect subscriptions`.
2. **Verify**: Pick a merchant and run `finjuice query "SELECT * FROM transactions WHERE merchant_raw = 'Netflix' ORDER BY date DESC"`.
