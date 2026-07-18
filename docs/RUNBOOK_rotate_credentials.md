# RUNBOOK — 凭据轮换与 Git 历史重写（P0-1）

> **适用**: Audiobook Studio 仓库 owner / 维护人员
> **触发条件**: `docs/AUDIT_REPORT_v3.md` P0-1（2026-07-18 实测）中列出的凭据已泄露至 `origin/main`（公开可读）。
> **完成判据**: `origin/main` 及所有 `refs/remotes/origin/*` 上不再出现以下四个前缀 / 字符串；Upstash Redis 与 Cloudflare R2 控制台已轮换凭据；本地及 CI 均跑通 `leak-scan` job。

---

## 0. 凭据泄露清单（完整脱敏表）

| 凭据类型 | 文件 | 泄露前缀（脱敏展示前 20 字符） | 用途 | 预期长度 |
|---|---|---|---|---|
| Upstash Redis AUTH 令牌 | `read_logs.py:15` 历史；`worker/kaggle_worker.py` 历史 | `gQAAAAAAAVCIAAIg…` | 生产 Redis 认证 | 62 字符 |
| Cloudflare R2 Access Key ID | `worker/kaggle_worker.py` 历史；`voxcpm2-pool/paddle/.env`（本地未推） | `2fc25bbebc34f9b8…` | R2 对象存储读 | 32 hex |
| Cloudflare R2 Secret Access Key | 同上 | `b7d997bc558346d8…` | R2 对象存储私钥 | 64 hex |
| Upstash Redis 主机名 | `read_logs.py:13` | `casual-sawfish-86152.upstash.io` | Redis 端点 | 31 字符 |

完整原值已写入 `scripts/security/leaked-credential-patterns.txt`（.gitignore 已排除）。

---

## A. 控制台凭据轮换（必须最先做，否则重写历史无法阻止已持令牌者继续访问）

### A.1 Upstash Redis AUTH 令牌轮换

1. 登录 <https://console.upstash.com/>
2. 选中 `casual-sawfish-86152` 实例 → **Settings** → **REST API & Tokens**（或 **Management API**）
3. **Revoke** 旧 token (`gQAAAAAAAA…`)；**Create New Token** 并记录（保存到 1Password / Bitwarden / Vault 中）
4. 如 Upstash 支持改实例名，**删除**该实例并新建一个新命名实例（旧主机名一并失效，旧 URL 不再可达）
5. 在 Upstash 控制台 **Access Logs** 下载最近 30 天访问日志，人工审阅有无异常 IP

### A.2 Cloudflare R2 Access Key 轮换

1. 登录 <https://dash.cloudflare.com/> → **R2** → **Your R2 account** → **Manage R2 API Tokens**
2. 定位泄露的 Access Key ID (`2fc25bbebc…`)
3. **删除** 该 Token → **Create API Token**；选择权限：Object Read & Write，bucket 限定为 `audiobook-assets`
4. 记录新的 Access Key ID + Secret Access Key 到密码管理器
5. Cloudflare 控制台 **Audit Log** → 过去 30 天 — 检查是否有非预期 IP 访问 bucket

### A.3 验证旧凭据已失效

```bash
# 1. 验证旧 Redis AUTH 已失效
redis-cli -h casual-sawfish-86152.upstash.io -p 6379 -a 'gQAAAAAAAVCIAAIg...原值' PING
# 期望: NOAUTH Authentication required / WRONGPASS invalid username-password pair

# 2. 验证旧 R2 Key 已失效
aws --endpoint-url https://061b064ef0dafd787d33f4ee1693aa1b.r2.cloudflarestorage.com \
    s3 ls --profile <OLD_PROFILE_NAME>
# 期望: InvalidAccessKeyId / 403 Forbidden
```

---

## B. Git 历史重写（用 git-filter-repo 替换明文凭据）

### B.1 安装 git-filter-repo

```bash
# macOS / Linux
pip3 install --user git-filter-repo
# 或用 homebrew
brew install git-filter-repo
```

### B.2 准备本地工作树

```bash
cd /Users/guwj/Desktop/AI_Lab/audiobook

# 1. 强制创建备份分支（已存在的 backup/pre-credential-rewrite-20260718 不要删）
git branch backup/pre-credential-rewrite-20260718-verify origin/main
git tag pre-rewrite-20260718 origin/main

# 2. 把当前 security/hotfix-rotate-credentials 分支上的未提交修改先收尾提交（见本分支 PR 内容）
git add -A
git commit -m "security(P0-1): rotate credentials + CI leak scan + .gitignore hardening"
```

### B.3 执行 git filter-repo

`git-filter-repo` 默认会要求仓库为 fresh clone 以防误操作；本仓库已被深度操作，使用 `--force` 跳过该保护（先确认已完成 B.2 的备份）。

```bash
# 切回主分支再重写，重写会作用于整个 commit DAG
git checkout main

# 执行重写
git filter-repo --replace-text scripts/security/leaked-credential-patterns.txt --force

# 该命令会：
#   - 遍历每个 commit 的 blob，把命中字符串替换为 ***REDACTED-*-ROTATED-20260718***
#   - 重写 commit hash（parent map 保形）
#   - 默认移除 remote 配置（避免不小心推送前未审计）
```

