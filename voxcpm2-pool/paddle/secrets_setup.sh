#!/usr/bin/env bash
# paddle/secrets_setup.sh
# 在百度智能云控制台创建 Secret，再用此脚本批量写入环境变量文件
#
# ⚠️ 使用前请将下方占位值替换为你的实际凭据
#    BOS_ACCESS_KEY_ID / BOS_ACCESS_KEY_SECRET 请在百度云控制台获取

set -euo pipefail

ENV_FILE="${PWD}/.env"

cat > "${ENV_FILE}" <<'EOF'
# Redis (Upstash)
REDIS_HOST=casual-sawfish-86152.upstash.io
REDIS_PORT=6379
REDIS_AUTH=gQAAAAAAAVCIAAIgcDI2Njk2ZDcyMmZkNTU0N2FmYTIxZDk4ZDY4MTBjOGM4ZA

# Cloudflare R2
R2_ENDPOINT=https://061b064ef0dafd787d33f4ee1693aa1b.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=2fc25bbebc34f9b88874a8affcda2e3a
R2_SECRET_ACCESS_KEY=b7d997bc558346d8146d33be06810b7db600baafe0cbe5d7356268ee948ef9d3
R2_BUCKET=audiobook-assets
R2_PUBLIC_URL=https://pub-xxx.r2.dev

# Worker 标识
WORKER_ID=baidu-v100-01
VOXCPM2_HF_REPO=openbmb/VoxCPM2

# 仅百度：开启 Paddle 后端
PREFER_PADDLE=true

# 百度云 BOS 配置（用于同步模型权重）
# ⚠️ 替换为你的实际凭据（从百度云控制台获取）
BOS_ACCESS_KEY_ID=your-bos-access-key-id
BOS_ACCESS_KEY_SECRET=your-bos-access-key-secret
BOS_ENDPOINT=https://bj.bcebos.com
BOS_BUCKET=voxcpm2-model
EOF

echo "✅ .env written to ${PWD}/.env"
echo ""
echo "⚠️  请编辑 .env 将 BOS_ACCESS_KEY_ID / BOS_ACCESS_KEY_SECRET"
echo "   替换为你在百度云控制台获取的实际凭据"
echo ""
echo "   获取地址: https://console.bce.baidu.com/iam/#/iam/accesskey"
