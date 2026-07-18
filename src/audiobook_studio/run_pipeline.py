#!/usr/bin/env python3
"""
Audiobook Studio V2 - 统一流水线执行脚本（带安全参数锁）

支持:
  --mock-data  生成/刷新 Mock 测试文本（按章节拆分，包含真实风格的中文小说内容）
  --init-db    初始化或重置数据库表结构（含项目种子数据）
  --books      指定要处理的书籍名称列表（默认: 红楼梦 三国演义）

用法示例:
  # 仅初始化数据库
  python -m audiobook_studio.run_pipeline --init-db

  # 生成 mock 数据 + 初始化数据库 + 运行流水线
  python -m audiobook_studio.run_pipeline --mock-data --init-db --books 红楼梦 三国演义

  # 仅运行流水线（使用已有数据和数据库）
  python -m audiobook_studio.run_pipeline --books 红楼梦
"""

import argparse
import asyncio
import logging
import os
import re
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from audiobook_studio.database import SessionLocal, init_db
from audiobook_studio.models import Project
from audiobook_studio.pipeline.checkpoint import CheckpointManager
from audiobook_studio.pipeline.orchestrator import (
    run_pipeline as orchestrator_run_pipeline,
    init_telemetry,
    shutdown_telemetry,
)
from audiobook_studio.utils.gc_manager import cleanup_after_export

# ── 日志配置 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
MOCK_DATA_DIR = DATA_DIR / "mock_data"
MOCK_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── 流水线阶段（按执行顺序） ────────────────────────────────────────────────
STAGES: List[str] = [
    "extract",
    "analyze",
    "annotate",
    "edit",
    "audio_postprocess",
    "review",
    "synthesize",
    "quality",
]

# ── 书籍配置 ──────────────────────────────────────────────────────────────────
BOOK_CONFIG: dict = {
    "红楼梦": {
        "title": "红楼梦",
        "author": "曹雪芹",
        "genre": "古典小说",
        "era": "清代",
        "difficulty": "C",
        "language": "zh",
        "num_mock_chapters": 3,
    },
    "三国演义": {
        "title": "三国演义",
        "author": "罗贯中",
        "genre": "历史小说",
        "era": "明代",
        "difficulty": "C",
        "language": "zh",
        "num_mock_chapters": 3,
    },
}

# ── 全局状态：用于信号处理 ──────────────────────────────────────────────────
_current_checkpoint_manager: Optional[CheckpointManager] = None
_current_project_id: Optional[int] = None
_interrupted = False


