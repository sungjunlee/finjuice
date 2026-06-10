# Support

finjuice is a developer-preview project maintained around a local-first,
privacy-preserving workflow. Public support is best effort.

## Where to Ask

- Usage questions and open-ended ideas: GitHub Discussions.
- Reproducible bugs: open a bug report issue.
- Feature requests: open a feature request issue.
- Security or privacy vulnerabilities: follow [SECURITY.md](SECURITY.md).

## Do Not Share Private Financial Data

Do not include raw Banksalad exports, transaction rows, merchant/account names,
account numbers, memo text, screenshots with financial details, local private
paths, `.env` files, databases, or generated private exports in public issues,
discussions, pull requests, logs, or attachments.

If an example is needed, share the smallest synthetic or redacted structure that
reproduces the behavior.

## Useful Support Details

For a bug report, include:

- finjuice version and install method.
- OS and Python version.
- The exact command, with private paths replaced by placeholders.
- Redacted `--json` error shape or stack trace.
- Minimal synthetic input shape, such as column names or fake values.
- Whether the behavior happens with a scratch data directory.

Good:

```text
finjuice version: 0.x.y
command: finjuice import ~/Downloads/redacted.xlsx --json
data shape: synthetic XLSX with columns date, merchant_raw, amount
error: {"error": {"code": "EXAMPLE_CODE", "message": "redacted"}}
```

Not acceptable:

```text
Real transaction rows, raw XLSX exports, account names, card names, memo text,
full private paths, screenshots, or uploaded databases.
```

## Response Expectations

This project prioritizes data safety, reproducibility, and stable CLI JSON
contracts over broad feature support. Support may ask for a smaller synthetic
reproduction before investigating.

## Updates and Rollback

For normal updates, use the installed skill helper:

```bash
skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json
```

If an update breaks your local workflow, reinstall a known Git tag or commit:

```bash
uv tool install --force git+https://github.com/sungjunlee/finjuice@<tag-or-commit>
```
