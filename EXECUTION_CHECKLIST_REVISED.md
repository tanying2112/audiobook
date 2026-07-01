# Audiobook Studio 执行清单（修订版）

## 阶段 R：Realignment（真实对齐）
- [ ] R-1 测试基础设施修复
- [ ] R-2 print() → logger 全面清理
- [ ] R-3 EXECUTION_CHECKLIST 瘦身
- [ ] R-4 PROJECT.md 日志归档
- [ ] R-5 Mock 代码真实状态标注
- [ ] R-6 覆盖率基线重测

## 阶段 S：Solidification（核心能力固化）
- [ ] S-1 auto_run.py 真实管线编排
- [ ] S-2 templates.py 范本应用逻辑
- [ ] S-3 publish.py 真实发布逻辑
- [ ] S-4 synthesize.py Mock 代码清理
- [ ] S-5 translate.py 真实翻译配音
- [ ] S-6 voice_cloning.py 真实克隆流程
- [ ] S-7 硬质检三件套真实接入

## 阶段 Q：Quality（质量达标）
- [ ] Q-1 低覆盖率模块补测
- [ ] Q-2 E2E 真实长书验证
- [ ] Q-3 CI 覆盖率阈值 75% → 80%
- [ ] Q-4 detect-secrets 阻断配置
- [ ] Q-5 非核心 Sprint G 代码标记
- [ ] Q-6 文档站点最终补齐

## 阶段 P：Polish（生产就绪）
- [ ] P-1 Docker 镜像真实测试
- [ ] P-2 Git Tag v0.2.0 发布
- [ ] P-3 用户文档与快速开始
- [ ] P-4 性能优化
- [ ] P-5 自我迭代闭环真实验证

生成时间: $(date -u +%Y-%m-%dT%H:%M:%SZ)