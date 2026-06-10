# 🕵️ Analyst Workflow Guide

> **Status**: Active  
> **Last Updated**: 2026-01-10

Power users and data analysts can use `finjuice`'s advanced CLI tools to deeply investigate financial data, debug classification logic, and generate custom insights using SQL.

This guide covers the **Analyst Toolset**: `explain`, `query`, `inspect`, `simulate`, and `context`.

---

## 🛠️ Toolset Overview

| Command | Purpose | When to use |
|---------|---------|-------------|
| `finjuice explain` | Debug classification | "Why was this transaction tagged as 'Cafe'?" |
| `finjuice query` | Custom SQL analysis | "I need a specific aggregation not in standard reports." |
| `finjuice inspect` | Deep-dive presets | "Show me all high-value transactions or potential subscriptions." |
| `finjuice simulate` | Test new rules | "What happens if I tag 'Coupang' as 'Shopping'?" |
| `finjuice context` | AI integration | "Get a data summary to paste into ChatGPT/Claude." (Use `--full` for more detail) |

---

## 🔍 Scenario 1: Investigating Spending Anomalies

You notice a spike in spending and want to find the culprit.

### Step 1: Check High-Value Transactions
Use the `inspect` command with the `high_value` preset:

```bash
finjuice inspect high_value
```

### Step 2: Custom SQL Analysis
If you want to find transactions above 100,000 KRW in the '미분류' (untagged) category:

```bash
finjuice query "SELECT date, merchant_raw, amount FROM transactions WHERE amount < -100000 AND category_final = '미분류'"
```

> **Note**: The `transactions` table is a virtual view of your CSV data. You can query it like any SQL table. Columns include: `date`, `merchant_raw`, `amount`, `category_final`, `tags_final`, etc.

---

## 🏷️ Scenario 2: Debugging Tagging Rules

A transaction from "Starbucks" isn't being tagged correctly.

### Step 1: Explain Classification
Find out which rules are currently applying:

```bash
finjuice explain "Starbucks"
```

This will show a trace of all matching rules, their priority, and the final tags applied.

### Step 2: Simulate a New Rule
Test a new rule before adding it to `rules.yaml`:

```bash
finjuice simulate "Starbucks" --tags "Cafe,Coffee" --category "Food"
```

This shows you:
- How many transactions match
- Total amount affected
- A sample of transactions that would be updated

---

## 🤖 Scenario 3: AI-Assisted Analysis

You want to ask a complex question to an LLM (like ChatGPT or Claude) about your finances.

### Step 1: Generate Context
Get a summary of your data schema and recent stats:

```bash
finjuice context --full > context.txt
```

### Step 2: Prompt Engineering
Paste the contents of `context.txt` into your LLM prompt:

> "Here is the context of my financial data:
> [PASTE context.txt content]
> 
> Question: Based on the recent month's data, what are my top 3 variable expense categories?"

---

## 📊 Available Inspection Presets

Run `finjuice inspect --list` to see all available presets:

- `monthly_summary`: Total income/expense by month
- `category_breakdown`: Spending by category (recent month)
- `high_value`: Transactions > 500k KRW
- `subscriptions`: Potential recurring payments (same amount, >3 times)
- `untagged`: Top untagged expenses

---

## ⚠️ Security & Safety

- **Read-Only (Keyword Blocking)**: `finjuice query` creates a read-only view and actively blocks modification keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`) and file access/system functions (`COPY`, `READ_CSV`, `READ_PARQUET`, `READ_JSON`, `READ_BLOB`, `INSTALL`, `LOAD`). Note that this is application-level protection, not database-level permissions.
- **Local Execution**: All analysis runs locally on your machine using DuckDB. No data leaves your computer.

---

## See Also

- [CLI Reference](../reference/cli.md) - Complete command reference
- [Rule Editing Workflow](../workflows/rule-editing-with-claude.md) - Claude Code CLI for tagging rules
- [DuckDB Analytics Layer](../setup/duckdb-setup.md) - High-performance SQL analytics
- [AI CLI Integration](../setup/ai-cli-setup.md) - Natural language queries with Claude Code
