#!/usr/bin/env bash
# =============================================================================
# Agent Worktree Setup — 本地物理隔离工作树
# =============================================================================
# 为 Agent A/B/C 创建完全独立的物理工作目录（git worktree），
# 彻底消除本地并发开发时的文件争抢和 .coverage 冲突。
#
# 用法:
#   chmod +x scripts/agent-worktree-setup.sh
#   ./scripts/agent-worktree-setup.sh setup       # 创建 3 个隔离工作树
#   ./scripts/agent-worktree-setup.sh status      # 查看所有工作树状态
#   ./scripts/agent-worktree-setup.sh teardown    # 移除所有 Agent 工作树
#
# 前置条件:
#   - 项目根目录必须是 git 仓库
#   - git >= 2.5（支持 worktree）
# =============================================================================

set -euo pipefail

# ── 颜色定义 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ── 配置 ────────────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARENT_DIR="$(dirname "$PROJECT_ROOT")"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
BASE_BRANCH="main"

# Agent 工作树定义：name|branch|scope_description
declare -A AGENT_WORKTREES=(
  ["agent-A"]="agent/A/workspace|后端核心: pipeline/quality/utils/llm/tts/schemas/models/feedback"
  ["agent-B"]="agent/B/workspace|前端基建: web/src/{views,components,stores,composables}"
  ["agent-C"]="agent/C/workspace|跨端胶水: api/monitoring/publish/auth/middleware/config"
)

# ── 函数 ────────────────────────────────────────────────────────────────────
log_info()  { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_ok()    { echo -e "${GREEN}✅ $1${NC}"; }
log_warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}🚨 $1${NC}"; }

usage() {
    echo "Usage: $0 {setup|status|teardown|help}"
    echo ""
    echo "Commands:"
    echo "  setup     为 Agent A/B/C 创建隔离工作树"
    echo "  status    查看所有工作树状态"
    echo "  teardown  移除所有 Agent 工作树"
    echo "  help      显示帮助信息"
    exit 0
}

cmd_setup() {
    log_info "在 ${PARENT_DIR}/ 下为 3 个 Agent 创建物理隔离工作树..."
    echo ""

    cd "$PROJECT_ROOT"

    # 确保基线分支存在
    if ! git rev-parse --verify "$BASE_BRANCH" &>/dev/null; then
        log_error "基线分支 $BASE_BRANCH 不存在，请先确保 main 分支就绪。"
        exit 1
    fi

    for agent_name in agent-A agent-B agent-C; do
        IFS='|' read -r branch_name scope_desc <<< "${AGENT_WORKTREES[$agent_name]}"
        worktree_path="${PARENT_DIR}/${PROJECT_NAME}-${agent_name}"

        if [[ -d "$worktree_path" ]]; then
            log_warn "${agent_name} 工作树已存在: ${worktree_path}  (跳过)"
            continue
        fi

        log_info "创建 ${agent_name} 工作树..."
        git worktree add "$worktree_path" -b "$branch_name" "$BASE_BRANCH" 2>/dev/null || \
            git worktree add "$worktree_path" "$branch_name" 2>/dev/null || \
            git worktree add "$worktree_path" "$BASE_BRANCH"

        # 在新工作树中初始化虚拟环境和 pre-commit
        if [[ -f "$worktree_path/pyproject.toml" ]]; then
            log_info "  初始化 ${agent_name} 虚拟环境..."
            (cd "$worktree_path" && python -m venv .venv 2>/dev/null && \
             "$worktree_path/.venv/bin/pip" install -e ".[dev]" 2>/dev/null && \
             "$worktree_path/.venv/bin/pre-commit" install 2>/dev/null) || true
        fi

        log_ok "${agent_name} 工作树就绪"
        echo -e "  📁 ${worktree_path}"
        echo -e "  🏷️  分支: ${branch_name}"
        echo -e "  🎯 领地: ${scope_desc}"
        echo ""
    done

    echo "───────────────────────────────────────────"
    log_ok "全部 3 个 Agent 工作树创建完毕！"
    echo ""
    echo "使用方法："
    echo "  cd ${PARENT_DIR}/${PROJECT_NAME}-agent-A   # Agent A 专属目录"
    echo "  cd ${PARENT_DIR}/${PROJECT_NAME}-agent-B   # Agent B 专属目录"
    echo "  cd ${PARENT_DIR}/${PROJECT_NAME}-agent-C   # Agent C 专属目录"
    echo ""
    echo "隔离效果："
    echo "  ✅ 每个 Agent 拥有独立的文件系统"
    echo "  ✅ pytest --cov 扫描互不干扰"
    echo "  ✅ .coverage 文件物理隔离，无读写冲突"
    echo "  ✅ 各自独立的 .venv 虚拟环境"
}

cmd_status() {
    log_info "当前 git worktree 状态："
    echo ""
    git worktree list
    echo ""
    log_info "Agent 专属工作树："
    for agent_name in agent-A agent-B agent-C; do
        worktree_path="${PARENT_DIR}/${PROJECT_NAME}-${agent_name}"
        if [[ -d "$worktree_path" ]]; then
            log_ok "${agent_name}: ${worktree_path} ($(cd "$worktree_path" && git branch --show-current 2>/dev/null || echo 'detached'))"
        else
            log_warn "${agent_name}: 未创建"
        fi
    done
}

cmd_teardown() {
    log_warn "即将移除所有 Agent 工作树（不删除分支，仅移除物理目录）..."
    read -p "确认？(y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "已取消。"
        exit 0
    fi

    cd "$PROJECT_ROOT"
    for agent_name in agent-A agent-B agent-C; do
        worktree_path="${PARENT_DIR}/${PROJECT_NAME}-${agent_name}"
        if [[ -d "$worktree_path" ]]; then
            git worktree remove --force "$worktree_path" 2>/dev/null || rm -rf "$worktree_path"
            log_ok "已移除 ${agent_name} 工作树: ${worktree_path}"
        fi
    done
    echo ""
    log_ok "清理完毕。注意：分支仍保留在 Git 中。"
}

# ── 入口 ────────────────────────────────────────────────────────────────────
case "${1:-help}" in
    setup)    cmd_setup ;;
    status)   cmd_status ;;
    teardown) cmd_teardown ;;
    help|*)   usage ;;
esac
