# Audiobook Studio — 生产级 GA 详细执行清单与验收标准

> 基于 2026-08-21 全面审计报告制定
> 目标：**零配置免费版开箱即用、流式合成实时预览、多语言零样本克隆、生产级 GA 发布**
> 版本：v1.0 | 制定日期：2026-08-21 | 维护者：@audiobook-team

---

## 总体里程碑时间表

| 版本 | 代号 | 目标日期 | 核心交付 | 验收标准 |
|------|------|----------|----------|----------|
| **v0.2** | Zero-Config Free | **+2 周** | 一键启动免费全栈，Mock 模式诚实降级 | `docker compose -f docker-compose.free.yml up` 全绿，Mock 跑通不报错 |
| **v0.3** | Streaming TTS | **+6 周** | 流式合成首包 <300ms，前端实时波形 | RTF<1.0，WebSocket 进度实时刷新，可边听边改 |
| **v0.4** | Multi-Lingual Clone | **+10 周** | XTTS-v2/OpenVoice V2 零样本跨语言 | 3秒参考音频→中英日韩任意语言合成，MOS>4.0 |
| **v0.5** | RAG Enhanced | **+14 周** | 角色/世界观检索注入，长文一致性 | 100章小说角色名/人称/风格零漂移 |
| **v1.0** | Production GA | **+24 周** | 多租户/RBAC/审计/Helm/插件市场 | 通过安全审计、压力测试、灾备演练，商业化就绪 |

---

## P0 阻塞性问题 (Must Fix First — v0.2 前完成)

### P0-1: Mock 模式质量门禁假阳性修复
**问题**: `FakeRemoteTTSPort` 生成静音 → DNSMOS=1.81 < 3.5 → 硬质检拦截 → 3次重试耗尽 → 标记人工复核
**根因**: Mock 音频无真实声学特征，Hard Metrics (DNSMOS/ASR/SpkSim) 不应在 Mock 模式运行

| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 1.1 修改 `QualityCheckPipeline.__init__` 增加 `mock_mode` 参数透传 | Backend | 2h | Mock 模式下自动禁用 Hard Metrics |
| 1.2 `QualityCheckPipeline.run()` 增加分支：`if mock_mode: skip_hard_checks()` | Backend | 2h | 仅跑 Rule-based + LLM Judge |
| 1.3 判断结果打标 `mock_mode=True`，前端 Dashboard 显示「模拟模式」徽标 | Backend/Frontend | 2h | 质量报告含 `mock_mode` 字段，UI 有视觉区分 |
| 1.4 更新 `SynthesizePipeline`：Mock 模式下生成含基频/谐波的正弦波而非静音 | Backend | 4h | 生成音频可被 ffprobe 识别时长/采样率，DNSMOS>2.0(可选) |
| 1.5 集成测试：`MOCK_LLM=true` 跑通 3 章完整流水线，零拦截 | QA | 2h | `pytest tests/integration/test_mock_pipeline.py -v` 全绿 |

**验收命令**:
```bash
cd /Users/guwj/Documents/audiobook
MOCK_LLM=true .venv/bin/python -m audiobook_studio.cli pipeline run 红楼梦
# 期望：全阶段通过，无「硬质检门禁」错误，总耗时 < 30s
```

---

### P0-2: 模型文件内置与零配置启动
**问题**: Kokoro ONNX 模型需手动下载，新用户首跑失败

| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 2.1 创建 `scripts/download_kokoro_model.py`：自动下载 `kokoro-v1.0.onnx` + `voices-v1.0.bin` 到 `models/kokoro-onnx/` | Backend | 4h | 支持断点续传、校验 SHA256、代理配置 |
| 2.2 Dockerfile 增加 `RUN python scripts/download_kokoro_model.py` (构建期缓存) | DevOps | 2h | 镜像体积 < 2GB，构建时间 < 10min |
| 2.3 创建 `docker-compose.free.yml`：Ollama + 本地 TTS + SQLite 纯免费栈 | DevOps | 4h | `docker compose -f docker-compose.free.yml up -d` 单机跑通 |
| 2.4 入口脚本 `entrypoint.sh`：启动前检查模型文件，缺失则自动下载 | DevOps | 2h | 冷启动无人值守完成 |
| 2.5 文档：`docs/getting-started/free-edition.md` 图文教程 | Docs | 4h | 新用户 10 分钟内跑出第一本有声书 |

