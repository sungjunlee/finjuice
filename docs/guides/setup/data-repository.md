# Data Repository Setup Guide

Complete guide for setting up a separate data repository for your personal financial data.

## Why Separate Data from Code?

**Security**: Personal financial data should never be in the same repository as program code, especially if you plan to share or open-source the program.

**Flexibility**: Update the program independently from your data. Multiple users can use the same program with their own private data repositories.

**Privacy**: Your transaction history stays private in your own repository with appropriate access controls.

## Quick Start

### Option 1: Default Setup (Recommended)

```bash
# First import auto-creates ~/.finjuice and runs the full pipeline
finjuice import ~/Downloads/banksalad_export.xlsx

# Re-run processing for pending imports or updated rules
finjuice refresh
```

### Option 2: Custom Location (Advanced)

```bash
# 1. Create custom data directory
mkdir -p ~/Documents/my-finance-data
cd ~/Documents/my-finance-data

# 2. Copy template files
cp <prog-repo>/templates/.gitignore.data .gitignore
cp <prog-repo>/templates/README.data.md README.md
cp <prog-repo>/data/examples/rules.yaml rules.yaml

# 3. Create directory structure
mkdir -p transactions imports exports cache

# 4. Initialize git (optional but recommended)
git init
git add .gitignore README.md rules.yaml
git commit -m "init: personal finance data repository"

# 5. (Optional) Connect to private remote
git remote add origin git@github.com:yourusername/my-finance-data-private.git
git push -u origin main
```

## Detailed Setup Instructions

### Step 1: Create Data Directory

By default, finjuice stores data in `~/.finjuice/`. Choose a custom location only if you need a
separate repository, cloud sync folder, or shared workspace.

Recommended custom locations:

- **macOS/Linux**: `~/Documents/my-finance-data/`
- **Windows**: `C:\Users\YourName\Documents\my-finance-data\`
- **Cloud sync** (if you trust the service): `~/Dropbox/finance/banksalad-data/`

```bash
mkdir -p ~/Documents/my-finance-data
cd ~/Documents/my-finance-data
```

### Step 2: Set Up Directory Structure

```bash
# Create required directories
mkdir -p transactions   # CSV partitions (will be populated by pipeline)
mkdir -p imports        # Put your Banksalad XLSX files here
mkdir -p exports        # Pipeline will create reports here

# Optional directories
mkdir -p cache          # For analytics cache (future)
mkdir -p backups        # For manual backups
```

### Step 3: Copy Configuration Files

From the program repository, copy the template files:

```bash
# Assuming program repo is at ~/finjuice
PROG_REPO=~/finjuice

# Copy gitignore template
cp $PROG_REPO/templates/.gitignore.data .gitignore

# Copy README template
cp $PROG_REPO/templates/README.data.md README.md

# Copy example rules
cp $PROG_REPO/data/examples/rules.yaml rules.yaml
```

### Step 4: Customize Tagging Rules

Edit `rules.yaml` to add your own tagging patterns:

```yaml
version: 1
rules:
  # Add your own rules here
  - name: my_gym_membership
    match: "헬스장|피트니스"
    fields: [merchant_raw, memo_raw]
    tags: ["건강", "정기지출"]
    priority: 85

  # Copy more examples from data/examples/rules.yaml
```

### Step 5: Initialize Git Repository (Recommended)

```bash
git init
git add .gitignore README.md rules.yaml
git commit -m "init: personal finance data repository"
```

### Step 6: Connect to Private Remote (Optional)

Create a **private** repository on GitHub/GitLab and connect:

```bash
# GitHub
gh repo create my-finance-data --private
git remote add origin git@github.com:yourusername/my-finance-data.git
git push -u origin main

# Or GitLab
git remote add origin git@gitlab.com:yourusername/my-finance-data.git
git push -u origin main
```

⚠️ **CRITICAL**: Ensure the remote repository is **private**!

### Step 7: Test the Setup

```bash
# Option A: Default location (~/.finjuice)
finjuice import ~/Downloads/banksalad_export.xlsx

# Option B: Custom location with --data-dir
finjuice --data-dir ~/Documents/my-finance-data import ~/Downloads/banksalad_export.xlsx

