# ADR-001: 认证体系选型

## 状态
Accepted (2026-06-10, implemented)

## 背景
Audiobook Studio 需要用户认证体系以支持：
- 多用户项目管理
- 协作功能 (collab 模块)
- RBAC 角色权限控制
- API 端点保护

约束：
- 初期为单体部署，后续可能水平扩容
- 优先轻量级方案，避免引入外部认证服务复杂性
- 前端 SPA (Vite + Vue 3) 需要无状态 API 认证

## 决策
**选定 JWT (HS256) + Refresh Token + bcrypt 密码哈希**

关键参数：
| 参数 | 值 | 理由 |
|------|-----|------|
| 算法 | HS256 | 对称签名，单服务无需公钥分发 |
| Access Token 过期 | 30 分钟 | 限制泄露窗口 |
| Refresh Token 过期 | 7 天 | 用户体验与安全平衡 |
| 密码哈希 | bcrypt, 12 rounds | 抗彩虹表，work factor 可调节 |
| 密钥熵值 | ≥256-bit (43+ URL-safe base64 字符) | 抗暴力破解 |
| 存储 | httpOnly Cookie (可选) + Authorization Header | SPA 兼容 |

## 替代方案

| 方案 | 优势 | 劣势 | 判定 |
|------|------|------|------|
| **Session + Redis** | 可即时撤销、无 JWT 大小开销 | 有状态 → 水平扩容需 sticky session 或共享 Redis；SPA CSRF 复杂 | ❌ 与未来扩容目标冲突 |
| **OAuth2 / OIDC** (Keycloak, Auth0) | 行业标准、支持 SSO、内置角色 | 引入外部依赖、部署复杂度高、初期过度设计 | ❌ MVP 阶段过度设计 |
| **PASETO** | 比 JWT 更安全的默认参数、无算法混淆风险 | 生态较小、工具链不如 JWT 成熟 | ⬜ 未来可评估迁移 |
| **JWT (RS256)** | 非对称签名、可公开验签 | 密钥管理复杂、多服务场景才值得 | ❌ 当前单服务不需要 |

## 后果

### 正面
- 无状态：水平扩容时任意实例可验签
- FastAPI 原生支持 python-jose + passlib/bcrypt
- RBAC 可通过 JWT payload 中的 roles claim 传递

### 负面
- Token 无法主动撤销（除非引入黑名单 Redis）
- Refresh Token 轮换逻辑增加前端复杂度
- JWT payload 大小随 roles 增长（需控制 permission 粒度）

### 后续行动
- 考虑引入 Token 黑名单 (Redis SET + TTL) 用于登出/封禁场景
- 评估 PASETO v4 迁移可行性 (PKI 轮换更安全)

## 关联
- Implementation: `src/audiobook_studio/auth/jwt_handler.py`, `auth/dependencies.py`, `auth/router.py`
- Security hardening: [`SEC-001`](../../.github/issues/SEC-001-jwt-secret-validation.md), [`SEC-002`](../../.github/issues/SEC-002-bcrypt-mandatory.md)
- RBAC: `src/audiobook_studio/auth/rbac.py`
- Related issue: [#17](../../.github/issues/SEC-001-jwt-secret-validation.md)