#!/usr/bin/env bash
# entrypoint.sh - Container startup script with model verification

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

MODEL_DIR="${MODELS_DIR:-/app/models}/kokoro-onnx"
REQUIRED_FILES=("kokoro-v1.0.onnx" "voices-v1.0.bin")

echo -e "${GREEN}=== Audiobook Studio Container Startup ===${NC}"
echo "Model directory: ${MODEL_DIR}"

# Check if we're in mock mode - skip model download if so
if [[ "${MOCK_TTS}" == "true" ]]; then
    echo -e "${YELLOW}Mock TTS mode enabled - skipping model download${NC}"
else
    # Check if models exist
    missing_files=()
    for file in "${REQUIRED_FILES[@]}"; do
        if [[ ! -f "${MODEL_DIR}/${file}" ]]; then
            missing_files+=("${file}")
        else
            echo -e "  ${GREEN}✓${NC} Found: ${file}"
        fi
    done

    # Download missing models
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        echo -e "${YELLOW}Missing model files: ${missing_files[*]}${NC}"
        echo "Downloading models..."
        
        python /tmp/download_kokoro_model.py --output-dir "${MODEL_DIR}"
        
        if [[ $? -eq 0 ]]; then
            echo -e "${GREEN}✓ Models downloaded successfully${NC}"
        else
            echo -e "${RED}✗ Failed to download models${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✓ All model files present${NC}"
    fi
fi

# Database migrations are managed EXTERNALLY (S3-4). The `migrate` service in
# docker-compose runs `scripts/migrate.sh up` (after db is healthy) and operators
# run `scripts/migrate.sh up` manually for zero-downtime, rollbackable deploys.
# The app itself never runs migrations at startup. Opt in for a single-container
# dev run with AUTO_MIGRATE=1.
if [[ "${AUTO_MIGRATE:-0}" == "1" && -f "alembic.ini" ]]; then
    echo "Running database migrations (AUTO_MIGRATE=1)..."
    alembic upgrade head
fi

# Execute the main command
echo -e "${GREEN}=== Starting Application ===${NC}"
exec "$@"