# Option C: Set environment variable
export FINJUICE_DATA_DIR=~/Documents/my-finance-data
finjuice refresh

# Option D: Work inside a private data repository
cd ~/Documents/my-finance-data
finjuice --data-dir "$PWD" refresh
```

## Usage Workflows

### Daily Workflow

```bash
# 1. Download Banksalad export
# (Manually download from Banksalad website)

# 2. Place XLSX in imports/
cp ~/Downloads/2025-01-01~2025-11-02.xlsx ~/Documents/my-finance-data/imports/

# 3. Run pipeline
export FINJUICE_DATA_DIR=~/Documents/my-finance-data
finjuice refresh

# 4. Review results
cat ~/Documents/my-finance-data/exports/reports/monthly_spend.csv

# 5. Commit changes
cd ~/Documents/my-finance-data
git add transactions/
git commit -m "chore: add November 2025 transactions"
git push
```

### Understanding Report Files

After running the pipeline, you'll find several report files in `exports/reports/`:

| Report | Purpose | Notes |
|--------|---------|-------|
| `monthly_spend.csv` | 월별 총 지출 | 전체 지출 트렌드 파악 |
| `by_category.csv` | 카테고리별 지출 (권장) | **중복 없는 정확한 집계**, `category_final` 기준 |
| `by_tag.csv` | 태그별 분석 | 다중 태그 시 중복 계산됨 (필터링/분석용) |
| `by_account.csv` | 계정/카드별 지출 | 결제수단 분석 |
| `transfers.csv` | 내부 이체 내역 | 이체 검증 및 감사 |

**Which report to use?**
- **지출 집계 (총액 확인)**: `by_category.csv` 사용 → 각 거래가 한 번만 계산됨
- **태그 분석 (패턴 파악)**: `by_tag.csv` 사용 → "정기지출 + 보험" 같은 다중 태그 분석 가능

> 💡 **Tip**: 거래에 여러 태그가 있으면 `by_tag.csv`에서 중복 계산됩니다.
> 정확한 지출 총액은 `by_category.csv`를 사용하세요.

### Updating Tagging Rules

```bash
cd ~/Documents/my-finance-data

# Edit rules
vim rules.yaml  # or nano, code, etc.

# Re-run tagging
finjuice --data-dir "$PWD" tag

# Commit rule changes
git add rules.yaml
git commit -m "feat: add rule for new coffee shop"
git push
```

### Viewing Historical Changes

```bash
cd ~/Documents/my-finance-data

# See all transaction updates
git log --oneline transactions/

# View specific month
git show HEAD:transactions/2025/01/transactions.csv

# Compare changes
git diff HEAD~1 transactions/2025/01/transactions.csv

# Restore previous version
git checkout HEAD~1 transactions/2025/01/transactions.csv
```

## Migration from Old Setup

If you have existing data in an older finjuice location or in a repository-local `data/`
directory, use `finjuice migrate`. It auto-detects legacy locations and moves the standard
layout into `~/.finjuice` by default.

### Preview the migration

```bash
finjuice migrate --dry-run
```

### Run the migration

```bash
# Auto-detect legacy location and move to ~/.finjuice
finjuice migrate

# Migrate from a specific source path
finjuice migrate --from ./data

# Migrate into a custom target directory
finjuice migrate --from ./data --target ~/Documents/my-finance-data
```

### Verify Migration

```bash
# Test that finjuice sees the migrated data
finjuice status

# Rebuild derived outputs after migration
finjuice refresh

# Check that data looks correct
ls ~/.finjuice/transactions/
cat ~/.finjuice/exports/reports/monthly_spend.csv

# Clean up old data directory (CAREFUL!)
# Only do this after verifying migration worked!
# Keep backups until you are confident the migration succeeded.
```

## Troubleshooting

### "No such file or directory: data/transactions"

**Cause**: finjuice is reading from the default `~/.finjuice` directory, not your custom location.

**Solution**: Specify data directory explicitly:

```bash
finjuice --data-dir ~/Documents/my-finance-data refresh
# or
export FINJUICE_DATA_DIR=~/Documents/my-finance-data
```

### "Permission denied" when writing files

**Cause**: Data directory has wrong permissions.

**Solution**:

```bash
chmod -R u+w ~/Documents/my-finance-data
```

### "Git remote rejected push"

**Cause**: Repository might not be set to private, or file is too large.

**Solution**:

```bash
# Check repository visibility
gh repo view yourusername/my-finance-data

