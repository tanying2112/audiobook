"""30 轮自主迭代马拉松驱动器（轮 1 已完成并部署 v43，本驱动跑轮 2-30）。

每轮:
  1. 注入 12 条人工修正反馈（模式燃料轮转：优先未烘焙的 edit 可映射模式；
     用尽后转「真实混合模式」——多样化 TTS 修稿理由，靠 LLM 分析器产指令）
  2. loop.auto_processor.trigger_now()   → 真实 LLM 差异分析
  3. loop._handle_new_analysis()         → 升级 → canary → 4 门 → 部署 → A/B
  4. 记录轮结果到 scratch/marathon_log.jsonl
每 5 轮: harness 沙箱迭代 tick（edit 阶段，双评判器，沙箱内晋升/部署）。

注意: 驱动期间禁止运行 pytest —— reset_storage() 会清空 data/golden/harness
与 prompts/harness（harness 测试夹具副作用）。
"""
import json
import logging
import os
import random
import sys
import time
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("SELF_ITERATION_MOCK", "false")
os.environ.setdefault("FCC_LOCAL_API_KEY", "freecc")
os.environ.setdefault("DATABASE_URL", "sqlite:///./src/data/audiobook.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "LiteLLM", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

START_ROUND = int(os.environ.get("START_ROUND", "2"))
END_ROUND = int(os.environ.get("END_ROUND", "30"))
# 复跑标记：RUN_TAG=run-c 的记录 phase 带 run-c 前缀，与 run-b 在 jsonl 中可辨
RUN_TAG = os.environ.get("RUN_TAG", "run-b")
LOG_PATH = Path("scratch/marathon_log.jsonl")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})
factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── 模式燃料库: (pattern → 修正理由模板) ────────────────────────────────────
PATTERN_RATIONALE = {
    "emotion_too_mild": "机器编辑的情感表达太淡：这段是冲突爆发情节，人物语气应激烈，"
                        "情感描述词应选'怒吼''颤抖'级别并提高情感强度，而不是平静叙述。",
    "emotion_too_strong": "机器编辑的情感强度过高：日常闲聊场景被处理成大喜大悲，"
                          "情感描述过度夸张，应克制为'平静''温和'的适度表达。",
    "speaker_wrong": "机器编辑稿对话归属识别错误：说话人标注错了，按对话引导词'说道'"
                     "主语应是前一句的说话人，需要修正说话人识别。",
    "sfx_missing": "机器编辑稿缺少场景音效标记：开门、脚步、风雨等场景应使用 [sfx:类型] 标记，"
                   "当前输出没有任何音效标记，沉浸感不足，需要补充场景音效。",
    "text_colloquial": "机器编辑稿过于书面化，需要口语化：'然而''因此''是否'等书面连词"
                       "应转换为'但是''所以''是不是'等自然口语表达。",
    "text_formal": "机器编辑稿过于口语随意：叙述部分'嘛''呗''啦'语气词太多，"
                   "对话外叙述应使用标准书面语，减少语气词的过度使用。",
    "speech_rate_issue": "机器编辑稿语速控制异常：长句未拆分导致朗读过快吞字，"
                         "应按 200-240 字/分钟的自然语速控制句子长度与停顿分布。",
}

