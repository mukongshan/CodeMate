# CodeMate

一个支持树形对话历史和 Lane 分支管理的编程智能体。

## 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

### 2. 运行后端

```bash
python main.py
```

服务将在 http://127.0.0.1:8000 启动。

### 3. API 文档

访问 http://127.0.0.1:8000/docs 查看自动生成的 API 文档。

## 核心功能

- **树形对话历史**：每条消息是树中的一个节点，支持分叉和回溯
- **Lane 分支管理**：类似 Git 分支，可以同时探索多个方案
- **六个核心工具**：
  - `read_file` - 读取文件内容
  - `write_file` - 写入文件
  - `edit_file` - 精确编辑文件
  - `bash` - 执行 shell 命令
  - `glob` - 文件搜索
  - `grep` - 内容搜索
- **三级权限控制**：SAFE（自动放行）/ WRITE（workspace 内自动放行）/ DANGEROUS（需用户确认）
- **子 Agent 系统**：将子任务委托给独立上下文的只读 Agent

## 项目结构

```
CodeMate/
├── main.py                      # FastAPI 应用入口
├── src/
│   ├── agent/                   # Agent 主循环
│   │   ├── loop.py             # 核心执行循环
│   │   ├── providers.py        # MessageProvider 抽象
│   │   ├── state.py            # 运行状态
│   │   └── prompts.py          # 系统提示词
│   ├── storage/                 # 树形历史存储
│   │   ├── session_storage.py  # Entry 树管理
│   │   ├── lane_manager.py     # Lane 指针管理
│   │   └── models.py           # 数据模型
│   ├── llm/                     # LLM 接口层
│   │   ├── client.py           # 统一客户端 + 重试
│   │   ├── providers.py        # OpenAI/DeepSeek Provider
│   │   └── events.py           # 流式事件定义
│   ├── tools/                   # 工具系统
│   │   ├── registry.py         # 工具注册表
│   │   ├── base.py             # Tool 基类
│   │   ├── file_tools.py       # 文件操作工具
│   │   ├── exec_tool.py        # 命令执行工具
│   │   ├── search_tools.py     # 搜索工具
│   │   └── subagent_tool.py    # 子 Agent 工具
│   ├── permission/              # 权限控制
│   │   ├── manager.py          # 权限管理器
│   │   └── rules.py            # 安全规则
│   ├── api/                     # Web API 层
│   │   ├── routes.py           # REST 路由
│   │   ├── ws.py               # WebSocket 端点
│   │   ├── schemas.py          # 请求/响应模型
│   │   └── session_service.py  # Session 管理
│   ├── errors/                  # 错误类型
│   ├── observability/           # 日志系统
│   └── config.py               # 配置加载
├── docs/                        # 设计文档
├── tests/                       # 测试
└── data/sessions/              # 运行时数据（JSONL）
```

## 设计文档

详细的系统设计和实现细节见 `docs/` 目录：

- [功能设计/00-首页.md](docs/功能设计/00-首页.md) - 项目概述和文档导航
- [功能设计/01-系统架构概览.md](docs/功能设计/01-系统架构概览.md) - 整体架构
- [功能设计/02-数据与存储层/02-树形对话历史系统.md](docs/功能设计/02-数据与存储层/02-树形对话历史系统.md) - 核心差异化功能
- [代码设计/00-总览与目录结构.md](docs/代码设计/00-总览与目录结构.md) - 代码组织

## 开发

```bash
# 运行测试
pytest

# 代码格式化
black src/ tests/

# 类型检查
mypy src/
```

## 技术栈

- **后端**: Python 3.11+, FastAPI, WebSocket
- **存储**: JSONL (追加式存储)
- **LLM**: OpenAI API / DeepSeek API

## License

MIT