**验收命令**:
```bash
# 全新环境测试
docker run --rm -v $(pwd)/models:/app/models ghcr.io/yourorg/audiobook:latest \
  python scripts/download_kokoro_model.py
# 期望：自动下载并校验通过

docker compose -f docker-compose.free.yml up -d
curl -s http://localhost:8000/health/ready
# 期望：{"status":"ready","checks":{"kokoro_model":"ok",...}}
```

---

### P0-3: 段落切分升级为独立 Stage
**问题**: 仅按 `\n\n` 切分，长段落/对话密集文本错误

| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 3.1 新建 `pipeline/segment.py`：`SegmentPipeline` 类，支持 rule/semantic/llm 三策略 | Backend | 8h | 策略可通过 YAML 配置切换 |
| 3.2 Rule 策略：`spacy` 句边界 + 启发式 (引号/标点/长度/换行) | Backend | 4h | 中文 F1>0.92，英文 F1>0.95 |
| 3.3 Semantic 策略：`sentence-transformers` 嵌入 + 聚类 (可选依赖) | Backend | 8h | 语义连贯性人工评分 >4.0/5.0 |
| 3.4 LLM 策略：复用 `LLMRouter` 调用结构化切分提示词 | Backend | 4h | Golden Dataset 准确率 >90% |
| 3.5 Stage Registry 注册 `segment`，`run_pipeline.py` 插在 `extract` 之后 | Backend | 2h | 流水线顺序：extract → segment → analyze → ... |
| 3.6 Golden Dataset：`tests/golden/segmentation/` 含 50 样本 (中/英/混合/对话/诗歌) | QA | 8h | `pytest tests/golden/test_segmentation.py` 全绿 |

**验收命令**:
```bash
# 单元测试
pytest tests/pipeline/test_segment.py -v
# 集成测试：对比切分前后段落数/长度分布
MOCK_LLM=true .venv/bin/python -c "
from src.audiobook_studio.pipeline.segment import SegmentPipeline
p = SegmentPipeline(mock_mode=True)
result = p.run(extract_file='data/mock_data/红楼梦/chapter_01.txt')
print(f'Segments: {len(result.segments)}, Avg len: {sum(len(s) for s in result.segments)/len(result.segments):.0f}')
"
```

---

## P1 重要问题 (v0.3 前完成)

### P1-1: 前端 WebSocket 实时进度
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 1.1 后端 `/api/ws` 扩展：发布 `PipelineProgressEvent` (project_id, chapter, stage, percent, message) | Backend | 4h | 现有 WebSocket 基础上扩展事件类型 |
| 1.2 前端 `composables/usePipelineProgress.ts`：订阅进度，驱动 Pinia store | Frontend | 4h | Vue DevTools 可见实时状态更新 |
| 1.3 `DashboardView.vue`：ECharts 实时刷新 (RTF/成本/延迟)，阶段进度条 | Frontend | 4h | 无需手动刷新，进度条平滑动画 |
| 1.4 `ProjectDetail.vue`：章节级时间轴，点击查看段落级进度 | Frontend | 8h | 类似 GitLab CI 阶段图可视化 |
| 1.5 压力测试：100 并发 WebSocket 连接，内存/CPU 稳定 | QA | 4h | `locust -f tests/load/websocket_load.py` 通过 |

**验收标准**: 运行 3 章流水线，Dashboard 无刷新实时显示每阶段进度、RTF 曲线动态更新。

---

