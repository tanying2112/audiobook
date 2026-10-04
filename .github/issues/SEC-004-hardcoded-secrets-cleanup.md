# SEC-004: 清理所有硬编码/配置泄露的凭证占位符

## 严重级别
**P0 - High** (安全关键)

## 问题描述
多处硬编码占位符凭证：
- `docker-compose.yml:17` `SECRET_KEY=${SECRET_KEY:-your-secret-key-change-in-production}`
- `ci.yml:111` `SECRET_KEY=test-secret-key-for-ci-only`
- `.env.example` 含 `OPENAI_API_KEY=sk-xxx` 等占位符

## 攻击场景
- 默认值被意外用于生产 → 密钥可预测
- CI 日志泄露测试密钥 → 复用风险

## 修复方案
1. 统一改为空值强制报错：`SECRET_KEY=${SECRET_KEY:?}` 或 Python 侧校验
2. CI 使用 `actions/create-github-app-token` 或 `secrets` 注入
3. `detect-secrets` baseline 更新，预提交钩子强制扫描

## 验收标准
- [ ] `grep -r "your-secret\|test-secret\|sk-xxx" --include="*.yml" --include="*.yaml" --include="*.example"` 返回空
- [ ] `docker compose up` 无 `SECRET_KEY` 时失败并提示
- [ ] CI `leak-scan` job 零新增泄露
- [ ] `.secrets.baseline` 更新后 `detect-secrets audit` 通过

## 关联文件
- `docker-compose.yml:17`
- `.github/workflows/ci.yml:111`
- `.env.example`
- `.secrets.baseline`