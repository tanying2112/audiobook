def _ensure_model_downloaded(model_dir: str, repo_id: str) -> None:
    """Rust 引擎 + 双端点回退 + 双鉴权策略 (Token / 匿名)"""
    import subprocess
    import shutil
    import time

    # ===== 1. 尝试 HF API 下载（双端点 + 双鉴权）=====
    endpoints = [
        ("https://hf-mirror.com", "国内镜像"),
        ("https://huggingface.co", "官方源"),
    ]

    # 清洗 Token
    raw = os.getenv("HF_TOKEN", "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    token = raw or None

    endpoints = [
        ("https://hf-mirror.com", "国内镜像"),
        ("https://huggingface.co", "官方源"),
    ]

    api_failed = False
    for ep_url, ep_name in endpoints:
        os.environ["HF_ENDPOINT"] = ep_url
        try:
            import huggingface_hub.constants as _hfc
            _hfc.HF_ENDPOINT = ep_url
            _hfc.HF_HUB_DISABLE_SSL_VERIFICATION = True
        except Exception:
            pass

        _log(f"🔄 尝试镜像: {ep_name} ({ep_url})")

        # 双鉴权策略：先 Token，再匿名
        for tok in (token, None):
            clean_tok = tok if tok else None
            strategy = "带Token" if tok else "匿名"
            _log(f"🔑 策略: {strategy}")

            for attempt in range(1, 4):
                try:
                    _log(f"📥 {ep_name}/{strategy} 下载尝试 {attempt}/3...")
                    snapshot_download(
                        repo_id=repo_id,
                        local_dir=model_dir,
                        token=tok,
                        ignore_patterns=["*.msgpack", "*.h5", "*.ot"],
                        max_workers=2,
                        tqdm_class=None,
                    )
                    _log(f"✅ 下载成功！来源: {ep_name} / 策略: {strategy}")
                    return
                except Exception as e:
                    _log(f"⚠️ 尝试 {attempt}/3 失败: {str(e)[:200]}")
                    time.sleep(2 ** attempt)

            # 该镜像源所有尝试均失败
            _log(f"   ❌ 端点 {ep_name} 多次重试均失败，切换下一个端点...")

    # ===== 所有 HF API 失败，启用 Git 克隆终极兜底 =====
    _log("🛡️ 所有 HF API 失败，启动终极兜底：Git 克隆...")
    try:
        import subprocess
        import shutil
        mirror_url = f"{endpoint}/{repo_id}"
        _log(f"🔧 终极兜底：Git 克隆 {mirror_url} -> {model_dir} (超时 15 分钟，跳过 LFS 文件)")

        # 确保目标目录完全不存在（Git clone 要求目标不存在）
        if os.path.exists(model_dir):
            _log(f"⚠️ 目录已存在，正在清理: {model_dir}")
            def remove_readonly(func, path, excinfo):
                os.chmod(path, 0o777)
                func(path)
            for _ in range(3):
                try:
                    shutil.rmtree(model_dir, onerror=remove_readonly)
                    break
                except Exception:
                    time.sleep(0.5)
            if os.path.exists(model_dir):
                raise RuntimeError(f"无法删除目标目录: {model_dir}")

            # Git clone 会自动创建目录，不需要预先创建
            _log(f"🔧 终极兜底：Git 克隆 {mirror_url} -> {model_dir} (超时 15 分钟，跳过 LFS 文件)")

            # 设置环境变量跳过 LFS 文件，只克隆元数据和配置
            env = os.environ.copy()
            env["GIT_LFS_SKIP_SMUDGE"] = "1"
            env["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
            env["HF_ENDPOINT"] = endpoint

            subprocess.run([
                "git", "clone",
                "--depth", "1",
                "--branch", "main",
                mirror_url,
                model_dir
            ], check=True, capture_output=True, text=True, timeout=900, env=env)
            _log(f"✅ Git 克隆成功！模型元数据已就绪: {model_dir}")
            return

    except subprocess.TimeoutExpired:
        _log("❌ Git 克隆超时 (15 分钟)")
    except subprocess.CalledProcessError as e:
        _log(f"❌ Git 克隆失败: {e.stderr[:300] if e.stderr else str(e)}")
    except Exception as e:
        _log(f"❌ Git 克隆异常: {str(e)[:300]}")

    raise RuntimeError("所有镜像/鉴权/Git 克隆均失败，模型下载彻底失败")