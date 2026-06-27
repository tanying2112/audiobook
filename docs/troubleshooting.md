# 故障排查指南

本文档提供 Audiobook Studio 常见问题的诊断和解决方案。

## 快速诊断

运行内置诊断工具：

```bash
# 完整系统健康检查
python -m src.audiobook_studio.health --full

# 仅检查 TTS 引擎
python -m src.audiobook_studio.tts.health_check

# 仅检查 LLM 连接
python -m src.audiobook_studio.llm.connection_test
```

## 问题分类索引

| 类别 | 常见问题 | 解决方案 |
|------|----------|----------|
| [安装问题](#安装问题) | 依赖安装失败、版本冲突 | 见下方 |
| [LLM 问题](#llm-相关问题) | API 连接失败、速率限制 | 见下方 |
| [TTS 问题](#tts-相关问题) | 合成失败、声音异常 | 见下方 |
| [流水线问题](#流水线问题) | 阶段失败、数据丢失 | 见下方 |
| [数据库问题](#数据库问题) | 连接失败、迁移错误 | 见下方 |
| [性能问题](#性能问题) | 内存不足、速度慢 | 见下方 |

---

## 安装问题

### 问题 1: pip 安装依赖失败

**症状**
```
ERROR: Could not find a version that satisfies the requirement xxx
ERROR: No matching distribution found for xxx
```

**解决方案**
```bash
# 1. 更新 pip 到最新版本
pip install --upgrade pip setuptools wheel

# 2. 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 清理缓存后重试
pip cache purge
pip install -r requirements.txt

# 4. 检查 Python 版本（需要 3.11+）
python --version
```

### 问题 2: Kokoro TTS 安装失败

**症状**
```
ERROR: Failed to build kokoro-onnx
error: can't find Rust compiler
```

**解决方案**
```bash
# 方法 1: 安装 Rust（macOS/Linux）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 方法 2: 使用预编译轮子
pip install kokoro-onnx --only-binary :all:

# 方法 3: 切换到 Edge TTS
export KOKORO_ENABLED=false
export TTS_ENGINE=edge-tts
```

### 问题 3: SQLite 数据库锁定

**症状**
```
sqlite3.OperationalError: database is locked
```

**解决方案**
```bash
# 1. 找到并终止占用进程
lsof audiobook.db

# 2. 删除锁文件
rm -f audiobook.db-journal
rm -f audiobook.db-shm
rm -f audiobook.db-wal

# 3. 如需重置数据库
rm audiobook.db
python -m src.audiobook_studio.database.init
```

---

## LLM 相关问题

### 问题 1: API 密钥无效

**症状**
```
Error: Invalid API key. Please check your ANTHROPIC_API_KEY
```

**解决方案**
```bash
# 1. 验证密钥格式
echo $ANTHROPIC_API_KEY

# 2. 重新设置密钥
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. 测试连接
curl -X POST https://api.anthropic.com/v1/messages \
  -H "Authorization: Bearer $ANTHROPIC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-5-20250929","max_tokens":10}'
```

### 问题 2: 速率限制

**症状**
```
RateLimitError: 429 Too Many Requests
```

**解决方案**
```bash
# 1. 增加重试延迟
export LLM_RETRY_DELAY=30

# 2. 降低并发请求数
export LLM_MAX_CONCURRENT=2

# 3. 切换到备用提供商
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY="sk-or-..."
```

### 问题 3: Schema 合规率低

**症状**
```
Warning: Schema compliance rate below threshold (85% < 99%)
```

**解决方案**
```bash
# 1. 启用 prompt 压缩
export ENABLE_PROMPT_COMPRESSION=true

# 2. 使用温度值 0（更确定）
export LLM_TEMPERATURE=0

# 3. 增加 max_tokens
export LLM_MAX_TOKENS=4096

# 4. 更新 prompt 模板
python scripts/update_prompts.py
```

---

## TTS 相关问题

### 问题 1: 合成完全失败

**症状**
```
TTSSynthesisError: All engines failed
```

**解决方案**
```bash
# 1. 检查引擎状态
python -c "from src.audiobook_studio.tts import TTSEngine; print(TTSEngine.list_engines())"

# 2. 测试单个引擎
python -c "
from src.audiobook_studio.tts import TTSEngine
engine = TTSEngine.get_engine('kokoro')
result = engine.synthesize('测试', '/tmp/test.wav')
print(result)
"

# 3. 查看引擎日志
tail -f logs/tts_engine.log
```

### 问题 2: 输出音频无声

**症状**
```
✓ Synthesis completed
∅ Output: silent.wav (44KB)
! Warning: Output appears to be silent
```

**解决方案**
```bash
# 1. 检查输入文本
# 确保文本非空且包含可读字符

# 2. 检查音量设置
python -c "
from pydub import AudioSegment
audio = AudioSegment.from_file('silent.wav')
print(f'RMS: {audio.rms}, dBFS: {audio.dBFS}')
"

# 3. 更换 TTS 引擎
export TTS_ENGINE=edge-tts
```

### 问题 3: 声音不自然/机械感

**症状**
- 语调平淡
- 停顿不自然
- 情感表达不足

**解决方案**
```yaml
# 调整 TTS 参数 (config/tts_config.yaml)
prosody:
  rate: +10%        # 稍快更自然
  pitch: +50Hz      # 微调音高
  volume: +3dB      # 增加音量

emotion_weight:
  enabled: true     # 启用情感加权
  intensity: 1.2    # 增强情感表达
```

---

## 流水线问题

### 问题 1: 阶段执行失败

**症状**
```
StageFailedError: Stage 'annotate_paragraph' failed after 3 retries
```

**解决方案**
```bash
# 1. 查看详细错误
tail -n 100 logs/pipeline.log | grep -A 20 "annotate_paragraph"

# 2. 清理阶段缓存
python -m src.audiobook_studio.pipeline.cleanup --stage annotate_paragraph

# 3. 单独重试该阶段
python -m src.audiobook_studio.pipeline.run_stage \
  --stage annotate_paragraph \
  --project-id <id> \
  --retry
```

### 问题 2: 数据不一致

**症状**
- 段落数量不匹配
- 章节信息丢失
- 角色绑定错误

**解决方案**
```bash
# 1. 运行数据完整性检查
python -m src.audiobook_studio.database.integrity_check

# 2. 修复外键
python -m src.audiobook_studio.database.fix_foreign_keys

# 3. 重建索引
python -m src.audiobook_studio.database.reindex
```

### 问题 3: 内存不足 (OOM)

**症状**
```
MemoryError: Unable to allocate 2.5 GiB
Killed
```

**解决方案**
```bash
# 1. 启用批处理模式
export BATCH_MODE=true
export BATCH_SIZE=10

# 2. 降低并发数
export MAX_CONCURRENT_SYNTHESIS=1

# 3. 使用流式处理
export STREAM_PROCESSING=true

# 4. 增加 swap（Linux）
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## 数据库问题

### 问题 1: Alembic 迁移失败

**症状**
```
alembic.util.exc.AlembicError: Table 'paragraphs' already exists
```

**解决方案**
```bash
# 1. 检查当前版本
alembic current

# 2. 标记已应用（不执行）
alembic stamp heads

# 3. 强制迁移
alembic upgrade head --sql

# 4. 或重置迁移历史（危险！）
rm alembic_version.db
alembic upgrade head
```

### 问题 2: 查询缓慢

**症状**
- 页面加载超时
- API 响应慢

**解决方案**
```bash
# 1. 分析慢查询
sqlite3 audiobook.db "PRAGMA query_pager=stdout; EXPLAIN QUERY PLAN SELECT * FROM paragraphs;"

# 2. 重建索引
sqlite3 audiobook.db "VACUUM; REINDEX;"

# 3. 检查索引状态
sqlite3 audiobook.db ".indices"
```

---

## 性能问题

### 问题 1: 合成速度慢

**症状**
- 单段合成 > 10 秒
- 整体进度缓慢

**解决方案**
```bash
# 1. 启用 GPU 加速（如可用）
export KOKORO_DEVICE=cuda

# 2. 使用更快的引擎
export TTS_ENGINE=edge-tts

# 3. 批量合成
python -m src.audiobook_studio.pipeline.synthesize \
  --batch-size 20 \
  --concurrency 4
```

### 问题 2: LLM 响应慢

**症状**
- Token 生成速度 < 10 tokens/s

**解决方案**
```bash
# 1. 切换到更快的模型
export LLM_MODEL=poolside/laguna-m.1:free

# 2. 降低 max_tokens
export LLM_MAX_TOKENS=1024

# 3. 启用缓存
export LLM_RESPONSE_CACHE=true
```

---

## 获取帮助

### 日志位置

```bash
# 主日志
tail -f logs/audiobook.log

# 流水线日志
tail -f logs/pipeline.log

# TTS 日志
tail -f logs/tts.log

# LLM 日志
tail -f logs/llm.log
```

### 诊断包

```bash
# 生成诊断报告
python -m src.audiobook_studio.diagnostic > diagnostic_report.txt

# 包含内容：
# - 系统信息
# - 依赖版本
# - 配置状态
# - 最近错误
```

### 寻求支持

1. **查看已有 Issue**: https://github.com/audiobook-studio/audiobook/issues
2. **提交新 Issue**: 附上诊断报告
3. **Discord 社区**: https://discord.gg/audiobook-studio