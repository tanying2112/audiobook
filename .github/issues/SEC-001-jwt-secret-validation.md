# SEC-001: JWT 密钥强制校验 + 密钥生成脚本

## 严重级别
**P0 - Critical** (生产阻断 / 安全关键)

## 问题描述
`src/audiobook_studio/config/settings.py:139-155` 中 `validate_jwt_secret()` 仅在 `ENVIRONMENT=production` 时拦截默认占位符，开发/测试环境允许弱密钥启动。`.env.example` 仍含占位符 `your-super-secret-key-change-in-production`。

## 攻击场景
1. 开发环境泄露 → 生产环境复用 → 令牌伪造、权限提升
2. CI 使用 `test-secret-key-for-ci-only` 导致测试环境可被攻破

## 修复方案
1. **启动时无条件校验** `JWT_SECRET_KEY` 熵值 ≥ 256-bit（Base64 ≥ 43 字符）
2. 移除 `.env.example` 占位符，改为生成脚本 `scripts/generate_secrets.py`
3. CI 新增 `detect-secrets` 历史扫描（已有 `leak-scan` job，需补全 baseline）

## 验收标准
- [ ] `python -c "from src.audiobook_studio.config import get_settings; get_settings()"` 无 `JWT_SECRET_KEY` 时直接 `RuntimeError`
- [ ] `grep -r "your-super-secret\|test-secret\|sk-xxx" --include="*.yml" --include="*.yaml" --include="*.example"` 返回空
- [ ] `detect-secrets scan --baseline .secrets.baseline` 零新增泄露
- [ ] `scripts/generate_secrets.py` 输出 256-bit Base64 密钥，可直接写入 `.env`

## 关联文件
- `src/audiobook_studio/config/settings.py:139-155`
- `.env.example`
- `.github/workflows/ci.yml` (leak-scan job)
- 新建 `scripts/generate_secrets.py`