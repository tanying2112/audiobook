# 全量套件基线 — 2026-08-31

> 本文件为 **green baseline** 的档案记录。对应的具名锚点为 git tag
> `baseline/full-suite-green-2026-08-31`（指向 commit `5fdf34d`）。
> 日后重跑全量套件，对比下方数字即可判断是否回归。

## 结果（run10，权威）

| 指标 | 数值 |
|---|---|
| collected | ~7927 |
| passed | **7784** |
| skipped | 143 |
| failed | **0** |
| errors | 0 |
| 耗时 | 833.95s (~13m54s) |
| 环境 | `.venv` Python 3.12 / pytest 9.1.1 / `pytest.ini`（asyncio 走 legacy 模式，pyproject 的 strict 不生效） |

命令：`.venv/bin/python -m pytest -p no:randomly -q`

## 行覆盖率口径（重要，红线 #2）

**本报告不提供精确行覆盖率百分比，也不编造任何数字。**

原因：conftest 在收集期就 eager-import 整个 `src`，对全量套件跑 `--cov=src` 会在
原生 C 扩展（torch 2.2.2 / tts / codec）上 segfault 崩溃，覆盖率工具无法完成。
仓库内的 coverage 门禁仅对 **unit tests** 强制且已通过，但该数字不等同于全量覆盖率。

因此本基线的权威健康信号是 **pass / skip / fail 计数**，而非 %。任何"全量覆盖率 = X%"
的宣称若无独立可复现的覆盖率产物支撑，均视为未经验证。

## 本基线覆盖的修复（相对 run7 的 29 个失败）

run7 暴露 29 失败 → run10 归零。分类：

1. **VoxCPM2（2 个，真坏）** — `bench_voxcpm2.detect_hardware` 把 mock torch 的
   `MagicMock` 直接塞进报告 dataclass，导致 `json.dumps` 崩溃。修复：cuda/mps 可用性
   强制 `bool()` coercion（生产加固，非测试造假）。
2. **分段测试（27 个，顺序依赖）** — `test_asr_wer*.py` 在 **collection 期** 把裸
   `MagicMock()` 写入 `sys.modules["torch"]`（无 `__version__`）；`MagicMock.__getattr__`
   将 `__version__` 当 dunder 抛 `AttributeError`，致 `import spacy`→`thinc`→`torch.__version__`
   崩溃。`tests/golden/` 字母序最前，在任何 per-test teardown 之前就执行，故既有 teardown /
   `pytest_collection_modifyitems` 修复都够不到。修复：`conftest.py` 新增 session 级 autouse
   fixture `_session_torch_repair`，在 collection 结束后、首个测试前重建 canonical torch mock。

修复提交：`a9e1e68`（torch 泄漏 + VoxCPM2 加固）、`5fdf34d`（instructor 补丁目标 /
extract 模块还原 / OTel 计数别名健壮化）。harness/feedback 特性工作已在 `a015925`
（"全量备案"）提交并推送。

## 红线声明（测试诚信）

- 红线 #1：Tier1 VoxCPM2 真音频不做伪造；e2e 仅校验路由接缝。
- 红线 #2：禁止空/假断言。e2e 在真实环境不可用时 **skip**（不伪造成功）。本基线
  0 failed 来自真实测试执行，非任何 `assert True` 式假通过。

## 如何复现 / 比对

```bash
.venv/bin/python -m pytest -p no:randomly -q 2>&1 | tail -1
# 期望：<N> passed, 143 skipped, 0 failed
```

若 `failed > 0` 或 `passed` 较 7784 明显下滑，即视为回归，需对照本基线排查。
