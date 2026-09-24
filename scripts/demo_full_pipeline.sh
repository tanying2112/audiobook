#!/usr/bin/env bash
# scripts/demo_full_pipeline.sh — 一键完整流水线演示
#
# 功能：启动免费栈 → 下载模型 → 导入样书 → 跑全流水线 → 导出 M4B → 推送 Audiobookshelf
# 目标：新贡献者 10 分钟跑通全流程（含等待合成时间）
# 模式：默认 cloud_hybrid (免费云 LLM + 本地 Kokoro ONNX)
# 前置：已安装 Docker、Python 3.11+、已配置 .env (或 .env.encrypted + age/sops)
#
# 用法：
#   ./scripts/demo_full_pipeline.sh [--project-name <name>] [--book <book_key>] [--mock] [--skip-export]
#   示例：./scripts/demo_full_pipeline.sh --book hongloumeng --mock

set -euo pipefail

# 默认配置
PROJECT_NAME="${PROJECT_NAME:-demo_$(date +%Y%m%d_%H%M%S)}"
BOOK_KEY="${BOOK_KEY:-hongloumeng}"
MOCK_MODE="${MOCK_MODE:-false}"
SKIP_EXPORT="${SKIP_EXPORT:-false}"
SKIP_MODEL_DOWNLOAD="${SKIP_MODEL_DOWNLOAD:-false}"
AUDIOBOOKSHELF_URL="${AUDIOBOOKSHELF_URL:-}"
AUDIOBOOKSHELF_API_KEY="${AUDIOBOOKSHELF_API_KEY:-}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --project-name) PROJECT_NAME="$2"; shift 2 ;;
        --book) BOOK_KEY="$2"; shift 2 ;;
        --mock) MOCK_MODE="true"; shift ;;
        --skip-export) SKIP_EXPORT="true"; shift ;;
        --skip-model-download) SKIP_MODEL_DOWNLOAD="true"; shift ;;
        --audiobookshelf-url) AUDIOBOOKSHELF_URL="$2"; shift 2 ;;
        --audiobookshelf-api-key) AUDIOBOOKSHELF_API_KEY="$2"; shift 2 ;;
        --help|-h)
            cat <<EOF
用法: $0 [选项]

一键完整流水线演示：启动免费栈 → 下载模型 → 导入样书 → 跑全流水线 → 导出 M4B → 推送 Audiobookshelf

选项:
  --project-name <name>       项目名称 (默认: demo_YYYYMMDD_HHMMSS)
  --book <book_key>           样书键名: hongloumeng|sanguoyanyi|xiyouji|shuihuzhuan (默认: hongloumeng)
  --mock                      使用 MOCK_LLM=true (无需 LLM API Key，秒级跑完)
  --skip-export               跳过导出和 Audiobookshelf 推送
  --skip-model-download       跳过模型下载 (已有模型时)
  --audiobookshelf-url <url>  Audiobookshelf API 地址
  --audiobookshelf-api-key <key> Audiobookshelf API Key
  --help, -h                  显示帮助

示例:
  # 完整演示 (需 API Key，约 10-15 分钟)
  ./scripts/demo_full_pipeline.sh --book hongloumeng

  # 快速演示 (Mock 模式，约 1-2 分钟)
  ./scripts/demo_full_pipeline.sh --book hongloumeng --mock

  # 仅跑流水线，不导出
  ./scripts/demo_full_pipeline.sh --book sanguoyanyi --skip-export
EOF
            exit 0
            ;;
        *) log_error "未知选项: $1"; exit 1 ;;
    esac
done

# 检查依赖
check_deps() {
    log_info "检查依赖..."
    for cmd in docker docker-compose python3 pip; do
        if ! command -v "$cmd" &>/dev/null; then
            log_error "缺少依赖: $cmd"
            exit 1
        fi
    done
    log_success "依赖检查通过"
}

# 环境准备
setup_env() {
    log_info "准备环境..."
    
    # 解密 .env (如果有加密文件)
    if [[ -f .env.encrypted && ! -f .env ]]; then
        if command -v sops &>/dev/null && [[ -f .agekey ]]; then
            log_info "解密 .env.encrypted..."
            SOPS_AGE_KEY_FILE=.agekey sops --input-type dotenv --output-type dotenv --decrypt .env.encrypted > .env
            chmod 600 .env
        else
            log_warn "发现 .env.encrypted 但缺少 sops/age 或 .agekey，跳过解密"
        fi
    fi
    
    # 加载环境变量
    if [[ -f .env ]]; then
        set -a
        source .env
        set +a
        log_success "已加载 .env"
    else
        log_warn "未找到 .env，使用默认值"
    fi
    
    # Mock 模式设置
    if [[ "$MOCK_MODE" == "true" ]]; then
        export MOCK_LLM="true"
        export MOCK_TTS="true"
        log_info "启用 MOCK 模式 (MOCK_LLM=true, MOCK_TTS=true)"
    fi
}

