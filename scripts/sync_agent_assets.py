#!/usr/bin/env python3
"""Sync AGENTS.md assets from the authoritative template.

Project discovery note:
- Agent runtime directories such as .claude/ and .codex/ are local-only.
- This script syncs repository-owned templates only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

SYNC_MAP = {
    "src/finjuice/templates/AGENTS.md": [
        "templates/AGENTS.md",
    ],
}


def sync_assets(root: Path, check_only: bool) -> int:
    """Sync files from authoritative sources to generated targets.

    Args:
        root: Project root directory.
        check_only: If True, only report drift and do not write files.

    Returns:
        0 if files are in sync / successfully synchronized, otherwise 1.
    """
    drift: list[tuple[Path, Path]] = []

    for src_rel, targets_rel in SYNC_MAP.items():
        src_path = root / src_rel
        if not src_path.exists():
            print(f"❌ Missing source file: {src_path}")
            return 1

        src_content = src_path.read_text(encoding="utf-8")

        for target_rel in targets_rel:
            target_path = root / target_rel
            target_exists = target_path.exists()
            target_content = target_path.read_text(encoding="utf-8") if target_exists else None

            if target_content == src_content:
                print(f"✅ In sync: {target_path}")
                continue

            drift.append((src_path, target_path))

            if check_only:
                print(f"❌ Drift detected: {target_path} (source: {src_path})")
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(src_content, encoding="utf-8")
            print(f"🔄 Synced: {target_path} <- {src_path}")

    if drift and check_only:
        print("\n❌ Agent asset drift detected.")
        print("   Edit the authoritative template only:")
        for src_rel in sorted(set(SYNC_MAP.keys())):
            print(f"   - {src_rel}")
        print("   Then regenerate generated targets:")
        print("   python scripts/sync_agent_assets.py")
        return 1

    if drift and not check_only:
        print(f"\n✅ Sync complete: updated {len(drift)} file(s)")
    else:
        print("\n✅ All agent assets already in sync")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync AGENTS.md assets from source templates")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check sync status only (exit 1 when drift exists)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root path (default: auto-detected from script location)",
    )

    args = parser.parse_args()
    root = args.root.resolve()

    print(f"Project root: {root}")
    return sync_assets(root=root, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
