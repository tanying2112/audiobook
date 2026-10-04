#!/usr/bin/env bash
# scan-leaked-credentials.sh
# Scans current worktree for known leaked credential patterns
# Part of P0-1 hardening per AUDIT_REPORT_v3.md

set -euo pipefail

echo "=== Scanning worktree for known leaked credential patterns ==="

# Patterns from AUDIT_REPORT_v3.md P0-1 findings
PATTERNS=(
    # Upstash Redis AUTH prefix
    "gQAAAAAA"
    # Cloudflare R2 Access Key prefix
    "2fc25bbebc"
    # Cloudflare R2 Secret Access Key prefix
    "b7d997bc5583"
)

FOUND=0
for pattern in "${PATTERNS[@]}"; do
    if git grep -I -n "$pattern" -- ':!docs/AUDIT_REPORT_v3.md' ':!AUDIT_REPORT_v3.md' 2>/dev/null; then
        echo "❌ LEAKED CREDENTIAL PATTERN FOUND: $pattern"
        FOUND=1
    fi
done

# Also run generic detect-secrets scan on worktree
python -m pip install --upgrade pip -q
pip install detect-secrets==1.5.0 -q
detect-secrets scan --baseline .secrets.baseline || true

if [ $FOUND -eq 1 ]; then
    echo "❌ FAILED: Known leaked credential patterns detected in worktree"
    exit 1
fi

echo "✅ Worktree scan clean — no known leaked credential patterns found"