### P1-2: Promotion Gate 线上影子流量验证
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 2.1 `PromotionGate.evaluate()` 新增 `shadow_traffic_pct` 参数 | Backend | 4h | 支持 0-100% 流量镜像 |
| 2.2 中间件 `ABTestMiddleware`：按比例分流请求到新旧 Prompt 版本 | Backend | 4h | 现有 A/B 测试框架复用 |
| 2.3 统计显著性检验：新版本在影子流量上质量/成本无回归才可晋升 | Backend | 8h | p-value < 0.05，效应量 > 0.1 |
| 2.4 审计日志：记录每次 Promotion 决策依据 (指标/流量/置信度) | Backend | 2h | 可追溯、可复现 |

**验收标准**: 创建一个故意降质的 Prompt 版本，影子流量 10% 跑 1 小时，Promotion Gate 自动拦截不晋升。

---

### P1-3: 成本主动告警
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 3.1 新建 `monitoring/cost_alert.py`：`CostAlertManager` 类 | Backend | 4h | 支持多渠道：Webhook/钉钉/飞书/邮件 |
| 3.2 告警规则 DSL：YAML 定义 (项目/模型/阶段/阈值/冷却期) | Backend | 4h | `config/cost_alerts.yaml` 热加载 |
| 3.3 定时任务：Celery Beat 每小时执行检查 | Backend | 2h | 无漏报、无风暴 |
| 3.4 前端 `MonitoringDashboard.vue` 告警历史/抑制/测试按钮 | Frontend | 4h | 一键发送测试告警验证通道 |

**验收标准**: 设置单章成本阈值 $0.01，跑流水线触发告警，钉钉/飞书收到通知 < 1min。

---

### P1-4: 多语言/多角色 Golden Dataset 与 CI 强制跑通
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 4.1 补充 `data/mock_data/Carnival/` (英文分级读物) 3 章 | QA | 4h | 真实文本，非机器翻译 |
| 4.2 补充 `data/mock_data/三国演义_en/` 英文翻译版 | QA | 4h | 角色声纹映射一致性验证 |
| 4.3 Golden Dataset：`tests/golden/multilingual/` 含 extract/analyze/annotate 期望输出 | QA | 8h | Schema 合规率 100% |
| 4.4 CI 增加 `multilingual` job：矩阵跑中/英/日/韩 (如可用) | DevOps | 4h | GitHub Actions 矩阵策略 |
| 4.5 基线锁定：`config/quality_baseline_multilingual.yaml` | Backend | 2h | PR 对比基线判定回归 |

**验收标准**: `pytest tests/golden/test_multilingual.py -v` 全绿，CI 矩阵通过。

---

### P1-5: 导出格式增强
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 5.1 MP3 单文件导出：`ExportFormat.MP3_SINGLE` | Backend | 4h | ffmpeg concat + ID3v2.4 标签完整 |
| 5.2 ZIP 打包：章节分文件 + 目录 JSON + 封面 | Backend | 4h | 解压即用，目录结构标准化 |
| 5.3 章节标记嵌入：M4B/MP3 chapter marks (QuickTime/ID3) | Backend | 8h | Apple Books/Spotify 可识别章节跳转 |
| 5.4 封面嵌入：自动生成/上传封面 → 嵌入音频元数据 | Backend | 4h | `ffprobe -show_entries format_tags=cover` 可见 |
| 5.5 前端 `ExportView.vue`：格式选择器、进度、下载链接 | Frontend | 4h | 导出任务可查看历史、重试 |

**验收标准**: 导出同一项目为 M4B/MP3/ZIP 三种格式，Apple Books/Spotify/网易云音乐均可正常导入播放、章节跳转。

---

## P2 优化/技术债 (v0.4-v1.0 持续改进)

### P2-1: LLM 推理加速 (vLLM/Ollama 直连)
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 1.1 `LLMProvidersConfig` 新增 `type: "vllm" / "ollama"` | Backend | 2h | 配置驱动，无代码修改 |
| 1.2 `LLMRouter.get_client()` 分支：直连 OpenAI 兼容端点，绕过 LiteLLM | Backend | 4h | 延迟降低 30%+，成本归零 |
| 1.3 基准测试：对比 LiteLLM vs 直连 vs vLLM (吞吐/延迟/显存) | QA | 4h | 文档 `docs/benchmarks/llm_routing.md` |
| 1.4 生产环境灰度：10% 流量走直连，监控错误率 | DevOps | 2h | 错误率 < 0.1% 才全量 |

