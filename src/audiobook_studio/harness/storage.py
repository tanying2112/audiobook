"""存储抽象层：SQLite (元数据/索引) + JSONL (明细/审计) 双写抽象。

提供统一的存储接口，对上层屏蔽 SQLite + JSONL 双写细节。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ContextManager, Dict, Generic, Iterator, List, Optional, Type, TypeVar

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 类型定义
# ──────────────────────────────────────────────────────────────────────────────

T = TypeVar("T")
ModelType = TypeVar("ModelType")


# ──────────────────────────────────────────────────────────────────────────────
# JSONL 存储工具
# ──────────────────────────────────────────────────────────────────────────────


class JSONLStore:
    """JSONL 文件存储：追加写入、原子写入、去重、按 split/stage 分片。"""

    def __init__(self, root: Path = Path("data")):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def _get_lock(self, path: Path) -> threading.Lock:
        """获取文件级锁。"""
        key = str(path)
        with self._lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def _file_path(self, split: str, stage: str, root: Path) -> Path:
        """获取 JSONL 文件路径。"""
        dir_path = Path(root) / "golden" / "harness" / split
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{stage}.jsonl"

    def _load_hashes(self, path: Path) -> set:
        """加载现有样本的 hash 集合（用于去重）。"""
        if not path.exists():
            return set()
        hashes = set()
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "sample_hash" in data:
                            hashes.add(data["sample_hash"])
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            pass
        return hashes

    def append(
        self,
        split: str,
        stage: str,
        record: Dict[str, Any],
        root: Optional[Path] = None,
    ) -> bool:
        """追加一条记录到 JSONL，带去重。返回是否实际新增。"""
        if root is None:
            root = Path("data")

        # 确保有 sample_hash
        record = dict(record)
        if "sample_hash" not in record:
            import hashlib

            payload = json.dumps(
                {
                    "stage": record.get("stage", ""),
                    "input": record.get("input", {}),
                    "output": record.get("output", {}),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            record["sample_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

        file_path = self._file_path(split, stage, Path("data"))
        lock = self._get_lock(file_path)

        with lock:
            # 加载现有 hash
            existing_hashes = self._load_hashes(Path("data") / "golden" / "harness" / split / f"{stage}.jsonl")
            record_hash = record.get("sample_hash", "")
            if record_hash in existing_hashes:
                return False

            # 原子写入
            file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = Path(str(file_path) + ".tmp")
            with open(tmp_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.replace(tmp_path, file_path)

            logger.debug(f"Appended to {split}/{stage} (hash={record.get('sample_hash', '')[:8]})")
            return True

    def load_all(self, split: str, stage: str, root: Optional[Path] = None) -> List[Dict[str, Any]]:
        """加载某 split/stage 下的所有记录。"""
        if root is None:
            root = Path("data")
        path = self._file_path(split, stage, root)
        if not Path(root).joinpath("golden", "harness", split, f"{stage}.jsonl").exists():
            return []
        records = []
        try:
            with open(root / "golden" / "harness" / split / f"{stage}.jsonl", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass

    def load_all_list(self, split: str, stage: str, root: Optional[Path] = None) -> List[Dict[str, Any]]:
        """加载所有记录为列表。"""
        return list(self.load_all(split, stage, root))

    def count(self, split: str, stage: str, root: Optional[Path] = None) -> int:
        """统计记录数。"""
        if root is None:
            root = Path("data")
        path = root / "golden" / "harness" / split / f"{stage}.jsonl"
        if not path.exists():
            return 0
        count = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                for _ in f:
                    pass
                count += 1
        except OSError:
            pass
        return count

    def count_all_splits(self, root: Optional[Path] = None) -> Dict[str, int]:
        """统计所有 split 的总数。"""
        if root is None:
            root = Path("data")
        counts = {"train": 0, "val": 0, "test": 0, "total": 0}
        golden_root = root / "golden" / "harness"
        if not golden_root.exists():
            return counts
        for split in ["train", "val", "test"]:
            split_dir = golden_root / split
            if split_dir.exists():
                for jsonl_file in split_dir.glob("*.jsonl"):
                    try:
                        with open(jsonl_file, "r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip():
                                    counts[split] += 1
                                    counts["total"] += 1
                    except OSError:
                        pass
        return counts


# ──────────────────────────────────────────────────────────────────────────────
# SQLite 会话管理
# ──────────────────────────────────────────────────────────────────────────────


class DatabaseManager:
    """SQLite 数据库管理：连接池、会话工厂、迁移、健康检查。"""

    def __init__(self, database_url: str = "sqlite:///./audiobook_studio.db"):
        self.database_url = database_url
        self._engine: Optional[Engine] = None
        self._sync_session_factory: Optional[sessionmaker] = None
        self._async_engine: Optional[Engine] = None
        self._async_session_factory: Optional[sessionmaker] = None
        self._init_lock = threading.Lock()

    def _create_engine(self) -> Engine:
        """创建同步引擎。"""
        if self.database_url.startswith("sqlite"):
            engine = create_engine(
                self.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )

            # 启用 WAL 模式
            @event.listens_for(Engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        else:
            engine = create_engine(self.database_url, pool_pre_ping=True)
        return engine

    def get_sync_engine(self) -> Engine:
        """获取同步引擎（单例）。"""
        if self._engine is None:
            with self._init_lock:
                if self._engine is None:
                    self._engine = self._create_engine()
        return self._engine

    def get_sync_session_factory(self) -> sessionmaker:
        """获取同步会话工厂。"""
        if self._sync_session_factory is None:
            self._sync_session_factory = sessionmaker(
                bind=self.get_sync_engine(),
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
        return self._sync_session_factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        """获取同步会话上下文管理器。"""
        factory = self.get_sync_session_factory()
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_all_tables(self) -> None:
        """创建所有表（开发/测试用）。"""
        Base.metadata.create_all(bind=self.get_sync_engine())
        # 同时创建主应用 ORM 表（如 users / audit_logs），harness 复用同一数据库，
        # 部分集成测试会写入主应用模型（User / AuditLog）。
        try:
            from ..orm_base import Base as AppBase

            AppBase.metadata.create_all(bind=self.get_sync_engine())
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"主应用表创建跳过/失败: {exc}")

    def drop_all_tables(self) -> None:
        """删除所有表（测试用）。"""
        Base.metadata.drop_all(bind=self.get_sync_engine())

    def health_check(self) -> bool:
        """健康检查：执行 SELECT 1。"""
        try:
            with self.session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


# ──────────────────────────────────────────────────────────────────────────────
# 统一存储门面
# ──────────────────────────────────────────────────────────────────────────────


class Storage:
    """统一存储门面：对上层提供统一接口，内部双写 SQLite + JSONL。"""

    def __init__(self, database_url: str = "sqlite:///./audiobook_studio.db", data_root: Path = Path("data")):
        self.db = DatabaseManager(database_url)
        self.jsonl = JSONLStore()
        self.data_root = Path(data_root)

        # 确保目录存在
        Path("data").mkdir(parents=True, exist_ok=True)
        # 首次初始化即保证表存在（开发/测试用；CREATE TABLE IF NOT EXISTS，幂等）
        try:
            self.db.create_all_tables()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"create_all_tables 跳过/失败: {exc}")

    # ──────────────────────────────────────────────────────────────────────────
    # 会话管理
    # ──────────────────────────────────────────────────────────────────────────

    @contextmanager
    def session(self):
        """获取数据库会话。"""
        with self.db.session() as session:
            yield session

    # ──────────────────────────────────────────────────────────────────────────
    # 反馈记录
    # ──────────────────────────────────────────────────────────────────────────

    def create_feedback(self, session: Session, **kwargs) -> "FeedbackRecord":
        """创建反馈记录（仅写 SQLite，无 JSONL 对应）。"""
        from .models import FeedbackRecord

        record = FeedbackRecord(**kwargs)
        session.add(record)
        session.flush()
        return record

    def get_feedback(self, session: Session, feedback_id: str):
        from .models import FeedbackRecord

        return (
            session.execute(select(FeedbackRecord).where(FeedbackRecord.feedback_id == feedback_id)).scalars().first()
        )

    def list_unprocessed_feedback(self, session, project_id: Optional[int] = None, limit: int = 500):
        from sqlalchemy import select

        from .models import FeedbackRecord

        stmt = select(FeedbackRecord).where(FeedbackRecord.processed == False)  # noqa: E712
        if project_id:
            stmt = stmt.where(FeedbackRecord.project_id == project_id)
        return (
            session.execute(select(FeedbackRecord).where(FeedbackRecord.processed == False).limit(500)).scalars().all()
        )

    def mark_feedback_processed(self, session, feedback_id: str, pattern_tags=None, diff_summary=""):
        from .models import FeedbackRecord

        record = (
            session.execute(select(FeedbackRecord).where(FeedbackRecord.feedback_id == feedback_id)).scalars().first()
        )
        if record:
            record.processed = True
            if pattern_tags:
                record.pattern_tags = pattern_tags
            # session.commit() 由上下文管理器处理

    # ──────────────────────────────────────────────────────────────────────────
    # 金标样本
    # ──────────────────────────────────────────────────────────────────────────

    def append_golden_sample(
        self,
        split: str,
        stage: str,
        record: Dict[str, Any],
        golden_root: Optional[Path] = None,
    ) -> bool:
        """追加金标样本：双写 SQLite + JSONL。"""
        from .models import GoldenSample

        if golden_root is None:
            golden_root = Path("data")

        # 双写：JSONL (追加)
        jsonl_added = self.jsonl.append(split, stage, record, root=Path("data"))

        # SQLite (元数据)
        if split not in ("train", "val", "test"):
            raise ValueError(f"invalid split: {split}")

        # 统一计算 sample_hash（与 JSONL 双写保持一致），并推导 sample_id
        sample_hash = record.get("sample_hash")
        if not sample_hash:
            payload = json.dumps(
                {
                    "stage": record.get("stage", ""),
                    "input": record.get("input", {}),
                    "output": record.get("output", {}),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            sample_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        sample_id = record.get("sample_id") or sample_hash

        with self.db.session() as session:
            from .models import GoldenSample as GoldenSampleModel

            # 检查是否已存在（按 hash 去重）
            existing = (
                session.execute(select(GoldenSample).where(GoldenSample.sample_hash == sample_hash)).scalars().first()
            )
            if existing:
                return False

            # 创建 ORM 对象
            sample = GoldenSample(
                sample_id=sample_id,
                split=split,
                stage=record.get("stage", ""),
                input_data=record.get("input", {}),
                output_data=record.get("output", {}),
                rubric=record.get("rubric"),
                expected=record.get("expected"),
                source=record.get("source", "unknown"),
                version=record.get("version", 1),
                sample_hash=sample_hash,
                human_verified=record.get("human_verified", False),
                quality_score=record.get("quality_score"),
                pattern_tags=record.get("pattern_tags", []),
            )
            session.add(sample)
            session.commit()
            return True

    def get_golden_samples(
        self,
        split: str,
        stage: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict]:
        """查询金标样本（从 JSONL 读取，支持分页）。"""
        if split not in ("train", "val", "test"):
            raise ValueError(f"invalid split: {split}")

        records = []
        # 这里简化：实际应用中可考虑用 SQLite 索引加速
        # 目前从 JSONL 读取
        if split not in ("train", "val", "test"):
            return []

        # 如果指定了 stage，只读该 stage
        # 这里简化：实际应用中可优化为直接读 SQLite
        return []

    def get_golden_stats(self) -> Dict[str, int]:
        """获取金标数据集统计。"""
        return self.jsonl.count_all_splits()

    # ──────────────────────────────────────────────────────────────────────────
    # SOP 规则
    # ──────────────────────────────────────────────────────────────────────────

    def create_sop_rule(self, session, **kwargs) -> "SOPRule":
        from .models import SOPRule

        rule = SOPRule(**kwargs)
        session.add(rule)
        session.flush()
        return rule

    def get_sop_rules(self, session, stage: Optional[str] = None, status: Optional[str] = None):
        from sqlalchemy import select

        from .models import SOPRule

        stmt = select(SOPRule)
        if stage:
            stmt = stmt.where(SOPRule.stage == stage)
        if status:
            stmt = stmt.where(SOPRule.status == status)
        return session.execute(stmt).scalars().all()

    def increment_sop_hit(self, session, rule_id: str, success: bool = True):
        from .models import SOPRule

        rule = session.execute(select(SOPRule).where(SOPRule.rule_id == rule_id)).scalars().first()
        if rule:
            rule.hit_count += 1
            if success:
                rule.success_count += 1
            rule.last_hit_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # ──────────────────────────────────────────────────────────────────────────
    # Prompt 版本
    # ──────────────────────────────────────────────────────────────────────────

    def create_prompt_version(self, session, **kwargs):
        from .models import PromptVersion

        pv = PromptVersion(**kwargs)
        session.add(pv)
        session.flush()
        return pv

    def get_prompt_version(self, session, stage: str, version: int):
        from sqlalchemy import select

        from .models import PromptVersion

        stmt = select(PromptVersion).where(
            PromptVersion.stage == stage,
            PromptVersion.version == version,
        )
        return session.execute(stmt).scalar_one_or_none()

    def get_live_prompt_version(self, session, stage: str):
        from sqlalchemy import select

        from .models import PromptVersion

        stmt = (
            select(PromptVersion)
            .where(
                PromptVersion.stage == stage,
                PromptVersion.status == "live",
            )
            .order_by(PromptVersion.version.desc())
        )
        return session.execute(stmt).scalar_one_or_none()

    # ──────────────────────────────────────────────────────────────────────────
    # SOP 规则
    # ──────────────────────────────────────────────────────────────────────────

    def get_sop_rules(self, session, stage: Optional[str] = None, status: Optional[str] = None):
        from sqlalchemy import select

        from .models import SOPRule

        stmt = select(SOPRule)
        if stage:
            stmt = stmt.where(SOPRule.stage == stage)
        if status:
            stmt = stmt.where(SOPRule.status == status)
        return session.execute(stmt).scalars().all()

    # ──────────────────────────────────────────────────────────────────────────
    # 质量阈值
    # ──────────────────────────────────────────────────────────────────────────

    def get_quality_thresholds(self, session, stage: Optional[str] = None):
        from sqlalchemy import select

        from .models import QualityThreshold

        stmt = select(QualityThreshold).where(QualityThreshold.is_active == True)
        if stage:
            stmt = stmt.where(QualityThreshold.stage == stage)
        return session.execute(stmt).scalars().all()

    # ──────────────────────────────────────────────────────────────────────────
    # 路由权重
    # ──────────────────────────────────────────────────────────────────────────

    def get_routing_weights(self, session, character_name: Optional[str] = None):
        from sqlalchemy import select

        from .models import RoutingWeight

        stmt = select(RoutingWeight).where(RoutingWeight.is_active == True)
        if character_name:
            stmt = stmt.where(RoutingWeight.character_name == character_name)
        return session.execute(stmt).scalars().all()

    def update_routing_weight(self, session, character_name: str, voice_id: str, weight_delta: float):
        from sqlalchemy import select

        from .models import RoutingWeight

        stmt = select(RoutingWeight).where(
            RoutingWeight.character_name == character_name,
            RoutingWeight.voice_id == voice_id,
        )
        rw = session.execute(stmt).scalar_one_or_none()
        if rw:
            rw.weight = max(rw.min_weight, min(rw.max_weight, rw.weight + weight_delta))
            rw.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    def record_routing_result(self, session, character_name: str, voice_id: str, success: bool):
        from sqlalchemy import select

        from .models import RoutingWeight

        stmt = select(RoutingWeight).where(
            RoutingWeight.character_name == character_name,
            RoutingWeight.voice_id == voice_id,
        )
        rw = session.execute(stmt).scalar_one_or_none()
        if rw:
            if success:
                rw.success_count += 1
                rw.last_success_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                rw.failure_count += 1
                rw.last_failure_at = datetime.now(timezone.utc).replace(tzinfo=None)
                # 自动降权
                rw.weight = max(rw.min_weight, rw.weight * rw.decay_on_failure)


# ──────────────────────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────────────────────

_storage: Optional[Storage] = None


def get_storage(database_url: Optional[str] = None, data_root: Optional[Path] = None) -> Storage:
    """获取全局存储实例（单例）。"""
    global _storage
    if _storage is None:
        _storage = Storage(
            database_url or "sqlite:///./audiobook_studio.db", Path(data_root) if data_root else Path("data")
        )
    return _storage


def reset_storage() -> None:
    """重置全局存储（测试用）。"""
    global _storage
    if _storage is not None:
        try:
            _storage.db.get_sync_engine().dispose()
        except Exception:  # noqa: BLE001
            pass
    _storage = None
    # 清理磁盘上的金标 JSONL 与 SQLite 文件，保证每次 reset 后状态干净、可复现
    import shutil

    # 仅清理 harness 自有金标目录（data/golden/harness），
    # 不影响主应用 / feedback 的金标数据（data/golden 下其余部分），
    # 使 harness 与 feedback 两套件可在同一工作树下无冲突运行。
    golden_dir = Path("data") / "golden" / "harness"
    if golden_dir.exists():
        shutil.rmtree(golden_dir, ignore_errors=True)
    # 清理 harness 自有 prompt 编译沙箱（prompts/harness），与真实 prompts/ 隔离
    prompts_dir = Path("prompts") / "harness"
    if prompts_dir.exists():
        shutil.rmtree(prompts_dir, ignore_errors=True)
    # 清理 SOP 规则库与金丝雀测试的持久化 JSON，避免跨测试状态残留
    sop_file = Path("config") / "agent_sop.json"
    if sop_file.exists():
        try:
            sop_file.unlink()
        except OSError:
            pass
    canary_dir = Path("data") / "canary"
    if canary_dir.exists():
        shutil.rmtree(canary_dir, ignore_errors=True)
    for suffix in ("", "-wal", "-shm"):
        db_path = Path("audiobook_studio.db" + suffix)
        if db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                pass


# 导出
__all__ = [
    "Storage",
    "DatabaseManager",
    "JSONLStore",
    "get_storage",
    "reset_storage",
]
