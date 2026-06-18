#!/usr/bin/env bash
# =============================================================================
# Audiobook Studio - 自动清理脚本 (clean_before_commit.sh)
# 用法: ./scripts/clean_before_commit.sh
# 自动运行 autoflake 和 autopep8 以提交前清理代码
# =============================================================================

set -euo pipefail

echo "🧹 开始自动代码清理..."

# 检查依赖是否安装
if ! command -v autoflake &> /dev/null; then
    echo "❌ autoflake 未安装，请先运行: pip install autoflake"
    exit 1
fi

if ! command -v autopep8 &> /dev/null; then
    echo "❌ autopep8 未安装，请先运行: pip install autopep8"
    exit 1
fi

# 运行 autoflake 删除未使用的导入和变量
echo "🔧 运行 autoflake 删除未使用的导入/变量..."
autoflake --remove-all-unused-imports --remove-duplicate-keys --remove-unused-variables --in-place --recursive src tests

# 运行 autopep8 修复 PEP8 格式
echo "🔧 运行 autopep8 修复 PEP8 格式..."
autopep8 --in-place --aggressive --aggressive --recursive src tests

echo "✅ 自动清理完成！"
echo "建议接下来运行: black src tests && isort src tests"