#!/usr/bin/env python3
"""接续活体门流程（项目 24 已 awaiting_review）：

phase1 完成：汇总/预览/编辑/422/逐章确认/confirm 放行 → 轮询到 completed
phase2 取消：再起 review run（checkpoint 跳过）→ 门内 /cancel → cancelled
             且 project.status 不滞留 awaiting_review

关键认识：/start 的 HTTP 响应被 ISOTimestampMiddleware 缓冲、直到后台
run 全程结束才 flush（Starlette BackgroundTasks 在中间件栈内执行）——
所以 /start 必须后台线程发、主线程轮询 /status。
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8123"
STATE = json.loads((ROOT / "scratch" / "e2e_state.json").read_text())
PID = STATE["pid"]
TOKEN = STATE["token"]

RESULTS: list[tuple[str, bool, str]] = []
start_outcomes: dict[str, dict] = {}


def check(label, ok, detail=""):
    RESULTS.append((label, ok, detail))
    print(f"{'✅' if ok else '❌'} {label}" + (f" — {detail}" if detail else ""), flush=True)


def poll_status(c, want, label, timeout):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = c.get(f"/api/projects/{PID}/auto-run/status")
        r.raise_for_status()
        s = r.json()
        cur = (s["status"], s.get("current_stage"))
        if cur != last:
            print(f"   [{label}] status={s['status']} stage={s.get('current_stage')}", flush=True)
            last = cur
        if s["status"] in want or s["status"] in ("failed", "cancelled"):
            return s
        time.sleep(2.0)
    raise RuntimeError(f"timeout waiting for {label}")


def start_run_bg(tag):
    """后台线程发 /start（响应要到 run 结束才回来，不能阻塞主流程）。"""
    def _run():
        try:
            with httpx.Client(base_url=BASE, timeout=1800.0) as c:
                c.headers["Authorization"] = f"Bearer {TOKEN}"
                r = c.post(f"/api/projects/{PID}/auto-run/start", json={"mode": "review"})
                start_outcomes[tag] = {"code": r.status_code, "elapsed": "n/a"}
        except Exception as e:  # noqa: BLE001
            start_outcomes[tag] = {"error": repr(e)}
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def main():
    with httpx.Client(base_url=BASE, timeout=120.0) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"

        # ── 门内状态 ──
        r = c.get(f"/api/projects/{PID}/review-gate")
        r.raise_for_status()
        summ = r.json()
        check("summary pending==total, none approved",
              summ["pending_chapters"] == summ["total_chapters"] == 1
              and summ["approved_chapters"] == 0 and not summ["all_approved"],
              f"total={summ['total_chapters']} pending={summ['pending_chapters']}")
        check("summary.run_status == awaiting_review",
              summ["run_status"] == "awaiting_review", summ["run_status"])
        cid = summ["chapters"][0]["chapter_id"]

        r = c.get(f"/api/projects/{PID}/review-gate/chapters/{cid}/routing-preview")
        r.raise_for_status()
        prev = r.json()
        synth = [p for p in prev["previews"] if not p["skipped"]]
        check("routing preview has synthesizable paragraphs", len(synth) >= 2,
              f"synth={prev['synthesized_count']} skipped={prev['skipped_count']}")
        para_id = synth[0]["paragraph_id"]

        # ── 段落编辑 ──
        r = c.patch(
            f"/api/projects/{PID}/review-gate/chapters/{cid}/paragraphs/{para_id}",
            json={"edited_text": "清晨的薄雾尚未散尽，山径湿润，露珠垂叶。（终审润色）",
                  "emotion": "joy", "emotion_intensity": 0.8,
                  "manual_engine": "edge", "note": "e2e 终审编辑"})
        r.raise_for_status()
        patch = r.json()
        check("paragraph PATCH applies edits", len(patch["changes_made"]) >= 2,
              f"changes={patch['changes_made']}")
        check("PATCH returns updated paragraph",
              patch["paragraph"]["emotion"] == "joy"
              and patch["paragraph"]["manual_engine"] == "edge")
        check("PATCH wrote TTSEdit audit",
              patch.get("tts_edit_version") is not None,
              f"version={patch.get('tts_edit_version')}")

        r = c.get(f"/api/projects/{PID}/review-gate/chapters/{cid}/routing-preview")
        pv = {p["paragraph_id"]: p for p in r.json()["previews"]}
        check("routing preview honors manual_engine=edge",
              pv[para_id]["engine_choice"] == "edge", str(pv[para_id]["engine_choice"]))

        r = c.patch(
            f"/api/projects/{PID}/review-gate/chapters/{cid}/paragraphs/{para_id}",
            json={"speech_rate": 9.9})
        check("out-of-range speech_rate rejected 422", r.status_code == 422,
              f"code={r.status_code}")

        # ── 逐章确认 + 整书放行 ──
        r = c.post(f"/api/projects/{PID}/review-gate/chapters/{cid}/approve")
        r.raise_for_status()
        check("chapter approve reflected", r.json()["approved_chapters"] == 1,
              f"approved={r.json()['approved_chapters']}")

        r = c.post(f"/api/projects/{PID}/review-gate/confirm")
        r.raise_for_status()
        conf = r.json()
        check("confirm releases live gate", conf["released"] is True, conf.get("message", ""))

        s = poll_status(c, {"completed"}, "phase1-run", 900.0)
        stages = s.get("completed_stages") or []
        check("pipeline completed", s["status"] == "completed",
              f"status={s['status']} err={s.get('error_message')}")
        check("synthesize + quality done",
              "synthesize" in stages and "quality" in stages, str(stages))

        # ── phase 2: 新纪元 + 门内取消 ──
        t2 = start_run_bg("phase2")
        s = poll_status(c, {"awaiting_review"}, "phase2-gate", 300.0)
        check("phase2 gate re-enters (epoch reset by /start)",
              s["status"] == "awaiting_review", s["status"])
        check("status.can_review true again", s.get("can_review") is True)

        r = c.post(f"/api/projects/{PID}/auto-run/cancel")
        check("cancel during gate accepted",
              r.status_code == 200 and r.json()["status"] == "cancelled",
              f"code={r.status_code}")
        s = poll_status(c, {"cancelled"}, "phase2-cancel", 60.0)
        check("run reaches cancelled", s["status"] == "cancelled", s["status"])

        r = c.get(f"/api/projects/{PID}")
        r.raise_for_status()
        ps = r.json().get("status")
        check("project status synced off awaiting_review",
              ps != "awaiting_review", f"project.status={ps}")

        t2.join(timeout=120)
        so = start_outcomes.get("phase2", {})
        check("phase2 /start response eventually returns 200",
              so.get("code") == 200, str(so))

    conn = sqlite3.connect(ROOT / "src" / "data" / "audiobook.db")
    n_seg = conn.execute(
        "SELECT COUNT(*) FROM audio_segments WHERE project_id=?", (PID,)).fetchone()[0]
    n_ap = conn.execute(
        "SELECT COUNT(*) FROM chapters WHERE project_id=? AND review_status='approved'",
        (PID,)).fetchone()[0]
    conn.close()
    check("audio segments persisted", n_seg >= 2, f"segments={n_seg}")
    check("chapters left approved after run", n_ap == 1, f"approved={n_ap}")

    failed = [x for x in RESULTS if not x[1]]
    print(f"\n== {'ALL PASS' if not failed else 'FAILURES'}: "
          f"{len(RESULTS) - len(failed)}/{len(RESULTS)} ==", flush=True)
    for label, ok, detail in failed:
        print(f"  ❌ {label} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