# Make it private if needed
gh repo edit yourusername/my-finance-data --visibility private

# Check file sizes
find ~/Documents/my-finance-data -type f -size +10M
```

### CSV partitions not being tracked by git

**Cause**: Wrong `.gitignore` configuration.

**Solution**:

```bash
# Check gitignore
cat .gitignore | grep transactions

# Should have:
# !transactions/
# !transactions/**/*.csv

# If not, copy template again
cp <prog-repo>/templates/.gitignore.data .gitignore
```

## Best Practices

### Security

1. ✅ **Always use private repositories** for financial data
2. ✅ **Enable 2FA** on GitHub/GitLab account
3. ✅ **Use SSH keys** instead of HTTPS passwords
4. ✅ **Review `.gitignore`** before committing
5. ❌ **Never commit** `.env` files or API keys
6. ❌ **Never share** data repository publicly

### Git Workflow

1. **Commit regularly**: After each import/tagging cycle
2. **Descriptive messages**: "chore: add 2025-01 transactions"
3. **Small commits**: One month at a time if possible
4. **Review diffs**: Check what changed before committing

### Performance

1. **CSV partitions**: Keep using monthly structure (8K tokens per month)
2. **Don't commit exports**: They can be regenerated
3. **Prune old branches**: Keep git history lean

### Backup

1. **Remote git**: GitHub/GitLab private repo
2. **Local backup**: Time Machine, Backblaze, etc.
3. **Export archive**: Periodic master XLSX backups

## Advanced Setup

### Multiple Data Sets

You can manage multiple data repositories:

```bash
# Personal finances
export BANKSALAD_DATA_PERSONAL=~/Documents/finance-personal
finjuice --data-dir $BANKSALAD_DATA_PERSONAL refresh

# Business finances
export BANKSALAD_DATA_BUSINESS=~/Documents/finance-business
finjuice --data-dir $BANKSALAD_DATA_BUSINESS refresh
```

### Shared Data Repository (Family)

```bash
# Clone shared repository
git clone git@github.com:family/shared-finance.git ~/Documents/family-finance

# Each member adds their own imports
cp ~/Downloads/my-banksalad.xlsx ~/Documents/family-finance/imports/

# Run pipeline
finjuice --data-dir ~/Documents/family-finance refresh

# Commit and push
cd ~/Documents/family-finance
git add transactions/
git commit -m "chore: add my November transactions"
git pull --rebase  # Get updates from other family members
git push
```

### Cloud Sync (Advanced)

If you use cloud storage with caution:

```bash
# Using Dropbox
mkdir -p ~/Dropbox/finance/banksalad-data
export FINJUICE_DATA_DIR=~/Dropbox/finance/banksalad-data

# Or using iCloud
mkdir -p ~/Library/Mobile\ Documents/com~apple~CloudDocs/finance-data
export FINJUICE_DATA_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/finance-data"
```

⚠️ **Warning**: Ensure cloud provider uses encryption and you trust their security!

## Next Steps

1. **Customize rules**: Edit `rules.yaml` to match your spending patterns
2. **Run first import**: Use `finjuice import ~/Downloads/banksalad_export.xlsx` to auto-initialize
3. **Review results**: Check generated reports in `exports/reports/`
4. **Iterate**: Refine tagging rules based on results
5. **Automate**: Set up monthly reminder to download and process Banksalad exports

## Support

- **Issues**: https://github.com/sungjunlee/finjuice/issues
- **Documentation**: https://github.com/sungjunlee/finjuice/blob/master/CLAUDE.md
- **Template files**: `templates/` directory in program repository

---

**Last updated**: 2025-11-02
**Related**: Phase 2 (flexible data paths), Phase 3 (finjuice init)
