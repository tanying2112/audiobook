#!/usr/bin/env python3
"""Generate changelog fragment from conventional commit message.

This script parses the latest commit message and creates a markdown fragment
in docs/changelog/auto/ for inclusion in the next release notes.

Usage: python scripts/generate_changelog_fragment.py [commit_hash]
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from subprocess import run

CHANGELOG_DIR = Path("docs/changelog/auto")
CHANGELOG_DIR.mkdir(parents=True, exist_ok=True)

# Conventional commit types -> changelog sections
TYPE_TO_SECTION = {
    "feat": "### Features",
    "fix": "### Bug Fixes",
    "perf": "### Performance",
    "refactor": "### Refactoring",
    "docs": "### Documentation",
    "test": "### Tests",
    "chore": "### Maintenance",
    "build": "### Build",
    "ci": "### CI/CD",
    "style": "### Style",
}

BREAKING_CHANGE_SECTION = "### ⚠️ Breaking Changes"


def parse_conventional_commit(message: str) -> dict:
    """Parse a conventional commit message.

    Format: <type>(<scope>): <description>
    """
    # First line is the header
    header = message.strip().split("\n")[0]

    # Parse: type(scope): description
    match = re.match(r"^(\w+)(?:\(([^)]+)\))?:\s*(.+)$", header)
    if not match:
        return {
            "type": "other",
            "scope": "",
            "description": header,
            "breaking": False,
            "body": "",
            "footers": [],
        }

    commit_type, scope, description = match.groups()

    # Check for breaking change indicator
    breaking = "!" in commit_type or "BREAKING CHANGE" in message.upper()
    if "!" in commit_type:
        commit_type = commit_type.replace("!", "")

    # Extract body and footers
    lines = message.strip().split("\n")
    body = ""
    footers = []

    if len(lines) > 1:
        body_lines = []
        footer_lines = []
        in_footer = False
        for line in lines[1:]:
            if re.match(r"^\w+(?:-\w+)*:\s", line):
                in_footer = True
            if in_footer and line.strip():
                footer_lines.append(line)
            elif line.strip() and not in_footer:
                body_lines.append(line)
        body = "\n".join(body_lines).strip()
        footers = footer_lines

    return {
        "type": commit_type,
        "scope": scope or "",
        "description": description,
        "breaking": breaking,
        "body": body,
        "footers": footers,
    }


def get_latest_commit(commit_hash: str = None) -> str:
    """Get the latest commit message."""
    cmd = ["git", "log", "-1", "--pretty=format:%B"]
    if commit_hash:
        cmd[-1] = commit_hash
    result = run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def generate_fragment(commit_info: dict, commit_hash: str) -> str:
    """Generate markdown fragment from commit info."""
    timestamp = datetime.now().strftime("%Y-%m-%d")
    lines = []

    # Header with commit hash
    scope_str = f"({commit_info['scope']})" if commit_info["scope"] else ""
    lines.append(f"#### {commit_info['type'].capitalize()}{scope_str}")
    lines.append("")
    lines.append(
        f"- {commit_info['description']} ([{commit_hash[:7]}](https://github.com/tanying2112/AI_Lab/commit/{commit_hash}))"
    )

    # Breaking change
    if commit_info["breaking"]:
        lines.append("")
        lines.append("- **BREAKING CHANGE**")
        for footer in commit_info["footers"]:
            if "BREAKING" in footer.upper():
                lines.append(f"  - {footer}")

    # Body
    if commit_info["body"]:
        lines.append("")
        for line in commit_info["body"].split("\n"):
            lines.append(f"  {line}")

    # Footers (except breaking)
    for footer in commit_info["footers"]:
        if "BREAKING" not in footer.upper():
            lines.append(f"  - {footer}")

    return "\n".join(lines)


def main():
    commit_hash = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        message = get_latest_commit(commit_hash)
        info = parse_conventional_commit(message)

        # Skip if not a conventional type
        if info["type"] not in TYPE_TO_SECTION:
            print(f"Skipping non-conventional commit: {info['type']}")
            return 0

        # Generate or append to fragment file
        date_str = datetime.now().strftime("%Y-%m-%d")
        fragment_file = CHANGELOG_DIR / f"{date_str}-{info['type']}.md"

        fragment = generate_fragment(info, commit_hash or "HEAD")

        if fragment_file.exists():
            # Append to existing file
            with open(fragment_file, "a") as f:
                f.write("\n\n" + fragment)
        else:
            # Create new file with section header
            section = TYPE_TO_SECTION.get(info["type"], "### Other")
            with open(fragment_file, "w") as f:
                f.write(f"{section}\n\n{fragment}\n")

        print(f"✅ Created/updated changelog fragment: {fragment_file}")
        return 0

    except Exception as e:
        print(f"Error generating changelog fragment: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
