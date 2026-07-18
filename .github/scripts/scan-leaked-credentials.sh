#!/usr/bin/env bash
# .github/scripts/scan-leaked-credentials.sh
# P0-1 凭据泄露治理 — 工作树扫描
#
# 作用: 检查当前 worktree 是否包含已撤销凭据的前缀。
# 来源: docs/AUDIT_REPORT_v3.md P0-1（2026-07-18）。
# 退出码: 0 = 干净；1 = 发现泄露。
#
# 安全设计:
#   - 本脚本只匹配凭据前缀（12-16 字符，足以唯一识别，不足以重构原值）。
#   - 同时排除自身 / audit 文档：这些文件本来就引用了前缀做证据，
#     合并进扫描只会自我误射。
#   - 前缀 < 16 字符；无法用前缀本身完成 Redis AUTH / R2 认证。

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# 已撤销凭据前缀（≤ 16 字符，不构成有效认证 token）。
declare -a LEAK_PREFIXES=(
    "gQAAAAAAAVCI"          # Redis AUTH token 开头 12 字符（原 62 字符 token 已轮换失效）
    "2fc25bbebc34"          # R2 Access Key ID 开头 12 字符（32 hex，已轮换）
    "b7d997bc5583"          # R2 Secret Access Key 开头 12 字符（64 hex，已轮换）
    "casual-sawfish-86152"  # Upstash Redis 主机名前段
)

# 排除自身与审计文档（它们就被设计为引用前缀，不构成二次泄露）。
EXCLUDE_PATTERN='^\.(github/scripts/|gitignore$)|^docs/(AUDIT_REPORT_v3|RUNBOOK_rotate_credentials)\.md$|^\.gitignore$'

echo "🔍 Scanning worktree for known leaked credential patterns..."
FOUND=0
for pat in "${LEAK_PREFIXES[@]}"; do
    matches=$(git ls-files | grep -vE "$EXCLUDE_PATTERN" | xargs grep -l -- "$pat" 2>/dev/null || true)
    if [ -n "$matches" ]; then
        echo "❌ Worktree contains leaked pattern (prefix): $pat"
        echo "$matches" | sed 's/^/    file: /'
        FOUND=1
    fi
done

if [ "$FOUND" -eq 1 ]; then
    echo ""
    echo "🚨 P0-1 LEAK DETECTED. See docs/AUDIT_REPORT_v3.md and docs/RUNBOOK_rotate_credentials.md."
    echo "    The credentials above have been revoked; please rotate to new values."
    exit 1
fi

echo "✅ Worktree clean of known leaked credential patterns."
exit 0