def _signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) and SIGTERM gracefully."""
    global _interrupted
    _interrupted = True
    logger.warning(f"Received signal {signum}, saving checkpoint before exit...")
    if _current_checkpoint_manager:
        try:
            _current_checkpoint_manager._flush()
            logger.info("Checkpoint saved. You can resume on next run.")
        except Exception as e:
            logger.error(f"Failed to save checkpoint on interrupt: {e}")
    print("\n⚠️  已保存进度检查点，下次运行可从断点继续。")
    sys.exit(130)  # Standard exit code for SIGINT


# Install signal handlers
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ══════════════════════════════════════════════════════════════════════════════
# 第一章: Mock 数据生成
# ══════════════════════════════════════════════════════════════════════════════


def _get_chapter_templates(book_name: str) -> dict:
    """返回指定书籍的章节文本模板。"""
    templates: dict = {}

    if book_name == "红楼梦":
        templates[1] = (
            "红楼梦第一回：甄士隐梦幻识通灵 贾雨村风尘怀闺秀\n\n"
            "此开卷第一回也。作者自云：因曾历过一番梦幻之后，故将真事隐去，"
            '而借"通灵"之说，撰此《石头记》一书也。故曰"甄士隐"云云。'
            '但书中所记何事何人？自又云："今风尘碌碌，一事无成，忽念及当日'
            "所有之女子，一一细考较去，觉其行止见识，皆出于我之上。何我堂堂"
            '须眉，诚不若彼裙钗哉？实愧则有余，悔又无益之大无可如何之日也！"\n\n'
            "列位看官：你道此书从何而来？说起根由虽近荒唐，细按则深有趣味。"
            "原来女娲氏炼石补天之时，于大荒山无稽崖练成高经十二丈、方经二十四丈"
            "顽石三万六千五百零一块。娲皇氏只用了三万六千五百块，只单单剩了一块"
            "未用，便弃在此山青埂峰下。谁知此石自经煅炼之后，灵性已通，因见众石"
            "俱得补天，独自己无材不堪入选，遂自怨自叹，日夜悲号惭愧。\n\n"
            "一日，正当嗟悼之际，俄见一僧一道远远而来，生得骨格不凡，丰神迥异，"
            "说说笑笑来至峰下，坐于石边高谈快论。先是说些云山雾海神仙玄幻之事，"
            "后便说到红尘中荣华富贵。此石听了，不觉打动凡心，也想要到人间去享一享"
            "这荣华富贵。"
        )
        templates[2] = (
            "红楼梦第二回：贾夫人仙逝扬州城 冷子兴演说荣国府\n\n"
            "却说封肃因听见公差传唤，忙出来陪笑启问。那些人只嚷："
            '"快请出甄爷来！"封肃忙陪笑道："小人姓封，并不姓甄。只有当日'
            '小婿姓甄，今已出家一二年了。"那些人道："我们也不知什么'
            "'真''假'，因奉太爷之命来问。他既是你女婿，便带了你去亲见"
            '太爷面禀。"说着，不容封肃多言，大家推拥他去了。\n\n'
            "那天约二更时，只见封肃方回来，欢天喜地。众人忙问端的。他乃说道："
            '"原来本府新升的太爷姓贾名化，本贯胡州人氏，曾与女婿旧日相交。'
            "方才在咱门前过去，因见娇杏那丫头买线，所以他只当女婿移住于此。"
            '我一一将原故回明，那太爷倒伤感叹息了一回。"\n\n'
            "且说贾雨村在旅店偶感风寒，愈后又因盘费不继，正欲寻个合式之处，"
            "暂且歇下。幸有两个旧友，亦在此境居住，因闻得鹾政欲聘一西宾，"
            "雨村便相托友力，谋了进去。"
        )
        templates[3] = (
            "红楼梦第三回：托内兄如海荐西宾 接外孙贾母惜孤女\n\n"
            "却说雨村忙回头看时，不是别人，乃是当日同僚一案参革的张如圭。"
            "他系此地人，革后家居，今打听得都中奏准起复旧员之信，他便四下里"
            "寻情找门路，忽遇见雨村，故忙道喜。二人见了礼，张如圭便将此信"
            "告诉雨村，雨村自是欢喜。\n\n"
            '次日，面谋之如海。如海道："天缘凑巧，因贱荆去世，都中家岳母'
            "念及小女无人依傍教育，前已遣了男女船只来接，因小女未曾大痊，"
            "故未及行。此刻正思向蒙训教之恩未经酬报，遇此机会，岂有不尽心"
            '图报之理。"\n\n'
            "黛玉听了，方洒泪拜别，随了奶娘及荣府几个老妇人登舟而去。雨村另有"
            "一只船，带两个小童，依附黛玉而行。有日到了都中，进入神京，雨村先"
            "整了衣冠，带了小童，拿着宗侄的名帖，至荣府的门前投递。"
        )

    elif book_name == "三国演义":
        templates[1] = (
            "三国演义第一回：宴桃园豪杰三结义 斩黄巾英雄首立功\n\n"
            "话说天下大势，分久必合，合久必分。周末七国分争，并入于秦。"
            "及秦灭之后，楚、汉分争，又并入于汉。汉朝自高祖斩白蛇而起义，"
            "一统天下，后来光武中兴，传至献帝，遂分为三国。推其致乱之由，"
            "殆始于桓、灵二帝。桓帝禁锢善类，崇信宦官。及桓帝崩，灵帝即位，"
            "大将军窦武、太傅陈蕃共相辅佐。时有宦官曹节等弄权，窦武、陈蕃"
            "谋诛之，机事不密，反为所害，中涓自此愈横。\n\n"
            "建宁二年四月望日，帝御温德殿。方升座，殿角狂风骤起。只见一条"
            "大青蛇，从梁上飞将下来，蟠于椅上。帝惊倒，左右急救入宫，百官"
            "俱奔避。须臾，蛇不见了。忽然大雷大雨，加以冰雹，落到半夜方止，"
            "坏却房屋无数。\n\n"
            "中平元年正月内，疫气流行，张角散施符水，为人治病，自称"
            '"大贤良师"。角有徒弟五百余人，云游四方，皆能书符念咒。'
            "次后徒众日多，角乃立三十六方，大方万余人，小方六七千，各立"
            '渠帅，讹言："苍天已死，黄天当立；岁在甲子，天下大吉。"'
        )
        templates[2] = (
            "三国演义第二回：张翼德怒鞭督邮 何国舅谋诛宦竖\n\n"
            "且说董卓字仲颖，陇西临洮人也，官拜河东太守，自来骄傲。当日"
            "怠慢了玄德，张飞性发，便欲杀之。玄德与关公急止之曰："
            '"他是朝廷命官，岂可擅杀？"飞曰："若不杀这厮，反要在他部下'
            '听令，其实不甘！二兄要便住在此，我自投别处去也！"玄德曰：'
            '"我三人义同生死，岂可相离？不若都投别处去便了。"\n\n'
            "却说张角有一军，正是天公将军张角。角全军尽行败走，奔至曲阳。"
            "玄德引兵追赶。时有诸将皆到，将角围住。角拚死战，不能得出。"
            "正危急间，忽见一彪军马，从角背后杀来，势如猛虎。角军大乱，"
            "四散奔走。\n\n"
            "原来玄德引军三千，前来接应。当下赵云见了玄德，深相投合，"
            "便拜玄德为兄。玄德遂认云为弟，云自此从玄德。"
        )
        templates[3] = (
            "三国演义第三回：议温明董卓叱丁原 馈金珠李肃说吕布\n\n"
            '且说曹操当日对何进曰："宦官之祸，古今皆有；但世主不当假之'
            "权宠，使至于此。若欲治罪，当除元恶，但付一狱吏足矣，何必纷纷"
            '召外兵乎？欲尽诛之，事必宣露。吾料其必败也。"何进怒曰：'
            '"孟德亦怀私意耶？"操退曰："乱天下者，必进也。"\n\n'
            "进乃暗差使命，赍密诏星夜往各镇去。却说前将军、鳌乡侯、西凉"
            "刺史董卓，先为破黄巾无功，朝廷将治其罪，因贿赂十常侍幸免；"
            "后又结托朝贵，遂任显官，统西州大军二十万，常有不臣之心。"
            "是时得诏大喜，点起军马，陆续便行。\n\n"
            "卓婿中郎将牛辅守住陕西，卓自领十五万，望洛阳进发。"
        )

    return templates


def create_mock_data() -> None:
    """为所有配置的书籍生成模拟章节文本文件。

    在 data/mock_data/ 下为每本书创建子目录，每章一个 .txt 文件。
    如果已有文件则跳过（不覆盖），方便用户自行修改后保留。
    """
    print("⚙️ [Action] 正在生成/刷新 Mock 测试文本文件...")

    for book_name, config in BOOK_CONFIG.items():
        templates = _get_chapter_templates(book_name)
        if not templates:
            print(f"  ⚠️  跳过 {book_name}：无章节模板")
            continue

        book_dir = MOCK_DATA_DIR / book_name
        book_dir.mkdir(parents=True, exist_ok=True)

        created = 0
        skipped = 0

        for chap_num in range(1, config["num_mock_chapters"] + 1):
            chap_file = book_dir / f"chapter_{chap_num:02d}.txt"

            if chap_file.exists():
                print(f"  ℹ️  已存在，跳过: {chap_file}")
                skipped += 1
                continue

            # 使用预设模板，若超出模板范围则自动生成占位文本
            if chap_num in templates:
                content = templates[chap_num]
            else:
                content = (
                    f"{book_name}第{chap_num}回：模拟章节{chap_num}\n\n"
                    f"这是《{book_name}》的第{chap_num}回，用于流水线测试。"
                    "本段落包含叙述性文字、人物对话、以及情感表达。通过模拟"
                    "真实小说文体，可以验证 TTS 文本编辑、角色标注、情感分析"
                    "等各阶段处理质量。\n\n"
                    '"这真是令人感慨万千啊！"角色甲叹息道。角色乙点点头，'
                    '沉思片刻后回答："确实如此，但我们仍需继续前行。"'
                )

            chap_file.write_text(content, encoding="utf-8")
            print(f"  ✅ 创建: {chap_file}")
            created += 1

        print(f"  📊 《{book_name}》: 创建 {created} 章, 跳过 {skipped} 章")

    print(f"✅ Mock 测试文本生成完成。所有文件位于: {MOCK_DATA_DIR}")


# ══════════════════════════════════════════════════════════════════════════════
# 第二章: 数据库初始化
# ══════════════════════════════════════════════════════════════════════════════


def initialize_database(seed_projects: bool = True) -> None:
    """初始化数据库表结构，可选地创建项目种子数据。

    使用 SQLAlchemy ORM 自省机制自动创建所有尚未存在的表。
    如果表已存在则不操作（幂等安全）。

    Args:
        seed_projects: 是否在初始化后为每本书创建 Project 记录。
    """
    print("🗄️ [Action] 正在初始化/重置数据库表结构...")

    # 第 1 步：创建所有表（幂等，CREATE TABLE IF NOT EXISTS）
    init_db()
    print("  ✅ 数据库表结构已就绪。")

    if not seed_projects:
        print("ℹ️  跳过项目种子数据创建。")
        return

    # 第 2 步：检查并创建项目记录
    db = SessionLocal()
    try:
        for _book_name, config in BOOK_CONFIG.items():
            existing = db.query(Project).filter(Project.title == config["title"]).first()
            if existing:
                print(f"  ℹ️  Project 已存在: {config['title']} (id={existing.id})")
                continue

            now = datetime.now().isoformat()
            project = Project(
                title=config["title"],
                author=config["author"],
                genre=config["genre"],
                difficulty=config["difficulty"],
                language=config["language"],
                era=config["era"],
                status="draft",
                total_chapters_estimated=config["num_mock_chapters"],
                current_stage="pending",
                progress=0.0,
                total_cost_usd=0.0,
                created_at=now,
                updated_at=now,
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            print(f"  ✅ Project 创建成功: {config['title']} (id={project.id})")
    except Exception as e:
        db.rollback()
        print(f"  ❌ 项目种子创建失败: {e}", file=sys.stderr)
        raise
    finally:
        db.close()

    print("✅ 数据库初始化完成。")


# ══════════════════════════════════════════════════════════════════════════════
# 第三章: 流水线编排
# ══════════════════════════════════════════════════════════════════════════════


def _find_project(db_session, book_name: str) -> Optional[Project]:
    """通过书名查找 Project 记录。"""
    if book_name in BOOK_CONFIG:
        title = BOOK_CONFIG[book_name]["title"]
    else:
        title = book_name
    return db_session.query(Project).filter(Project.title == title).first()


def _get_chapter_files(book_name: str) -> List[Tuple[int, Path]]:
    """获取指定书的章节文件列表，按章节号排序。

    Returns:
        List of (chapter_number, file_path) tuples.
    """
    book_dir = MOCK_DATA_DIR / book_name
    if not book_dir.exists():
        # 回退到 data/ 下的单文件
        single_file = DATA_DIR / f"{book_name}.txt"
        if single_file.exists():
            return [(1, single_file)]
        print(f"  ⚠️  找不到《{book_name}》的章节文件，跳过。")
        return []

    chapter_files: List[Tuple[int, Path]] = []
    pattern = re.compile(r"chapter_(\d+)\.txt")
    for f in sorted(book_dir.iterdir()):
        m = pattern.match(f.name)
        if m:
            chapter_files.append((int(m.group(1)), f))

    if not chapter_files:
        print(f"  ⚠️  《{book_name}》目录下无 chapter_*.txt 文件，跳过。")
        return []

    return chapter_files


def run_book_pipeline(
    book_name: str,
    stages: Optional[List[str]] = None,
    chapter_filter: Optional[List[int]] = None,
    bgm_path: Optional[str] = None,
    bg_volume: float = -20.0,
    keep_tmp: bool = False,
) -> Optional[int]:
    """对指定书籍执行完整流水线。

    流程:
      1. 打开数据库会话
      2. 查找或创建 Project 记录
      3. 读取章节文件
      4. 按指定章节（若提供）逐章串行执行 extract → analyze → annotate → edit → synthesize → quality
      5. 导出最终音频（可选：混入背景音乐）
      6. 自动清理临时中间音频文件（除非指定 --keep-tmp）

    Args:
        book_name: 书籍名称（如 "红楼梦"），用于查找配置和章节文件。
        stages: 要执行的流水线阶段列表。默认为全局 STAGES。
        chapter_filter: 要处理的章节号列表（如 [1,3]），若为 None 则处理所有章节。
        bgm_path: 背景音乐文件路径（用于导出时混音）。
        bg_volume: 背景音乐音量 (dB，默认 -20dB，相对于主轨).
        keep_tmp: 保留临时中间音频文件（默认 False，导出成功后自动清理以节省磁盘）。

    Returns:
        项目 ID（若成功），失败返回 None。
    """
    active_stages = stages or STAGES
    print(f"📖 正在处理: 《{book_name}》...")

    db = SessionLocal()
    try:
        # ── 查找或创建 Project ──────────────────────────────────────────
        project = _find_project(db, book_name)
        if not project:
            config = BOOK_CONFIG.get(book_name)
            if config:
                now = datetime.now().isoformat()
                project = Project(
                    title=config["title"],
                    author=config["author"],
                    genre=config["genre"],
                    difficulty=config["difficulty"],
                    language=config["language"],
                    era=config["era"],
                    status="draft",
                    total_chapters_estimated=config["num_mock_chapters"],
                    current_stage="pending",
                    progress=0.0,
                    total_cost_usd=0.0,
                    created_at=now,
                    updated_at=now,
                )
                db.add(project)
                db.commit()
                db.refresh(project)
                print(f"  ✅ 自动创建 Project: {config['title']} (id={project.id})")
            else:
                print(f"  ❌ 找不到《{book_name}》的配置，跳过。")
                return

        project_id = project.id
        print(f"  🆔 Project ID: {project_id}")

        # ── 检查点恢复机制 ──────────────────────────────────────────────
        checkpoint_manager = CheckpointManager(project_id)

        # Check if there's an existing incomplete pipeline
        has_incomplete = False
        for chap_num, _ in _get_chapter_files(book_name):
            if checkpoint_manager.last_completed_stage(chap_num) is not None:
                has_incomplete = True
                break

        if has_incomplete:
            # Check if running in non-interactive mode (CI/CD)
            import sys
            if sys.stdin.isatty():
                print("⚠️  发现未完成进度，是否从检查点继续？(Y/n): ", end="")
                try:
                    response = input().strip().lower()
                    if response and response[0] != 'y':
                        print("用户选择重新开始，清除检查点...")
                        checkpoint_manager._data = {"project_id": project_id, "chapters": {}, "version": 2}
                        checkpoint_manager._save()
                    else:
                        print("✅ 从检查点恢复，跳过已完成阶段...")
                except (EOFError, KeyboardInterrupt):
                    print("\n用户中断，退出。")
                    return
            else:
                # Non-interactive mode: auto-resume
                print("ℹ️  非交互模式，自动从检查点恢复...")

        # ── 初始化遥测收集器 ────────────────────────────────────────────
        output_dir = Path(f"./output/project_{project_id}")
        output_dir.mkdir(parents=True, exist_ok=True)
        init_telemetry(
            project_id=str(project_id),
            output_dir=str(output_dir),
        )

        # ── 获取章节文件 ────────────────────────────────────────────────
        chapter_files = _get_chapter_files(book_name)
        if not chapter_files:
            print(f"  ❌ 无章节文件可处理，跳过《{book_name}》。")
            return

        if chapter_filter is not None:
            chapter_files = [(num, path) for num, path in chapter_files if num in chapter_filter]
            if not chapter_files:
                print(f"  ⚠️  指定的章节 {chapter_filter} 在《{book_name}》中未找到，跳过。")
                return

        total_chapters = len(chapter_files)
        print(f"  📚 共 {total_chapters} 章")

        # ── 创建检查点管理器 ────────────────────────────────────────────
        checkpoint_manager = CheckpointManager(project_id=project_id)
        global _current_checkpoint_manager, _current_project_id
        _current_checkpoint_manager = checkpoint_manager
        _current_project_id = project_id

        # ── 逐章运行流水线 ──────────────────────────────────────────────
        for i, (chap_num, chap_file) in enumerate(chapter_files, 1):
            print(f"  ── [{i}/{total_chapters}] 第{chap_num}章: {chap_file.name} ──")

            try:
                chap_text = chap_file.read_text(encoding="utf-8")
                if not chap_text.strip():
                    print("    ⚠️  章节文件为空，跳过。")
                    continue

                print(f"    📝 文本长度: {len(chap_text)} 字符")

                # ── 阶段 1-2: 章节级 (extract, analyze) ──
                chapter_stages_1 = [s for s in active_stages if s in ("extract", "analyze")]
                if chapter_stages_1:
                    results = asyncio.run(orchestrator_run_pipeline(
                        stages=chapter_stages_1,
                        db=db,
                        project_id=project_id,
                        chapter_index=chap_num,
                        checkpoint_manager=checkpoint_manager,
                        # ── extract 阶段参数 ──
                        file_path=str(chap_file),
                        mime_type="text/plain",
                        detect_language=True,
                        # ── analyze 阶段参数 ──
                        title_hint=book_name,
                        author_hint=BOOK_CONFIG.get(book_name, {}).get("author", ""),
                        target_difficulty=BOOK_CONFIG.get(book_name, {}).get("difficulty", "B"),
                    ))
                    print(f"    ✅ 第{chap_num}章 章节级流水线完成（{len(results)} 个阶段输出）")

                # Fetch chapter from DB after extract/analyze
                from audiobook_studio.models import Chapter

                chapter = db.query(Chapter).filter(Chapter.project_id == project_id, Chapter.index == chap_num).first()
                if not chapter:
                    print(f"    ❌ 找不到第{chap_num}章记录，跳过段落级流水线。")
                    continue

                # ── 阶段 3-5: 段落级前半段 (annotate, edit, audio_postprocess) ──
                paragraph_stages_pre = [s for s in active_stages if s in ("annotate", "edit", "audio_postprocess")]
                if paragraph_stages_pre:
                    # Get paragraphs for this chapter
                    from audiobook_studio.models import Paragraph

                    paragraphs = (
                        db.query(Paragraph)
                        .filter(
                            Paragraph.project_id == project_id,
                            Paragraph.chapter_id == chapter.id,
                        )
                        .order_by(Paragraph.index)
                        .all()
                    )
                    if not paragraphs:
                        print(f"    ⚠️  第{chap_num}章无段落记录，跳过段落级流水线。")
                    else:
                        print(f"    📄 发现 {len(paragraphs)} 个段落，开始段落级前半段处理...")
                        for para in paragraphs:
                            print(f"      ── 段落 {para.index}/{len(paragraphs)} ──")
                            try:
                                para_results = asyncio.run(orchestrator_run_pipeline(
                                    stages=paragraph_stages_pre,
                                    db=db,
                                    project_id=project_id,
                                    chapter_index=chap_num,
                                    chapter_id=chapter.id,
                                    paragraph_index=para.index,
                                    paragraph_id=para.id,
                                    checkpoint_manager=checkpoint_manager,
                                ))
                                print(f"        ✅ 段落 {para.index} 完成（{len(para_results)} 个阶段输出）")
                            except Exception as e:
                                logger.error("第%d章段落%d处理失败: %s", chap_num, para.index, e, exc_info=True)
                                print(f"        ❌ 段落 {para.index} 处理失败: {e}", file=sys.stderr)

                # Refresh chapter to get updated paragraphs with audio_postprocess results
                db.refresh(chapter)

                # ── 阶段 6: 章节级 Review (quality gate before synthesis) ──
                if "review" in active_stages:
                    print(f"    🔍 运行 Reviewer Agent 质量门禁...")
                    review_results = asyncio.run(orchestrator_run_pipeline(
                        stages=["review"],
                        db=db,
                        project_id=project_id,
                        chapter_index=chap_num,
                        chapter_id=chapter.id,
                        checkpoint_manager=checkpoint_manager,
                    ))
                    # Check if review passed
                    review_judgment = review_results[0] if review_results else None
                    if review_judgment and hasattr(review_judgment, 'overall_passed') and not review_judgment.overall_passed:
                        print(f"    ❌ Reviewer Agent 拦截: {review_judgment.blocking_issues} 个阻断性问题")
                        print(f"       终端显示拦截/重试日志，等待 Developer Agent 修复...")
                        # In production, this would trigger a retry loop or human intervention
                        # For now, we log and continue (or could raise to stop pipeline)
                        if os.environ.get("REVIEWER_STRICT", "false").lower() == "true":
                            raise RuntimeError(f"Reviewer Agent blocked synthesis: {review_judgment.summary}")
                    else:
                        print(f"    ✅ Reviewer Agent 通过: 所有段落质量门禁通过")

                # ── 阶段 7-8: 段落级后半段 (synthesize, quality) ──
                paragraph_stages_post = [s for s in active_stages if s in ("synthesize", "quality")]
                if paragraph_stages_post:
                    from audiobook_studio.models import Paragraph

                    paragraphs = (
                        db.query(Paragraph)
                        .filter(
                            Paragraph.project_id == project_id,
                            Paragraph.chapter_id == chapter.id,
                        )
                        .order_by(Paragraph.index)
                        .all()
                    )
                    if paragraphs:
                        print(f"    🎙️ 开始段落级合成与质检...")
                        for para in paragraphs:
                            print(f"      ── 段落 {para.index}/{len(paragraphs)} ──")
                            try:
                                para_results = asyncio.run(orchestrator_run_pipeline(
                                    stages=paragraph_stages_post,
                                    db=db,
                                    project_id=project_id,
                                    chapter_index=chap_num,
                                    chapter_id=chapter.id,
                                    paragraph_index=para.index,
                                    paragraph_id=para.id,
                                    checkpoint_manager=checkpoint_manager,
                                ))
                                print(f"        ✅ 段落 {para.index} 完成（{len(para_results)} 个阶段输出）")
                            except Exception as e:
                                logger.error("第%d章段落%d处理失败: %s", chap_num, para.index, e, exc_info=True)
                                print(f"        ❌ 段落 {para.index} 处理失败: {e}", file=sys.stderr)

                print(f"    ✅ 第{chap_num}章完整流水线完成")

            except Exception as e:
                logger.error("第%d章流水线失败: %s", chap_num, e, exc_info=True)
                print(f"    ❌ 第{chap_num}章处理失败: {e}", file=sys.stderr)
                # 继续下一章（容错）

        # ── 更新项目状态 ────────────────────────────────────────────────
        project.current_stage = "completed"
        project.progress = 100.0
        project.updated_at = datetime.now().isoformat()
        db.commit()
        print(f"✅ 《{book_name}》全部 {total_chapters} 章处理完毕。")

        # ── 可选：导出最终音频 ────────────────────────────────────
        if bgm_path:
            print("🎵 开始导出音频（包含背景音乐混音）...")
            try:
                from audiobook_studio.export import ExportJob, ExportFormat
                from audiobook_studio.export.audio_ducking import MixConfig

                # MixConfig 仅暴露 ducking 参数（bgm_volume_db / duck_attack_ms /
                # duck_release_ms / ...）；bgm 路径交给 ExportJob(Form) 承载。
                mix_config = MixConfig(
                    bgm_volume_db=bg_volume,
                )

                job = ExportJob(
                    project_id=project.id,
                    chapter_ids=None,
                    formats={ExportFormat.M4B_SRT},
                    bgm_path=bgm_path,
                    include_cover=True,
                    cover_image=None,
                    normalize=True,
                    subtitle_config=None,
                    mix_config=mix_config,
                    output_dir=None,
                )

                # Run export synchronously. 注意：SessionLocal 已在模块顶部导入
                # (from audiobook_studio.database import SessionLocal)，此处切勿局部
                # 重导入——否则 Python 会把 SessionLocal 局部化，导致函数顶部
                # db = SessionLocal() 触发 UnboundLocalError（即便该分支不执行）。
                from audiobook_studio.export.batch_exporter import export_project

                export_db = SessionLocal()
                try:
                    result_job = export_project(project.id, export_db, job)
                    if result_job.progress.value == "complete":
                        print(f"✅ 导出完成: {result_job.output_paths}")
                        # 自动清理临时中间音频文件（回收 ~90% 磁盘空间）
                        if not keep_tmp:
                            print("🧹 正在清理临时中间音频文件...")
                            cleanup_after_export(project.id, keep_final=True)
                            print("✅ 临时文件清理完成")
                    else:
                        print(f"❌ 导出失败: {result_job.error}")
                finally:
                    export_db.close()
            except Exception as e:
                logger.error(f"Export failed: {e}")
                print(f"⚠️ 导出失败: {e}")

        # 清除全局检查点引用
        _current_checkpoint_manager = None
        _current_project_id = None

        # ── 关闭遥测收集器 ──────────────────────────────────────────────
        shutdown_telemetry()

        return project.id

    except Exception as e:
        logger.error("《%s》流水线整体失败: %s", book_name, e, exc_info=True)
        print(f"❌ 《{book_name}》流水线处理失败: {e}", file=sys.stderr)
        # 确保检查点已保存
        if _current_checkpoint_manager:
            _current_checkpoint_manager._flush()
        raise
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 命令行入口
# ══════════════════════════════════════════════════════════════════════════════


def parse_arguments() -> argparse.Namespace:
    """解析命令行参数，构建安全锁"""
    parser = argparse.ArgumentParser(description="Audiobook Studio V2 流水线核心启动入口")

    parser.add_argument(
        "--mock-data", action="store_true", help="⚙️ 脚手架操作：自动生成《红楼梦》和《三国演义》的 Mock 测试文本。"
    )

    parser.add_argument(
        "--init-db", action="store_true", help="⚠️ 危险操作：初始化或重置数据库结构。未指定则使用当前现有数据库。"
    )

    parser.add_argument(
        "--books",
        nargs="+",
        default=["红楼梦", "三国演义"],
        help="指定要运行流水线的书籍名称列表 (空格分隔，默认: 红楼梦 三国演义)",
    )

    parser.add_argument(
        "--chapter",
        type=int,
        help="只处理指定章节号（如 1）",
    )

    parser.add_argument(
        "--quick", action="store_true", help="🚀 快速模式：仅执行 extract → analyze → annotate，跳过合成与质检。"
    )

    # BGM mixing options for export stage
    parser.add_argument(
        "--bg-music",
        type=str,
        help="背景音乐文件路径 (用于导出时混音)",
    )

    parser.add_argument(
        "--bg-volume",
        type=float,
        default=-20.0,
        help="背景音乐音量 (dB，默认 -20dB，相对于主轨)",
    )

    parser.add_argument(
        "--keep-tmp",
        action="store_true",
        help="保留临时中间音频文件（默认导出成功后自动清理以节省磁盘）",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    print("=" * 50)
    print("🎙️  Audiobook Studio V2 Pipeline Controller")
    print("=" * 50)

    # ── 安全锁 1：Mock 数据生成 ──────────────────────────────────────────
    if args.mock_data:
        create_mock_data()
    else:
        print("ℹ️ [Safety] 跳过 Mock 文本生成（使用工作区现有文本）")

    # ── 安全锁 2：数据库初始化 ──────────────────────────────────────────
    if args.init_db:
        initialize_database(seed_projects=True)
    else:
        print("ℹ️ [Safety] 跳过数据库初始化（安全挂载现有数据库）")

    # ── 确定流水线阶段 ──────────────────────────────────────────────────
    active_stages: List[str]
    if args.quick:
        active_stages = ["extract", "analyze", "annotate"]
        stage_label = "快速模式(extract+analyze+annotate)"
    else:
        active_stages = STAGES
        stage_label = "完整流水线(extract→quality)"
    print(f"  🎯 流水线模式: {stage_label}")

    # ── 核心业务循环 ────────────────────────────────────────────────────
    print("-" * 50)
    print(f"🚀 准备启动音频合成流水线，目标书籍: {', '.join(args.books)}")
    print("-" * 50)

    has_error = False
    for book_name in args.books:
        try:
            run_book_pipeline(
                book_name,
                stages=active_stages,
                bgm_path=args.bg_music,
                bg_volume=args.bg_volume,
                keep_tmp=args.keep_tmp,
            )
        except Exception as e:
            has_error = True
            print(f"❌ 《{book_name}》处理失败，错误原因: {e}", file=sys.stderr)

    print("=" * 50)
    if has_error:
        print("⚠️  部分任务执行完毕（存在错误）。")
    else:
        print("🎉 所有指定任务执行完毕。")
    print("=" * 50)


if __name__ == "__main__":
    main()
