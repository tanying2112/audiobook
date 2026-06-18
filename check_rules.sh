#!/usr/bin/env bash
# =============================================================================
# Audiobook Studio 自检脚本 (check_rules.sh)
# 用法: ./check_rules.sh [--fast] [--full]
#   --fast : 仅检查关键文件存在性和语法错误（跳过依赖安装检查）
#   --full : 完整检查（默认）
# =============================================================================

set -euo pipefail

# macOS bash 3.2 不支持 globstar，用 find 替代 ** 通配符
# shopt -s globstar  # （已移除，macOS 兼容）

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# 计数器
declare -i PASSED=0
declare -i FAILED=0
declare -i WARNINGS=0

# 选项
MODE="full"
while [[ $# -gt 0 ]]; do
    case $1 in
        --fast)
            MODE="fast"
            shift
            ;;
        --full)
            MODE="full"
            shift
            ;;
        -h|--help)
            echo "用法: $0 [--fast] [--full]"
            echo "  --fast : 仅快速检查（跳过依赖安装验证）"
            echo "  --full : 完整检查（默认）"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# 辅助函数
# -----------------------------------------------------------------------------
log_info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[PASS]${NC}  $1"; PASSED=$((PASSED+1)); }
log_fail()    { echo -e "${RED}[FAIL]${NC}  $1"; FAILED=$((FAILED+1)); }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; WARNINGS=$((WARNINGS+1)); }
log_header()  { echo -e "\n${BOLD}${CYAN}━━━ $1 ━━━${NC}"; }

# 检查文件是否存在
check_file() {
    local file="$1"
    local desc="${2:-}"
    if [[ -f "$file" ]]; then
        log_success "文件存在: ${file}${desc:+ - $desc}"
    else
        log_fail "文件缺失: ${file}${desc:+ - $desc}"
    fi
}

# 检查目录是否存在
check_dir() {
    local dir="$1"
    local desc="${2:-}"
    if [[ -d "$dir" ]]; then
        log_success "目录存在: ${dir}${desc:+ - $desc}"
    else
        log_fail "目录缺失: ${dir}${desc:+ - $desc}"
    fi
}

# 检查命令是否存在
check_cmd() {
    local cmd="$1"
    local desc="${2:-}"
    if command -v "$cmd" &> /dev/null; then
        log_success "命令可用: ${cmd}${desc:+ - $desc}"
    else
        log_fail "命令缺失: ${cmd}${desc:+ - $desc}"
    fi
}

# 检查 Python 语法
check_py_syntax() {
    local file="$1"
    if python3 -m py_compile "$file" 2>/dev/null; then
        log_success "Python 语法正确: $file"
        return 0
    else
        log_fail "Python 语法错误: $file"
        return 1
    fi
}

