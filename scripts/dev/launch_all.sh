#!/usr/bin/env bash
# filename: launch_all.sh
# 暗夜音频工厂 v1.1 - 多云 GPU 全自动抢单集群拉起

set -e

echo "====================================================="
echo "🏎️  暗夜音频工厂 v1.1 - 多云 GPU 全自动抢单集群拉起"
echo "====================================================="

# 1. 通道 A：Kaggle 异步批处理推流
if command -v kaggle >/dev/null 2>&1; then
    echo "🛰️  [1/3] 正在向 Kaggle 推送 Batch 任务..."
    cd ./worker_kaggle && kaggle kernels push && kaggle kernels start
    cd ..
else
    echo "⚠️  未检测到 Kaggle CLI，跳过通道 A。"
fi

# 2. 通道 B：Lightning AI Studio 弹性挂载
if command -v lightning >/dev/null 2>&1; then
    echo "⚡ [2/3] 正在拉起 Lightning AI 独立 T4 Studio 节点..."
    lightning run studio --instance-type gpu-t4 ./worker/worker.py
else
    echo "⚠️  未检测到 Lightning CLI，跳过通道 B。"
fi

# 3. 通道 C：Modal Serverless GPU 矩阵（Detach 模式，云端原生自毁）
if command -v modal >/dev/null 2>&1; then
    echo "🌌 [3/3] 正在以 Detach 模式引爆 Modal Serverless GPU 矩阵..."
    modal run ./worker/modal_worker.py --detach
else
    echo "⚠️  未检测到 Modal CLI，跳过通道 C。"
fi

echo "====================================================="
echo "✅ 所有可用通道已拉起。云端 GPU 正在疯狂抢单中..."
echo "====================================================="