# 下载模型
download_models() {
    if [[ "$SKIP_MODEL_DOWNLOAD" == "true" ]]; then
        log_info "跳过模型下载"
        return
    fi
    
    log_info "下载 Kokoro ONNX 模型..."
    if [[ -f models/kokoro-v1.0.onnx && -f models/voices-v1.0.bin ]]; then
        log_success "模型已存在，跳过下载"
    else
        python scripts/download_kokoro_model.py
        log_success "模型下载完成"
    fi
}

# 启动服务
start_services() {
    log_info "启动 Docker 服务..."
    docker compose up -d --build
    
    # 等待服务就绪
    log_info "等待服务就绪..."
    local max_wait=120
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
            log_success "API 服务就绪"
            break
        fi
        sleep 5
        waited=$((waited + 5))
        echo -n "."
    done
    echo
    
    if [[ $waited -ge $max_wait ]]; then
        log_error "服务启动超时"
        docker compose logs --tail=50
        exit 1
    fi
}

# 创建项目
create_project() {
    log_info "创建演示项目: $PROJECT_NAME (书籍: $BOOK_KEY)..."
    
    local response
    response=$(curl -sf -X POST "http://localhost:8000/api/projects/" \
        -H "Content-Type: application/json" \
        -d "{\"title\": \"$PROJECT_NAME\", \"book_key\": \"$BOOK_KEY\"}" 2>/dev/null) || {
        log_error "创建项目失败"
        exit 1
    }
    
    PROJECT_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
    log_success "项目创建成功，ID: $PROJECT_ID"
}

# 上传样书文件
upload_book() {
    log_info "上传样书: $BOOK_KEY..."
    
    # 查找样书文件
    local book_file=""
    for ext in txt epub pdf; do
        if [[ -f "data/books/${BOOK_KEY}.${ext}" ]]; then
            book_file="data/books/${BOOK_KEY}.${ext}"
            break
        fi
    done
    
    if [[ -z "$book_file" ]]; then
        log_warn "未找到样书文件，使用内置 mock 数据"
        return
    fi
    
    log_info "上传文件: $book_file"
    local response
    response=$(curl -sf -X POST "http://localhost:8000/api/projects/${PROJECT_ID}/upload" \
        -F "file=@${book_file}" 2>/dev/null) || {
        log_error "上传失败"
        exit 1
    }
    
    UPLOAD_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['upload_id'])")
    log_success "上传成功，Upload ID: $UPLOAD_ID"
    
    # 等待上传处理完成
    log_info "等待文件处理..."
    local max_wait=60
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        local status_resp
        status_resp=$(curl -sf "http://localhost:8000/api/projects/${PROJECT_ID}/upload/${UPLOAD_ID}/status" 2>/dev/null)
        local status=$(echo "$status_resp" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))")
        if [[ "$status" == "completed" ]]; then
            log_success "文件处理完成"
            break
        elif [[ "$status" == "failed" ]]; then
            log_error "文件处理失败"
            exit 1
        fi
        sleep 3
        waited=$((waited + 3))
        echo -n "."
    done
    echo
}

# 运行全流水线
run_pipeline() {
    log_info "启动全流水线..."
    
    local response
    response=$(curl -sf -X POST "http://localhost:8000/api/projects/${PROJECT_ID}/auto-run/start" \
        -H "Content-Type: application/json" \
        -d "{\"books\": [\"${BOOK_KEY}\"], \"stages\": [\"extract\", \"analyze\", \"annotate\", \"edit\", \"audio_postprocess\", \"synthesize\", \"quality\"], \"quick\": false, \"no_resume\": true}" 2>/dev/null) || {
        log_error "启动流水线失败"
        exit 1
    }
    
    RUN_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['run_id'])")
    log_success "流水线启动，Run ID: $RUN_ID"
    
    # 轮询进度
    log_info "等待流水线完成 (预计 5-15 分钟)..."
    local max_wait=1800  # 30 分钟
    local waited=0
    local last_progress=0
    
    while [[ $waited -lt $max_wait ]]; do
        local status_resp
        status_resp=$(curl -sf "http://localhost:8000/api/projects/${PROJECT_ID}/auto-run/status" 2>/dev/null)
        local status=$(echo "$status_resp" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))")
        local progress=$(echo "$status_resp" | python3 -c "import sys, json; print(json.load(sys.stdin).get('progress', 0))")
        local stage=$(echo "$status_resp" | python3 -c "import sys, json; print(json.load(sys.stdin).get('current_stage', ''))")
        
        if [[ "$progress" != "$last_progress" ]]; then
            log_info "进度: ${progress}% | 阶段: ${stage}"
            last_progress=$progress
        fi
        
        case "$status" in
            "completed")
                log_success "流水线完成！"
                return 0
                ;;
            "failed")
                log_error "流水线失败"
                echo "$status_resp" | python3 -m json.tool
                exit 1
                ;;
            "running"|"paused")
                # 继续等待
                ;;
            *)
                log_warn "未知状态: $status"
                ;;
        esac
        
        sleep 10
        waited=$((waited + 10))
    done
    
    log_error "流水线超时 (30 分钟)"
    exit 1
}

