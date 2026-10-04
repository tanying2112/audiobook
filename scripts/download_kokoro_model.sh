#!/bin/bash
# Kokoro-ONNX 模型下载脚本（支持断点续传）
# 用法: bash scripts/download_kokoro_model.sh
#
# 下载目标:
#   - kokoro-v1.0.onnx (~310 MB) → models/kokoro-v1.0.onnx
#   - voices-v1.0.bin    (~27 MB)  → models/voices-v1.0.bin
#
# 预计耗时: 约 30-90 分钟（取决于网络）
# 支持中断后重启自动续传

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODELS_DIR="$PROJECT_DIR/models"

MODEL_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

mkdir -p "$MODELS_DIR"
cd "$MODELS_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Kokoro-ONNX 模型下载工具 ===${NC}"
echo "下载目录: $MODELS_DIR"
echo ""

# --- 下载 voices-v1.0.bin (小文件，先下载) ---
VOICES_FILE="$MODELS_DIR/voices-v1.0.bin"
EXPECTED_VOICES_SIZE=28214398  # ~26.9 MB

if [ -f "$VOICES_FILE" ] && [ "$(stat -f%z "$VOICES_FILE" 2>/dev/null || echo 0)" -ge "$EXPECTED_VOICES_SIZE" ]; then
    echo -e "${GREEN}✓ voices-v1.0.bin 已完整 ($(du -h "$VOICES_FILE" | cut -f1))${NC}"
else
    echo -e "${YELLOW}→ 下载 voices-v1.0.bin (~27 MB)...${NC}"
    curl -L -C - -o voices-v1.0.bin --retry 3 --retry-delay 5 --connect-timeout 15 --max-time 600 "$VOICES_URL"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ voices-v1.0.bin 下载完成${NC}"
    else
        echo -e "${RED}✗ voices-v1.0.bin 下载失败，请重试${NC}"
        exit 1
    fi
fi

# --- 下载 kokoro-v1.0.onnx (大文件) ---
MODEL_FILE="$MODELS_DIR/kokoro-v1.0.onnx"
EXPECTED_ONNX_SIZE=325532387  # ~310.5 MB

if [ -f "$MODEL_FILE" ]; then
    CURRENT_SIZE=$(stat -f%z "$MODEL_FILE" 2>/dev/null || echo 0)
    if [ "$CURRENT_SIZE" -ge "$EXPECTED_ONNX_SIZE" ]; then
        echo -e "${GREEN}✓ kokoro-v1.0.onnx 已完整 ($(du -h "$MODEL_FILE" | cut -f1))${NC}"
        echo -e "${GREEN}所有模型文件已就绪！${NC}"
        exit 0
    else
        echo -e "${YELLOW}⊗ kokoro-v1.0.onnx 不完整 (${CURRENT_SIZE}/${EXPECTED_ONNX_SIZE} bytes)，续传中...${NC}"
    fi
fi

echo -e "${YELLOW}→ 下载 kokoro-v1.0.onnx (~310 MB) - 请耐心等待，约需要 30-90 分钟...${NC}"
echo -e "${YELLOW}  (按 Ctrl+C 可中断，再次运行本脚本将自动续传)${NC}"
echo ""

# 带进度条的下载
curl -L -C - -o kokoro-v1.0.onnx --retry 10 --retry-delay 15 --connect-timeout 30 \
    --progress-bar "$MODEL_URL"

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    FINAL_SIZE=$(stat -f%z "$MODEL_FILE" 2>/dev/null || echo 0)
    echo -e "${GREEN}✓ kokoro-v1.0.onnx 下载完成 (${FINAL_SIZE} bytes)${NC}"
    echo -e "${GREEN}所有模型文件已就绪！${NC}"
else
    echo -e "${RED}✗ 下载中断（exit code: ${EXIT_CODE}），请重新运行脚本继续${NC}"
fi

exit $EXIT_CODE