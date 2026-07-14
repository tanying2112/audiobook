# ADR 001: 确立以 Hermes 异步流为核心调度，Celery 为虚级轻量编排的架构设计

## 状态
已接受 (Accepted)

## 上下文 (Context)
Audiobook Studio 作为一个长链路有声书系统，面临以下物理约束：
1. **长耗时性**：TTS 语音合成与后期混音属于典型的密集型、长耗时任务（长达数分钟至数小时）。
2. **算力源不稳定**：分布式 GPU Worker 运行在异构多云或非稳定算力源（如免费 VPS、Kaggle/Colab 隧道等）上，随时可能遭遇断网、实例被回收或配额耗尽。
3. **大资产传输**：生成的中间音频切片与最终成品体积庞大，不适合通过轻量级 Message Broker 结果后端直接进行高频网络传输。

原有的纯 Celery 混合架构导致 Worker 长时间被长耗时任务独占，超时与重试语义极难调优，算力崩塌时易丢失任务。

## 决策 (Decision)
我们彻底确立**“Hermes 为实、Celery 为虚”**的双轨架构：

1. **外轨为实（Hermes 调度器）**：
   - 核心 TTS 切片合成、重试、限流与分布式 Worker 调度，完全交由底层的 **Hermes 调度机制**（基于 Redis 状态机 + Cloudflare R2 对象存储指针）。
   - 任务采用“拉取式（Pull-based）”领取，配合可见性超时（Visibility Timeout）与天然的可重新拉回队列（Requeue）机制，确保分布式算力节点离线时任务自愈。
2. **内轨为虚（Celery 编排器）**：
   - Celery 仅保留其在 Web 异步触发侧的**轻量级流程编排职责**（如一键触发全书导出、章节打包、RSS 生成或通知推送）。
   - 严禁在 Celery 任务内部直接跑底层的 VoxCPM2 音频切片合成循环。Celery 任务应当仅仅作为 Hermes 的客户端，通过调用 Port 契约向 Hermes 提交任务指针，并轮询状态（`port.submit()` / `port.get_status()`）。
3. **本地降级与过渡期**：
   - 本地 Kokoro 轻量引擎或本地开发测试路径，统一继承相同的 Port 接口。现有 HTTP 的 `RemoteVoxCPM2Client` 降为薄网关，与 Redis 任务主路径在当前 Sprint 结束前完成收口合并。

## 后果 (Consequences)
- **正面影响**：消除长任务导致的 Celery Worker 阻塞问题，极大降低多云异构节点接入算力的门槛（仅需极简 Pull 客户端）。
- **负面影响**：需要严格维护 Redis 状态契约，对任务的幂等性与 Port 接口层抽象要求极高。