# 检查 Shell 语法
check_sh_syntax() {
    local file="$1"
    if bash -n "$file" 2>/dev/null; then
        log_success "Shell 语法正确: $file"
        return 0
    else
        log_fail "Shell 语法错误: $file"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# 主检查流程
# -----------------------------------------------------------------------------
main() {
    local start_time
    start_time=$(date +%s)

    echo -e "${BOLD}${CYAN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║         Audiobook Studio 自检脚本 v1.0.0                      ║"
    local mode_display
    case "$MODE" in
        fast) mode_display="Fast" ;;
        full) mode_display="Full" ;;
        *) mode_display="$MODE" ;;
    esac
    echo "║         检查模式: ${mode_display}                                       ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # =========================================================================
    # 1. 关键文件检查
    # =========================================================================
    log_header "1. 关键文件检查"

    # 文档类
    check_file "README.md" "项目说明"
    check_file "PROJECT.md" "项目描述"
    check_file "CONTRIBUTING.md" "贡献指南"
    check_file "CODE_OF_CONDUCT.md" "行为准则"
    check_file "SECURITY.md" "安全政策"
    check_file "LICENSE" "许可证"
    check_file ".env.example" "环境变量模板"

    # 配置文件
    check_file "requirements.txt" "Python 依赖"
    check_file ".pre-commit-config.yaml" "Git 预提交配置"
    check_file ".gitignore" "Git 忽略规则"
    check_file "mkdocs.yml" "MkDocs 配置"
    check_file "Dockerfile" "Docker 构建文件"
    check_file "docker-compose.yml" "Docker Compose 配置"

    # CI/CD
    check_file ".github/workflows/ci.yml" "GitHub Actions CI 配置"

    # =========================================================================
    # 2. 目录结构检查
    # =========================================================================
    log_header "2. 目录结构检查"

    check_dir "src" "源代码目录"
    check_dir "tests" "测试目录"
    check_dir "docs" "文档目录"
    check_dir "scripts" "脚本目录"
    check_dir "src/audiobook_studio" "主应用包"

    # =========================================================================
    # 3. 必需命令检查
    # =========================================================================
    log_header "3. 必需命令检查"

    check_cmd "python3" "Python 3 解释器"
    check_cmd "git" "Git 版本控制"
    check_cmd "docker" "Docker 容器"
    check_cmd "pip" "Python 包管理器"

    # =========================================================================
    # 4. Python 源码语法检查
    # =========================================================================
    log_header "4. Python 源码语法检查"

    if [[ -d "src" ]]; then
        while IFS= read -r py_file; do
            check_py_syntax "$py_file"
        done < <(find src -name "*.py" -type f)
    fi

    # =========================================================================
    # 5. Shell 脚本语法检查
    # =========================================================================
    log_header "5. Shell 脚本语法检查"

    for sh_file in scripts/*.sh; do
        [[ -f "$sh_file" ]] && check_sh_syntax "$sh_file"
    done

    # 检查自身
    check_sh_syntax "$0"

    # =========================================================================
    # 6. pre-commit 钩子检查
    # =========================================================================
    log_header "6. pre-commit 钩子检查"

    if [[ -f ".pre-commit-config.yaml" ]]; then
        if command -v pre-commit &> /dev/null; then
            log_success "pre-commit 已安装"
            if pre-commit run --all-files; then
                log_success "pre-commit 检查全部通过"
            else
                log_warn "pre-commit 检查有失败项（详见上方输出）"
            fi
        else
            log_warn "pre-commit 未安装，跳过钩子检查"
            log_info "安装命令: pip install pre-commit && pre-commit install"
        fi
    else
        log_fail ".pre-commit-config.yaml 不存在"
    fi

    # =========================================================================
    # 7. 依赖检查（仅 full 模式）
    # =========================================================================
    if [[ "$MODE" == "full" ]]; then
        log_header "7. Python 依赖检查"

        if [[ -f "requirements.txt" ]]; then
            log_info "检查 requirements.txt 中的依赖..."

            # 核心依赖检查
            local core_deps=("fastapi" "uvicorn" "pydantic" "python-dotenv" "requests")
            for dep in "${core_deps[@]}"; do
                if grep -q "^${dep}==" requirements.txt; then
                    log_success "依赖已声明: $dep"
                else
                    log_warn "依赖未在 requirements.txt 中声明: $dep"
                fi
            done

            # 检查是否已安装
            if command -v pip &> /dev/null; then
                log_info "验证已安装的包..."
                for dep in "${core_deps[@]}"; do
                    if pip show "$dep" &> /dev/null; then
                        local version
                        version=$(pip show "$dep" 2>/dev/null | grep "^Version:" | awk '{print $2}')
                        log_success "已安装: ${dep}==${version}"
                    else
                        log_warn "未安装: $dep（需要运行: pip install -r requirements.txt）"
                    fi
                done
            fi
        else
            log_fail "requirements.txt 不存在"
        fi
    fi

    # =========================================================================
    # 8. Docker 检查
    # =========================================================================
    log_header "8. Docker 配置检查"

    if [[ -f "Dockerfile" ]]; then
        log_success "Dockerfile 存在"

        # 检查 Dockerfile 基本指令
        if grep -q "^FROM" Dockerfile; then
            log_success "Dockerfile 包含 FROM 指令"
        else
            log_fail "Dockerfile 缺少 FROM 指令"
        fi

        if grep -q "WORKDIR" Dockerfile; then
            log_success "Dockerfile 包含 WORKDIR 指令"
        else
            log_fail "Dockerfile 缺少 WORKDIR 指令"
        fi

        if grep -q "COPY" Dockerfile; then
            log_success "Dockerfile 包含 COPY 指令"
        else
            log_fail "Dockerfile 缺少 COPY 指令"
        fi

        if grep -q "RUN" Dockerfile; then
            log_success "Dockerfile 包含 RUN 指令"
        else
            log_fail "Dockerfile 缺少 RUN 指令"
        fi

        if grep -q "EXPOSE" Dockerfile; then
            log_success "Dockerfile 包含 EXPOSE 指令"
        else
            log_fail "Dockerfile 缺少 EXPOSE 指令"
        fi

        if grep -q "ENTRYPOINT\|CMD" Dockerfile; then
            log_success "Dockerfile 包含 ENTRYPOINT 或 CMD"
        else
            log_fail "Dockerfile 缺少 ENTRYPOINT 或 CMD"
        fi
    else
        log_fail "Dockerfile 不存在"
    fi

    if [[ -f "docker-compose.yml" ]]; then
        log_success "docker-compose.yml 存在"

        # 检查基本服务定义
        if grep -q "services:" docker-compose.yml; then
            log_success "docker-compose.yml 包含 services 定义"
        else
            log_fail "docker-compose.yml 缺少 services 定义"
        fi
    else
        log_warn "docker-compose.yml 不存在（建议添加以便本地开发）"
    fi

    # =========================================================================
    # 9. Git 配置检查
    # =========================================================================
    log_header "9. Git 配置检查"

    if [[ -f ".gitignore" ]]; then
        log_success ".gitignore 存在"

        # 检查关键忽略规则
        local gitignore_patterns=("__pycache__" "*.pyc" ".env" "node_modules" "*.egg-info")
        for pattern in "${gitignore_patterns[@]}"; do
            if grep -q "$pattern" .gitignore; then
                log_success ".gitignore 包含规则: $pattern"
            else
                log_warn ".gitignore 缺少规则: $pattern"
            fi
        done

        # 检查 Dockerfile 是否被忽略（不应该被忽略）
        if grep -qE "^Dockerfile$|^Dockerfile$|^/Dockerfile$" .gitignore; then
            log_fail "Dockerfile 被 .gitignore 忽略了（不应该忽略）"
        else
            log_success "Dockerfile 未被忽略"
        fi
    else
        log_fail ".gitignore 不存在"
    fi

    # =========================================================================
    # 10. 文档检查
    # =========================================================================
    log_header "10. 文档检查"

    if [[ -f "mkdocs.yml" ]]; then
        log_success "mkdocs.yml 存在"

        # 检查 docs 目录中的必需文件
        local docs=("index.md" "architecture.md" "quick_start.md")
        for doc in "${docs[@]}"; do
            if [[ -f "docs/$doc" ]]; then
                log_success "文档存在: docs/$doc"
            else
                log_warn "文档缺失: docs/$doc"
            fi
        done
    else
        log_fail "mkdocs.yml 不存在"
    fi

    # =========================================================================
    # 11. 测试检查
    # =========================================================================
    log_header "11. 测试检查"

    if [[ -d "tests" ]]; then
        log_success "tests 目录存在"

        local test_count
        test_count=$(find tests -name "test_*.py" -o -name "*_test.py" 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$test_count" -gt 0 ]]; then
            log_success "找到 $test_count 个测试文件"

            # 尝试运行测试（如果 pytest 可用）
            if command -v pytest &> /dev/null; then
                log_info "运行 pytest..."
                if pytest --collect-only -q; then
                    log_success "pytest 能够收集测试用例"
                else
                    log_warn "pytest 收集测试用例失败"
                fi
            else
                log_warn "pytest 未安装，跳过测试运行"
                log_info "安装命令: pip install pytest pytest-cov"
            fi
        else
            log_warn "tests 目录为空，没有找到测试文件"
        fi
    else
        log_warn "tests 目录不存在（建议添加单元测试）"
    fi

    # =========================================================================
    # 12. CI/CD 检查
    # =========================================================================
    log_header "12. CI/CD 检查"

    if [[ -f ".github/workflows/ci.yml" ]]; then
        log_success "GitHub Actions CI 配置存在"

        # 检查必需的 CI 步骤
        local ci_steps=("lint" "test" "build")
        for step in "${ci_steps[@]}"; do
            if grep -q "$step" .github/workflows/ci.yml; then
                log_success "CI 包含步骤: $step"
            else
                log_warn "CI 缺少步骤: $step"
            fi
        done
    else
        log_fail "GitHub Actions CI 配置不存在"
    fi

    # =========================================================================
    # 13. 环境变量模板检查
    # =========================================================================
    log_header "13. 环境变量模板检查"

    if [[ -f ".env.example" ]]; then
        log_success ".env.example 存在"

        # 检查常见环境变量
        local env_vars=("OPENAI_API_KEY" "LLM_PROVIDER" "AUDIO_OUTPUT_DIR")
        for var in "${env_vars[@]}"; do
            if grep -q "$var" .env.example; then
                log_success ".env.example 包含: $var"
            else
                log_warn ".env.example 缺少: $var"
            fi
        done
    else
        log_fail ".env.example 不存在"
    fi

    # =========================================================================
    # 14. 文档同步检查（新增）
    # =========================================================================
    log_header "14. 文档同步检查"
    # 检查是否有 .md 文件在 docs/ 目录之外被修改（除了一些允许的根文件）
    # 获取所有修改过的 .md 文件（相对于 HEAD）
    # 如果在 CI 环境中没有 git 历史，则跳过此检查
    if git rev-parse --git-dir > /dev/null 2>&1; then
        # 获取已暂存和未暂存的修改
        changed_md_files=$(git diff --name-only HEAD 2>/dev/null | grep '\.md$' || true)
        # 允许的根目录 .md 文件
        allowed_root_md="README.md PROJECT.md CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md LICENSE"
        # 检查每个变动的 .md 文件是否在 docs/ 目录或是允许的根文件
        unexpected_md=()
        while IFS= read -r file; do
            if [[ -z "$file" ]]; then continue; fi
            if [[ "$file" == docs/* ]]; then
                continue
            fi
            # 检查是否是允许的根文件
            allowed=false
            for allowed_file in $allowed_root_md; do
                if [[ "$file" == "$allowed_file" ]]; then
                    allowed=true
                    break
                fi
            done
            if ! $allowed; then
                unexpected_md+=("$file")
            fi
        done <<< "$changed_md_files"

        if [[ ${#unexpected_md[@]} -gt 0 ]]; then
            log_warn "检测到以下 .md 文件在 docs/ 目录之外被修改（可能需要同步到 docs/）："
            for f in "${unexpected_md[@]}"; do
                echo -e "  ${YELLOW}$f${NC}"
            done
            log_info "建议：如果这些是代码相关的文档更新，请将内容移至 docs/ 目录并使用 docs: 前缀提交"
            WARNINGS=$((WARNINGS + ${#unexpected_md[@]}))
        else
            log_success "所有 .md 文件修改均在 docs/ 目录或允许的根文件范围内"
        fi
    else
        log_warn "无法执行 git 检查（非 git 仓库或 HEAD 不可用），跳过文档同步检查"
    fi

    # =========================================================================
    # 15. 安全检查
    # =========================================================================
    log_header "15. 安全检查"

    # 检查是否有敏感文件泄露风险
    if [[ -f ".env" ]] && ! grep -q "^\.env$" .gitignore 2>/dev/null; then
        log_fail ".env 文件存在但未被 .gitignore 忽略（敏感信息泄露风险）"
    else
        log_success "未检测到 .env 泄露风险"
    fi

    # 检查 API key 占位符
    if grep -r "YOUR_API_KEY\|TODO.*API.*KEY\|placeholder" . --include="*.py" --include="*.sh" 2>/dev/null | grep -v ".git" | head -5 | grep -q .; then
        log_warn "检测到可能的 API key 占位符（请确保生产环境使用真实密钥）"
    else
        log_success "未检测到明显的 API key 占位符"
    fi

    # =========================================================================
    # 16. 代码质量检查（如果可用）
    # =========================================================================
    if [[ "$MODE" == "full" ]]; then
        log_header "16. 代码质量检查"

        # Black 格式化检查
        if command -v black &> /dev/null; then
            log_info "检查代码格式（black）..."
            if black --check .; then
                log_success "代码格式符合 black 规范"
            else
                log_warn "代码格式不符合 black 规范（运行: black . 修复）"
            fi
        fi

        # isort 导入排序检查
        if command -v isort &> /dev/null; then
            log_info "检查导入排序（isort）..."
            if isort --check .; then
                log_success "导入排序符合 isort 规范"
            else
                log_warn "导入排序不符合 isort 规范（运行: isort . 修复）"
            fi
        fi

        # flake8 代码检查
        if command -v flake8 &> /dev/null; then
            log_info "检查代码质量（flake8）..."
            # 排除 .venv、site-packages、node_modules 等自动生成的目录
            if flake8 . --exclude=.venv,__pycache__,node_modules,site,venv,.git; then
                log_success "flake8 检查通过"
            else
                log_warn "flake8 检查有警告（见上方输出）"
            fi
        fi
    fi

    # =========================================================================
    # 汇总报告
    # =========================================================================
    log_header "检查完成 - 汇总报告"

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))

    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "  ${GREEN}✓ 通过: $PASSED${NC}"
    echo -e "  ${RED}✗ 失败: $FAILED${NC}"
    echo -e "  ${YELLOW}⚠ 警告: $WARNINGS${NC}"
    echo -e "  ${BLUE}⏱ 耗时: ${duration}s${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if [[ $FAILED -gt 0 ]]; then
        echo -e "\n${RED}${BOLD}❌ 检查未通过，请修复上述失败项后重新运行。${NC}"
        exit 1
    elif [[ $WARNINGS -gt 0 ]]; then
        echo -e "\n${YELLOW}${BOLD}⚠ 检查完成但有警告，建议查看并修复。${NC}"
        exit 0
    else
        echo -e "\n${GREEN}${BOLD}✅ 所有检查通过！${NC}"
        exit 0
    fi
}

# 运行主函数
main "$@"