# ── 真实混合模式燃料库: (修改理由, 机器稿, 人工修正稿) ──────────────────────
# 具体文本差异（而非空泛理由）驱动 LLM 分析器产出可烘焙指令；旧版仅理由+样板文本，
# 12 条 diff 全同 → 指令全同 → 烘焙去重后 21 轮空转（run A 教训）。
# 每轮前 3 条记录携带 cursor 轮转的 3 个「新场景类」（batch_upgrade 指令上限 [:3]
# 按记录序取前 3），其余 9 条为背景轮转。
MIXED_SCENARIOS = [
    ("数字与单位朗读不一致：阿拉伯数字与单位符号直接合成会读错，需要归一化为中文读法。",
     "第{i}段：他在2024年买了3.5kg苹果，又跑了100m。",
     "第{i}段：他在二零二四年买了三点五公斤苹果，又跑了一百米。"),
    ("中英混排处理不当：机器稿把英文术语删除造成信息损失，英文应保留原文并加空格。",
     "第{i}段：他们用英文框架训练了一个新模型，效果不错。",
     "第{i}段：他们用 TensorFlow 训练了一个新模型，效果不错。"),
    ("多音字未消歧：'的/得/长'等多音字按常用音读错，需要按语义标注拼音。",
     "第{i}段：他说地很对，这件事的影响很长。",
     "第{i}段：他说得(de)很对，这件事的影响很长(cháng)。"),
    ("括注残留：舞台指示括注会被 TTS 朗读出来，需要清理或转为语气标记。",
     "第{i}段：他推门而入（笑），把伞放在门边。",
     "第{i}段：他推门而入，把伞放在门边。"),
    ("拟声词被改写：拟声词应保留原样增强听感画面感。",
     "第{i}段：雨下得很大，雷声也很响。",
     "第{i}段：雨哗啦啦地下着，雷声轰隆隆地滚过。"),
    ("章节标题与正文连排：标题后应有较长停顿并放慢语速。",
     "第{i}段：第三章 风起云涌 李明推开门走进书斋。",
     "第{i}段：第三章 风起云涌 [pause_before_ms=800] 李明推开门走进书斋。"),
    ("对话与旁白无区分：对话句应加说话人标记区分叙述者。",
     "第{i}段：李明说今天不去了，明天再谈。",
     "第{i}段：李明说：[speaker=李明]「今天不去了，明天再谈。」"),
    ("儿化音被规范改写：口语儿化应保留自然写法。",
     "第{i}段：他在这个地方等了很久。",
     "第{i}段：他在这儿等了很久。"),
    ("诗词引文被改写：诗句应保留原样并整体放慢、前后加停顿。",
     "第{i}段：他想起一句古诗，心中满是乡愁。",
     "第{i}段：他想起一句古诗——[slow]「床前明月光，疑是地上霜。」[normal]，心中满是乡愁。"),
    ("语气词堆叠：口头禅重复过多应精简保留一两处。",
     "第{i}段：嗯那个，这个我觉得吧，应该还行吧大概。",
     "第{i}段：我觉得应该还行。"),
    ("专有名词特殊读音：人名地名未标注读音会读错。",
     "第{i}段：他长期研究龟兹与单于的历史。",
     "第{i}段：他长期研究龟兹(qiūcí)与单于(chányú)的历史。"),
    ("破折号省略号滥用：停顿标记泛滥，应仅在语义转折处保留。",
     "第{i}段：他——想了想……然后——就走了……",
     "第{i}段：他想了想，然后就走了。"),
    ("长句未拆分：朗读过快吞字，应按 200-240 字/分钟控制句长。",
     "第{i}段：在那个飘着细雨的清晨他背着褪色的行囊穿过熙攘的集市走向站台远处传来汽笛声。",
     "第{i}段：在那个飘着细雨的清晨，他背着褪色的行囊，穿过熙攘的集市走向站台。远处传来汽笛声。"),
    ("的地得用法错误：书面错误会误导读音判断，需按语法修正。",
     "第{i}段：他高兴的说，这件事办的地地道道。",
     "第{i}段：他高兴地说，这件事办得地道。"),
    ("百分数直接写符号：合成易读错，应改写为「百分之X」。",
     "第{i}段：销量增长了15%，利润提高了8%。",
     "第{i}段：销量增长了百分之十五，利润提高了百分之八。"),
    ("电话号码按数量词连读：应逐位转中文。",
     "第{i}段：有急事请拨打13800138000。",
     "第{i}段：有急事请拨打一三八零零一三八零零零。"),
    ("时间写法生硬：应转为完整中文读法。",
     "第{i}段：会议定在10月1日上午9:30。",
     "第{i}段：会议定在十月一日上午九点三十分。"),
    ("门牌地址按数字读：应按习惯读法（X号楼X单元XXX室）。",
     "第{i}段：他住在3号楼2单元501室。",
     "第{i}段：他住在三号楼二单元五零一室。"),
    ("列表序号「1. 2. 3.」合成读错：应改为「第一、第二、第三」。",
     "第{i}段：注意事项：1. 系好安全带 2. 关闭手机 3. 保持安静。",
     "第{i}段：注意事项：第一，系好安全带；第二，关闭手机；第三，保持安静。"),
    ("引语归属后置：先闻其声不知其人，应归属前置。",
     "第{i}段：「我不去了。」他低声说。",
     "第{i}段：他低声说：「我不去了。」"),
    ("关键词无重音标记：强调信息被平淡带过，应加 emphasis 标记。",
     "第{i}段：这是最后一次机会，别再错过。",
     "第{i}段：这是<emphasis>最后</emphasis>一次机会，别再错过。"),
    ("场景切换无停顿：两幕连读突兀，应加 500ms 级停顿。",
     "第{i}段：会议结束了。当晚他坐上了北行的列车。",
     "第{i}段：会议结束了。[pause_before_ms=600]当晚他坐上了北行的列车。"),
    ("感叹句无语气标记：感叹强度不足，应加语气标记与叹号。",
     "第{i}段：真是太好了，大家都激动起来。",
     "第{i}段：[tone=excited]真是太好了！大家都激动起来。"),
    ("疑问句以句号结尾：合成语调不上扬，应改问号触发疑问语调。",
     "第{i}段：你明天会来吗，他问。",
     "第{i}段：你明天会来吗？他问。"),
    ("英文缩写按单词读会错：缩写应逐字母拼读。",
     "第{i}段：这台设备的CPU和GPU都需要升级。",
     "第{i}段：这台设备的C-P-U和G-P-U都需要升级。"),
    ("单位符号直接朗读失败：应转为中文单位名。",
     "第{i}段：今日气温28℃，风速12km/h。",
     "第{i}段：今日气温二十八摄氏度，风速十二公里每小时。"),
    ("书名未加书名号：合成连读边界不清，应加书名号。",
     "第{i}段：他每晚都读红楼梦，一直读到深夜。",
     "第{i}段：他每晚都读《红楼梦》，一直读到深夜。"),
    ("外文人名未译：中文有声书应译为中文译名。",
     "第{i}段：他给David发了邮件，约好下周见。",
     "第{i}段：他给大卫发了邮件，约好下周见。"),
    ("重复修饰词堆叠：听感拖沓，应精简为一处。",
     "第{i}段：这是一个非常非常重要的决定。",
     "第{i}段：这是一个非常重要的决定。"),
    ("快节奏播报段无语速标记：应加 rate 标记匹配内容节奏。",
     "第{i}段：以下是今日赛事比分快讯。",
     "第{i}段：[rate=fast]以下是今日赛事比分快讯。[/rate]"),
    ("呼语与正文连排：呼语后应有停顿。",
     "第{i}段：各位听众下面请听详细报道。",
     "第{i}段：各位听众，[pause_before_ms=400]下面请听详细报道。"),
    ("括号补注被朗读出来：补注信息应改写为正文或删除。",
     "第{i}段：该馆共有藏品186万余件（截至2024年）。",
     "第{i}段：该馆共有藏品一百八十六万余件，数据截至二零二四年。"),
    ("绕口令类句子未放慢：会含糊不清，应加 slow 标记。",
     "第{i}段：他念了句十四是十四四十是四十。",
     "第{i}段：他念了句[slow]「十四是十四，四十是四十。」[normal]"),
    ("英文缩略语未展开：中文有声书应译为中文全称。",
     "第{i}段：公司决定开展AI与LLM的联合研发。",
     "第{i}段：公司决定开展人工智能与大语言模型的联合研发。"),
    ("情感场景无情感标记：合成情绪平淡，应加 emotion 标记。",
     "第{i}段：他哽咽着说，谢谢大家还记得他。",
     "第{i}段：[emotion=sad, intensity=0.7]他哽咽着说，谢谢大家还记得他。"),
    ("长段一逗到底：应按语义用句号/破折号建立停顿层次。",
     "第{i}段：夜深了他还没有睡他在等一个电话，一个也许永远不会来的电话。",
     "第{i}段：夜深了，他还没有睡。他在等一个电话——一个也许永远不会来的电话。"),
]


