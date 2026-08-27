"""
编程智能体核心实现

实现 agent 的主循环逻辑：
1. 接收用户任务
2. 与 LLM 交互，获取下一步动作
3. 执行工具调用
4. 判断是否完成任务
5. 循环直到任务完成或达到最大迭代次数
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from ..llm.client import LLMClient
from ..tools.registry import ToolRegistry
from ..context.manager import ContextManager
from ..utils.logger import get_logger

logger = get_logger(__name__)

class CodingAgent:
    """编程智能体"""

    def __init__(
        self,
        workspace: Path,
        max_iterations: int = None,
        model_name: str = None
    ):
        """
        初始化 agent

        Args:
            workspace: 工作空间目录
            max_iterations: 最大迭代次数
            model_name: 使用的模型名称
        """
        self.workspace = workspace
        self.max_iterations = max_iterations or int(os.getenv("MAX_ITERATIONS", "20"))

        # 初始化组件
        self.llm_client = LLMClient(model_name=model_name)
        self.tool_registry = ToolRegistry(workspace=workspace)
        self.context_manager = ContextManager()

        logger.info(f"Agent 初始化完成，最大迭代次数: {self.max_iterations}")

    def execute(self, task: str) -> str:
        """
        执行任务

        Args:
            task: 任务描述

        Returns:
            任务执行结果
        """
        logger.info(f"开始执行任务: {task}")

        # 添加用户消息到上下文
        self.context_manager.add_user_message(task)

        # 主循环
        for iteration in range(self.max_iterations):
            logger.info(f"第 {iteration + 1}/{self.max_iterations} 轮迭代")

            try:
                # 调用 LLM
                response = self.llm_client.chat(
                    messages=self.context_manager.get_messages(),
                    tools=self.tool_registry.get_tool_schemas()
                )

                # 添加 assistant 消息到上下文
                self.context_manager.add_assistant_message(response)

                # 检查是否需要调用工具
                if response.get("tool_calls"):
                    # 执行工具调用
                    tool_results = self._execute_tools(response["tool_calls"])

                    # 添加工具结果到上下文
                    for tool_call, result in zip(response["tool_calls"], tool_results):
                        self.context_manager.add_tool_result(
                            tool_call_id=tool_call["id"],
                            content=result
                        )

                    # 继续下一轮循环
                    continue

                # 没有工具调用，任务完成
                final_response = response.get("content", "任务完成")
                logger.info(f"任务完成: {final_response}")
                return final_response

            except Exception as e:
                logger.error(f"迭代出错: {e}", exc_info=True)
                # 可以选择重试或终止
                raise

        # 达到最大迭代次数
        logger.warning(f"达到最大迭代次数 {self.max_iterations}")
        return "任务未完成：达到最大迭代次数"

    def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[str]:
        """
        执行工具调用

        Args:
            tool_calls: 工具调用列表

        Returns:
            工具执行结果列表
        """
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args = tool_call["function"]["arguments"]

            logger.info(f"执行工具: {tool_name}，参数: {tool_args}")

            try:
                # 从注册表获取并执行工具
                result = self.tool_registry.execute(tool_name, tool_args)
                results.append(result)
                logger.info(f"工具执行成功: {tool_name}")
            except Exception as e:
                error_msg = f"工具执行失败: {str(e)}"
                logger.error(error_msg)
                results.append(error_msg)

        return results
