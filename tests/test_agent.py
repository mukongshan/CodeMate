"""
测试 Agent 基本功能
"""

import pytest
from pathlib import Path
from src.agent.agent import CodingAgent


def test_agent_initialization(tmp_path):
    """测试 Agent 初始化"""
    agent = CodingAgent(workspace=tmp_path, max_iterations=10)
    assert agent.workspace == tmp_path
    assert agent.max_iterations == 10


def test_agent_file_operations(tmp_path):
    """测试 Agent 文件操作"""
    agent = CodingAgent(workspace=tmp_path, max_iterations=5)

    # 创建文件
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # 验证文件存在
    assert test_file.exists()