def unbaked_edit_patterns():
    """当前最新 edit_for_tts prompt 中尚未烘焙的模式（edit 可映射）。"""
    from audiobook_studio.feedback.prompt_upgrader import (
        PATTERN_PROMPT_FIXES, _load_current_prompt, _map_pattern_to_stage,
    )

    content, _ = _load_current_prompt("edit_for_tts")
    return [
        p for p in PATTERN_PROMPT_FIXES
        if _map_pattern_to_stage(p) == "edit_for_tts"
        and PATTERN_PROMPT_FIXES[p][:40] not in content
    ]


def inject_records(pattern=None, n=12, rnd=0, cursor=0):
    """注入 n 条人工修正反馈; pattern=None 时按 cursor 轮转混合场景（前 3 条为新类）。"""
    from audiobook_studio.models.feedback_record import FeedbackRecord

    base = json.loads(Path("data/golden/val/edit/edit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    inp = base["input"]
    db = factory()
    try:
        for i in range(n):
            if pattern:
                rationale = PATTERN_RATIONALE[pattern]
                machine = f"第{i + 1}段：他说道，今晚的月色很好，我们继续赶路吧。"
                corrected = machine + " [pause_before_ms=500]"
            else:
                total = len(MIXED_SCENARIOS)
                # 前 3 条 = cursor 起的 3 个新场景类（指令烘焙 [:3] 按记录序取）；
                # 其余 9 条 = 背景轮转（含轮次扰动的已见类，真实反馈流噪声）。
                s_idx = (cursor + i) % total if i < 3 else (cursor + 3 + i + rnd) % total
                rationale, mach_t, corr_t = MIXED_SCENARIOS[s_idx]
                machine = mach_t.format(i=i + 1)
                corrected = corr_t.format(i=i + 1)
            db.add(FeedbackRecord(
                feedback_id=f"marathon-r{rnd}-{uuid.uuid4().hex[:12]}",
                project_id=1,
                source="human_correction",
                stage="edit",
                input_snapshot=inp,
                llm_output={"edited_text": machine, "changes_made": ["常规编辑"],
                            "forbidden_content_removed": [], "confidence": 0.9,
                            "rationale": "机器初稿"},
                corrected_output={"edited_text": corrected, "changes_made": ["人工修正"],
                                  "forbidden_content_removed": [], "confidence": 0.9,
                                  "rationale": "人工修正稿"},
                rationale=rationale,
            ))
        db.commit()
    finally:
        db.close()


def seed_harness_sandbox():
    """把当前 live edit prompt 播种到 harness 沙箱（reset_storage 清空后重建）。"""
    live = Path("prompts/edit_for_tts/v1.j2")
    sandbox = Path("prompts/harness/edit_for_tts")
    if not (sandbox / "v1.j2").exists():
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "v1.j2").write_text(live.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[seed] prompts/harness/edit_for_tts/v1.j2 ← live ({live.stat().st_size}B)")


def harness_tick():
    """harness 沙箱迭代一轮（edit 阶段，双评判器，沙箱内自动部署）。"""
    from audiobook_studio.feedback.offline_judge import OfflineJudge, QualityCompositeJudge
    from audiobook_studio.harness.harness import run_iteration_cycle

    rep = run_iteration_cycle(
        "edit",
        run_fn=None,  # 缺省 → _harness_run_fn_for：沙箱候选版本 swap 进 v1.j2 跑真实 stage
        judge=OfflineJudge(),
        quality_judge=QualityCompositeJudge(),
        auto_deploy=True,
    )
    return rep.to_dict()


def live_version():
    from audiobook_studio.feedback.deploy import served_version
    return served_version("edit_for_tts") or 1


def _load_scenario_cursor():
    """从日志恢复场景 cursor（最后一条含 scenario_cursor 的记录）；无则 0。

    run A（混合燃料缺陷轮）未烘焙任何真实场景类指令（样板 diff → 指令全为
    停顿/情感类），故重跑从 cursor=0 开始。
    """
    if not LOG_PATH.exists():
        return 0
    cursor = 0
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        c = rec.get("scenario_cursor")
        if isinstance(c, int):
            cursor = c
    return cursor


def main():
    from audiobook_studio.feedback.integration import SelfIterationLoop

    seed_harness_sandbox()
    loop = SelfIterationLoop(
        db_session_factory=factory,
        project_id=1,
        canary_percentage=0.1,
        enable_auto_pr=False,   # 混合暂存树 checkout 危险; PR 由收尾统一范围化提交
        enable_auto_merge=False,
        auto_deploy=True,
    )

    random.seed(20261005)
    consecutive_failures = 0
    for rnd in range(START_ROUND, END_ROUND + 1):
        t0 = time.time()
        pattern = None
        cursor = _load_scenario_cursor()  # try 外预载：异常路径也要能记录未推进的 cursor
        try:
            # 已尝试过的模式不再重复注入燃料：分析器标签为 LLM 自由归类（不可控），
            # 未烘焙≠值得重试——语义改进已经由 stage_instructions 指令通道带给候选。
            # 记住已尝试的模式，保证燃料轮转推进到新模式/混合场景。
            attempted = set()
            if LOG_PATH.exists():
                for _line in LOG_PATH.read_text(encoding="utf-8").splitlines():
                    try:
                        _rec = json.loads(_line)
                    except Exception:
                        continue
                    _p = _rec.get("pattern")
                    if _p and _p != "mixed":
                        attempted.add(_p)
            remaining = [p for p in unbaked_edit_patterns() if p not in attempted]
            if remaining:
                pattern = remaining[0]  # 每轮注入一个未尝试的新模式燃料
                print(f"\n{'='*70}\n[round {rnd}] 模式燃料: {pattern} (未尝试 {len(remaining)})")
            else:
                pattern = None
                fresh = [MIXED_SCENARIOS[(cursor + k) % len(MIXED_SCENARIOS)][0][:16] for k in range(3)]
                print(f"\n{'='*70}\n[round {rnd}] 混合模式燃料（cursor={cursor}, 新类: {fresh}）")

            inject_records(pattern=pattern, rnd=rnd, cursor=cursor)

            analysis = loop.auto_processor.trigger_now()
            if analysis is None:
                raise RuntimeError("trigger_now 返回 None（分析失败）")
            print(f"[round {rnd}] analyzed={analysis.total_analyzed} "
                  f"top={analysis.top_patterns[:4]} "
                  f"instructions={sum(len(v) for v in analysis.stage_instructions.values())}")

            loop._handle_new_analysis(analysis)

            # 每逢 5 的倍数轮: harness 沙箱 tick
            harness = None
            if rnd % 5 == 0:
                try:
                    harness = harness_tick()
                    print(f"[round {rnd}] harness tick: candidate=v{harness.get('candidate_version')} "
                          f"passed={harness.get('passed')} deployed={harness.get('deployed')} "
                          f"quality_ratio={harness.get('quality_score_ratio')}")
                except Exception as e:
                    harness = {"error": str(e)[:200]}
                    print(f"[round {rnd}] harness tick 失败: {e}")

            outcome = {
                "round": rnd,
                "pattern": pattern or "mixed",
                "phase": f"{RUN_TAG}-fixed-fuel" if not pattern else RUN_TAG,
                "analyzed": analysis.total_analyzed,
                "top_patterns": analysis.top_patterns[:6],
                "llm_instructions": sum(len(v) for v in analysis.stage_instructions.values()),
                "fresh_scenarios": (
                    [MIXED_SCENARIOS[(cursor + k) % len(MIXED_SCENARIOS)][0][:16] for k in range(3)]
                    if not pattern else None
                ),
                "scenario_cursor": (cursor + 3) % len(MIXED_SCENARIOS) if not pattern else cursor,
                "upgraded_prompts": {k: str(v) for k, v in loop._upgraded_prompts.items()},
                "validation": {
                    k: {kk: vv for kk, vv in v.items()
                        if kk in ("passed_count", "pass_rate", "avg_quality_ratio", "avg_similarity")}
                    for k, v in loop._validation_results.items()
                },
                "live_version": live_version(),
                "iteration_count": loop._iteration_count,
                "harness": harness,
                "elapsed_s": round(time.time() - t0),
                "ok": True,
            }
            consecutive_failures = 0
        except Exception as e:
            traceback.print_exc()
            outcome = {
                "round": rnd, "pattern": pattern or "mixed", "error": str(e)[:400],
                "scenario_cursor": cursor,  # 失败轮不推进 cursor，下轮重试同组新类
                "live_version": live_version(), "elapsed_s": round(time.time() - t0), "ok": False,
            }
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print(f"!! 连续 {consecutive_failures} 轮失败，中止马拉松")
                LOG_PATH.open("a").write(json.dumps(outcome, ensure_ascii=False) + "\n")
                sys.exit(1)

        with LOG_PATH.open("a") as f:
            f.write(json.dumps(outcome, ensure_ascii=False, default=str) + "\n")
        print(f"[round {rnd}] done in {outcome['elapsed_s']}s → live=v{outcome['live_version']}")

    print(f"\n{'='*70}\n[marathon complete] rounds {START_ROUND}-{END_ROUND}, live=v{live_version()}")


if __name__ == "__main__":
    main()