---

### P2-2: Streaming TTS 集成 (v0.3 核心)
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 2.1 调研选型：CosyVoice-Stream / MeloTTS / Seed-TTS-Stream (开源版) | Research | 16h | 对比表：首包延迟/音质/显存/许可证 |
| 2.2 `TTSProsody` 扩展：支持 `stream=True`、增量文本输入 | Backend | 8h | 向后兼容，非流式不受影响 |
| 2.3 `RemoteTTSPort` 新增 `submit_stream()` / `get_stream()` 接口 | Backend | 8h | 统一抽象，引擎可插拔 |
| 2.4 前端 `AudioPlayer.vue`：Web Audio API 实时播放 PCM 流 | Frontend | 16h | 首包 <300ms，无卡顿，支持倍速/暂停 |
| 2.5 可视化：`WaveformView.vue` 实时渲染波形/频谱 | Frontend | 8h | Canvas/WebGL，60fps |

---

### P2-3: 零样本多语言克隆 (v0.4 核心)
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 3.1 集成 XTTS-v2 (Coqui)：`pip install TTS` + 模型下载脚本 | Backend | 8h | 支持 16 语言，3秒参考音频 |
| 3.2 集成 OpenVoice V2 (MyShell)：更轻量、音色相似度更高 | Backend | 8h | 支持 4 语言，RTF<0.5 |
| 3.3 `VoiceCloningManager` 统一接口：`clone(engine, ref_audio, text, language)` | Backend | 4h | 引擎可插拔，配置驱动 |
| 3.4 声纹锚定扩展：跨语言共享同一 `VoiceAnchor` | Backend | 4h | 中英日韩同角色声纹一致 |
| 3.5 质量基线：MOS 测试 50 样本 (中/英/日/韩/混合) | QA | 16h | MOS>4.0，相似度>0.85 |

---

### P2-4: RAG 增强长文一致性 (v0.5 核心)
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 4.1 接入 ChromaDB：`docker compose` 新增 `chromadb` 服务 | DevOps | 4h | 持久化卷、备份策略 |
| 4.2 `RAGManager`：文档分块/嵌入/检索/重排 (BGE-M3 + Reranker) | Backend | 16h | 检索 Recall@10 > 0.9 |
| 4.3 `AnalyzeStructurePipeline` 注入 RAG 上下文：角色设定/世界观/时间线 | Backend | 8h | 提示词模板新增 `{rag_context}` |
| 4.4 `AnnotateParagraphPipeline` 段落级检索：当前段落相关设定片段 | Backend | 8h | 角色名/人称/风格零漂移 |
| 4.5 评测：100章小说跑通，人工抽检 20 章一致性 | QA | 16h | 漂移率 < 1% |

---

### P2-5: 生产级 GA 就绪 (v1.0)
| 任务项 | 负责人 | 预计工时 | 验收标准 |
|--------|--------|----------|----------|
| 5.1 多租户：`Organization` / `Project` 隔离，Row Level Security | Backend | 24h | 租户间数据零泄露 |
| 5.2 RBAC 细粒度：`Permission`/`Role`/`Policy`，支持自定义角色 | Backend | 16h | 通过 OWASP Authorization Testing |
| 5.3 审计日志：所有写操作记录 `AuditLog` (who/what/when/ip) | Backend | 8h | 不可篡改、可导出合规报告 |
| 5.4 Helm Chart：`helm install audiobook ./charts/audiobook` | DevOps | 16h | 单命令部署 K8s，支持 HPA/VPA |
| 5.5 压力测试：1000 并发用户，100 并发流水线，持续 2h | QA | 24h | P99 延迟 < 5s，错误率 < 0.1% |
| 5.6 灾备演练：Redis/DB 主从切换、模型缓存失效、网络分区 | DevOps | 16h | RPO<1min, RTO<5min |
| 5.7 安全审计：SAST/DAST/依赖扫描、渗透测试报告 | Security | 24h | 无 High/Critical 漏洞 |
| 5.8 插件市场：`PluginManager`、市场后台、收益分成 | Backend | 40h | 第三方可发布插件、用户一键安装 |

