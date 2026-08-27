# Code Mate - 编程智能体

一个从零构建的编程智能体，能够通过与大语言模型交互，自主完成读写文件、执行命令等编程任务。

## 项目特点

- 🚀 无框架依赖：不使用任何 agent 框架，核心逻辑完全自主实现
- 🛠️ 工具系统：支持文件读写、命令执行、代码搜索等工具
- 💬 对话管理：完整的上下文和历史管理
- 🔄 智能循环：自主判断任务完成与终止条件
- ⚡ 错误处理：完善的异常捕获和重试机制

## 快速开始

### 环境要求

- Python 3.8+

### 安装

```bash
pip install -r requirements.txt
```

### 配置

创建 `.env` 文件并配置你的 API key：

```env
# OpenAI API（或兼容的其他模型）
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选，使用其他兼容服务时配置
MODEL_NAME=gpt-4  # 使用的模型名称
```

### 运行

```bash
python main.py
```

## 架构设计

```
code-mate/
├── src/
│   ├── agent/          # Agent 核心逻辑
│   ├── llm/            # LLM 接口封装
│   ├── tools/          # 工具系统
│   ├── context/        # 对话上下文管理
│   └── utils/          # 工具函数
├── tests/              # 测试
├── examples/           # 示例任务
└── main.py             # 程序入口
```

## 核心模块

### Agent 核心
- 主循环控制
- 任务规划与执行
- 终止条件判断

### LLM 接口
- 模型调用封装
- Tool calling 处理
- 流式输出支持

### 工具系统
- 文件读写工具
- 命令执行工具
- 代码搜索工具
- 自定义工具扩展

### 上下文管理
- 对话历史存储
- Token 计数与控制
- 上下文压缩策略

## 开发进度

- [ ] 基础架构搭建
- [ ] LLM 接口实现
- [ ] 工具系统实现
- [ ] Agent 主循环
- [ ] 错误处理完善
- [ ] 演示案例

## License

MIT
