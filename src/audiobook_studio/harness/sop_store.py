"""SOP 规则库：可版本化、可统计命中率的规则库管理器。

提供 SOP 规则的 CRUD、版本化、命中统计、自动归档等功能。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..harness.models import SOPRuleCreate, SOPRuleOut, SOPRuleUpdate

logger = logging.getLogger(__name__)

SOP_FILE = Path("config/agent_sop.harness.json")


class SOPRuleStore:
    """SOP 规则库管理器：提供规则的 CRUD、版本化、命中统计、自动归档。"""

    def __init__(self):
        self.settings = None
        self._sop_file = Path("config/agent_sop.harness.json")
        self._lock = __import__("threading").Lock()

    def _load_sop_file(self) -> Dict[str, Any]:
        """加载 agent_sop.json 文件。"""
        if not self._sop_file.exists():
            return {"rules": [], "version": 1, "updated_at": datetime.now(timezone.utc).isoformat()}
        try:
            return json.loads(self._sop_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load SOP file: {e}")
            return {"rules": [], "version": 1, "updated_at": datetime.now(timezone.utc).isoformat()}

    def _save_sop_file(self, data: Dict[str, Any]) -> None:
        """原子写入 SOP 文件。"""
        tmp = Path(str(self._sop_file) + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._sop_file)

    def _get_lock(self):
        return self._lock

    # ──────────────────────────────────────────────────────────────────────────
    # 核心 CRUD
    # ──────────────────────────────────────────────────────────────────────────

    def create_rule(self, rule_data: "SOPRuleCreate") -> "SOPRuleOut":
        """创建新 SOP 规则。"""
        with self._lock:
            data = self._load_sop_file()
            rules = data.get("rules", [])

            # 检查 rule_id 唯一性
            if any(r.get("rule_id") == rule_data.rule_id for r in rules):
                raise ValueError(f"Rule ID {rule_data.rule_id} already exists")

            datetime.now(timezone.utc).isoformat()
            new_rule = {
                "rule_id": rule_data.rule_id,
                "name": rule_data.name,
                "description": rule_data.description,
                "stage": rule_data.stage,
                "condition": rule_data.condition,
                "action": rule_data.action,
                "status": "active",
                "version": 1,
                "parent_rule_id": rule_data.parent_rule_id,
                "hit_count": 0,
                "success_count": 0,
                "last_hit_at": None,
                "created_by": rule_data.created_by,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "archived_at": None,
            }

            rules.append(new_rule)
            data["rules"] = rules
            current_version = int(data.get("version", 1))
            if isinstance(current_version, str):
                try:
                    current_version = int(float(current_version))
                except ValueError:
                    current_version = 1
            data["version"] = current_version + 1
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_sop_file(data)

            logger.info(f"Created SOP rule: {rule_data.rule_id}")
            return self._rule_to_out(new_rule)

    def _rule_to_out(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """转换为输出格式。"""
        return {
            "rule_id": rule.get("rule_id"),
            "name": rule.get("name"),
            "description": rule.get("description"),
            "stage": rule.get("stage"),
            "condition": rule.get("condition"),
            "action": rule.get("action"),
            "status": rule.get("status"),
            "version": rule.get("version", 1),
            "parent_rule_id": rule.get("parent_rule_id"),
            "hit_count": rule.get("hit_count", 0),
            "success_count": rule.get("success_count", 0),
            "last_hit_at": rule.get("last_hit_at"),
            "created_at": rule.get("created_at"),
            "updated_at": rule.get("updated_at"),
            "archived_at": rule.get("archived_at"),
        }

    def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """获取单条规则。"""
        data = self._load_sop_file()
        for rule in data.get("rules", []):
            if rule.get("rule_id") == rule_id:
                return rule
        return None

    def get_rules(
        self,
        stage: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询规则列表。"""
        data = self._load_sop_file()
        rules = data.get("rules", [])

        if stage:
            rules = [r for r in rules if r.get("stage") == stage]
        if status:
            rules = [r for r in rules if r.get("status") == status]

        return rules[offset : offset + limit]

    def update_rule(self, rule_id: str, update: "SOPRuleUpdate") -> Optional[Dict[str, Any]]:
        """更新规则（版本号自增）。"""
        with self._lock:
            data = self._load_sop_file()
            rules = data.get("rules", [])

            for i, rule in enumerate(rules):
                if rule.get("rule_id") == rule_id:
                    if isinstance(update, dict):
                        update_data = update
                    else:
                        update_data = update.model_dump(exclude_unset=True)
                    if not update_data:
                        return rules[i]

                    # 版本号自增
                    rules[i]["version"] = int(rules[i].get("version", 1)) + 1
                    rules[i].update(update_data)
                    rules[i]["updated_at"] = datetime.now(timezone.utc).isoformat()

                    data["rules"] = rules
                    data["version"] = int(data.get("version", 1)) + 1
                    data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._save_sop_file(data)

                    logger.info(f"Updated SOP rule: {rule_id} -> v{rules[i]['version']}")
                    return rules[i]

        return None

    def delete_rule(self, rule_id: str, force: bool = False) -> bool:
        """删除规则（软删除：标记为 archived）。"""
        with self._lock:
            data = self._load_sop_file()
            rules = data.get("rules", [])

            for i, rule in enumerate(rules):
                if rule.get("rule_id") == rule_id:
                    if rule.get("status") == "archived" and not force:
                        logger.warning(f"Rule {rule_id} already archived")
                        return False

                    rules[i]["status"] = "archived"
                    rules[i]["archived_at"] = datetime.now(timezone.utc).isoformat()
                    rules[i]["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._save_sop_file(
                        {
                            "rules": rules,
                            "version": int(data.get("version", 1)) + 1,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    logger.info(f"Archived SOP rule: {rule_id}")
                    return True

        return False

    def archive_low_hit_rules(self, min_hit_count: int = 5, days_inactive: int = 90) -> int:
        """自动归档低命中规则。"""
        from datetime import timedelta

        with self._lock:
            data = self._load_sop_file()
            data.get("rules", [])
            datetime.now(timezone.utc) - timedelta(days=90)
            archived = 0

            for rule in data.get("rules", []):
                if rule.get("status") != "active":
                    continue

                hit_count = rule.get("hit_count", 0)
                last_hit = rule.get("last_hit_at")
                if last_hit:
                    last_hit_dt = datetime.fromisoformat(last_hit.replace("Z", "+00:00"))
                    inactive = datetime.now(timezone.utc) - last_hit_dt
                    if inactive > timedelta(days=days_inactive) and hit_count < 5:
                        rule["status"] = "archived"
                        rule["archived_at"] = datetime.now(timezone.utc).isoformat()
                        rule["updated_at"] = datetime.now(timezone.utc).isoformat()
                        archived += 1
                        logger.info(f"Auto-archived low-hit rule: {rule.get('rule_id')} (hits={hit_count})")

            if archived > 0:
                data["version"] = int(data.get("version", 1)) + 1
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save_sop_file(data)
                logger.info(f"Auto-archived {archived} low-hit SOP rules")

        return archived

    def record_hit(self, rule_id: str, success: bool = True) -> bool:
        """记录规则命中（用于统计）。"""
        with self._lock:
            data = self._load_sop_file()
            for rule in data.get("rules", []):
                if rule.get("rule_id") == rule_id:
                    rule["hit_count"] = rule.get("hit_count", 0) + 1
                    if success:
                        rule["success_count"] = rule.get("success_count", 0) + 1
                    rule["last_hit_at"] = datetime.now(timezone.utc).isoformat()
                    rule["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._save_sop_file(data)
                    return True
        return False

    def get_hit_stats(self, rule_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取命中统计。"""
        data = self._load_sop_file()
        rules = data.get("rules", [])

        if rule_id:
            rules = [r for r in data.get("rules", []) if r.get("rule_id") == rule_id]

        stats = []
        for rule in rules:
            rule.get("hit_count", 0)
            rule.get("success_count", 0)
            stats.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "name": rule.get("name"),
                    "stage": rule.get("stage"),
                    "hit_count": rule.get("hit_count", 0),
                    "success_count": rule.get("success_count", 0),
                    "success_rate": rule.get("success_count", 0) / max(rule.get("hit_count", 1), 1),
                    "last_hit_at": rule.get("last_hit_at"),
                    "status": rule.get("status"),
                }
            )
        return stats

    def get_rule_out(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """转换为输出格式。"""
        return {
            "rule_id": rule.get("rule_id"),
            "name": rule.get("name"),
            "description": rule.get("description"),
            "stage": rule.get("stage"),
            "condition": rule.get("condition"),
            "action": rule.get("action"),
            "status": rule.get("status"),
            "version": rule.get("version", 1),
            "parent_rule_id": rule.get("parent_rule_id"),
            "hit_count": rule.get("hit_count", 0),
            "success_count": rule.get("success_count", 0),
            "last_hit_at": rule.get("last_hit_at"),
            "created_at": rule.get("created_at"),
            "updated_at": rule.get("updated_at"),
            "archived_at": rule.get("archived_at"),
        }


# 全局单例
_sop_store: Optional["SOPRuleStore"] = None


def get_sop_store() -> "SOPRuleStore":
    """获取全局 SOP 规则库实例。"""
    global _sop_store
    if _sop_store is None:
        _sop_store = SOPRuleStore()
    return _sop_store


_sop_store: Optional["SOPRuleStore"] = None


# ──────────────────────────────────────────────────────────────────────────────
# API 兼容层
# ──────────────────────────────────────────────────────────────────────────────


def create_sop_rule(rule_data: Dict[str, Any]) -> Dict[str, Any]:
    """API 兼容：创建规则。"""
    store = get_sop_store()
    from ..harness.models import SOPRuleCreate

    rule_data = SOPRuleCreate(**rule_data)
    from ..harness.models import SOPRuleOut

    return SOPRuleOut(**store.create_rule(rule_data))


def get_sop_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    store = get_sop_store()
    return store.get_rule(rule_id)


def get_sop_rules(
    stage: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0
) -> List[Dict[str, Any]]:
    store = get_sop_store()
    return store.get_rules(stage=stage, status=status, limit=limit, offset=offset)


def update_sop_rule(rule_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    store = get_sop_store()
    from ..harness.models import SOPRuleUpdate

    update = SOPRuleUpdate(**update_data)
    return store.update_rule(rule_id, update)


def delete_sop_rule(rule_id: str, force: bool = False) -> bool:
    store = get_sop_store()
    return store.delete_rule(rule_id, force)


def archive_low_hit_sop_rules(min_hit_count: int = 5, days_inactive: int = 90) -> int:
    store = get_sop_store()
    return store.archive_low_hit_rules(min_hit_count, days_inactive)


def record_sop_hit(rule_id: str, success: bool = True) -> bool:
    store = get_sop_store()
    return store.record_hit(rule_id, success)


def get_sop_hit_stats(rule_id: Optional[str] = None) -> List[Dict[str, Any]]:
    store = get_sop_store()
    return store.get_hit_stats(rule_id)
