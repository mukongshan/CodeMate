"""
日志工具

统一的日志配置和管理
"""

import logging
import sys
from pathlib import Path


def setup_logger(verbose: bool = False) -> logging.Logger:
    """
    设置全局日志配置

    Args:
        verbose: 是否显示详细日志

    Returns:
        根日志记录器
    """
    level = logging.DEBUG if verbose else logging.INFO

    # 配置根日志记录器
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # 创建 logs 目录
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # 添加文件处理器
    file_handler = logging.FileHandler(
        logs_dir / "code-mate.log",
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    )

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称（通常是模块名）

    Returns:
        日志记录器
    """
    return logging.getLogger(name)
