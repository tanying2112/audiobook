#!/usr/bin/env python3
"""人工终审门 live E2E — MOCK_LLM + MOCK_TTS 全链路验证。

Phase 1（主链路）:
  注册/登录 → 建项目 → 上传 txt → 抽取章节 → auto-run(mode=review)
  → 门暂停(awaiting_review) → 汇总/路由预览 → 段落编辑(含 422 值域
  + P0 回归：非 14 枚举 emotion 必 422) → 逐章确认 → 整书放行
  → 合成+质检完成 → audio_segments 落库

Phase 2（取消路径）:
  再起 mode=review → 门暂停 → /cancel → run=cancelled 且 project
  状态回写（不留幽灵门）

关键机制：/start 的 HTTP 响应被 ISOTimestampMiddleware 缓冲、直到
后台 run 全程结束才 flush（Starlette BackgroundTasks 在中间件栈内
执行）——/start 一律后台线程发，主线程轮询 /status。

不依赖真实 LLM/TTS 引擎；Redis 用专用端口 6380，不碰本机其他会话。
E2E 专用 harness 关闭限流（RATE_LIMIT_ENABLED=false），消除轮询 429 噪声。
"""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
REDIS_PORT = 6380
SERVER_LOG = ROOT / "scratch" / "e2e_review_gate_server.log"

BOOK_TEXT = """第一章 山间清晨

清晨的薄雾还未散去，山间的小路湿漉漉的。
李明背起行囊，对母亲说：「娘，我出发了。」
母亲点点头，眼里有不舍，也有骄傲。

第二章 古镇奇遇

古镇的石板路被岁月磨得发亮。
张三拦住他的去路，问道：「这位兄弟，可否借一步说话？」
李明抱拳还礼：「兄台请讲。」
夜色渐深，客栈的灯火一盏盏熄灭。

第三章 归途

三年后，李明回到了故乡。
山还是那座山，水还是那道水。
他轻声自语：「我回来了。」
"""

RESULTS: list[tuple[str, bool, str]] = []
# /start 是异步发射的；响应（被中间件缓冲到 run 结束）结局记在这里。
start_outcomes: dict[str, dict] = {}


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, ok, detail))
    print(f"{'✅' if ok else '❌'} {label}" + (f" — {detail}" if detail else ""), flush=True)


def wait_http(url: str, timeout: float, label: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1.0)
    raise RuntimeError(f"timeout waiting for {label}")


def poll_status(client: httpx.Client, pid: int, timeout: float,
                want: set[str], label: str) -> dict:
    """轮询 auto-run status；打印状态/阶段变迁；命中 want 集合即返回。

    429（限流偶发）不算失败：退避后继续。
    """
    deadline = time.time() + timeout
    last = None
    n_429 = 0
    while time.time() < deadline:
        r = client.get(f"/api/projects/{pid}/auto-run/status")
        if r.status_code == 429:
            n_429 += 1
            if n_429 == 1:
                print(f"   [{label}] 429 rate-limited, backing off", flush=True)
            time.sleep(10.0)
            continue
        r.raise_for_status()
        s = r.json()
        cur = (s["status"], s.get("current_stage"))
        if cur != last:
            print(f"   [{label}] status={s['status']} stage={s.get('current_stage')}", flush=True)
            last = cur
        if s["status"] in want:
            return s
        if s["status"] in ("failed", "cancelled") and "failed" not in want:
            return s  # 提前失败也返回，由调用方断言
        time.sleep(3.0)
    raise RuntimeError(f"timeout waiting for {label} (wanted {want})")