---

## 验收标准统一模板

每个任务项必须包含以下验收维度：

```yaml
# 任务验收清单模板 (复制到每个 PR 描述中)
acceptance_criteria:
  functional:
    - [ ] 核心功能按需求文档实现
    - [ ] 边界条件处理 (空输入/异常/超时/并发)
    - [ ] 向后兼容：现有 API/配置/数据无破坏性变更
  quality:
    - [ ] 单元测试覆盖率 ≥ 80% (新增代码)
    - [ ] 集成测试通过 (CI 绿色)
    - [ ] 代码审查通过 (2人 LGTM)
    - [ ] 静态分析通过 (mypy/ruff/bandit 无报错)
  performance:
    - [ ] 关键路径延迟 ≤ 基线 × 1.1
    - [ ] 内存/CPU 无泄漏 (24h 压测稳定)
    - [ ] 并发支持 ≥ 设计值 × 1.5
  observability:
    - [ ] 关键指标已接入 Prometheus/Langfuse
    - [ ] 告警规则已配置 (如适用)
    - [ ] 日志结构化、含 trace_id
  documentation:
    - [ ] API 文档自动更新 (OpenAPI)
    - [ ] 架构决策记录 (ADR) 如涉及架构变更
    - [ ] 用户文档/迁移指南已更新
  security:
    - [ ] 无硬编码密钥/凭证
    - [ ] 输入验证/注入防护
    - [ ] 依赖扫描无 High/Critical
```

---

## 进度追踪看板 (建议在 GitHub Projects 创建)

| 列 | 说明 |
|----|------|
| **Backlog** | 未排期任务 |
| **Ready** | 需求明确、设计评审通过、可开工 |
| **In Progress** | 正在开发，每日站会同步 |
| **Code Review** | PR 提交，等待 Review |
| **Testing** | QA 验收中 |
| **Done** | 所有验收标准 ✅，合入主分支 |

**WIP 限制**: In Progress ≤ 团队人数 × 1.5

---

## 快速启动：本周行动项 (P0 优先)

```bash
# 1. 克隆仓库建立特性分支
git checkout -b fix/p0-mock-quality-gate
git checkout -b fix/p0-model-bundling
git checkout -b feat/p0-segment-stage

# 2. 本地跑通 Mock 流水线 (基线)
MOCK_LLM=true .venv/bin/python -m audiobook_studio.cli pipeline run 红楼梦

# 3. 并行开发三大 P0
#   - P0-1: 修改 quality_check.py + synthesize.py
#   - P0-2: 编写 download_kokoro_model.py + Dockerfile + docker-compose.free.yml
#   - P0-3: 新建 pipeline/segment.py + 注册 Stage

# 4. 每日同步：在 #audiobook-p0 Slack 频道贴进度截图
# 5. 周五前：三个 PR 全部合入 main，CI 全绿
```

---

## 变更记录

| 版本 | 日期 | 变更人 | 变更内容 |
|------|------|--------|----------|
| 1.0 | 2026-08-21 | @auditor | 初版，基于全面审计报告生成 |

---

> **执行原则**:
> 1. **P0 绝对优先** — 未解决不进入 P1
> 2. **小步快跑** — 每个 PR < 400 行，单一职责
> 3. **测试先行** — 先写失败测试，再写实现 (TDD)
> 4. **可观测先行** — 无指标不发布，无告警不上线
> 5. **文档同步** — 代码与文档同仓同命，PR 必带文档更新

**让我们把 Audiobook Studio 做成开源有声书领域的「Linux」——免费、可控、可进化、生产级！**
