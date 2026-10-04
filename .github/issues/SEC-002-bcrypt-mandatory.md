# SEC-002: bcrypt 强依赖 + 密码哈希迁移

## 严重级别
**P0 - High** (安全关键)

## 问题描述
`src/audiobook_studio/auth/jwt_handler.py:24-45` 中 `try/except ImportError` 导致生产环境若缺 `bcrypt` 静默降级为 SHA-256+salt，抗彩虹表能力弱。

## 攻击场景
- 依赖解析失败/供应链攻击 → 无 `bcrypt` → 密码哈希降级 → 离线破解风险指数级上升

## 修复方案
1. `pyproject.toml` 将 `bcrypt>=4.0` 移入 `dependencies`（非 optional）
2. 移除 fallback 逻辑，启动时强制检查 `bcrypt` 可用性
3. 现有 SHA-256 哈希迁移脚本（`alembic` revision + `passlib.hash.bcrypt.upgrade`）

## 验收标准
- [ ] 无 `bcrypt` 环境启动报错 `RuntimeError: bcrypt required for password hashing`
- [ ] 现有密码可透明升级：登录时自动重哈希为 bcrypt
- [ ] `bandit -r src/` 无 B106/B324 告警
- [ ] Alembic 迁移脚本 `versions/xxxx_migrate_sha256_to_bcrypt.py` 可执行回滚

## 关联文件
- `src/audiobook_studio/auth/jwt_handler.py:24-45`
- `pyproject.toml` (dependencies)
- 新建 `alembic/versions/xxxx_migrate_sha256_to_bcrypt.py`
- 新建 `scripts/migrate_passwords.py`