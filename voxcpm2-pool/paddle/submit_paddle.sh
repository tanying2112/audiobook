#!/usr/bin/env bash
# paddle/submit_paddle.sh
# 先同步镜像，再提交 Job

set -euo pipefail

echo "🔄 Syncing model weights..."
bash mirror_sync.sh

echo "🚀 Submitting Paddle job..."
paddlectl job create -f paddle_job.yaml
EOF