"""Validate a generated GitHub Issue draft before any external write."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


COMMON_SECTIONS = (
    "## Acceptance Criteria",
)
BUG_SECTIONS = (
    "## Environment",
    "## Reproduction",
    "## Observed Behavior",
    "## Expected Behavior",
)
PLANNED_SECTIONS = (
    "## Problem / Context",
    "## Proposed Scope",
    "## Non-goals",
    "## Validation Plan",
)


def validate(text: str, *, kind: str = "auto") -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        errors.append("draft must start with a non-empty title")
    if text.count("## Acceptance Criteria") != 1:
        errors.append("draft must contain exactly one '## Acceptance Criteria' section")
    for section in COMMON_SECTIONS:
        if section not in text:
            errors.append(f"missing required section: {section}")
    if kind == "auto":
        kind = "bug" if "## Reproduction" in text else "planned"
    required = BUG_SECTIONS if kind == "bug" else PLANNED_SECTIONS
    for section in required:
        if section not in text:
            errors.append(f"missing {kind} section: {section}")
    secret_markers = ("sk-", "ghp_", "github_pat_", "password=", "postgresql://postgres:")
    lowered = text.lower()
    for marker in secret_markers:
        if marker in lowered and "<password>" not in lowered:
            errors.append(f"possible secret marker found: {marker}")
    if "[ ]" not in text:
        errors.append("acceptance criteria must contain at least one unchecked checkbox")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--kind", choices=("auto", "bug", "planned"), default="auto")
    args = parser.parse_args()
    try:
        text = args.draft.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot read draft: {exc}", file=sys.stderr)
        return 2
    errors = validate(text, kind=args.kind)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: issue draft satisfies the minimum contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
