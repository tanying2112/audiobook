"""轮 1 A/B 盲评：live 基线 v1（部署前内容已升级，A 按版本号=旧 live 语义运行 v1 文件槽）。

按 _handle_new_analysis 语义：A=old_version(v1 槽), B=v43。此处 v1 槽已被部署覆盖 ——
为诚实对比，A 臂用 git HEAD 的 v1.j2 原始内容（部署前 live 基线）。
"""
import logging, os, sys, time
sys.path.insert(0, "src")
os.environ.setdefault("SELF_ITERATION_MOCK", "false")
os.environ.setdefault("FCC_LOCAL_API_KEY", "freecc")
os.environ.setdefault("DATABASE_URL", "sqlite:///./src/data/audiobook.db")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "LiteLLM", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from audiobook_studio.feedback.integration import SelfIterationLoop

engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})
factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 恢复旧 live 基线到 v0.j2（部署前的 v1 原始内容来自 git HEAD），A 臂跑 v0
import subprocess
old_v1 = subprocess.run(["git", "show", "HEAD:prompts/edit_for_tts/v1.j2"], capture_output=True, text=True, cwd=".")
if old_v1.returncode == 0:
    Path("prompts/edit_for_tts/v0.j2").write_text(old_v1.stdout, encoding="utf-8")
    print("[baseline] 已把 git HEAD 的部署前 v1.j2 落到 v0.j2 作为 A 臂基线")

loop = SelfIterationLoop(db_session_factory=factory, project_id=1,
                         enable_auto_pr=False, enable_auto_merge=False, auto_deploy=True)
t0 = time.time()
old_v = 0 if old_v1.returncode == 0 else 1
ab = loop._run_ab_test_for_stage("edit_for_tts", old_v, 43)
print(f"[A/B] samples={ab.num_samples} A={ab.avg_score_a:.3f} B={ab.avg_score_b:.3f} "
      f"improvement={ab.improvement_pct:+.1f}% significant={ab.is_significant} p={ab.p_value:.4f} "
      f"a_wins={ab.a_wins} b_wins={ab.b_wins} ties={ab.ties}")
print(f"[A/B] recommendation: {ab.recommendation}")
print(f"elapsed {time.time()-t0:.0f}s")
