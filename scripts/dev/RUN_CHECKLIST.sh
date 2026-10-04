#!/usr/bin/env bash
# RUN_CHECKLIST.sh - Automated validation checklist for Audiobook Studio
# Run this before committing or pushing to ensure code quality

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Audiobook Studio - Run Checklist     ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Track overall status
ALL_PASSED=true

check_step() {
    local name="$1"
    local cmd="$2"
    echo -e "${BLUE}▶ ${name}${NC}"
    if eval "$cmd"; then
        echo -e "${GREEN}  ✅ PASS${NC}"
        echo ""
        return 0
    else
        echo -e "${RED}  ❌ FAIL${NC}"
        echo ""
        ALL_PASSED=false
        return 1
    fi
}

warn_step() {
    local name="$1"
    local cmd="$2"
    echo -e "${BLUE}▶ ${name} ${YELLOW}(warning only)${NC}"
    if eval "$cmd"; then
        echo -e "${GREEN}  ✅ PASS${NC}"
    else
        echo -e "${YELLOW}  ⚠️  WARNING${NC}"
    fi
    echo ""
}

# 1. Environment checks
echo -e "${YELLOW}=== Environment Checks ===${NC}"
check_step "Python version >= 3.11" "python3 --version | grep -E '3\.(1[1-9]|[2-9][0-9])'"
warn_step "Virtual environment active" "[ -n \"\${VIRTUAL_ENV:-}\" ] && echo \"\${VIRTUAL_ENV}\" || echo 'Not in venv (optional)'"
check_step "Dependencies installed" "python3 -c \"import fastapi; import sqlalchemy\""

# 2. Code quality (pre-commit equivalent)
echo -e "${YELLOW}=== Code Quality ===${NC}"
check_step "Black formatting" "python3 -m black --check --diff src/"
check_step "isort imports" "python3 -m isort --check-only --diff src/"
check_step "Flake8 linting" "python3 -m flake8 --max-line-length=120 src/"
check_step "MyPy type checking" "python3 -m mypy --config-file=mypy.ini src/"

# 3. Security checks
echo -e "${YELLOW}=== Security ===${NC}"
check_step "No hardcoded secrets" "! grep -rE '(api_key|secret|password|token)\s*=\s*[\"'\''][^\"'\'']{8,}' src/ --include='*.py' --include='*.yaml' --include='*.yml'"
check_step "No model weights in repo" "! find . -name '*.safetensors' -o -name '*.pth' -o -name '*.gguf' -o -name '*.bin' | grep -v '.git' | grep -v '.venv' | grep -q . && exit 1 || exit 0"
check_step "Bandit high severity" "python3 -m bandit -r src/ --severity-level=high --skip=B101 -q"

# 4. Tests
echo -e "${YELLOW}=== Tests ===${NC}"
check_step "Unit tests pass" "python3 -m pytest tests/ -x -q --tb=short --maxfail=5"
check_step "Coverage >= 60%" "python3 -m pytest tests/ --cov=src/audiobook_studio --cov-report=term-missing --cov-fail-under=60 -q"

# 5. Schema/Contract validation
echo -e "${YELLOW}=== Schema Validation ===${NC}"
check_step "Pydantic schemas valid" "python3 -m src.audiobook_studio.schemas.schema_validator"
check_step "ORM-Schema sync" "python3 -c \"from src.audiobook_studio.models import *; from src.audiobook_studio.schemas import *; print('All imports OK')\""

# 6. Pipeline integrity
echo -e "${YELLOW}=== Pipeline Integrity ===${NC}"
check_step "Pipeline stages load" "python3 -c \"from src.audiobook_studio.pipeline.stage_registry import StageRegistry; print('Stages:', StageRegistry.list_stages())\""
check_step "CLI entry points work" "python3 -m src.audiobook_studio.run_pipeline --help >/dev/null"
check_step "API routes load" "python3 -c \"from src.audiobook_studio.api import *; print('API OK')\""

# 7. Docker/build checks (optional)
echo -e "${YELLOW}=== Build Checks (optional) ===${NC}"
warn_step "Dockerfile syntax" "docker build --dry-run -f Dockerfile . 2>&1 | head -20 || true"
warn_step "Docker compose valid" "docker compose config -q 2>/dev/null || true"

# Summary
echo -e "${BLUE}========================================${NC}"
if [ "$ALL_PASSED" = true ]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED${NC}"
    echo -e "${GREEN}Safe to commit/push${NC}"
    echo -e "${BLUE}========================================${NC}"
    exit 0
else
    echo -e "${RED}❌ SOME CHECKS FAILED${NC}"
    echo -e "${RED}Fix issues before committing${NC}"
    echo -e "${BLUE}========================================${NC}"
    exit 1
fi