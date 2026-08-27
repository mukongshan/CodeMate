"""
LLM 客户端封装

负责与大语言模型交互，处理：
1. API 调用
2. Tool calling 请求与响应解析
3. 流式输出
4. 错误重试
"""

import os
import json
from typing import List, Dict, Any, Optional

from openai import OpenAI
from ..utils.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    """LLM 客户端"""

    def __init__(self, model_name: Optional[str] = None):
        """
        初始化 LLM 客户端

        Args:
            model_name: 模型名称，默认从环境变量读取
        """
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("未设置 OPENAI_API_KEY 环境变量")

        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model_name = model_name or os.getenv("MODEL_NAME", "gpt-4")
        self.max_tokens = int(os.getenv("MAX_TOKENS", "4096"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.7"))

        # 创建 OpenAI 客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

        logger.info(f"LLM 客户端初始化完成，模型: {self.model_name}")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        调用 LLM 进行对话

        Args:
            messages: 对话历史消息列表
            tools: 可用工具的 schema 列表
            stream: 是否使用流式输出

        Returns:
            LLM 响应，格式：
            {
                "content": "回复内容",
                "tool_calls": [
                    {
                        "id": "call_xxx",
                        "function": {
                            "name": "tool_name",
                            "arguments": {...}
                        }
                    }
                ]
            }
        """
        try:
            # 构建请求参数
            kwargs = {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            logger.debug(f"调用 LLM，消息数: {len(messages)}")

            # 调用 API
            response = self.client.chat.completions.create(**kwargs)

            # 解析响应
            message = response.choices[0].message
            result = {}

            if message.content:
                result["content"] = message.content
                logger.debug(f"LLM 回复: {message.content[:100]}...")

            if message.tool_calls:
                result["tool_calls"] = []
                for tool_call in message.tool_calls:
                    result["tool_calls"].append({
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": json.loads(tool_call.function.arguments)
                        }
                    })
                logger.debug(f"LLM 请求调用工具: {[tc['function']['name'] for tc in result['tool_calls']]}")

            return result

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}", exc_info=True)
            raise
