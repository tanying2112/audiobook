#!/usr/bin/env bash
# start_gpu_stack.sh - Start Audiobook Studio with GPU TTS services (Pro Studio mode)
#
# This script starts the full stack with VoxCPM2 and/or CosyVoice GPU services.
# It handles model downloading, health checks, and environment setup.
#
# Usage:
#   ./scripts/start_gpu_stack.sh [voxcpm2|cosyvoice|both] [--dev]
#
# Prerequisites:
#   - NVIDIA GPU with 8GB+ VRAM
#   - nvidia-container-toolkit installed
#   - Docker Compose v2+
#   - HF_TOKEN or MODELSCOPE_TOKEN for gated models (export in .env.gpu or shell)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Default profile
PROFILE="${1:-both}"
DEV_MODE=false

if [[ "${2:-}" == "--dev" ]] || [[ "${1:-}" == "--dev" ]]; then
    DEV_MODE=true
    if [[ "${1:-}" != "--dev" ]]; then
        PROFILE="${2:-both}"
    else
        PROFILE="${3:-both}"
    fi
fi

# Validate profile
case "$PROFILE" in
    voxcpm2|cosyvoice|both) ;;
    *)
        echo "Error: Invalid profile '$PROFILE'. Use: voxcpm2, cosyvoice, or both"
        exit 1
        ;;
esac

# Check for nvidia-container-toolkit
if ! docker info 2>/dev/null | grep -q "Runtimes:.*nvidia"; then
    echo "Warning: nvidia-container-toolkit not detected. GPU services may fail to start."
    echo "Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
fi

# Load environment
if [[ -f .env.gpu ]]; then
    echo "Loading .env.gpu..."
    set -a
    source .env.gpu
    set +a
elif [[ -f .env ]]; then
    echo "Loading .env..."
    set -a
    source .env
    set +a
fi

# Check for required tokens
if [[ -z "${HF_TOKEN:-}" && -z "${MODELSCOPE_TOKEN:-}" ]]; then
    echo "Warning: Neither HF_TOKEN nor MODELSCOPE_TOKEN set."
    echo "Some models (VoxCPM2, CosyVoice) are gated and require authentication."
    echo "Get HF token: https://huggingface.co/settings/tokens"
    echo "Get ModelScope token: https://modelscope.cn/my/myaccesstoken"
fi

# Build compose command
COMPOSE_CMD="docker compose -f docker-compose.gpu.yml"

if [[ "$PROFILE" == "voxcpm2" ]]; then
    COMPOSE_CMD="$COMPOSE_CMD --profile voxcpm2"
elif [[ "$PROFILE" == "cosyvoice" ]]; then
    COMPOSE_CMD="$COMPOSE_CMD --profile cosyvoice"
else
    COMPOSE_CMD="$COMPOSE_CMD --profile voxcpm2 --profile cosyvoice"
fi

if [[ "$DEV_MODE" == "true" ]]; then
    COMPOSE_CMD="$COMPOSE_CMD --profile dev"
fi

echo "=========================================="
echo "Starting Audiobook Studio GPU Stack"
echo "Profile: $PROFILE"
echo "Dev mode: $DEV_MODE"
echo "=========================================="

# Pull base images first (faster startup)
echo "Pulling base images..."
docker pull nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04 || true
docker pull postgres:16-alpine
docker pull redis:7-alpine
docker pull node:20-alpine

# Build and start
echo "Building and starting services..."
$COMPOSE_CMD build --parallel
$COMPOSE_CMD up -d

# Wait for services to be healthy
echo "Waiting for services to be healthy..."

wait_for_health() {
    local service=$1
    local max_wait=${2:-300}
    local waited=0
    local interval=10

    echo -n "Waiting for $service... "
    while [[ $waited -lt $max_wait ]]; do
        if docker compose -f docker-compose.gpu.yml ps "$service" 2>/dev/null | grep -q "healthy"; then
            echo "OK"
            return 0
        fi
        sleep $interval
        waited=$((waited + interval))
        echo -n "."
    done
    echo "TIMEOUT"
    return 1
}

# Wait for infrastructure first
wait_for_health db 60
wait_for_health redis 30

# Wait for GPU services (longer timeout for model loading)
if [[ "$PROFILE" == "voxcpm2" || "$PROFILE" == "both" ]]; then
    wait_for_health voxcpm2 240
fi
if [[ "$PROFILE" == "cosyvoice" || "$PROFILE" == "both" ]]; then
    wait_for_health cosyvoice 300
fi

# Wait for main API
wait_for_health api 60

echo ""
echo "=========================================="
echo "All services healthy!"
echo "=========================================="
echo ""
echo "Endpoints:"
echo "  Main API:       http://localhost:8000"
echo "  API Docs:       http://localhost:8000/docs"
if [[ "$PROFILE" == "voxcpm2" || "$PROFILE" == "both" ]]; then
    echo "  VoxCPM2:        http://localhost:5010"
    echo "  VoxCPM2 Health: http://localhost:5010/health"
fi
if [[ "$PROFILE" == "cosyvoice" || "$PROFILE" == "both" ]]; then
    echo "  CosyVoice:      http://localhost:5020"
    echo "  CosyVoice Health: http://localhost:5020/health"
fi
if [[ "$DEV_MODE" == "true" ]]; then
    echo "  Frontend:       http://localhost:5173"
fi
echo ""
echo "Logs: docker compose -f docker-compose.gpu.yml logs -f"
echo "Stop: docker compose -f docker-compose.gpu.yml down"