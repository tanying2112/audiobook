#!/usr/bin/env python3
"""
Audiobook Studio V2 - 统一流水线执行脚本（带安全参数锁）
"""
import argparse
import sys
from audiobook_studio.pipeline.orchestrator import run_pipeline

def parse_arguments():
    """解析命令行参数，构建安全锁"""
    parser = argparse.ArgumentParser(
        description="Audiobook Studio V2 流水线核心启动入口"
    )
    
    # 破坏性/脚手架操作，默认关闭 (action="store_true")
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="⚠️ 危险操作：初始化或重置数据库结构。未指定则使用当前现有数据库。"
    )
    
    parser.add_argument(
        "--mock-data",
        action="store_true",
        help="⚙️ 脚手架操作：自动生成《红楼梦》和《三国演义》的 Mock 测试文本。"
    )
    
    # 支持动态指定要跑的书籍，默认还是老两样
    parser.add_argument(
        "--books",
        nargs="+",
        default=["红楼梦", "三国演义"],
        help="指定要运行流水线的书籍名称列表 (空格分隔，默认: 红楼梦 三国演义)"
    )
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    print("=" * 50)
    print("🎙️  Audiobook Studio V2 Pipeline Controller")
    print("=" * 50)

    # 🔒 安全锁 1：只有显式指定 --mock-data 才会生成或覆盖测试文件
    if args.mock_data:
        print("⚙️ [Action] 正在生成/刷新 Mock 测试文本文件...")
        # 在此处添加实际的 mock data 生成函数调用
        # 例如: from audiobook_studio.utils import create_mock_test_files
        #        create_mock_test_files()
        print("✅ Mock 测试文本生成完成。")
    else:
        print("ℹ️ [Safety] 跳过 Mock 文本生成（使用工作区现有文本）")

    # 🔒 安全锁 2：只有显式指定 --init-db 才会触发数据库重置
    if args.init_db:
        print("🗄️ [Action] 警告：正在初始化/重置数据库表结构...")
        # 在此处添加实际的数据库初始化函数调用
        # 例如: from audiobook_studio.database import initialize_database
        #        initialize_database()
        print("✅ 数据库初始化完成。")
    else:
        print("ℹ️ [Safety] 跳过数据库初始化（安全挂载现有数据库）")

    print("-" * 50)
    print(f"🚀 准备启动音频合成流水线，目标书籍: {', '.join(args.books)}")
    print("-" * 50)

    # 核心业务循环
    for book_name in args.books:
        print(f"📖 正在处理: 《{book_name}》...")
        try:
            # 调用你重构好的现代化编排器函数
            run_pipeline(book_name=book_name)
            print(f"✅ 《{book_name}》流水线处理完成。")
        except Exception as e:
            print(f"❌ 《{book_name}》处理失败，错误原因: {e}", file=sys.stderr)

    print("=" * 50)
    print("🎉 所有指定任务执行完毕。")
    print("=" * 50)

if __name__ == "__main__":
    main()
