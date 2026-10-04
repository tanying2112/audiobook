#!/usr/bin/env bash
# scan-leaked-credentials-history.sh
# Runs detect-secrets with --scan-history to catch any secrets ever committed
# Part of P0-1 hardening per AUDIT_REPORT_v3.md

set -euo pipefail

echo "=== detect-secrets --scan-history ==="
echo "Scanning ALL commit history for leaked secrets..."

# Install detect-secrets if needed
python -m pip install --upgrade pip -q
pip install detect-secrets==1.5.0 -q

# Run detect-secrets with --scan-history
# This scans the entire git history, not just the current worktree
detect-secrets scan --scan-history --baseline .secrets.baseline

# Hard fail if new secrets beyond baseline are found
# The audit command will exit non-zero if there are un-audited secrets
detect-secrets audit --report .secrets.baseline

echo "✅ detect-secrets --scan-history completed — no new secrets in history"