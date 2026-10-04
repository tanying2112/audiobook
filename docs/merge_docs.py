#!/usr/bin/env python3
"""Documentation consolidation script for Audiobook Studio.

Merges scattered .md files into organized sections and generates
a unified documentation structure for MkDocs.

Usage:
    python docs/merge_docs.py [--dry-run] [--output-dir docs/]
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

# Documentation categories and their source files
DOC_CATEGORIES = {
    "agents": {
        "title": "Agent 系统文档",
        "sources": [
            "AGENTS.md",
            "AGENT_TASKS.md",
            "docs/agents.md",
            "docs/agents/collaboration.md",
            "docs/agents/roles.md",
        ],
        "target": "docs/merged/agents.md",
    },
    "harness": {
        "title": "HARNESS 规范",
        "sources": [
            "HARNESS_SPECIFICATIONS.md",
            "HARNESS_SPECIFICATIONS_EXAMPLE.md",
            "docs/harness_specifications.md",
        ],
        "target": "docs/merged/harness_specifications.md",
    },
    "development": {
        "title": "开发指南",
        "sources": [
            "DEVELOPMENT_PLAN.md",
            "IMPLEMENTATION_ROADMAP.md",
            "CONTRIBUTING.md",
        ],
        "target": "docs/merged/development.md",
    },
    "reports": {
        "title": "项目报告",
        "sources": [
            "SPRINT_E_SUMMARY.md",
            "SPRINT_G_COMPLETION_RECORD.md",
            "ANALYSIS_SUMMARY.md",
            "EXECUTION_CHECKLIST.md",
        ],
        "target": "docs/merged/reports.md",
    },
}


def merge_category(name: str, config: dict, dry_run: bool = False) -> bool:
    """Merge files for a documentation category."""
    root = Path(__file__).parent.parent
    merged_content = []
    merged_content.append(f"# {config['title']}\n")
    merged_content.append(f"> 自动生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    merged_content.append("---\n")

    files_merged = 0
    for source in config["sources"]:
        source_path = root / source
        if source_path.exists():
            with open(source_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Add section header
            section_name = source_path.stem.replace("_", " ").title()
            merged_content.append(f"\n## {section_name}\n")
            merged_content.append(f"\n<!-- 来源：{source} -->\n")
            merged_content.append(content)
            merged_content.append("\n---\n")
            files_merged += 1

            if not dry_run:
                print(f"  ✓ 读取：{source}")
        else:
            if not dry_run:
                print(f"  - 跳过（不存在）: {source}")

    if files_merged == 0:
        print(f"⚠ 警告：{name} 类别没有找到任何文件")
        return False

    if not dry_run:
        target_path = root / config["target"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("\n".join(merged_content))
        print(f"✓ 已写入：{config['target']}")

    return True


def create_docs_index(root: Path, dry_run: bool = False) -> None:
    """Create a unified documentation index."""
    index_content = """# 文档索引

> 自动生成 - 包含所有合并后的文档链接

## 📖 核心文档

| 文档 | 说明 |
|------|------|
| [首页](index.md) | 项目概览和快速开始 |
| [架构设计](architecture.md) | 三档变速架构说明 |
| [API 参考](api.md) | API 接口文档 |

## 🤖 Agent 系统

| 文档 | 说明 |
|------|------|
| [Agent 系统总览](merged/agents.md) | 多 Agent 协作完整说明 |
| [Agent 任务](AGENTS.md) | Agent 任务分配说明 |

## 📐 HARNESS 规范

| 文档 | 说明 |
|------|------|
| [HARNESS 规范总览](merged/harness_specifications.md) | 三层架构详细说明 |
| [示例说明](HARNESS_SPECIFICATIONS_EXAMPLE.md) | 实际应用示例 |

## 🔧 开发指南

| 文档 | 说明 |
|------|------|
| [开发计划](merged/development.md) | 开发路线图和待办 |
| [贡献指南](CONTRIBUTING.md) | 如何贡献代码 |

## 📊 项目报告

| 文档 | 说明 |
|------|------|
| [Sprint 总结](merged/reports.md) | 各次 Sprint 完成记录 |
| [架构分析](ANALYSIS_SUMMARY.md) | 代码审计报告 |
| [执行清单](EXECUTION_CHECKLIST.md) | 任务执行检查清单 |

## 📦 发布与安全

| 文档 | 说明 |
|------|------|
| [发布记录](RELEASE_NOTES.md) | 版本发布历史 |
| [安全策略](SECURITY.md) | 安全相关事宜 |
| [代码规范](CODE_OF_CONDUCT.md) | 代码行为准则 |
"""

    if not dry_run:
        index_path = root / "docs" / "INDEX.md"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_content)
        print(f"✓ 已创建文档索引：docs/INDEX.md")


def main():
    parser = argparse.ArgumentParser(description="Consolidate documentation files")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="docs/merged",
        help="Output directory for merged docs",
    )
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    print("=" * 60)
    print("Audiobook Studio 文档合并工具")
    print("=" * 60)
    print()

    merged_count = 0
    for name, config in DOC_CATEGORIES.items():
        print(f"[{name}] {config['title']}")
        if merge_category(name, config, dry_run=args.dry_run):
            merged_count += 1
        print()

    if not args.dry_run:
        create_docs_index(root)

    print("=" * 60)
    print(f"完成：已合并 {merged_count}/{len(DOC_CATEGORIES)} 个文档类别")
    if args.dry_run:
        print("(Dry run - 未写入任何文件)")
    print("=" * 60)


if __name__ == "__main__":
    main()
