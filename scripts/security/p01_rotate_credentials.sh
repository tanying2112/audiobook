#!/usr/bin/env bash
# ==============================================================================
# P0-1 Credential Rotation & History Rewrite Runbook
# Run as repository owner. Requires: git-filter-repo, gh CLI (optional)
# ==============================================================================
set -euo pipefail

# ── Color output ───────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()   { echo -e "${GREEN}[RUNBOOK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Step 0: Pre-flight checks ──────────────────────────────────────────────────
command -v git >/dev/null || { err "git not found"; exit 1; }
command -v git-filter-repo >/dev/null || { err "git-filter-repo not installed (pip install git-filter-repo)"; exit 1; }

# Verify we're in the right repo
if [[ ! -d .git ]]; then
    err "Not a git repository. Run from repo root."
    exit 1
fi

ORIGIN_URL=$(git remote get-url origin 2>/dev/null || echo "")
log "Repository: $ORIGIN_URL"

# ── Step A: Console Credential Rotation (MUST DO FIRST) ────────────────────────
cat <<'EOF'

╔══════════════════════════════════════════════════════════════════════════════╗
║ STEP A: Rotate credentials in cloud consoles                              ║
║ Run these MANUALLY in your browser / CLI.                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 1. UPSTASH REDIS                                                           ║
║    - Go to https://console.upstash.com                                     ║
║    - Select database: casual-sawfish-86152                                 ║
║    - Settings → Reset Password / Regenerate Token                          ║
║    - Copy NEW token → store in password manager                            ║
║    - Update GitHub / CI secret: REDIS_AUTH                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 2. CLOUDFLARE R2                                                           ║
║    - Go to https://dash.cloudflare.com → R2 → Manage API Tokens            ║
║    - Delete leaked Access Key (starts with 2fc25bbebc...)                  ║
║    - Create new API Token with R2 read/write permissions                   ║
║    - Copy Access Key ID + Secret Access Key                                ║
║    - Update GitHub / CI secrets: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 3. Verify rotation worked:                                                 ║
║    - Test Redis: redis-cli -h casual-sawfish-86152.upstash.io -p 6379      ║
║      -a "<NEW_AUTH>" PING  → should return PONG                            ║
║    - Test R2: aws s3 ls --endpoint-url                                     ║
║      https://<account>.r2.cloudflarestorage.com                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

EOF

read -p "Press ENTER after Step A is COMPLETE in consoles..."

# ── Step B: Prepare filter-repo patterns ───────────────────────────────────────
PATTERNS_FILE=".github/scripts/leaked-credential-patterns.txt"
mkdir -p .github/scripts

cat > "$PATTERNS_FILE" <<'EOF'
# Format: literal_prefix==>***REDACTED***
# These are 12-16 char prefixes that CANNOT be used to reconstruct full secrets
gQAAAAAAAVCIAAIgcDI2Njk2==>***REDACTED***
2fc25bbebc==>***REDACTED***
b7d997bc558346d8146d==>***REDACTED***
casual-sawfish-86152.upstash.io==>***REDACTED***
EOF

log "Created patterns file: $PATTERNS_FILE"
cat "$PATTERNS_FILE"

# ── Step C: Rewrite ALL branches + tags ────────────────────────────────────────
log "Starting git filter-repo (this may take a while)..."

# Create backup branch just in case
git branch backup/pre-filter-repo-$(date +%s)

git filter-repo \
    --force \
    --replace-text "$PATTERNS_FILE" \
    --path-glob '**' \
    --invert-paths \
    --path "***REDACTED***" 2>&1 | tee filter-repo.log

# Verify no patterns remain
log "Verifying no leaked patterns remain..."
patterns_remain=0
while IFS= read -r line; do
    prefix=${line%==>*}
    if git log --all --source --full-history -p -- "$prefix" 2>/dev/null | grep -q "$prefix"; then
        warn "Pattern $prefix still found in history!"
        patterns_remain=1
    fi
done < "$PATTERNS_FILE"

if [[ $patterns_remain -eq 0 ]]; then
    log "✅ No leaked patterns found in rewritten history"
else
    err "❌ Some patterns still present — re-run filter-repo with additional patterns"
    exit 1
fi

# ── Step D: Force-push all branches + tags ─────────────────────────────────────
log "Force-pushing all branches to origin..."
git push origin --force --all
git push origin --force --tags

# ── Step E: Notify clone holders ────────────────────────────────────────────────
cat <<'EOF'

╔══════════════════════════════════════════════════════════════════════════════╗
║ STEP E: Notify all clone holders                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Send this message to everyone who has cloned the repo:                    ║
║                                                                           ║
║  ⚠️  SECURITY: Repository history rewritten due to credential leak.       ║
║  You MUST re-clone:                                                        ║
║    rm -rf audiobook && git clone <repo-url>                               ║
║                                                                           ║
║  Or if you have local commits:                                            ║
║    git fetch origin && git reset --hard origin/main                       ║
║                                                                           ║
║  All leaked credentials have been rotated in cloud consoles.              ║
╚══════════════════════════════════════════════════════════════════════════════╝

EOF

# ── Step F: Update CI/CD secrets ──────────────────────────────────────────────
log "Don't forget to update GitHub Actions secrets:"
echo "  gh secret set REDIS_AUTH --body '<new-upstash-auth>'"
echo "  gh secret set R2_ACCESS_KEY_ID --body '<new-r2-access-key>'"
echo "  gh secret set R2_SECRET_ACCESS_KEY --body '<new-r2-secret-key>'"

log "=========================================="
log "✅ P0-1 RUNBOOK COMPLETE"
log "Credential rotation + history rewrite done."
log "=========================================="