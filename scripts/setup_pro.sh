#!/bin/bash
# Audiobook Studio — Pro Studio 档一键拉起脚本 (P2.14)
#
# 一键配置 pro_studio 档: GPU/显存检测 → VoxCPM2 模型下载 → CosyVoice 指引 → 切 active_profile。
# 用法: bash scripts/setup_pro.sh
#
# 诚实约束 (红线#1):
#   - 无 GPU 或显存 < 16GB: 诚实降级提示退出, 不假声明成功
#   - 不自动拉 GB 级模型: VoxCPM2 编排既有 download_voxcpm2.py, CosyVoice 仅给 HF 指引 (免费资源上限)
#   - 每步失败明确报错退出, 不 silent-fallback-as-success
#
# 退出码:
#   0  Pro 档配置完成 (模型就绪 + active_profile 已切)
#   1  硬件不达标 (无 GPU / 显存不足) — 诚实降级, 请补硬件后重跑
#   2  模型下载/校验失败 — 见 stderr, 重跑或手动补模型

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/config/hardware_profile.yaml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Audiobook Studio — Pro Studio 档配置 ===${NC}"
echo "项目根: $PROJECT_DIR"
echo ""

# ── 1. GPU + 显存检测 (诚实判断 pro_studio 前提硬件) ──────────────────────
echo -e "${YELLOW}→ [1/4] 检测 GPU (pro_studio 要求 min_vram_gb=16)...${NC}"

GPU_DETECTED=false
VRAM_GB=0

if command -v nvidia-smi >/dev/null 2>&1; then
    # NVIDIA CUDA: 取首张 GPU 显存(MB)
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    if [ -n "$VRAM_MB" ] && [ "$VRAM_MB" -gt 0 ] 2>/dev/null; then
        GPU_DETECTED=true
        VRAM_GB=$((VRAM_MB / 1024))
    fi
elif command -v system_profiler >/dev/null 2>&1 && [[ "$(uname)" == "Darwin" ]]; then
    # macOS Apple Silicon / AMD: system_profiler 无独立显存概念, Metal 统一内存按总 RAM 估
    # 诚实: Metal unified memory 不等价 CUDA VRAM, 仅作 GPU 存在性判断, 显存按主存提示
    CHIP=$(system_profiler SPHardwareDataType 2>/dev/null | grep -i "Chip" | head -1)
    if echo "$CHIP" | grep -qi "Apple M\|Apple S"; then
        GPU_DETECTED=true
        # Apple Silicon 无独立 VRAM, 用 unified memory; pro_studio CUDA 路径未必可用
        # 诚实降级: 不假报 16GB VRAM 达标
        GPU_DETECTED=false
        echo -e "${YELLOW}  检测到 Apple Silicon。VoxCPM2/CosyVoice 为 CUDA 优化模型,${NC}"
        echo -e "${YELLOW}  Apple Metal 路径尚未验证支持。pro_studio 档建议 NVIDIA/AMD CUDA 环境。${NC}"
    fi
fi

if [ "$GPU_DETECTED" != "true" ]; then
    echo -e "${RED}✗ 未检测到可用的 CUDA GPU, 或显存信息不可读。${NC}"
    echo -e "${RED}  pro_studio 档要求 NVIDIA/AMD GPU 且 VRAM ≥ 16GB (推荐 24GB)。${NC}"
    echo -e "${RED}  诚实降级: 不切换到 pro_studio (避免假装成功)。${NC}"
    echo -e "${YELLOW}  请补硬件后重跑, 或保持 cloud_hybrid/potato 档。${NC}"
    exit 1
fi

if [ "$VRAM_GB" -lt 16 ]; then
    echo -e "${RED}✗ GPU 显存 ${VRAM_GB}GB < pro_studio 要求的 16GB。${NC}"
    echo -e "${RED}  诚实降级: 不切换 pro_studio (显存不足会 OOM 崩源, 不假装成功)。${NC}"
    exit 1
fi

echo -e "${GREEN}✓ GPU 检测通过: ${VRAM_GB}GB VRAM ≥ 16GB${NC}"
echo ""

