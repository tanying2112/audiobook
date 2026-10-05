"""Fix 1b + Fix 5：以 v43 live 规约为基准生成真实感金标 edit 数据。

替换 mock 内容（「这是一个很长的测试段落…」）为真实叙事中文段落，
expected_output 严格按 live prompt v43 的难度规则推导：
  A=原文保留；B=+数字归一化(中文→阿拉伯)/去无意义符号/长句拆分；
  C=+冗余修饰删减/每句≤30字；D=+生僻词注音/古诗词分句；
  forbid_edit=true 仅数字归一化；对话归属按 [说话人] 前缀模式修复。
同时产出 harness 平铺格式（{"stage","input","output"} + sample_hash）。
"""
import hashlib
import json
from pathlib import Path

def ann(idx, speaker, is_dlg, emotion, intensity=0.6, conf=0.9, notes="", pause_b=300, pause_a=500):
    return {
        "paragraph_index": idx, "speaker_canonical_name": speaker, "is_dialogue": is_dlg,
        "emotion": emotion, "emotion_intensity": intensity, "speech_rate": 1.0,
        "pitch_shift_semitones": 0, "needs_sfx": False, "sfx_tags": [],
        "pause_before_ms": pause_b, "pause_after_ms": pause_a, "confidence": conf, "notes": notes,
    }

