"""
上下文管理器

负责管理对话历史和上下文：
1. 消息存储
2. 上下文窗口控制
3. Token 计数（简化版）
"""

from typing import List, Dict, Any

from ..utils.logger import get_logger

logger = get_logger(__name__)


class ContextManager:
    """上下文管理器"""

    def __init__(self, max_messages: int = 50):
        """
        初始化上下文管理器

        Args:
            max_messages: 最大消息数，超过则进行裁剪
        """
        self.max_messages = max_messages
        self.messages: List[Dict[str, Any]] = []

        # 添加系统提示
        self._add_system_prompt()

        logger.info(f"上下文管理器初始化完成，最大消息数: {max_messages}")

    def _add_system_prompt(self):
        """添加系统提示"""
        system_prompt = """你是一个编程助手，能够帮助用户完成各种编程任务。

你可以使用以下工具：
- read_file: 读取文件内容
- write_file: 写入文件内容
- list_files: 列出目录内容
- execute_command: 执行 shell 命令

工作流程：
1. 理解用户的任务需求
2. 规划完成任务的步骤
3. 使用工具执行具体操作
4. 总结任务完成情况

注意事项：
- 执行命令前先思考是否必要
- 修改文件前先读取当前内容
- 遇到错误时分析原因并调整策略
- 任务完成后给出清晰的总结

请始终保持专业和友好。"""

        self.messages.append({
            "role": "system",
            "content": system_prompt
        })

    def add_user_message(self, content: str):
        """
        添加用户消息

        Args:
            content: 消息内容
        """
        self.messages.append({
            "role": "user",
            "content": content
        })
        self._check_and_trim()
        logger.debug(f"添加用户消息，当前消息数: {len(self.messages)}")

    def add_assistant_message(self, response: Dict[str, Any]):
        """
        添加 assistant 消息

        Args:
            response: LLM 响应，包含 content 和可能的 tool_calls
        """
        message = {"role": "assistant"}

        if response.get("content"):
            message["content"] = response["content"]

        if response.get("tool_calls"):
            message["tool_calls"] = response["tool_calls"]

        self.messages.append(message)
        self._check_and_trim()
        logger.debug(f"添加 assistant 消息，当前消息数: {len(self.messages)}")

    def add_tool_result(self, tool_call_id: str, content: str):
        """
        添加工具执行结果

        Args:
            tool_call_id: 工具调用 ID
            content: 工具执行结果
        """
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })
        self._check_and_trim()
        logger.debug(f"添加工具结果，当前消息数: {len(self.messages)}")

    def get_messages(self) -> List[Dict[str, Any]]:
        """
        获取当前所有消息

        Returns:
            消息列表
        """
        return self.messages

    def _check_and_trim(self):
        """检查并裁剪消息历史"""
        if len(self.messages) <= self.max_messages:
            return

        # 保留系统提示和最近的消息
        # 简化策略：保留第一条（system）和最后 N-1 条
        logger.warning(f"消息数超过限制 ({len(self.messages)} > {self.max_messages})，进行裁剪")

        system_msg = self.messages[0]
        recent_messages = self.messages[-(self.max_messages - 1):]

        self.messages = [system_msg] + recent_messages
        logger.info(f"裁剪后消息数: {len(self.messages)}")

    def clear(self):
        """清空上下文（保留系统提示）"""
        self.messages = [self.messages[0]]
        logger.info("上下文已清空")