# 导出 M4B
export_m4b() {
    if [[ "$SKIP_EXPORT" == "true" ]]; then
        log_info "跳过导出"
        return
    fi
    
    log_info "导出 M4B..."
    
    local response
    response=$(curl -sf -X POST "http://localhost:8000/api/projects/${PROJECT_ID}/export/" \
        -H "Content-Type: application/json" \
        -d '{"formats": ["m4b"], "include_cover": true, "normalize": true}' 2>/dev/null) || {
        log_error "导出失败"
        exit 1
    }
    
    local export_id=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['export_id'])")
    log_info "导出任务启动，ID: $export_id"
    
    # 等待导出完成
    local max_wait=300
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        local status_resp
        status_resp=$(curl -sf "http://localhost:8000/api/projects/${PROJECT_ID}/export/status" 2>/dev/null)
        local status=$(echo "$status_resp" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))")
        
        if [[ "$status" == "complete" ]]; then
            local output_paths=$(echo "$status_resp" | python3 -c "import sys, json; print(json.load(sys.stdin).get('output_paths', {}))")
            M4B_PATH=$(echo "$output_paths" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('m4b', ''))")
            log_success "M4B 导出完成: $M4B_PATH"
            return 0
        elif [[ "$status" == "failed" ]]; then
            log_error "导出失败"
            exit 1
        fi
        sleep 5
        waited=$((waited + 5))
    done
    
    log_error "导出超时"
    exit 1
}

# 推送到 Audiobookshelf
push_audiobookshelf() {
    if [[ "$SKIP_EXPORT" == "true" ]]; then
        return
    fi
    
    if [[ -z "$AUDIOBOOKSHELF_URL" || -z "$AUDIOBOOKSHELF_API_KEY" ]]; then
        log_warn "未配置 Audiobookshelf URL/Key，跳过推送"
        log_info "可通过环境变量配置: AUDIOBOOKSHELF_URL, AUDIOBOOKSHELF_API_KEY"
        return
    fi
    
    if [[ -z "$M4B_PATH" || ! -f "$M4B_PATH" ]]; then
        log_error "M4B 文件不存在"
        return
    fi
    
    log_info "推送到 Audiobookshelf..."
    
    # 这里需要根据 Audiobookshelf API 实现上传
    # 示例调用 (需根据实际 API 调整):
    # curl -X POST "$AUDIOBOOKSHELF_URL/api/items" \
    #   -H "Authorization: Bearer $AUDIOBOOKSHELF_API_KEY" \
    #   -F "file=@$M4B_PATH" \
    #   -F 'metadata={"title":"..."}'
    
    log_warn "Audiobookshelf 推送功能需根据实际 API 实现"
    log_info "M4B 文件位置: $M4B_PATH"
}

# 清理
cleanup() {
    log_info "清理临时资源..."
    # 可选：停止 docker compose
    # docker compose down
}

# 主流程
main() {
    echo "=========================================="
    echo "  Audiobook Studio - 完整流水线演示"
    echo "=========================================="
    echo "项目: $PROJECT_NAME"
    echo "样书: $BOOK_KEY"
    echo "Mock 模式: $MOCK_MODE"
    echo "跳过导出: $SKIP_EXPORT"
    echo "=========================================="
    
    trap cleanup EXIT
    
    check_deps
    setup_env
    download_models
    start_services
    create_project
    upload_book
    run_pipeline
    export_m4b
    push_audiobookshelf
    
    echo ""
    echo "=========================================="
    log_success "🎉 完整流水线演示完成！"
    echo "=========================================="
    echo "项目 ID: $PROJECT_ID"
    if [[ -n "${M4B_PATH:-}" ]]; then
        echo "M4B 文件: $M4B_PATH"
    fi
    echo "API 文档: http://localhost:8000/docs"
    echo "监控面板: http://localhost:8000/monitoring"
}

main "$@"