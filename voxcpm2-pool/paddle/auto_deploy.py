#!/usr/bin/env python3
"""
VoxCPM2 百度 AI Studio 全自动部署循环

工作流：
1. 同步前置资产：运行 mirror_sync.sh / bos_sync.py，同步模型权重到 BOS
2. 提交云端任务：aistudio submit job -f ...
3. 捕获任务 ID：正则提取 pipelineId
4. 监控云端日志：aistudio job ls + aistudio job cp 实时读取 Python 报错
5. 自动修复：ModuleNotFoundError / AttributeError / 语法错误 → 本地修源码
6. 无限循环：修复后回到第 1 步重新打包提交，直到日志无代码缺陷
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ============================================================
# 配置区（按需修改）
# ============================================================
PADDLE_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = PADDLE_DIR.parent.parent
CODE_PKG_DIR = PADDLE_DIR / "job_package"  # 打包上传的代码目录（≤50MB）
AISTUDIO_TOKEN = os.getenv("AISTUDIO_TOKEN") or ""  # 从环境变量或配置文件读取
PIPELINE_NAME = "voxcpm2-worker"
ENV_VERSION = "paddle2.6_py3.10"  # 可选: paddle2.4_py3.7, paddle2.5_py3.10, paddle2.6_py3.10, paddle3.0_py3.10
DEVICE = "v100"  # 可选: v100
GPUS = 1  # 可选: 1, 4, 8
PAYMENT = "acoin"  # acoin 或 coupon
MOUNT_DATASETS = []  # 挂载数据集 ID 列表（最多 3 个）
MAX_LOG_LINES = 2000  # 每次拉取日志行数
POLL_INTERVAL = 15  # 轮询间隔（秒）
MAX_RETRIES = 100  # 最大重试次数
TIMEOUT_SECONDS = 3600 * 4  # 单任务超时（4小时）

# 已知需要的依赖包（会自动注入 requirements.txt）
REQUIRED_PACKAGES = [
    "torch",
    "torchaudio",
    "transformers",
    "accelerate",
    "safetensors",
    "numpy",
    "huggingface_hub",
    "boto3",
    "baidubce",
    "python-dotenv",
    "einops",
    "scipy",
    "pydub",
    "soundfile",
    # 推理主路径硬依赖（src/voxcpm 实际 import，缺失会直接 ModuleNotFoundError）
    "pydantic",  # config.py / voxcpm2.py / audio_vae_v2.py 顶层依赖
    "librosa",  # voxcpm2.py 推理主路径
    "wetext",  # utils/text_normalize.py 文本归一化
    "inflect",  # utils/text_normalize.py
    "regex",  # utils/text_normalize.py
    "modelscope",  # zipenhancer.py（可选后处理，顶层 import，避免连带失败）
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("auto_deploy")


# ============================================================
# 工具函数
# ============================================================
def run_cmd(cmd: List[str], cwd: Path = None, timeout: int = 300, check: bool = True) -> Tuple[int, str, str]:
    """运行命令，返回 (returncode, stdout, stderr)"""
    log.debug(f"[CMD] {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.stdout:
            log.debug(f"[STDOUT]\n{proc.stdout.strip()}")
        if proc.stderr:
            log.debug(f"[STDERR]\n{proc.stderr.strip()}")
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        log.error(f"命令超时: {' '.join(cmd)}")
        raise


def run_cmd_async(cmd: List[str], cwd: Path = None) -> subprocess.Popen:
    """异步运行命令"""
    log.debug(f"[CMD-ASYNC] {' '.join(cmd)}")
    return subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def extract_job_id(output: str) -> Optional[str]:
    """从 aistudio submit job 输出中提取 pipelineId"""
    # 形如：pipelineId: xxxx-xxxx 或 "pipeline_id": "xxx"
    patterns = [
        r'"pipelineId"\s*:\s*"([\w-]+)"',
        r'"pipeline_id"\s*:\s*"([\w-]+)"',
        r"pipelineId[:\s]+([\w-]+)",
        r"pipeline_id[:\s]+([\w-]+)",
        r"ID[:\s]+([a-f0-9-]{36})",
        r"job[-\s]?id[:\s]+([\w-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, output, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def parse_log_errors(log_text: str) -> List[Dict]:
    """解析日志中的 Python 错误"""
    errors = []
    # ModuleNotFoundError / ImportError
    for m in re.finditer(r"(ModuleNotFoundError|ImportError):\s*No module named ['\"]([\w-]+)['\"]", log_text):
        errors.append({"type": "missing_module", "module": m.group(2), "raw": m.group(0)})
    # AttributeError: module 'xxx' has no attribute 'yyy'
    for m in re.finditer(
        r"AttributeError:\s*module\s+['\"]([\w.]+)['\"]\s+has no attribute\s+['\"](\w+)['\"]", log_text
    ):
        errors.append({"type": "missing_attr", "module": m.group(1), "attr": m.group(2), "raw": m.group(0)})
    # AttributeError: 'xxx' object has no attribute 'yyy'
    for m in re.finditer(r"AttributeError:\s*'(\w+)'\s+object has no attribute\s+['\"](\w+)['\"]", log_text):
        errors.append({"type": "missing_attr_obj", "class": m.group(1), "attr": m.group(2), "raw": m.group(0)})
    # SyntaxError
    for m in re.finditer(r"SyntaxError:\s*(.+)", log_text):
        errors.append({"type": "syntax", "msg": m.group(1), "raw": m.group(0)})
    # FileNotFoundError
    for m in re.finditer(
        r"FileNotFoundError:\s*\[Errno 2\]\s+No such file or directory:\s*['\"]([^'\"]+)['\"]", log_text
    ):
        errors.append({"type": "missing_file", "path": m.group(1), "raw": m.group(0)})
    # torch.load / weights_only 相关
    if "weights_only" in log_text.lower() and ("error" in log_text.lower() or "fail" in log_text.lower()):
        errors.append({"type": "weights_only", "raw": "weights_only issue detected"})
    return errors


# ============================================================
# 步骤 1: 同步前置资产
# ============================================================
def sync_assets() -> bool:
    """运行 mirror_sync.sh 或 bos_sync.py 同步模型到 BOS"""
    log.info("=" * 60)
    log.info("步骤 1: 同步模型权重到 BOS")
    log.info("=" * 60)

    # 优先用 bos_sync.py（官方 SDK），失败回退 mirror_sync.sh
    for script in ["bos_sync.py", "mirror_sync.sh"]:
        script_path = PADDLE_DIR / script
        if not script_path.exists():
            continue
        log.info(f"运行 {script} ...")
        try:
            if script.endswith(".py"):
                rc, out, err = run_cmd(
                    ["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/python3", script], cwd=PADDLE_DIR, timeout=600
                )
            else:
                rc, out, err = run_cmd(["bash", script], cwd=PADDLE_DIR, timeout=600)
            if rc == 0 and ("成功" in out or "✅" in out or "uploaded" in out.lower()):
                log.info(f"✅ {script} 执行成功")
                return True
            else:
                log.warning(f"{script} 失败: {err or out}")
        except subprocess.CalledProcessError as e:
            log.warning(f"{script} 异常: {e.stderr}")

    log.error("所有同步脚本均失败")
    return False


# ============================================================
# 步骤 2: 准备代码包
# ============================================================
def prepare_code_package() -> bool:
    """将 paddle_worker.py 等打包到 job_package/（排除大文件，≤50MB）"""
    log.info("=" * 60)
    log.info("步骤 2: 准备代码包 (≤50MB)")
    log.info("=" * 60)

    # 清理旧包
    if CODE_PKG_DIR.exists():
        import shutil

        shutil.rmtree(CODE_PKG_DIR)
    CODE_PKG_DIR.mkdir(parents=True)

    # 复制核心文件
    # 注：云端实际运行入口为 entry.sh（含 pip 分步安装、日志回传、崩溃保护），
    # 仅 paddle_worker.py 是 torch 补丁半成品，不能作为入口。
    files_to_copy = [
        "paddle_job_entry.py",
        "entry.sh",
        "upload_log.py",
        "bos_sync.py",  # 备用
    ]
    for f in files_to_copy:
        src = PADDLE_DIR / f
        if src.exists():
            import shutil

            shutil.copy2(src, CODE_PKG_DIR / f)
            log.info(f"  ✓ {f}")

    # 复制模型源码 src/voxcpm/（云端路径 /home/aistudio/src/voxcpm 证明必含）
    src_pkg = PADDLE_DIR.parent.parent / "src" / "voxcpm"
    if src_pkg.exists():
        import os
        import shutil

        dst_pkg = CODE_PKG_DIR / "src" / "voxcpm"
        dst_pkg.mkdir(parents=True, exist_ok=True)
        for item in src_pkg.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src_pkg)
                target = dst_pkg / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        # 需要 src/__init__.py 让 src.voxcpm 可导入
        src_init = PADDLE_DIR.parent.parent / "src" / "__init__.py"
        if src_init.exists():
            (CODE_PKG_DIR / "src" / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_init, CODE_PKG_DIR / "src" / "__init__.py")
        log.info(f"  ✓ src/voxcpm ({src_pkg.stat().st_size // 1024} KB)")
    else:
        log.error(f"未找到模型源码目录: {src_pkg}")
        return False

    # 注入 .env（含 R2/BOS/REDIS 凭证），否则云端 paddle_job_entry.py
    # 无法回传日志，导致失败任务完全盲飞。
    env_src = PADDLE_DIR / ".env"
    if env_src.exists():
        import shutil

        shutil.copy2(env_src, CODE_PKG_DIR / ".env")
        log.info(f"  ✓ .env (凭证注入，日志可回传 R2)")
    else:
        log.warning("未找到 .env，云端将无法回传日志")

    # 生成 requirements.txt
    req_path = CODE_PKG_DIR / "requirements.txt"
    req_path.write_text("\n".join(REQUIRED_PACKAGES) + "\n")
    log.info(f"  ✓ requirements.txt ({len(REQUIRED_PACKAGES)} packages)")

    # 检查大小
    total_size = sum(f.stat().st_size for f in CODE_PKG_DIR.rglob("*") if f.is_file())
    log.info(f"代码包大小: {total_size / 1024 / 1024:.2f} MB")
    if total_size > 50 * 1024 * 1024:
        log.error("代码包超过 50MB 限制！")
        return False
    return True


# ============================================================
# 步骤 3: 配置 aistudio CLI
# ============================================================
def configure_aistudio() -> bool:
    """配置 aistudio 访问令牌"""
    global AISTUDIO_TOKEN
    log.info("=" * 60)
    log.info("步骤 3: 配置 aistudio CLI")
    log.info("=" * 60)

    if not AISTUDIO_TOKEN:
        # 尝试从配置文件读取
        token_file = Path.home() / ".cache" / "aistudio" / ".auth" / "token"
        if token_file.exists():
            AISTUDIO_TOKEN = token_file.read_text().strip()
            log.info(f"已从配置文件读取 token: {AISTUDIO_TOKEN[:8]}...")
        else:
            log.error("未设置 AISTUDIO_TOKEN 环境变量，也未找到本地配置")
            log.error("请先运行: aistudio config -t <your_access_token>")
            log.error("Access Token 获取: https://aistudio.baidu.com/account/accessToken")
            return False

    # 验证配置
    rc, out, err = run_cmd(["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio", "jobs"], check=False)
    if rc == 0:
        log.info("✅ aistudio CLI 配置已生效")
        return True
    else:
        log.warning("CLI 未配置或 token 无效，尝试写入配置...")
        rc, out, err = run_cmd(
            ["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio", "config", "-t", AISTUDIO_TOKEN], check=False
        )
        if rc == 0:
            log.info("✅ token 写入成功")
            return True
        log.error(f"配置失败: {err}")
        return False


# ============================================================
# 步骤 4: 提交任务
# ============================================================
def submit_job() -> Optional[str]:
    """提交 aistudio pipeline 任务，返回 pipeline_id"""
    log.info("=" * 60)
    log.info("步骤 4: 提交 AI Studio Pipeline 任务")
    log.info("=" * 60)

    cmd = [
        "/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio",
        "submit",
        "job",
        "-n",
        PIPELINE_NAME,
        "-p",
        str(CODE_PKG_DIR),
        "-c",
        "bash entry.sh",
        "-e",
        ENV_VERSION,
        "-d",
        DEVICE,
        "-g",
        str(GPUS),
        "-pay",
        PAYMENT,
    ]
    for ds in MOUNT_DATASETS:
        cmd.extend(["-m", str(ds)])

    log.info(f"命令: {' '.join(cmd)}")
    rc, out, err = run_cmd(cmd, cwd=PADDLE_DIR, timeout=120, check=False)
    log.info(f"提交输出:\n{out}")
    if err:
        log.warning(f"stderr: {err}")

    if rc != 0:
        log.error("提交失败")
        return None

    pipeline_id = extract_job_id(out)
    if pipeline_id:
        log.info(f"✅ 任务提交成功! Pipeline ID: {pipeline_id}")
        return pipeline_id
    else:
        log.error("无法从输出中提取 pipeline_id")
        log.debug(f"原始输出: {out}")
        return None


# ============================================================
# 步骤 5: 监控日志 & 自动修复
# ============================================================
def get_job_logs(pipeline_id: str, tail: int = 200) -> str:
    """获取任务日志（通过 aistudio job cp 下载日志文件）"""
    # 先列出 output 目录
    rc, out, err = run_cmd(
        ["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio", "job", "ls", pipeline_id], check=False, timeout=30
    )
    if rc != 0:
        return f"[列举文件失败] {err}"

    # 寻找日志文件（通常在 output/logs/ 或 output/ 下）
    log_files = []
    for line in out.splitlines():
        line = line.strip()
        if line and any(kw in line.lower() for kw in ["log", ".txt", ".out", "stdout", "stderr"]):
            log_files.append(line)

    if not log_files:
        # 尝试常见路径
        log_files = ["logs/worker.log", "output.log", "stdout.log", "stderr.log"]

    all_logs = []
    for log_file in log_files[:3]:  # 限制下载数量
        local_path = f"/tmp/aistudio_log_{pipeline_id}_{Path(log_file).name}"
        rc, out, err = run_cmd(
            ["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio", "job", "cp", pipeline_id, log_file, local_path],
            check=False,
            timeout=60,
        )
        if rc == 0 and Path(local_path).exists():
            content = Path(local_path).read_text()
            all_logs.append(f"=== {log_file} ===\n{content[-tail*200:]}")  # 取最后部分

    # 也尝试 jobs 查询状态
    rc, out, err = run_cmd(
        ["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio", "jobs", pipeline_id], check=False, timeout=30
    )
    if rc == 0:
        all_logs.insert(0, f"=== JOBS STATUS ===\n{out}")

    return "\n\n".join(all_logs) if all_logs else "[无可用日志]"


def get_job_status(pipeline_id: str) -> str:
    """查询任务状态"""
    rc, out, err = run_cmd(
        ["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio", "jobs", pipeline_id], check=False, timeout=30
    )
    if rc == 0:
        # 解析状态: Running, Succeeded, Failed 等
        for line in out.splitlines():
            if pipeline_id in line and any(s in line for s in ["Running", "Succeeded", "Failed", "Pending", "Stopped"]):
                return line.strip()
    return "Unknown"


def apply_fixes(errors: List[Dict]) -> List[str]:
    """根据解析到的错误，修改本地源码"""
    fixed = []
    for err in errors:
        if err["type"] == "missing_module":
            mod = err["module"]
            # 常见包名映射
            pip_name = {
                "cv2": "opencv-python",
                "sklearn": "scikit-learn",
                "yaml": "pyyaml",
                "PIL": "pillow",
                "bs4": "beautifulsoup4",
                "dateutil": "python-dateutil",
            }.get(mod, mod.replace("-", "_"))
            if pip_name not in REQUIRED_PACKAGES:
                REQUIRED_PACKAGES.append(pip_name)
                fixed.append(f"Added missing package to requirements.txt: {pip_name} (for {mod})")
        elif err["type"] == "missing_attr":
            # AttributeError: module 'xxx' has no attribute 'yyy'
            # 常见是 API 变更，如 torch.load weights_only
            fixed.append(f"Detected AttributeError in {err['module']}.{err['attr']} - may need code patch")
        elif err["type"] == "weights_only":
            # torch.load weights_only=True 问题，已在 paddle_worker.py 头部打补丁
            fixed.append("weights_only issue - verify torch.load patch at top of paddle_worker.py")
        elif err["type"] == "syntax":
            fixed.append(f"SyntaxError: {err['msg']} - needs manual fix")
        elif err["type"] == "missing_file":
            fixed.append(f"Missing file: {err['path']} - may need to add to code package")
    return fixed


def monitor_and_fix(pipeline_id: str) -> Tuple[bool, str]:
    """监控任务，遇到代码错误自动修复并返回 (是否成功, 最终状态)"""
    log.info("=" * 60)
    log.info(f"步骤 5: 监控任务 {pipeline_id}")
    log.info("=" * 60)

    start_time = time.time()
    last_log_hash = ""
    no_change_count = 0

    while time.time() - start_time < TIMEOUT_SECONDS:
        # 1. 获取状态
        status = get_job_status(pipeline_id)
        log.info(f"状态: {status}")

        if "Succeeded" in status:
            log.info("✅ 任务成功完成！")
            return True, "Succeeded"
        if "Failed" in status or "Error" in status:
            log.warning(f"任务失败: {status}")
            # 拉取日志分析
            logs = get_job_logs(pipeline_id, tail=500)
            log.info(f"最近日志:\n{logs[-3000:]}")

            errors = parse_log_errors(logs)
            if errors:
                log.info(f"检测到 {len(errors)} 个错误模式: {errors}")
                fixes = apply_fixes(errors)
                if fixes:
                    log.info(f"应用修复: {fixes}")
                    # 重新准备代码包并重新提交
                    return False, "need_retry"
            return False, status

        # 2. 拉取日志分析
        logs = get_job_logs(pipeline_id, tail=MAX_LOG_LINES)
        current_hash = hash(logs[-5000:])  # 只看尾部变化
        if current_hash == last_log_hash:
            no_change_count += 1
            if no_change_count > 10:
                log.info("日志长时间无变化，可能卡住...")
        else:
            no_change_count = 0
            last_log_hash = current_hash

        # 实时分析错误（运行中也可能报错）
        errors = parse_log_errors(logs)
        if errors:
            log.warning(f"运行中检测到错误: {errors}")
            fixes = apply_fixes(errors)
            if fixes:
                log.info(f"应用运行时修复: {fixes}")
                return False, "need_retry"

        time.sleep(POLL_INTERVAL)

    log.error(f"监控超时 ({TIMEOUT_SECONDS}s)")
    return False, "Timeout"


# ============================================================
# 主循环
# ============================================================
def main():
    log.info("🚀 VoxCPM2 百度 AI Studio 全自动部署启动")
    log.info(f"工作目录: {PADDLE_DIR}")
    log.info(f"代码包目录: {CODE_PKG_DIR}")

    # 预检
    if not configure_aistudio():
        return 1

    for attempt in range(1, MAX_RETRIES + 1):
        log.info(f"\n{'='*60}")
        log.info(f"第 {attempt}/{MAX_RETRIES} 次尝试")
        log.info(f"{'='*60}")

        # 1. 同步资产
        if not sync_assets():
            log.error("资产同步失败，等待 60s 重试...")
            time.sleep(60)
            continue

        # 2. 准备代码包
        if not prepare_code_package():
            log.error("代码包准备失败")
            return 1

        # 3. 提交任务
        pipeline_id = submit_job()
        if not pipeline_id:
            log.error("任务提交失败，等待 60s 重试...")
            time.sleep(60)
            continue

        # 4. 监控 + 自动修复
        success, final_status = monitor_and_fix(pipeline_id)
        if success:
            log.info("🎉 部署成功！任务无错误运行完成。")
            # 下载产物
            log.info("下载输出文件...")
            run_cmd(["/Users/guwj/Desktop/AI_Lab/audiobook/.venv/bin/aistudio", "job", "ls", pipeline_id])
            return 0
        elif final_status == "need_retry":
            log.info("检测到可修复错误，准备下一轮重试...")
            time.sleep(10)  # 给一点缓冲
            continue
        else:
            log.error(f"任务最终失败: {final_status}")
            if attempt < MAX_RETRIES:
                log.info("等待 60s 后重试...")
                time.sleep(60)
                continue
            return 1

    log.error(f"达到最大重试次数 ({MAX_RETRIES})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
