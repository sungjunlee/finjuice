#!/usr/bin/env python3
"""
Check for broken @doc references in markdown files.

Searches for patterns like:
- @path/to/file.md
- [@docs/guide.md](docs/guide.md)
- See @templates/schema.yaml

Validates that referenced files exist.
Exit code 0 (success) or 1 (broken links found).
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple

# Directories to skip
EXCLUDE_DIRS = {
    ".git",
    ".codex",
    ".gstack",
    ".serena",
    ".venv",
    "venv",
    "node_modules",
    "htmlcov",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    "dist",
    "build",
    "*.egg-info",
}


def find_markdown_files(root: Path = Path(".")) -> List[Path]:
    """Find all markdown files, excluding hidden/ignored directories."""
    md_files = []
    for md_file in root.rglob("*.md"):
        # Skip if any parent dir is in exclude list
        if any(exclude in md_file.parts for exclude in EXCLUDE_DIRS):
            continue
        if any(part.startswith(".") for part in md_file.parts[1:]):  # Skip hidden
            continue
        md_files.append(md_file)
    return md_files


def extract_doc_references(content: str) -> List[Tuple[int, str]]:
    """
    Extract @path/to/file references from markdown.

    Returns list of (line_number, reference_path) tuples.
    """
    references = []
    valid_exts = [".md", ".yaml", ".yml", ".py", ".toml", ".txt", ".example", ".json"]

    # Pattern 1: @path/to/file.ext (handles multiple extensions like .yaml.example)
    # Matches: @path/to/file followed by one or more .extensions
    for match in re.finditer(r"@([a-zA-Z0-9/_-]+(?:\.[a-zA-Z0-9]+)+)", content):
        line_num = content[: match.start()].count("\n") + 1
        ref_path = match.group(1)
        # Only include common doc file extensions
        if any(ref_path.endswith(ext) for ext in valid_exts):
            references.append((line_num, ref_path))

    # Pattern 2: [@description](path/to/file.ext) - extract path from markdown link
    for match in re.finditer(r"\[@[^\]]+\]\(([a-zA-Z0-9/_-]+(?:\.[a-zA-Z0-9]+)+)\)", content):
        line_num = content[: match.start()].count("\n") + 1
        ref_path = match.group(1)
        if any(ref_path.endswith(ext) for ext in valid_exts):
            references.append((line_num, ref_path))

    return references


def check_doc_links() -> int:
    """
    Check all markdown files for broken @doc references.

    Returns 0 if all links valid, 1 if broken links found.
    """
    root = Path(".")
    md_files = find_markdown_files(root)

    print(f"🔍 Checking {len(md_files)} markdown files for broken @doc links...")

    broken_links = []
    total_refs = 0

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"⚠️  Warning: Could not read {md_file} (encoding issue)")
            continue

        references = extract_doc_references(content)
        total_refs += len(references)

        for line_num, ref_path in references:
            # Check if file exists (relative to project root)
            target = root / ref_path
            if not target.exists():
                broken_links.append((md_file, line_num, ref_path))

    # Report results
    if broken_links:
        print(f"\n❌ Found {len(broken_links)} broken @doc reference(s):\n")
        for md_file, line_num, ref_path in broken_links:
            print(f"  {md_file}:{line_num}")
            print(f"    → @{ref_path} (not found)")
            print()
        print("💡 Tip: Check for typos or create missing files")
        return 1
    else:
        print(f"✅ All {total_refs} @doc references are valid!")
        return 0


if __name__ == "__main__":
    sys.exit(check_doc_links())