### B.4 验证重写结果

```bash
# 1. 历史中应当再也找不到原凭据前缀
.github/scripts/scan-leaked-credentials-history.sh
# 期望: ✅ Git history is clean of known leaked credential patterns.

# 2. 工作树当前的源码也已不包含原凭据
.github/scripts/scan-leaked-credentials.sh
# 期望: ✅ Worktree clean of known leaked credential patterns.

# 3. 抽检 57e4759 这一关键 commit 的 read_logs.py
git log --all --oneline -p -S 'gQAAAAAAAVCIAAIg' | head -5
# 期望: 无任何 +++ / --- 行命中

# 4. 抽检 R2 Access / Secret Key
git log --all --oneline -p -S '2fc25bbebc' | head -5
git log --all --oneline -p -S 'b7d997bc5583' | head -5
# 期望: 无命中
```

### B.5 重连 remote 并强推

```bash
# git-filter-repo 默认会移除 origin，需要重连
git remote add origin git@github.com:tanying2112/audiobook.git

# 同步所有本地分支并强推（注意: --force-with-lease 更安全，但 filter-repo 后 commit 全部重写，
# lease 不会命中旧 origin，所以只能用 --force 或 --force-with-lease --force-if-includes）
git push --force origin main
git push --force origin agent/A/fix-api-crud
git push --force origin agent/B/feat-state-normalize
git push --force origin agent/C/fix-sse-pipeline
git push --force origin feat/collab-module

# 安全分支也要推: backup 与 security/hotfix-rotate-credentials
git push --force origin backup/pre-credential-rewrite-20260718
git push -u origin security/hotfix-rotate-credentials
```

### B.6 清理本地孤立对象

```bash
# 重写后 origin 已无旧 commit，需要把 gc 跑一遍以彻底清除磁盘上的旧 blob
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 再验证一次
.github/scripts/scan-leaked-credentials-history.sh
```

---

## C. CI 验证

本分支已经在 `.github/workflows/ci.yml` 加入 `leak-scan` job：

- `scan-leaked-credentials.sh` 扫描当前工作树
- `scan-leaked-credentials-history.sh` 扫描所有 commit 历史（重写后必须返回 0）

合并到 main 后 PR 上会跑 `leak-scan` job；重写完毕的强推也会触发 CI。CI 红则阻止后续 PR 合并。

---

## D. 通知所有 clone 用户

历史重写后所有现有 clone 都变成了"旧副本"。应：

1. 在仓库 README 顶部贴一个简短告示：`⚠️ 2026-07-18: History rewritten due to credential leak. All clones MUST re-clone. See docs/RUNBOOK_rotate_credentials.md.`
2. 通知已知 clone 用户清单（git config `user.email` 不一定能枚举，退而求其次通知近期提交者）：
   ```bash
   git log --all --pretty=format:"%ae" | sort -u
   ```
3. 在聊天群（Slack/钉钉/微信群）正式广播一遍。

---

## E. 后续监测

- 在 Cloudflare Upstash 设置 **alert on unusual access**，监测未来 7 天是否有旧 IP 重连（数据应在 A.1/A.2 后立即归零）
- 在 Cloudflare 设置 R2 bucket **audit log** 推送到 Splunk / Loki，监测未来 14 天是否有非预期 IP 访问 audiobook-assets
- 7 天后再跑 `scan-leaked-credentials-history.sh` 一次，确认无回归

---

## F. 如果出问题

| 现象 | 排查 |
|---|---|
| `git filter-repo` 报 "Refusing to destructively overwrite repo history" | 已是 fresh clone or `--force` 未加；确认已备份后加 `--force` |
| 重写后某些分支 commit hash 变了但 history 仍有命中 | patterns 文件没放入仓库根目录 / 命令使用了相对路径；使用 `--replace-text $(pwd)/scripts/security/leaked-credential-patterns.txt` 绝对路径 |
| 重写后 `backup/pre-credential-rewrite-20260718` 仍包含旧凭据 | 该分支也必须被重写；`git push --force` 该分支或删它 |
| CI `leak-scan-history` job 在 origin 上挂红 | origin 仍有旧 commit 未清理；对每个 `refs/remotes/origin/*` 重复 B.5 |
| 用户 clone 后 push 出现 老 commit | 用户必须 `git fetch --all && git reset --hard origin/main`，或最稳妥：**删本地 repo，重新 clone** |

---

## G. 关联文件

| 文件 | 作用 |
|---|---|
| `docs/AUDIT_REPORT_v3.md` | 触发本次轮换的原始审计报告 |
| `scripts/security/leaked-credential-patterns.txt` | git-filter-repo 输入文件（.gitignore 规则已排除） |
| `.github/scripts/scan-leaked-credentials.sh` | 工作树扫描 CI 脚本 |
| `.github/scripts/scan-leaked-credentials-history.sh` | 历史扫描 CI 脚本 |
| `.github/workflows/ci.yml` | CI leak-scan job |
| `.gitignore` | 已加入 secrets_setup.sh、mirror_sync.sh、bos_sync.py、*.env.swp 等 |
| `read_logs.py` | 已移除硬编码 By-Env-Required 模式 |

---

*最后更新: 2026-07-18* · *作者: Claude Code（在 P0-1 修复 PR 中落地）*
