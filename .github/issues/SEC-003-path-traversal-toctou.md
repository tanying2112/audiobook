# SEC-003: safe_join TOCTOU 竞争条件修复 + 统一 safe_open

## 严重级别
**P0 - High** (安全关键)

## 问题描述
`src/audiobook_studio/security.py:95-120` `safe_join()` 使用 `Path.resolve()` 后 `relative_to(base)` 检查，但检查通过到实际 `open()` 间隙可被 symlink 攻击（TOCTOU）。

## 攻击场景
1. 攻击者上传合法路径 `uploads/project_1/chapter_1.txt`
2. 检查通过后、写入前，将 `chapter_1.txt` 替换为指向 `/etc/passwd` 的 symlink
3. 程序写入敏感数据泄露或覆盖系统文件

## 修复方案
1. 引入原子安全打开：`os.open(path, O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC)` + `os.fdopen()`
2. 或引入 `securepath` / `pathvalidate` 库做原子校验
3. 所有文件写入点统一走 `safe_open()`：
   - `src/audiobook_studio/api/upload.py`
   - `src/audiobook_studio/export/*.py`
   - `src/audiobook_studio/tts/asset_manager.py`
   - `src/audiobook_studio/pipeline/audio_finalize.py`

## 验收标准
- [ ] `pytest tests/unit/test_security.py -k path_traversal` 新增 5 个 adversarial case 全绿
- [ ] `bandit -r src/` 无 B108 告警
- [ ] 所有写入文件调用点 grep 确认使用 `safe_open()`
- [ ] 压力测试并发 100 写入无竞态

## 关联文件
- `src/audiobook_studio/security.py:95-120` (safe_join)
- 新增 `src/audiobook_studio/security.py:safe_open()`
- 所有调用点重构