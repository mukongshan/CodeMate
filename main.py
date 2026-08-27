#!/usr/bin/env python3
"""
Code Mate - 编程智能体主入口

用法：
    python main.py
"""

import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

from src.agent.agent import CodingAgent
from src.utils.logger import setup_logger

# 加载环境变量
load_dotenv()

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Code Mate - 编程智能体",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--task",
        type=str,
        help="直接执行的任务描述"
    )

    parser.add_argument(
        "--workspace",
        type=str,
        default="./workspace",
        help="工作空间目录"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示详细日志"
    )

    args = parser.parse_args()

    # 设置日志
    logger = setup_logger(verbose=args.verbose)

    # 创建工作空间
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    # 创建 agent
    agent = CodingAgent(workspace=workspace)

    logger.info("Code Mate 启动成功")
    logger.info(f"工作空间: {workspace.absolute()}")

    # 如果指定了任务，直接执行
    if args.task:
        logger.info(f"执行任务: {args.task}")
        result = agent.execute(args.task)
        logger.info(f"任务完成: {result}")
        return

    # 交互式模式
    logger.info("进入交互模式，输入 'exit' 或 'quit' 退出")
    print("\n" + "="*60)
    print("欢迎使用 Code Mate 编程智能体")
    print("请描述你想要完成的编程任务")
    print("="*60 + "\n")

    while True:
        try:
            user_input = input("\n👤 你: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\n再见！")
                break

            print("\n🤖 Agent 正在思考...\n")
            result = agent.execute(user_input)
            print(f"\n✅ 任务完成\n")

        except KeyboardInterrupt:
            print("\n\n中断执行")
            break
        except Exception as e:
            logger.error(f"执行出错: {e}", exc_info=True)
            print(f"\n❌ 出错了: {e}\n")

if __name__ == "__main__":
    main()