def start_run_bg(tag: str, token: str, pid: int) -> threading.Thread:
    """后台线程发 mode=review 的 /start。

    响应要等整个 run（含门等待）结束才 flush——绝不能在主流程阻塞等它。
    """
    def _run():
        try:
            with httpx.Client(base_url=BASE, timeout=1800.0) as bg:
                bg.headers["Authorization"] = f"Bearer {token}"
                r = bg.post(f"/api/projects/{pid}/auto-run/start",
                            json={"mode": "review"})
                start_outcomes[tag] = {"code": r.status_code}
        except Exception as e:  # noqa: BLE001
            start_outcomes[tag] = {"error": repr(e)}
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def main() -> int:
    print("== 人工终审门 live E2E ==", flush=True)
    log_f = open(SERVER_LOG, "wb")

    redis_proc = subprocess.Popen(
        ["redis-server", "--port", str(REDIS_PORT), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 应用的本地默认库是 src/data/audiobook.db（database_async.py 的 parent.parent
    # 解析到 src/），已 upgrade head；显式钉住 DATABASE_URL 保证 app/断言一致。
    db_path = ROOT / "src" / "data" / "audiobook.db"
    env = os.environ.copy()
    env.update({
        "MOCK_LLM": "true",
        "MOCK_TTS": "true",
        "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}/0",
        "AUTH_REGISTRATION_MODE": "open",
        "DATABASE_URL": f"sqlite:///{db_path}",
        # E2E harness 专用：关掉限流，轮询不再 429（生产保护与本验证无关）
        "RATE_LIMIT_ENABLED": "false",
    })
    server = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "uvicorn",
         "src.audiobook_studio.main:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=log_f, stderr=subprocess.STDOUT,
    )
    try:
        wait_http(f"{BASE}/health", 90.0, "server boot")
        print("server up", flush=True)

        user = f"e2e_{uuid.uuid4().hex[:8]}"
        with httpx.Client(base_url=BASE, timeout=120.0) as c:
            # ── 注册 + 登录 ──
            r = c.post("/api/auth/register", json={
                "username": user, "email": f"{user}@example.com",
                "password": "E2eTest#2026"})
            check("register 201", r.status_code == 201, f"code={r.status_code}")
            r = c.post("/api/auth/login", data={
                "username": user, "password": "E2eTest#2026"})
            r.raise_for_status()
            token = r.json()["access_token"]
            c.headers["Authorization"] = f"Bearer {token}"
            check("login ok", True)

            # ── 建项目 + 上传 ──
            r = c.post("/api/projects/", json={"title": "E2E 终审门验证", "language": "zh"})
            if r.status_code >= 500:
                print(f"project create failed: {r.status_code}\n{r.text[:500]}")
                raise RuntimeError("project create 5xx")
            pid = r.json()["id"]
            print(f"project_id={pid}", flush=True)
            r = c.post(f"/api/projects/{pid}/upload", files={
                "file": ("book.txt", BOOK_TEXT.encode("utf-8"), "text/plain")})
            r.raise_for_status()
            job_id = r.json().get("extraction_job_id")
            print(f"uploaded, job={job_id}", flush=True)

            # 等抽取任务真正完成（MOCK_LLM 下 extract 返回固定模拟文本 →
            # 章节数为 1 是预期行为，不再依赖上传内容分章）
            js = {"status": "pending"}
            deadline = time.time() + 180.0
            while time.time() < deadline:
                r = c.get(f"/api/projects/{pid}/extraction/{job_id}/status")
                r.raise_for_status()
                js = r.json()
                if js["status"] in ("completed", "failed"):
                    break
                time.sleep(1.5)
            check("extraction job completed", js["status"] == "completed",
                  f"status={js['status']} err={js.get('error')}")

            r = c.get(f"/api/projects/{pid}/chapters")
            r.raise_for_status()
            chapters = r.json()
            check("chapters persisted", len(chapters) >= 1,
                  f"n={len(chapters)} (mock extract → 1)")
            cid = chapters[0]["id"]

            # ── Phase 1: mode=review 启动（后台线程），门应暂停 ──
            t1 = start_run_bg("phase1", token, pid)
            s = poll_status(c, pid, 420.0, {"awaiting_review"}, "phase1-gate")
            check("gate pauses at awaiting_review", s["status"] == "awaiting_review",
                  f"got {s['status']} err={s.get('error_message')}")
            check("status.can_review true", s.get("can_review") is True)

            # ── 门内交互 ──
            r = c.get(f"/api/projects/{pid}/review-gate")
            r.raise_for_status()
            summ = r.json()
            check("summary: pending == total, none approved",
                  summ["pending_chapters"] == summ["total_chapters"]
                  and summ["approved_chapters"] == 0
                  and not summ["all_approved"],
                  f"total={summ['total_chapters']} pending={summ['pending_chapters']}")
            check("summary.run_status == awaiting_review",
                  summ["run_status"] == "awaiting_review", summ["run_status"])

            r = c.get(f"/api/projects/{pid}/review-gate/chapters/{cid}/routing-preview")
            r.raise_for_status()
            prev = r.json()
            synth_paras = [p for p in prev["previews"] if not p["skipped"]]
            check("routing preview has a synthesizable paragraph",
                  len(synth_paras) >= 1, f"synth={prev['synthesized_count']}")
            para = synth_paras[0]

            # 段落编辑：润色 + 情绪 + 人工引擎覆盖（emotion 用 14 枚举内的
            # "tender"——mock annotate 落的是 "neutral"，保证 changes_made 含它）
            r = c.patch(
                f"/api/projects/{pid}/review-gate/chapters/{cid}/paragraphs/{para['paragraph_id']}",
                json={"edited_text": "用于测试的模拟提取文本。终审润色：语调更沉稳、停顿更从容。",
                      "emotion": "tender", "emotion_intensity": 0.8,
                      "manual_engine": "edge", "note": "e2e 终审编辑"})
            r.raise_for_status()
            patch = r.json()
            check("paragraph PATCH applies edits", len(patch["changes_made"]) >= 2,
                  f"changes={patch['changes_made']}")
            check("PATCH response carries updated paragraph",
                  patch["paragraph"]["emotion"] == "tender"
                  and patch["paragraph"]["manual_engine"] == "edge")
            check("PATCH wrote TTSEdit audit",
                  patch.get("tts_edit_version") is not None,
                  f"version={patch.get('tts_edit_version')}")

            # 预览应反映人工覆盖（engine=edge）——P0 修复后路由决策不再炸
            r = c.get(f"/api/projects/{pid}/review-gate/chapters/{cid}/routing-preview")
            r.raise_for_status()
            pv = {p["paragraph_id"]: p for p in r.json()["previews"]}
            check("routing preview honors manual_engine=edge",
                  pv[para["paragraph_id"]]["engine_choice"] == "edge",
                  str(pv[para["paragraph_id"]]["engine_choice"]))

            # 值域越界 → 422
            r = c.patch(
                f"/api/projects/{pid}/review-gate/chapters/{cid}/paragraphs/{para['paragraph_id']}",
                json={"speech_rate": 9.9})
            check("out-of-range speech_rate rejected 422", r.status_code == 422,
                  f"code={r.status_code}")

            # P0 回归（live E2E 实证的漏洞）：非 14 枚举 emotion 必须在
            # 保存入口挡下（422），绝不能落库后到合成期才炸。
            r = c.patch(
                f"/api/projects/{pid}/review-gate/chapters/{cid}/paragraphs/{para['paragraph_id']}",
                json={"emotion": "joy"})
            check("non-canonical emotion rejected 422 (P0 fix)",
                  r.status_code == 422 and "joy" in r.text,
                  f"code={r.status_code}")

            # 逐章确认
            r = c.post(f"/api/projects/{pid}/review-gate/chapters/{cid}/approve")
            r.raise_for_status()
            check("chapter approve reflected", r.json()["approved_chapters"] == 1,
                  f"approved={r.json()['approved_chapters']}")

            # 整书放行
            r = c.post(f"/api/projects/{pid}/review-gate/confirm")
            r.raise_for_status()
            conf = r.json()
            check("confirm releases live gate", conf["released"] is True,
                  conf.get("message", ""))

            s = poll_status(c, pid, 900.0, {"completed", "failed", "cancelled"}, "phase1-run")
            stages = s.get("completed_stages") or []
            check("pipeline completed", s["status"] == "completed",
                  f"status={s['status']} stage={s.get('current_stage')} "
                  f"err={s.get('error_message')}")
            check("synthesize + quality done",
                  "synthesize" in stages and "quality" in stages, str(stages))

            t1.join(timeout=120)
            so = start_outcomes.get("phase1", {})
            check("phase1 /start response eventually returns 200",
                  so.get("code") == 200, str(so))

            # ── Phase 2: 再起 review run（/start 重置审核纪元）→ 门内 cancel ──
            t2 = start_run_bg("phase2", token, pid)
            s = poll_status(c, pid, 420.0, {"awaiting_review"}, "phase2-gate")
            check("phase2 gate re-enters (epoch reset by /start)",
                  s["status"] == "awaiting_review", s["status"])
            check("status.can_review true again", s.get("can_review") is True)

            r = c.post(f"/api/projects/{pid}/auto-run/cancel")
            check("cancel during gate accepted",
                  r.status_code == 200 and r.json()["status"] == "cancelled",
                  f"code={r.status_code}")
            s = poll_status(c, pid, 60.0, {"cancelled"}, "phase2-cancel")
            check("run reaches cancelled", s["status"] == "cancelled", s["status"])

            # t2.join = run 函数已返回 → 门循环的 cancel 路径已执行
            # _sync_project_progress(..., "cancelled")。在 join 前查
            # project.status 会与门的 ~2s tick 竞态（/cancel 端点只改内存
            # 状态，行同步在门循环里做）。
            t2.join(timeout=120)
            so = start_outcomes.get("phase2", {})
            check("phase2 /start response eventually returns 200",
                  so.get("code") == 200, str(so))

            r = c.get(f"/api/projects/{pid}")
            r.raise_for_status()
            proj_status = r.json().get("status")
            check("project status synced off awaiting_review",
                  proj_status != "awaiting_review", f"project.status={proj_status}")

        # ── 收尾：合成产物落库断言（服务器停止后读 SQLite）──
        print("stopping server...", flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
        redis_proc.terminate()
        redis_proc.wait(timeout=10)
        log_f.close()

    # 断言用与服务端相同的库（见 main() 中 DATABASE_URL 钉定）
    conn = sqlite3.connect(ROOT / "src" / "data" / "audiobook.db")
    n_seg = conn.execute(
        "SELECT COUNT(*) FROM audio_segments WHERE project_id=?", (pid,)).fetchone()[0]
    n_pending = conn.execute(
        "SELECT COUNT(*) FROM chapters WHERE project_id=? AND review_status='pending_review'",
        (pid,)).fetchone()[0]
    n_joy = conn.execute(
        "SELECT COUNT(*) FROM paragraphs p JOIN chapters c ON p.chapter_id=c.id "
        "WHERE c.project_id=? AND p.emotion NOT IN "
        "('neutral','happy','sad','angry','fearful','surprised','disgusted',"
        "'tense','tender','contemplative','whisper','cold_laugh','sigh','sarcastic')",
        (pid,)).fetchone()[0]
    n_edited = conn.execute(
        "SELECT COUNT(*) FROM paragraphs p JOIN chapters c ON p.chapter_id=c.id "
        "WHERE c.project_id=? AND p.edited_text LIKE '%终审润色%'",
        (pid,)).fetchone()[0]
    conn.close()
    check("audio segments persisted", n_seg >= 1, f"segments={n_seg}")
    # phase-2 /start 重置审核纪元（approved→NULL），门把 NULL 置 pending_review，
    # 随后 run 被取消 → 章节按设计停在 pending_review（绝不该是 approved）
    check("chapters left pending_review after cancelled gate", n_pending >= 1,
          f"pending={n_pending}")
    check("customer edit survived to DB", n_edited >= 1, f"edited={n_edited}")
    check("no non-canonical emotion in DB (P0 fix held)", n_joy == 0, f"bad={n_joy}")

    failed = [x for x in RESULTS if not x[1]]
    print(f"\n== {'ALL PASS' if not failed else 'FAILURES'}: "
          f"{len(RESULTS) - len(failed)}/{len(RESULTS)} ==", flush=True)
    for label, ok, detail in failed:
        print(f"  ❌ {label} — {detail}")
    if failed:
        print(f"\nserver log tail ({SERVER_LOG}):")
        os.system(f"tail -40 '{SERVER_LOG}'")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
