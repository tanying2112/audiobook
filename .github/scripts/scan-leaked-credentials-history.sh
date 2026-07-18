#!/usr/bin/env bash
# .github/scripts/scan-leaked-credentials-history.sh
# P0-1 凭据泄露治理 — Git 历史扫描
#
# 作用: 检查所有 commits 是否包含已撤销凭据前缀。
#       在 docs/AUDIT_REPORT_v3.md P0-1 重写历史完成后，预期返回 0。
#       若历史重写完成前 CI 跑此脚本，会失败——这正是其目的：
#       防止"重写历史被遗忘"。
# 来源: docs/AUDIT_REPORT_v3.md P0-1（2026-07-18）。
# 退出码: 0 = 干净；1 = 发现泄露。
#
# 安全设计: 同 scan-leaked-credentials.sh；前缀 ≤ 16 字符，不构成有效凭据。

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# 与 worktree 脚本保持一致的前缀。
declare -a LEAK_PREFIXES=(
    "gQAAAAAAAVCI"
    "2fc25bbebc34"
    "b7d997bc5583"
    "casual-sawfish-86152"
)

ALL_COMMITS=$(git rev-list --all 2>/dev/null || git rev-list HEAD)

echo "🔍 Scanning $(echo "$ALL_COMMITS" | wc -l | tr -d ' ') commits for known leaked credential patterns..."
FOUND=0
for pat in "${LEAK_PREFIXES[@]}"; do
    # git grep 多 commit 时退出码 0/1/2，用 `|| true` 兼容。
    # 通过 pathspec 排除本扫描脚本自身与审计文档（这些文件天然引用前缀）。
    matches=$(git grep -l -- "$pat" $ALL_COMMITS -- \
        ':!.github/scripts/scan-leaked-credentials.sh' \
        ':!.github/scripts/scan-leaked-credentials-history.sh' \
        ':!docs/AUDIT_REPORT_v3.md' \
        ':!docs/RUNBOOK_rotate_credentials.md' \
        2>/dev/null || true)
    if [ -n "$matches" ]; then
        count=$(echo "$matches" | wc -l | tr -d ' ')
        echo "❌ Found leaked pattern (prefix): $pat  (in $count commits/files)"
        echo "$matches" | head -10 | sed 's/^/    /'
        if [ "$count" -gt 10 ]; then
            echo "    ...(total $count hits, showing first 10)"
        fi
        FOUND=1
    fi
done

if [ "$FOUND" -eq 1 ]; then
    echo ""
    echo "🚨 P0-1 LEAK STILL PRESENT in git history."
    echo "    To fix: run docs/RUNBOOK_rotate_credentials.md step B (git filter-repo),"
    echo "    then force-push main (and all topic branches)."
    exit 1
fi

echo "✅ Git history is clean of known leaked credential patterns."
exit 0