# ── 2. VoxCPM2 模型下载 (编排既有 download_voxcpm2.py) ─────────────────────
echo -e "${YELLOW}→ [2/4] VoxCPM2 模型 (编排 scripts/download_voxcpm2.py)...${NC}"
echo -e "${YELLOW}  约 4-8 GB, 视网络 10-60 分钟。中断可重跑自动续传。${NC}"

if [ -f "$PROJECT_DIR/models/VoxCPM2/config.json" ]; then
    echo -e "${GREEN}✓ VoxCPM2 模型已存在, 跳过下载 (verify-only 校验)${NC}"
    if ! .venv/bin/python scripts/download_voxcpm2.py --verify-only 2>&1; then
        echo -e "${RED}✗ VoxCPM2 校验失败, 模型残缺。请删 models/VoxCPM2 后重跑下载。${NC}"
        exit 2
    fi
else
    echo -e "${YELLOW}→ 下载中 (huggingface_hub)...${NC}"
    if ! .venv/bin/python scripts/download_voxcpm2.py 2>&1; then
        echo -e "${RED}✗ VoxCPM2 下载失败。见上方错误。${NC}"
        echo -e "${RED}  国内网络可加 --hf-mirror https://hf-mirror.com 重跑。${NC}"
        exit 2
    fi
fi
echo ""

# ── 3. CosyVoice 回退模型指引 (无专用下载脚本, 仅给 HF 指引) ───────────────
echo -e "${YELLOW}→ [3/4] CosyVoice 回退模型 (pro_studio fallback_chain 第一回退)...${NC}"
COSYVOICE_DIR="$PROJECT_DIR/models/CosyVoice-300M"
if [ -f "$COSYVOICE_DIR/config.json" ]; then
    echo -e "${GREEN}✓ CosyVoice 模型已存在: $COSYVOICE_DIR${NC}"
else
    echo -e "${YELLOW}  CosyVoice 无专用下载脚本, 请手动拉取 (免费资源上限, 不自动拉):${NC}"
    echo -e "${YELLOW}    pip install -U huggingface_hub${NC}"
    echo -e "${YELLOW}    huggingface-cli download FunAudioLLM/CosyVoice-300M --local-dir models/CosyVoice-300M${NC}"
    echo -e "${YELLOW}  pro_studio 档主引擎为 VoxCPM2, CosyVoice 仅为回退; 缺失时自动降级 VoxCPM2→kokoro。${NC}"
fi
echo ""

# ── 4. 切换 active_profile 到 pro_studio ──────────────────────────────────
echo -e "${YELLOW}→ [4/4] 切 active_profile → pro_studio (config/hardware_profile.yaml)...${NC}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}✗ 配置文件不存在: $CONFIG_FILE${NC}"
    exit 2
fi

# 用 sed 原地替换 active_profile 行 (兼容 cloud_hybrid / potato 等任意旧值)
if sed -i.bak -E 's/^active_profile:[[:space:]]*["A-Za-z_-]+/active_profile: "pro_studio"/' "$CONFIG_FILE"; then
    rm -f "$CONFIG_FILE.bak"
    # 核实替换成功
    NEW_VAL=$(grep -E '^active_profile:' "$CONFIG_FILE" | head -1)
    if echo "$NEW_VAL" | grep -q '"pro_studio"'; then
        echo -e "${GREEN}✓ 已切换: $NEW_VAL${NC}"
    else
        echo -e "${RED}✗ 替换未生效, 当前: $NEW_VAL${NC}"
        exit 2
    fi
else
    echo -e "${RED}✗ sed 替换失败${NC}"
    exit 2
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Pro Studio 档配置完成${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  GPU: ${VRAM_GB}GB VRAM"
echo -e "  VoxCPM2: models/VoxCPM2 (就绪)"
[ -f "$COSYVOICE_DIR/config.json" ] && echo -e "  CosyVoice: models/CosyVoice-300M (就绪)" || echo -e "  CosyVoice: 未就绪 (手动拉取, 见上方指引)"
echo -e "  active_profile: pro_studio"
echo ""
echo -e "${YELLOW}下一步: 启动服务验证 (如 docker compose up -d 或按 README 运行)。${NC}"
echo -e "${YELLOW}注: tensorrt/torch+cuda 依赖若未装, 请先 pip install -r requirements.txt。${NC}"
exit 0
