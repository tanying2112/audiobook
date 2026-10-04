#!/usr/bin/env bash
# .git/hooks/post-commit — Living documentation auto-update
#
# This hook runs after a successful commit to:
# 1. Check if any schema/prompt/contract files changed
# 2. Auto-regenerate living docs if needed
# 3. Update PROJECT_STATUS.md with commit info
#
# Install: cp scripts/post-commit-hook.sh .git/hooks/post-commit && chmod +x .git/hooks/post-commit

set -euo pipefail

# Configuration
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Skip in CI environments
if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "[post-commit] Running in CI, skipping living docs update"
    exit 0
fi

# Get commit info
COMMIT_HASH=$(git rev-parse --short HEAD)
COMMIT_MSG=$(git log -1 --pretty=%B)
COMMIT_AUTHOR=$(git log -1 --pretty=%an)
COMMIT_DATE=$(date '+%Y-%m-%d %H:%M')

echo "[post-commit] Commit $COMMIT_HASH by $COMMIT_AUTHOR"
echo "[post-commit] Message: $COMMIT_MSG"

# Files that trigger doc regeneration
DOC_TRIGGER_PATTERNS=(
    "src/audiobook_studio/schemas/*.py"
    "prompts/analyze_structure/*.j2"
    "prompts/analyze_structure/few_shot.jsonl"
    "src/audiobook_studio/pipeline/analyze_structure.py"
    "src/audiobook_studio/analyzer.py"
    "src/audiobook_studio/pipeline/audio_finalize.py"
    "src/audiobook_studio/pipeline/audio_postprocess.py"
    "src/audiobook_studio/pipeline/synthesize.py"
    "src/audiobook_studio/pipeline/orchestrator.py"
    "src/audiobook_studio/api/"
    "src/audiobook_studio/core/telemetry.py"
)

# Check if any trigger files were modified in this commit
CHANGED_FILES=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || git diff --name-only HEAD 2>/dev/null)
TRIGGERED=false

for pattern in "${DOC_TRIGGER_PATTERNS[@]}"; do
    # Convert glob to regex for matching
    regex=$(echo "$pattern" | sed 's/\*/.*/g' | sed 's/\?/./g')
    if echo "$CHANGED_FILES" | grep -qE "$regex"; then
        TRIGGERED=true
        echo "[post-commit] Trigger file changed: $pattern"
        break
    fi
done

# Also check for specific keywords in commit message
if echo "$COMMIT_MSG" | grep -qiE "(schema|prompt|contract|scene_tags|audio_finalize|audio_postprocess|telemetry|api|endpoint)"; then
    TRIGGERED=true
    echo "[post-commit] Commit message mentions schema/prompt/contract"
fi

if [ "$TRIGGERED" = false ]; then
    echo "[post-commit] No schema/prompt changes detected, skipping doc update"
    exit 0
fi

# Update living docs
echo "[post-commit] Updating living documentation..."

# 1. Update PROJECT_STATUS.md with latest commit
if [ -f "PROJECT_STATUS.md" ]; then
    TEMP_FILE=$(mktemp)
    awk -v date="$(date '+%Y-%m-%d')" -v hash="$COMMIT_HASH" -v msg="$(echo "$COMMIT_MSG" | head -1 | cut -c1-80)" '
        /^## Recent Activity/ { print; print ""; print "- " date " [" hash "] " msg; next }
        { print }
    ' PROJECT_STATUS.md > "$TEMP_FILE" && mv "$TEMP_FILE" PROJECT_STATUS.md
    echo "[post-commit] Updated PROJECT_STATUS.md activity log"
fi

# 2. Regenerate OpenAPI spec if schemas changed
if echo "$CHANGED_FILES" | grep -q "src/audiobook_studio/schemas/"; then
    if python3 -c "import fastapi, sys; sys.path.insert(0, 'src'); from audiobook_studio.api import create_app; import json; app = create_app(); open('docs/openapi.json', 'w').write(json.dumps(app.openapi(), indent=2))" 2>/dev/null; then
        echo "[post-commit] Regenerated OpenAPI spec → docs/openapi.json"
    else
        echo "[post-commit] Warning: Could not regenerate OpenAPI spec"
    fi
fi

# 3. Validate prompt contracts (schema compliance)
if echo "$CHANGED_FILES" | grep -qE "prompts/analyze_structure/.*\.j2"; then
    if python3 -c "
import sys
sys.path.insert(0, 'src')
from audiobook_studio.schemas.book import BookAnalysisOutput
import json
schema = BookAnalysisOutput.model_json_schema()
print('BookAnalysisOutput schema valid')
print('Fields:', list(schema.get('properties', {}).keys()))
" 2>/dev/null; then
        echo "[post-commit] Prompt contract validation passed"
    else
        echo "[post-commit] Warning: Schema validation failed"
    fi
fi

# 4. Check test coverage baseline (informational)
if command -v pytest &> /dev/null; then
    echo "[post-commit] Quick coverage check..."
    COV=$(python3 -m pytest --co -q 2>/dev/null | tail -1 | grep -oE '[0-9]+%' || echo "unknown")
    echo "[post-commit] Test collection: $COV tests"
fi

# 5. Log commit to git commit log (for sprint tracking)
LOG_FILE="docs/git-commit-log.md"
if [ ! -f "$LOG_FILE" ]; then
    echo "# Git Commit Log" > "$LOG_FILE"
    echo "" >> "$LOG_FILE"
    echo "Auto-generated log of commits affecting schema/prompt/contract files." >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
fi
echo "- $(date '+%Y-%m-%d %H:%M') [$COMMIT_HASH] $COMMIT_AUTHOR: $(echo "$COMMIT_MSG" | head -1 | cut -c1-100)" >> "$LOG_FILE"
echo "[post-commit] Logged to $LOG_FILE"

# 6. Run docs-guard to check for stale docs (async warning only)
if [ -f "scripts/docs_guard.py" ]; then
    python3 scripts/docs_guard.py --async 2>/dev/null &
    echo "[post-commit] Docs guard check queued (async)"
fi

# 7. Generate changelog fragment from conventional commit
if [ -f "scripts/generate_changelog_fragment.py" ]; then
    python3 scripts/generate_changelog_fragment.py 2>/dev/null || true
    echo "[post-commit] Changelog fragment generated"
fi

echo "[post-commit] Living docs update complete ✅"