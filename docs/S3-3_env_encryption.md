# S3-3: .env 加密与解密流程

## 概述
使用 **sops + age** 对 `.env` 进行加密存储，确保：
- `.env` **永不入库**（已在 `.gitignore`）
- `.env.encrypted` 可安全提交到仓库
- CI/CD 通过 `AGE_KEY` secret 自动解密
- 本地开发通过 `.agekey` 文件解密

## 工具安装

```bash
# macOS
brew install age sops

# Linux (Debian/Ubuntu)
sudo apt-get install -y age sops

# 或使用二进制下载
# age: https://github.com/FiloSottile/age/releases
# sops: https://github.com/getsops/sops/releases
```

## 密钥生成

```bash
# 生成 age 密钥对
age-keygen -o .agekey

# 输出示例:
# Public key: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#
# 重要:
# - .agekey (私钥) → **绝不提交**，已在 .gitignore
# - 公钥 → 用于加密，可公开
```

## 加密流程 (本地)

```bash
# 1. 确保 .env 存在
cp .env.example .env
# 编辑 .env 填入真实值

# 2. 加密
sops --age age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
     --encrypt .env > .env.encrypted

# 3. 验证解密
SOPS_AGE_KEY_FILE=.agekey sops --input-type dotenv --output-type dotenv --decrypt .env.encrypted
```

## 解密脚本

```bash
# 使用统一脚本
scripts/decrypt_env.sh

# 或指定参数
scripts/decrypt_env.sh --age-key-file /path/to/key --encrypted-file .env.encrypted --output .env
```

## CI/CD 配置 (GitHub Actions)

### 1. 添加仓库 Secret
- Settings → Secrets and variables → Actions → New repository secret
- Name: `AGE_KEY`
- Value: **`.agekey` 文件完整内容**（私钥）

### 2. Workflow 已配置
`.github/workflows/ci.yml` 已包含：
- 自动安装 `age` `sops`
- 从 `AGE_KEY` secret 写入 `.agekey`
- 解密 `.env.encrypted` → `.env`
- 测试/构建完成后自动清理敏感文件

### 3. 部署环境
- `deploy-staging` (develop 分支)
- `deploy-production` (main 分支)
- 均自动解密并注入环境变量

## 本地开发流程

```bash
# 首次克隆后
git clone ...
cd audiobook

# 1. 放置私钥 (团队内部安全分发，或从密钥管理系统获取)
# 方式 A: 从密钥管理系统获取
# 方式 B: 团队成员通过安全渠道共享 .agekey

# 2. 解密
scripts/decrypt_env.sh

# 3. 开发
# .env 已生成，正常开发

# 4. 修改配置后重新加密
vim .env
sops --age age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx --encrypt .env > .env.encrypted
git add .env.encrypted
git commit -m "chore: update encrypted env"
```

## 密钥轮换

```bash
# 1. 生成新密钥对
age-keygen -o .agekey.new

# 2. 用新公钥重新加密
sops --age age1NEW_PUBLIC_KEY --encrypt .env > .env.encrypted

# 3. 更新 CI Secret
# GitHub Settings → Secrets → AGE_KEY 更新为 .agekey.new 内容

# 4. 团队分发新私钥
# 4. 清理旧密钥
rm .agekey.new
```

## 常见问题

| 问题 | 解决 |
|------|------|
| `sops: command not found` | `brew install sops` / `apt install sops` |
| `age: command not found` | `brew install age` / `apt install age` |
| `Incorrect Usage. flag provided but not defined: -age-key-file` | 使用 `SOPS_AGE_KEY_FILE=.agekey` 环境变量 |
| `Could not unmarshal input data` | 加 `--input-type dotenv --output-type dotenv` |
| CI 报错 `AGE_KEY secret not found` | 检查 GitHub Settings → Secrets → AGE_KEY 是否配置 |

## 验收清单

- [ ] `.env` 在 `.gitignore` 中
- [ ] `.agekey` 在 `.gitignore` 中
- [ ] `.env.encrypted` 可正常解密
- [ ] `scripts/decrypt_env.sh` 可执行且工作
- [ ] GitHub Actions 配置 `AGE_KEY` secret
- [ ] CI 能自动解密并跑通测试
- [ ] 部署环境能自动解密注入
- [ ] 文档同步更新