# (input_text, annotation, difficulty, forbid_edit, expected_text, changes_made, confidence, rationale)
TRAIN = [
    # ── A 级：原文保留（无数字/无干扰，期望=输入逐字一致） ──
    ("秋收过后，田野一下子空旷起来，只剩下几只麻雀在稻茬间蹦跳觅食。",
     ann(1, "旁白", False, "neutral", notes="平缓叙述段"), "A", False,
     "秋收过后，田野一下子空旷起来，只剩下几只麻雀在稻茬间蹦跳觅食。",
     [], 0.93, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("他坐在门槛上抽着旱烟，望着远处连绵的青山，久久没有说话。",
     ann(2, "旁白", False, "neutral", notes="静态描写"), "A", False,
     "他坐在门槛上抽着旱烟，望着远处连绵的青山，久久没有说话。",
     [], 0.94, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("海水退潮后，滩涂上留下深深浅浅的水洼，映着天边的晚霞。",
     ann(3, "旁白", False, "tender", intensity=0.5, notes="景物描写"), "A", False,
     "海水退潮后，滩涂上留下深深浅浅的水洼，映着天边的晚霞。",
     [], 0.95, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("巷口的石磨早已无人使用，磨盘上积了厚厚的一层落叶。",
     ann(4, "旁白", False, "neutral", notes="怀旧叙述"), "A", False,
     "巷口的石磨早已无人使用，磨盘上积了厚厚的一层落叶。",
     [], 0.94, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("夜里落了一场小雨，清晨的空气里满是湿润的泥土气息。",
     ann(5, "旁白", False, "tender", intensity=0.4, notes="过渡段"), "A", False,
     "夜里落了一场小雨，清晨的空气里满是湿润的泥土气息。",
     [], 0.95, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("风筝越飞越高，孩子们在打谷场上追着跑，笑声惊起了树梢的斑鸠。",
     ann(6, "旁白", False, "tender", intensity=0.7, notes="欢快场景"), "A", False,
     "风筝越飞越高，孩子们在打谷场上追着跑，笑声惊起了树梢的斑鸠。",
     [], 0.92, "难度 A 级：完全保留原文，不做任何编辑。"),
    # ── B 级 forbid_edit=true：仅数字归一化 ──
    ("他攒了两百四十块钱，终于买下那匹枣红色的马。",
     ann(7, "旁白", False, "neutral", notes="编辑锁段"), "B", True,
     "他攒了240块钱，终于买下那匹枣红色的马。",
     ["数字归一化"], 0.9, "forbid_edit=true：仅做数字归一化，其余内容锁定。"),
    # ── B 级：数字归一化 ──
    ("爷爷常说起一九五八年的那个春天，他在镇上做了三十年木工，攒下两百四十块钱。",
     ann(8, "旁白", False, "tender", intensity=0.5, notes="回忆叙述"), "B", False,
     "爷爷常说起1958年的那个春天，他在镇上做了30年木工，攒下240块钱。",
     ["数字归一化"], 0.9, "难度 B 级：中文数字转阿拉伯数字。"),
    ("船队共有十二艘帆船，载着九百多名水手，在一六零五年秋天起航。",
     ann(9, "旁白", False, "neutral", notes="史实叙述"), "B", False,
     "船队共有12艘帆船，载着900多名水手，在1605年秋天起航。",
     ["数字归一化"], 0.9, "难度 B 级：中文数字转阿拉伯数字。"),
    ("县志上记载，这场大水淹没了三千多亩良田，冲垮了十七座桥梁。",
     ann(10, "旁白", False, "sad", intensity=0.6, notes="灾情叙述"), "B", False,
     "县志上记载，这场大水淹没了3000多亩良田，冲垮了17座桥梁。",
     ["数字归一化"], 0.9, "难度 B 级：中文数字转阿拉伯数字。"),
    # ── B 级：无意义符号 ──
    ("※※※ 他坐在灯下补渔网，妻子在一旁纳鞋底，谁也没有说话。※※※",
     ann(11, "旁白", False, "neutral", notes="含装饰符"), "B", False,
     "他坐在灯下补渔网，妻子在一旁纳鞋底，谁也没有说话。",
     ["去除无意义符号"], 0.9, "难度 B 级：去除※等干扰字符。"),
    # ── B 级：长句拆分（单句>50字） ──
    ("暮色四合的时候，老周头赶着那群羊从山坡上慢慢走下来，羊铃声在寂静的村道上断断续续地响着，家家户户的烟囱里升起了淡淡的炊烟。",
     ann(12, "旁白", False, "tender", intensity=0.5, notes="长句需拆分"), "B", False,
     "暮色四合的时候，老周头赶着那群羊从山坡上慢慢走下来。羊铃声在寂静的村道上断断续续地响着，家家户户的烟囱里升起了淡淡的炊烟。",
     ["长句拆分"], 0.88, "难度 B 级：单句超过50字，在逗号处拆分。"),
    ("集市散了以后，街上还留着些没来得及收走的竹筐和干草，几个摊主蹲在屋檐下抽着烟等雨停，谁也不肯先开口说今天亏了多少。",
     ann(13, "旁白", False, "neutral", notes="长句需拆分"), "B", False,
     "集市散了以后，街上还留着些没来得及收走的竹筐和干草。几个摊主蹲在屋檐下抽着烟等雨停，谁也不肯先开口说今天亏了多少。",
     ["长句拆分"], 0.88, "难度 B 级：单句超过50字，在逗号处拆分。"),
    # ── B 级：对话归属标注 ──
    ("林婉说：「今晚的月色真好，我们继续赶路吧。」",
     ann(14, "林婉", True, "tender", intensity=0.6, notes="对话归属后置"), "B", False,
     "[林婉] 今晚的月色真好，我们继续赶路吧。",
     ["对话归属标注"], 0.85, "难度 B 级：对话加说话人方括号标注，对话内容 1:1 保留。"),
    # ── B 级：组合 ──
    ("据说这座桥建于清代乾隆三十九年，桥面由三百多块青石板铺成，每逢雨后石板上便映出天光云影，来往的行人都爱在桥头歇脚。",
     ann(15, "旁白", False, "neutral", notes="数字+长句"), "B", False,
     "据说这座桥建于清代乾隆39年，桥面由300多块青石板铺成。每逢雨后石板上便映出天光云影，来往的行人都爱在桥头歇脚。",
     ["数字归一化", "长句拆分"], 0.87, "难度 B 级：数字归一化并拆分超长句。"),
    ("···第二十三回···秋菱提着篮子过了石桥，去镇上裁铺取她订做的两丈蓝布。",
     ann(16, "旁白", False, "neutral", notes="章回头+符号"), "B", False,
     "第23回 秋菱提着篮子过了石桥，去镇上裁铺取她订做的2丈蓝布。",
     ["去除无意义符号", "数字归一化"], 0.87, "难度 B 级：去除装饰符并归一化数字。"),
    # ── C 级 ──
    ("这是一个非常非常重要的决定，他反反复复想了很久很久，才最终下定了决心。",
     ann(17, "旁白", False, "sad", intensity=0.6, notes="修饰堆叠"), "C", False,
     "这是一个重要的决定，他反复想了很久，才下定决心。",
     ["冗余修饰删减"], 0.88, "难度 C 级：删除重复意义的修饰词。"),
    ("那口古井早已干涸了，可是村里上了年纪的老人还是常常常常提起它当年的清甜。",
     ann(18, "旁白", False, "tender", intensity=0.5, notes="修饰堆叠"), "C", False,
     "那口古井早已干涸了，可是村里上了年纪的老人还是常常提起它当年的清甜。",
     ["冗余修饰删减"], 0.88, "难度 C 级：删除重复修饰。"),
    ("少年背着一捆比他还高的柴禾深一脚浅一脚地踩着积雪往山下走寒风刮在脸上像小刀子一样。",
     ann(19, "旁白", False, "sad", intensity=0.6, notes="超长单句"), "C", False,
     "少年背着一捆比他还高的柴禾，深一脚浅一脚地踩着积雪往山下走。寒风刮在脸上，像小刀子一样。",
     ["长句拆分"], 0.86, "难度 C 级：拆句并控制每句长度。"),
    ("这批货足足有五百多箱，他们反反复复清点了三遍三遍，才敢在账册上落笔。",
     ann(20, "旁白", False, "neutral", notes="数字+修饰"), "C", False,
     "这批货足足有500多箱，他们反复清点了3遍，才敢在账册上落笔。",
     ["数字归一化", "冗余修饰删减"], 0.87, "难度 C 级：数字归一化并删除重复修饰。"),
    ("「我不去了。」沈青梧低声说。",
     ann(21, "沈青梧", True, "sad", intensity=0.7, notes="对话归属后置"), "C", False,
     "[沈青梧] 我不去了。",
     ["对话归属标注"], 0.85, "难度 C 级：对话加说话人标注，内容 1:1 保留。"),
    ("她来来回回反反复复地修改那封写了很久很久的信，始终不知道该怎么署名。",
     ann(22, "旁白", False, "sad", intensity=0.6, notes="修饰堆叠"), "C", False,
     "她反复修改那封写了很久的信，始终不知道该怎么署名。",
     ["冗余修饰删减"], 0.88, "难度 C 级：删除重复意义的修饰词。"),
    # ── D 级 ──
    ("老掌柜说，这方砚台产自歙州，配的龟兹玉镇纸如今可不多见了。",
     ann(23, "旁白", False, "neutral", notes="含生僻地名"), "D", False,
     "老掌柜说，这方砚台产自歙(shè)州，配的龟兹(qiūcí)玉镇纸如今可不多见了。",
     ["生僻词注音"], 0.85, "难度 D 级：为生僻词注音。"),
    ("祖父放下酒杯，低声念道：床前明月光疑是地上霜举头望明月低头思故乡，声音里满是苍凉。",
     ann(24, "旁白", False, "sad", intensity=0.7, notes="古诗词连排"), "D", False,
     "祖父放下酒杯，低声念道：床前明月光，疑是地上霜。举头望明月，低头思故乡。声音里满是苍凉。",
     ["古诗词分句"], 0.85, "难度 D 级：古诗词保持原有格式并分句。"),
]

VAL = [
    ("立冬那天，屋檐下的白菜垛得整整齐齐，母亲说今年的收成比去年好。",
     ann(1, "旁白", False, "tender", intensity=0.5, notes="日常叙述"), "A", False,
     "立冬那天，屋檐下的白菜垛得整整齐齐，母亲说今年的收成比去年好。",
     [], 0.93, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("渡口的木船吱呀一声离了岸，艄公的号子在雾气里传出去很远。",
     ann(2, "旁白", False, "neutral", notes="场景描写"), "A", False,
     "渡口的木船吱呀一声离了岸，艄公的号子在雾气里传出去很远。",
     [], 0.94, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("灶膛里的火光映在墙上，忽明忽暗，像谁在轻轻地眨眼睛。",
     ann(3, "旁白", False, "tender", intensity=0.4, notes="静态描写"), "A", False,
     "灶膛里的火光映在墙上，忽明忽暗，像谁在轻轻地眨眼睛。",
     [], 0.95, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("社戏散了，戏台前的空地上只剩下几张长凳和满地的瓜子壳。",
     ann(4, "旁白", False, "neutral", notes="场景收尾"), "A", False,
     "社戏散了，戏台前的空地上只剩下几张长凳和满地的瓜子壳。",
     [], 0.94, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("槐花开的时候，整条巷子都是甜的，蜜蜂嗡嗡地绕着枝头打转。",
     ann(5, "旁白", False, "tender", intensity=0.6, notes="春景"), "A", False,
     "槐花开的时候，整条巷子都是甜的，蜜蜂嗡嗡地绕着枝头打转。",
     [], 0.93, "难度 A 级：完全保留原文，不做任何编辑。"),
    ("老陈头挑着一百二十斤的谷子过了河，一步都没有歇。",
     ann(6, "旁白", False, "neutral", notes="编辑锁段"), "B", True,
     "老陈头挑着120斤的谷子过了河，一步都没有歇。",
     ["数字归一化"], 0.9, "forbid_edit=true：仅做数字归一化，其余内容锁定。"),
    ("戏班一共来了二十五个人，在祠堂前搭起了三丈高的戏台。",
     ann(7, "旁白", False, "neutral", notes="含中文数字"), "B", False,
     "戏班一共来了25个人，在祠堂前搭起了3丈高的戏台。",
     ["数字归一化"], 0.9, "难度 B 级：中文数字转阿拉伯数字。"),
    ("那一年黄河决了口，淹没了一百多个村庄，逼得数万人扶老携幼往高处逃。",
     ann(8, "旁白", False, "sad", intensity=0.7, notes="史实叙述"), "B", False,
     "那一年黄河决了口，淹没了100多个村庄，逼得数万人扶老携幼往高处逃。",
     ["数字归一化"], 0.9, "难度 B 级：中文数字转阿拉伯数字。"),
    ("※ 楔子 ※ 故事要从四十多年前的那个冬天说起，那一年雪下得格外早。",
     ann(9, "旁白", False, "neutral", notes="含装饰符"), "B", False,
     "楔子 故事要从四十多年前的那个冬天说起，那一年雪下得格外早。",
     ["去除无意义符号"], 0.88, "难度 B 级：去除※等干扰字符。"),
    ("春耕时节田埂上到处是挑担送饭的人，孩童们跟在大人身后拾捡遗落的稻种，田里的水光一晃一晃地映着日头。",
     ann(10, "旁白", False, "tender", intensity=0.5, notes="长句需拆分"), "B", False,
     "春耕时节田埂上到处是挑担送饭的人，孩童们跟在大人身后拾捡遗落的稻种。田里的水光一晃一晃地映着日头。",
     ["长句拆分"], 0.88, "难度 B 级：单句超过50字，在逗号处拆分。"),
    ("「明早卯时出发，谁也不许迟到。」队长站在磨盘上喊。",
     ann(11, "队长", True, "neutral", intensity=0.6, notes="对话归属后置"), "B", False,
     "[队长] 明早卯时出发，谁也不许迟到。",
     ["对话归属标注"], 0.85, "难度 B 级：对话加说话人方括号标注，对话内容 1:1 保留。"),
    ("药铺的账本上记着当归八钱、黄芪三两，掌柜的拨着算盘一一核对了两遍。",
     ann(12, "旁白", False, "neutral", notes="数字+叙述"), "B", False,
     "药铺的账本上记着当归8钱、黄芪3两，掌柜的拨着算盘一一核对了两遍。",
     ["数字归一化"], 0.89, "难度 B 级：中文数字转阿拉伯数字。"),
    ("她非常非常想念那座住了十几年十几年的老宅子，梦里总是回到那条洒满槐花的小巷。",
     ann(13, "旁白", False, "sad", intensity=0.7, notes="修饰堆叠"), "C", False,
     "她非常想念那座住了十几年的老宅子，梦里总是回到那条洒满槐花的小巷。",
     ["冗余修饰删减"], 0.88, "难度 C 级：删除重复意义的修饰词。"),
    ("他心里明白得很清楚这一次进城多半是凶多吉少可他还是把家里仅剩的几吊钱都缝进了衣角。",
     ann(14, "旁白", False, "sad", intensity=0.7, notes="超长单句"), "C", False,
     "他心里明白得很清楚，这一次进城多半是凶多吉少。可他还是把家里仅剩的几吊钱都缝进了衣角。",
     ["长句拆分"], 0.86, "难度 C 级：拆句并控制每句长度。"),
    ("账房先生仔仔细细认认真真地核完了最后一页账目，才把算盘推到一边。",
     ann(15, "旁白", False, "neutral", notes="修饰堆叠"), "C", False,
     "账房先生仔细地核完了最后一页账目，才把算盘推到一边。",
     ["冗余修饰删减"], 0.88, "难度 C 级：删除重复意义的修饰词。"),
    ("「娘，我回来了。」阿宝隔着院墙就喊了起来。",
     ann(16, "阿宝", True, "tender", intensity=0.8, notes="对话归属后置"), "C", False,
     "[阿宝] 娘，我回来了。",
     ["对话归属标注"], 0.85, "难度 C 级：对话加说话人标注，内容 1:1 保留。"),
    ("祖父说，这卷手抄的《茶经》是他年轻时在陆羽故居前从一个落魄书生手里换来的。",
     ann(17, "旁白", False, "tender", intensity=0.5, notes="含书名号"), "C", False,
     "祖父说，这卷手抄的《茶经》是他年轻时在陆羽故居前从一个落魄书生手里换来的。",
     [], 0.9, "难度 C 级：专有名词与书名保护，无冗余可删。"),
    ("这一次考试他一共做对了一百二十道题错了一十五道题，先生在名册上圈了又圈。",
     ann(18, "旁白", False, "neutral", notes="数字+修饰"), "C", False,
     "这一次考试他一共做对了120道题错了15道题，先生在名册上圈了又圈。",
     ["数字归一化"], 0.87, "难度 C 级：中文数字转阿拉伯数字。"),
    ("教书先生捋着胡子念道，学而时习之不亦说乎有朋自远方来不亦乐乎，窗外的雨声正密。",
     ann(19, "旁白", False, "neutral", notes="文言引文"), "D", False,
     "教书先生捋着胡子念道：学而时习之，不亦说乎？有朋自远方来，不亦乐乎？窗外的雨声正密。",
     ["古诗词分句"], 0.85, "难度 D 级：文言引文分句并加停顿。"),
    ("图注里写着，这幅《溪山行旅图》相传出自范宽之手，画中庋藏处题款已经漫漶难辨。",
     ann(20, "旁白", False, "neutral", notes="含生僻字"), "D", False,
     "图注里写着，这幅《溪山行旅图》相传出自范宽之手，画中庋(guǐ)藏处题款已经漫漶(huàn)难辨。",
     ["生僻词注音"], 0.85, "难度 D 级：为生僻字注音。"),
]

def prod_example(row):
    text, annotation, difficulty, forbid, exp_text, changes, conf, rationale = row
    annotation = dict(annotation)
    annotation["text"] = text
    return {
        "input": {
            "paragraph_text": text,
            "paragraph_annotation": annotation,
            "difficulty": difficulty,
            "forbid_edit": forbid,
        },
        "expected_output": {
            "edited_text": exp_text,
            "changes_made": changes,
            "forbidden_content_removed": [],
            "confidence": conf,
            "rationale": rationale,
        },
    }

def harness_example(row, source):
    ex = prod_example(row)
    rec = {"stage": "edit", "input": ex["input"], "output": ex["expected_output"], "source": source}
    payload = json.dumps({"stage": rec["stage"], "input": rec["input"], "output": rec["output"]},
                        ensure_ascii=False, sort_keys=True)
    rec["sample_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return rec

def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{path} <- {len(records)} 条")

assert len(TRAIN) == 24 and len(VAL) == 20, (len(TRAIN), len(VAL))
# 唯一性检查（段落文本不得重复）
texts = [r[0] for r in TRAIN] + [r[0] for r in VAL]
assert len(set(texts)) == len(texts), "段落文本存在重复"

write_jsonl(Path("data/golden/train/edit/edit.jsonl"), [prod_example(r) for r in TRAIN])
write_jsonl(Path("data/golden/val/edit/edit.jsonl"), [prod_example(r) for r in VAL])
write_jsonl(Path("data/golden/harness/train/edit.jsonl"),
            [harness_example(r, "spec_aligned_golden:v43:train") for r in TRAIN])
write_jsonl(Path("data/golden/harness/test/edit.jsonl"),
            [harness_example(r, "spec_aligned_golden:v43:val") for r in VAL])
print("全部写入完成")
