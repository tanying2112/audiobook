#!/usr/bin/env python3
"""Docs Guard - 文档守卫脚本.

在 pre-push 阶段检查代码变更是否需要更新相关文档.
当检测到特定文件变更时，提示用户确认相关文档已同步更新.
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set

# 代码文件模式到相关文档文件的映射
CODE_to_DOC_MAP: Dict[str, List[str]] = {
    # 架构相关
    "src/audiobook_studio/di.py": ["docs/architecture.md", "docs/architecture_deep_dive.md"],
    "src/audiobook_studio/llm/router.py": ["docs/pipeline_tts.md", "docs/api_reference.md"],
    "src/audiobook_studio/tts/__init__.py": ["docs/pipeline_tts.md"],
    # Pipeline 相关
    "src/audiobook_studio/pipeline/": ["docs/pipeline_tts.md", "docs/harness_specifications.md"],
    "src/audiobook_studio/feedback/": ["docs/agents.md", "docs/harness_specifications.md"],
    "src/audiobook_studio/quality/": ["docs/pipeline_tts.md"],
    # Schema 相关
    "src/audiobook_studio/schemas/": ["docs/api_reference.md", "docs/harness_specifications.md"],
    # API 相关
    "src/audiobook_studio/api/": ["docs/api.md", "docs/api_reference.md"],
    # 配置相关
    "config/": ["docs/installation.md", "docs/quick_start.md"],
}

# 如果这些核心文件变更，必须更新 DEVELOPMENT_PLAN.md
CORE_FILES = [
    "src/audiobook_studio/main.py",
    "src/audiobook_studio/database.py",
    "src/audiobook_studio/llm/",
    "src/audiobook_studio/pipeline/",
]


def get_changed_files(staged: bool = False) -> Set[str]:
    """获取变更的文件列表."""
    try:
        if staged:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        else:
            result = subprocess.run(
                ["git", "diff", "HEAD", "--name-only", "--diff-filter=ACM"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return set()


def check_docs_needed(changed_files: Set[str]) -> List[str]:
    """检查哪些文档需要更新."""
    docs_to_update: Set[str] = set()

    for changed_file in changed_files:
        # 检查核心文件
        for core_file in CORE_FILES:
            if changed_file.startswith(core_file) or changed_file == core_file:
                docs_to_update.add("docs/DEVELOPMENT_PLAN.md")
                break

        # 检查代码到文档的映射
        for code_pattern, doc_files in CODE_to_DOC_MAP.items():
            if code_pattern in changed_file:
                docs_to_update.update(doc_files)

    # 排除不存在的文档文件
    existing_docs = {doc for doc in docs_to_update if Path(doc).exists()}

    return sorted(existing_docs)


def main() -> int:
    """主函数."""
    # 获取本次提交变更的文件
    changed_files = get_changed_files(staged=True)

    if not changed_files:
        print("[Docs Guard] 没有检测到代码变更")
        return 0

    # 检查是否需要更新文档
    docs_to_update = check_docs_needed(changed_files)

    if not docs_to_update:
        print("[Docs Guard] 代码变更不需要更新文档")
        return 0

    print("[Docs Guard] 检测到以下文档可能需要更新:")
    for doc in docs_to_update:
        print(f"  - {doc}")

    print("\n请确认这些文档已随代码变更同步更新。")
    print("如确认已更新，请继续 push；否则请先更新相关文档。")

    # 仅作为警告，不阻止 push
    return 0


if __name__ == "__main__":
    sys.exit(main())